"""她自己的天堂：面板可调的开关。"""

from __future__ import annotations

import json
import os

DEFAULTS = {
    "enabled": True,
    "state_enabled": True,          # 感知他此刻累/忙/难过
    "state_ttl_hours": 3.0,         # 状态多久失效
    "question_budget_enabled": True,
    "max_questions": 2,             # 15 分钟内最多几个问号
    "question_window_minutes": 15.0,
    "politeness_enabled": True,     # 小事不纠正
    "tone_memory_enabled": True,    # 记住他的语气
    "thread_enabled": True,         # 收场前留话头
    "delay_enabled": True,          # 回复前停顿
    "delay_max_sec": 1.6,
    "delay_per_char": 0.012,
}

RULES = {
    "state_ttl_hours": (0.5, 24.0, float),
    "max_questions": (0, 6, int),
    "question_window_minutes": (1.0, 120.0, float),
    "delay_max_sec": (0.0, 5.0, float),
    "delay_per_char": (0.0, 0.1, float),
}

BOOLS = (
    "enabled",
    "state_enabled",
    "question_budget_enabled",
    "politeness_enabled",
    "tone_memory_enabled",
    "thread_enabled",
    "delay_enabled",
)


def _clean(data: dict) -> dict:
    out = dict(DEFAULTS)
    for key, (low, high, typ) in RULES.items():
        try:
            value = typ((data or {}).get(key, DEFAULTS[key]))
        except Exception:
            value = DEFAULTS[key]
        out[key] = max(low, min(high, value))
    for key in BOOLS:
        raw = (data or {}).get(key, DEFAULTS[key])
        out[key] = raw.strip().lower() in {"1", "true", "yes", "on"} if isinstance(raw, str) else bool(raw)
    return out


class Settings:
    def __init__(self, path: str) -> None:
        self.path = path
        self.data = dict(DEFAULTS)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.load()

    def load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = _clean(json.load(f))
        except FileNotFoundError:
            self.data = dict(DEFAULTS)
            self.save()
        except Exception:
            self.data = dict(DEFAULTS)
        return self.data

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def update(self, payload: dict) -> dict:
        merged = dict(self.data)
        merged.update(payload or {})
        self.data = _clean(merged)
        self.save()
        return self.data
