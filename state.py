"""她自己的天堂：温柔的一些具体做法。

四个能力：
1. 他的状态感知（累/忙/难过/生病/开心）—— 提前一步，不用他明说
2. 问题预算 —— 不连着抛问题
3. 留体面 —— 小事不纠正
4. 话头 —— 收场之前先留半句
5. 语气簿 —— 记住他那天是什么语气

全部按 QQ 分开存，不读任何其它插件的数据。
"""

from __future__ import annotations

import json
import os
import time

# ---------------- 状态识别 ----------------

STATE_WORDS = {
    "tired": ("累", "困", "熬夜", "没睡", "通宵", "睁不开眼", "好倦"),
    "busy": ("忙", "开会", "赶", "没空", "加班", "在弄", "来不及"),
    "sad": ("难过", "难受", "不开心", "郁闷", "委屈", "想哭", "烦死", "低落"),
    "sick": ("感冒", "发烧", "头疼", "头疼", "不舒服", "胃疼", "拉肚子", "咳嗽"),
    "happy": ("开心", "高兴", "顺利", "成了", "搞定了", "太好了", "爽"),
}

STATE_LABEL = {
    "tired": "累",
    "busy": "忙",
    "sad": "难过",
    "sick": "不舒服",
    "happy": "开心",
}

STATE_HINT = {
    "tired": "他现在累，别抛问题，别让他解释，话短一点",
    "busy": "他现在忙，别拖着他聊，说一句就行",
    "sad": "他现在心情不好，先接住，不要问为什么，也别讲道理",
    "sick": "他身体不舒服，别多问，轻轻应一声就好",
    "happy": "他心情不错，可以跟着松一点",
}

# ---------------- 语气识别 ----------------

TONE_RULES = [
    ("轻", ("嗯", "没事", "算了", "没关系", "...", "…", "随便")),
    ("急", ("快点", "赶紧", "！！", "!!", "马上")),
    ("笑", ("哈", "嘿", "草", "笑死", "233")),
    ("疲", ("累", "困", "睡了", "晚安")),
    ("凶", ("滚", "闭嘴", "别烦", "烦死")),
]

CLOSING_WORDS = (
    "先不聊", "不聊了", "去睡", "先睡", "快睡", "关灯", "不吵你",
    "明天再说", "回聊", "上课", "先这样", "挂了",
)

MAX_TONES = 30
MAX_THREADS = 20


def _now() -> float:
    return time.time()


def detect_state(text: str) -> str:
    text = str(text or "")
    for kind, words in STATE_WORDS.items():
        for word in words:
            if word in text:
                return kind
    return ""


def detect_tone(text: str) -> str:
    text = str(text or "")
    for name, words in TONE_RULES:
        for word in words:
            if word in text:
                return name
    return ""


def count_questions(text: str) -> int:
    text = str(text or "")
    return text.count("?") + text.count("？")


class ParadiseStore:
    def __init__(self, path: str, settings: dict | None = None) -> None:
        self.path = path
        self.settings = dict(settings or {})
        self.data: dict = {"users": {}}
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.load()

    # ---------------- 持久化 ----------------

    def load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            raw = {}
        users = raw.get("users") if isinstance(raw, dict) else {}
        self.data = {"users": users if isinstance(users, dict) else {}}

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # ---------------- 用户记录 ----------------

    def _user(self, qq: str, name: str = "") -> dict:
        qq = str(qq or "").strip()
        users = self.data.setdefault("users", {})
        row = users.get(qq)
        if not isinstance(row, dict):
            row = {
                "name": "",
                "state": {},
                "tone_log": [],
                "questions": [],
                "threads": [],
                "last_user_text": "",
                "last_reply": "",
                "updated_at": 0,
                "talks": 0,
            }
            users[qq] = row
        row.setdefault("state", {})
        row.setdefault("tone_log", [])
        row.setdefault("questions", [])
        row.setdefault("threads", [])
        if name:
            row["name"] = str(name)[:40]
        return row

    def touch(self, qq: str, name: str = "") -> dict:
        row = self._user(qq, name)
        row["updated_at"] = _now()
        row["talks"] = int(row.get("talks") or 0) + 1
        return row

    # ---------------- 他此刻的状态 ----------------

    def note_user_message(self, qq: str, name: str, text: str) -> dict:
        row = self.touch(qq, name)
        text = str(text or "").strip()
        row["last_user_text"] = text[:200]
        if not text:
            return row

        kind = detect_state(text)
        if kind:
            row["state"] = {"kind": kind, "at": _now(), "note": text[:80]}

        tone = detect_tone(text)
        if tone and len(text) >= 2:
            log = row.setdefault("tone_log", [])
            log.append({"tone": tone, "text": text[:80], "at": _now()})
            row["tone_log"] = log[-MAX_TONES:]

        # 收场词由她的回复触发话头，这里只记录他说了什么
        self.save()
        return row

    def current_state(self, qq: str) -> dict | None:
        row = self.data.get("users", {}).get(str(qq)) or {}
        state = row.get("state") or {}
        if not state.get("kind"):
            return None
        ttl = float(self.settings.get("state_ttl_hours", 3) or 3) * 3600
        if _now() - float(state.get("at") or 0) > ttl:
            return None
        return state

    # ---------------- 问题预算 ----------------

    def note_reply(self, qq: str, reply: str) -> int:
        """记下她这条回复里的问号。"""
        row = self._user(qq)
        q = count_questions(reply)
        if q:
            marks = row.setdefault("questions", [])
            marks.append(_now())
            row["questions"] = marks[-20:]
        row["last_reply"] = str(reply or "")[:200]
        row["updated_at"] = _now()
        self.save()
        return q

    def recent_questions(self, qq: str, minutes: float = 15) -> int:
        row = self.data.get("users", {}).get(str(qq)) or {}
        cutoff = _now() - minutes * 60
        return sum(1 for t in row.get("questions") or [] if float(t) >= cutoff)

    # ---------------- 话头 ----------------

    def maybe_thread(self, qq: str, reply: str) -> dict | None:
        """她这条回复像在收场 → 把他上一句存成话头。"""
        reply = str(reply or "")
        if not any(word in reply for word in CLOSING_WORDS):
            return None
        row = self.data.get("users", {}).get(str(qq)) or {}
        last = str(row.get("last_user_text") or "").strip()
        if len(last) < 4:
            return None
        threads = row.setdefault("threads", [])
        if any(t.get("text") == last for t in threads):
            return None
        item = {"text": last[:120], "at": _now(), "done": False, "used": 0}
        threads.append(item)
        row["threads"] = threads[-MAX_THREADS:]
        self.save()
        return item

    def open_thread(self, qq: str) -> dict | None:
        row = self.data.get("users", {}).get(str(qq)) or {}
        for item in row.get("threads") or []:
            if not item.get("done"):
                return item
        return None

    def finish_thread(self, qq: str, text: str = "") -> bool:
        row = self.data.get("users", {}).get(str(qq)) or {}
        for item in row.get("threads") or []:
            if text and item.get("text") != text:
                continue
            if item.get("done"):
                continue
            item["done"] = True
            item["done_at"] = _now()
            self.save()
            return True
        return False

    # ---------------- 语气簿 ----------------

    def recent_tone(self, qq: str) -> dict | None:
        row = self.data.get("users", {}).get(str(qq)) or {}
        log = row.get("tone_log") or []
        if not log:
            return None
        return log[-1]

    # ---------------- 快照 ----------------

    def snapshot(self) -> dict:
        now = _now()
        users = []
        for qq, row in (self.data.get("users") or {}).items():
            state = self.current_state(qq)
            threads = [t for t in (row.get("threads") or []) if not t.get("done")]
            tones = row.get("tone_log") or []
            users.append(
                {
                    "qq": qq,
                    "name": row.get("name") or qq,
                    "state": STATE_LABEL.get((state or {}).get("kind"), "") if state else "",
                    "state_kind": (state or {}).get("kind", ""),
                    "state_age_min": round((now - float((state or {}).get("at") or now)) / 60)
                    if state
                    else 0,
                    "questions": self.recent_questions(qq),
                    "threads": [
                        {"text": t.get("text"), "at": t.get("at")} for t in threads[:5]
                    ],
                    "tones": [{"tone": t.get("tone"), "text": t.get("text")} for t in tones[-5:]],
                    "talks": int(row.get("talks") or 0),
                    "last_seen": float(row.get("updated_at") or 0),
                }
            )
        users.sort(key=lambda u: -float(u["last_seen"] or 0))
        return {"users": users, "ts": now}
