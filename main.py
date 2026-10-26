"""她自己的天堂（astrbot_plugin_paradise）

独立插件：把「温柔」拆成几件能做的事，而不是一句形容词。

* 他在累 / 忙 / 难过 / 不舒服 / 开心 —— 提前一步，不用他明说
* 问题预算 —— 不连着抛问号
* 留体面 —— 他说错的小事不纠正
* 话头 —— 收场之前先留半句
* 语气簿 —— 记住他那天是什么语气
* 稍微慢一点 —— 回复前有个停顿

不依赖、不修改任何其它插件；注入走临时内容块，不改 system_prompt。
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.message import TextPart
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .settings import DEFAULTS, Settings
from .state import STATE_HINT, ParadiseStore

PLUGIN_NAME = "astrbot_plugin_paradise"
API_PREFIX = f"/{PLUGIN_NAME}"

try:
    from quart import request
except Exception:  # pragma: no cover
    request = None


@register(
    PLUGIN_NAME,
    "若剑清",
    "她自己的天堂：把温柔拆成能做的事——感知他的状态、不追问、不纠正、留话头、记住语气。",
    "0.1.0",
    "",
)
class ParadisePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | dict | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        data_dir = os.path.join(get_astrbot_plugin_data_path(), PLUGIN_NAME)
        self.settings = Settings(os.path.join(data_dir, "settings.json"))
        self.store = ParadiseStore(os.path.join(data_dir, "paradise.json"), self.settings.data)
        self._register_web_apis()
        snap = self.store.snapshot()
        logger.info("[Paradise] 她自己的天堂加载完成，记录的用户 %d 个", len(snap.get("users") or []))

    # ---------------- 基础 ----------------

    async def _json_body(self) -> dict:
        if request is None:
            return {}
        try:
            payload = await request.get_json(silent=True)
        except Exception:
            payload = None
        return payload if isinstance(payload, dict) else {}

    def _register_web_apis(self) -> None:
        register = getattr(self.context, "register_web_api", None)
        if not callable(register):
            logger.info("[Paradise] 当前 AstrBot 版本不支持插件 Web API，跳过面板注册")
            return
        routes = [
            ("/overview", self.api_overview, ["GET"], "概览"),
            ("/settings", self.api_settings, ["GET"], "读取参数"),
            ("/settings/save", self.api_settings_save, ["POST"], "保存参数"),
            ("/thread/done", self.api_thread_done, ["POST"], "话头已接"),
            ("/reset", self.api_reset, ["POST"], "清空某人"),
        ]
        for path, handler, methods, desc in routes:
            try:
                register(f"{API_PREFIX}{path}", handler, methods, desc)
            except Exception as exc:
                logger.warning("[Paradise] 注册面板 API 失败 %s: %s", path, exc)

    async def api_overview(self):
        snap = self.store.snapshot()
        snap["ok"] = True
        snap["settings"] = self.settings.data
        return snap

    async def api_settings(self):
        return {"ok": True, "settings": self.settings.data, "defaults": DEFAULTS}

    async def api_settings_save(self):
        payload = await self._json_body()
        data = self.settings.update(payload)
        self.store.settings = data
        return {"ok": True, "settings": data}

    async def api_thread_done(self):
        payload = await self._json_body()
        qq = str(payload.get("qq") or "").strip()
        text = str(payload.get("text") or "").strip()
        ok = self.store.finish_thread(qq, text)
        return {"ok": ok, "overview": self.store.snapshot()}

    async def api_reset(self):
        payload = await self._json_body()
        qq = str(payload.get("qq") or "").strip()
        users = self.store.data.setdefault("users", {})
        if qq:
            users.pop(qq, None)
        else:
            users.clear()
        self.store.save()
        return {"ok": True, "overview": self.store.snapshot()}

    # ---------------- 记录 ----------------

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def record_user(self, event: AstrMessageEvent):
        if not self.settings.data.get("enabled", True):
            return
        try:
            qq = str(event.get_sender_id() or "").strip()
            name = str(getattr(event, "get_sender_name", lambda: "")() or "").strip()
            text = str(getattr(event, "message_str", "") or "").strip()
            if not qq or not text:
                return
            self.store.note_user_message(qq, name, text)
        except Exception as exc:
            logger.debug("[Paradise] 记录失败: %s", exc)

    # ---------------- 注入 ----------------

    @filter.on_llm_request()
    async def inject_paradise(self, event: AstrMessageEvent, req: Any) -> None:
        s = self.settings.data
        if not s.get("enabled", True):
            return
        try:
            qq = str(event.get_sender_id() or "").strip()
        except Exception:
            qq = ""
        if not qq:
            return

        lines: list[str] = []

        state_used = False
        if s.get("state_enabled", True):
            state = self.store.current_state(qq)
            if state:
                hint = STATE_HINT.get(state.get("kind", ""), "")
                if hint:
                    lines.append(hint)
                    state_used = True

        if s.get("question_budget_enabled", True):
            limit = int(s.get("max_questions", 2) or 0)
            window = float(s.get("question_window_minutes", 15) or 15)
            if limit and self.store.recent_questions(qq, window) >= limit:
                lines.append("最近你问得有点多了，这轮只回应他说的，不要再抛问题")

        if s.get("politeness_enabled", True):
            lines.append("他说错的小事别当场纠正，听着往下接；要紧的事轻声问一句就行")

        if s.get("thread_enabled", True):
            thread = self.store.open_thread(qq)
            if thread:
                lines.append("上次他没说完的是「%s」，这次可以先接这个" % str(thread.get("text"))[:60])

        if s.get("tone_memory_enabled", True) and not state_used:
            tone = self.store.recent_tone(qq)
            if tone and tone.get("tone") in ("轻", "疲", "凶"):
                lines.append(
                    "上次他说「%s」的时候语气是「%s」，你记着这个"
                    % (str(tone.get("text"))[:40], tone.get("tone"))
                )

        if not lines:
            return

        block = "【这会儿怎么相处】\n" + "\n".join("- " + line for line in lines)
        try:
            parts = getattr(req, "extra_user_content_parts", None)
            if not isinstance(parts, list):
                parts = []
                req.extra_user_content_parts = parts
            parts.append(TextPart(text=block).mark_as_temp())
        except Exception as exc:
            logger.debug("[Paradise] 注入失败: %s", exc)

    # ---------------- 回复后：数问号、留话头、慢一点 ----------------

    @filter.on_decorating_result()
    async def after_reply(self, event: AstrMessageEvent):
        s = self.settings.data
        if not s.get("enabled", True):
            return
        try:
            result = event.get_result()
            if not result or not getattr(result, "chain", None):
                return
            texts = []
            for comp in result.chain:
                text = getattr(comp, "text", None)
                if text:
                    texts.append(str(text))
            reply = "".join(texts).strip()
            if not reply:
                return
            qq = str(event.get_sender_id() or "").strip()
            if not qq:
                return

            self.store.note_reply(qq, reply)
            if s.get("thread_enabled", True):
                self.store.maybe_thread(qq, reply)

            if s.get("delay_enabled", True):
                base = 0.35
                extra = len(reply) * float(s.get("delay_per_char", 0.012) or 0)
                delay = min(float(s.get("delay_max_sec", 1.6) or 0), base + extra)
                if delay > 0:
                    await asyncio.sleep(delay)
        except Exception as exc:
            logger.debug("[Paradise] 回复后处理失败: %s", exc)

    async def terminate(self) -> None:
        try:
            self.store.save()
        except Exception:
            pass
        logger.info("[Paradise] 她自己的天堂已停止。")
