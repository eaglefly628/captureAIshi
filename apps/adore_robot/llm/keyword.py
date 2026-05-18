"""Offline keyword fallback for demo / sandboxed environments.

Implements the same BaseLLMClient interface used by deepseek / anthropic
adapters so the demo runs identically with or without an API key. Picks
intents off the latest user message via regex and emits a single
update_scene-shaped tool call.

Triggered automatically via factory.auto_detect_provider() when no
provider API key env var is set.
"""

from __future__ import annotations

import re
import time

from .base import BaseLLMClient, ChatResponse, Message, ToolCall, ToolDef

LIGHTING_WARM = {
    "warehouse": "mixed",
    "living_room": "evening_warm",
    "industrial_corner": "mixed",
}
LIGHTING_COOL = {
    "warehouse": "cool_white",
    "living_room": "cool_daylight",
    "industrial_corner": "halogen_spot",
}
LIGHTING_DEFAULT = {
    "warehouse": "warehouse_sodium",
    "living_room": "indoor_tungsten",
    "industrial_corner": "indoor_tungsten",
}

PARAM_BUMP = {
    "warehouse": {
        "more_dense": [("shelf_density", "+", 0.2)],
        "less_dense": [("shelf_density", "-", 0.2)],
        "more_count": [("forklift_count", "+", 1)],
        "less_count": [("forklift_count", "-", 1)],
        "more_variety": [("prop_variety", "+", 1)],
    },
    "living_room": {
        "more_dense": [("furniture_density", "+", 0.15), ("clutter_level", "+", 0.1)],
        "less_dense": [("furniture_density", "-", 0.15), ("clutter_level", "-", 0.1)],
        "more_variety": [("decor_variety", "+", 1)],
    },
    "industrial_corner": {
        "more_dense": [("toolboard_density", "+", 0.2), ("crate_count", "+", 1)],
        "less_dense": [("toolboard_density", "-", 0.2), ("crate_count", "-", 1)],
        "more_count": [("machine_count", "+", 1)],
        "more_variety": [("pipe_complexity", "+", 1)],
    },
}

RANGES = {
    "shelf_density": (0.2, 1.0),
    "alley_width_m": (1.5, 4.0),
    "forklift_count": (0, 5),
    "prop_variety": (1, 5),
    "pallet_load_factor": (0.0, 1.0),
    "furniture_density": (0.3, 0.9),
    "decor_variety": (2, 8),
    "clutter_level": (0.0, 1.0),
    "machine_count": (1, 4),
    "toolboard_density": (0.3, 1.0),
    "pipe_complexity": (1, 5),
    "oil_stain_amount": (0.0, 0.8),
    "crate_count": (0, 6),
    "room_w_m": (8.0, 40.0),
    "room_l_m": (8.0, 60.0),
    "ceiling_h_m": (3.0, 9.0),
    "worker_count": (0, 8),
}


def _clamp(name: str, val):
    lo, hi = RANGES.get(name, (None, None))
    if lo is None:
        return val
    if isinstance(val, int):
        return max(int(lo), min(int(hi), val))
    rounded = round(max(lo, min(hi, float(val))), 4)
    return rounded


def _match_intents(text: str) -> list[str]:
    t = text.lower()
    intents = []
    if re.search(r"(密|多放|多一些|挤|更多)", t):
        intents.append("more_dense")
    if re.search(r"(疏|稀|少一些|少|减少)", t):
        intents.append("less_dense")
    if re.search(r"(加.*?台|多放.*?个|增加.*?数|再来.*?个)", t):
        intents.append("more_count")
    if re.search(r"(种类多|多样|丰富)", t):
        intents.append("more_variety")
    return intents


def _lighting_intent(text: str) -> str | None:
    t = text.lower()
    if re.search(r"(暖|温暖|傍晚|偏黄|夕阳)", t):
        return "warm"
    if re.search(r"(冷|清冷|白光|日光|偏蓝)", t):
        return "cool"
    if re.search(r"(默认|还原|重置.*?灯|原灯)", t):
        return "default"
    return None


def _apply_delta(scene_id: str, current: dict, intents: list[str]) -> dict:
    delta: dict = {}
    bump_table = PARAM_BUMP.get(scene_id, {})
    for intent in intents:
        for name, op, step in bump_table.get(intent, []):
            base = current.get(name, 0)
            new_val = base + step if op == "+" else base - step
            delta[name] = _clamp(name, new_val)
    return delta


def _last_user_text(messages: list[Message]) -> str:
    for m in reversed(messages):
        if m.role == "user":
            if isinstance(m.content, str):
                return m.content
            if isinstance(m.content, list):
                return " ".join(
                    blk.get("text", "") for blk in m.content
                    if isinstance(blk, dict) and blk.get("type") == "text"
                )
    return ""


def _extract_current_spec(text: str) -> tuple[str, dict]:
    scene_id = "warehouse"
    current: dict = {}
    m = re.search(r'scene_id[\s:"]+(\w+)', text)
    if m:
        scene_id = m.group(1)
    try:
        import json as _json
        spec_match = re.search(r"current_spec[^{]*({.*?})(?=\n|$)", text, re.DOTALL)
        if spec_match:
            current = _json.loads(spec_match.group(1)).get("pcg_params", {})
    except Exception:
        pass
    return scene_id, current


class KeywordFallbackClient(BaseLLMClient):
    """No-network heuristic adapter. Same shape as deepseek/anthropic clients."""

    def __init__(self, model: str = "offline-heuristic-v1"):
        self.model = model

    def chat_with_tools(
        self,
        messages: list[Message],
        tools: list[ToolDef] | None = None,
        tool_choice: str | dict | None = None,
        max_tokens: int = 1024,
        temperature: float | None = None,
        system: str | None = None,
    ) -> ChatResponse:
        t0 = time.time()
        user_text = _last_user_text(messages)

        if not tools:
            elapsed = int((time.time() - t0) * 1000)
            return ChatResponse(
                text=(
                    "[offline keyword fallback] 当前未配置真 LLM (DEEPSEEK_API_KEY 未设). "
                    "自由对话需要真模型. 请在 cmd 设 set DEEPSEEK_API_KEY=... 后重启, "
                    "或在 apps/adore_robot/.env 里填好 key.\n\n"
                    f"你刚才说: {user_text!r}"
                ),
                tool_calls=[],
                finish_reason="stop",
                usage={"elapsed_ms": elapsed},
                raw={"mode": "free", "fallback": True},
            )
        scene_id, current = _extract_current_spec(user_text)
        intents = _match_intents(user_text)
        delta = _apply_delta(scene_id, current, intents)

        light_intent = _lighting_intent(user_text)
        if light_intent == "warm":
            delta["lighting_preset"] = LIGHTING_WARM.get(scene_id, "mixed")
        elif light_intent == "cool":
            delta["lighting_preset"] = LIGHTING_COOL.get(scene_id, "cool_white")
        elif light_intent == "default":
            delta["lighting_preset"] = LIGHTING_DEFAULT.get(scene_id, "warehouse_sodium")

        # Per-noun count extraction: each count param looks for "N <unit>? <noun>"
        # in its own neighborhood, so '加 2 个工人, 4 台叉车' resolves cleanly to
        # worker_count=2 + forklift_count=4 instead of fighting over the first N.
        for pat, key in [
            (r"(\d+)\s*(?:个|名|位)?\s*(?:工人|人员|操作员|worker)", "worker_count"),
            (r"(\d+)\s*(?:台|辆)?\s*(?:叉车|forklift)",             "forklift_count"),
            (r"(\d+)\s*(?:台)?\s*(?:机器|machine)",                  "machine_count"),
            (r"(\d+)\s*(?:个|只)?\s*(?:工具箱|板箱|箱|crate)",        "crate_count"),
        ]:
            m = re.search(pat, user_text)
            if m:
                delta[key] = _clamp(key, int(m.group(1)))

        # room dimensions: "30 米宽 / 40 米长 / 4 米层高"
        for pat, key in [
            (r"(\d+(?:\.\d+)?)\s*(?:米|m)?\s*宽", "room_w_m"),
            (r"(\d+(?:\.\d+)?)\s*(?:米|m)?\s*长", "room_l_m"),
            (r"层高\s*(\d+(?:\.\d+)?)",            "ceiling_h_m"),
        ]:
            m = re.search(pat, user_text)
            if m:
                delta[key] = _clamp(key, float(m.group(1)))
        # "30×40" / "30x40" sizing
        sz_match = re.search(r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)", user_text)
        if sz_match:
            delta["room_w_m"] = _clamp("room_w_m", float(sz_match.group(1)))
            delta["room_l_m"] = _clamp("room_l_m", float(sz_match.group(2)))

        rationale_parts = []
        if intents:
            rationale_parts.append(f"intents: {', '.join(intents)}")
        if light_intent:
            rationale_parts.append(f"lighting: {light_intent}")
        if not delta:
            rationale_parts.append("无可匹配关键词, 参数未变更")
        rationale = "; ".join(rationale_parts) + " [keyword fallback]"

        tool_name = "update_scene"
        if isinstance(tool_choice, dict) and tool_choice.get("name"):
            tool_name = tool_choice["name"]
        elif tools:
            tool_name = tools[0].name

        args = {
            "scene_id": scene_id,
            "pcg_params": delta,
            "rationale": rationale,
        }
        elapsed = int((time.time() - t0) * 1000)
        return ChatResponse(
            text="",
            tool_calls=[ToolCall(id=f"kw-{int(time.time() * 1000)}", name=tool_name, arguments=args)],
            finish_reason="tool_use",
            usage={"elapsed_ms": elapsed},
            raw={"intents": intents, "lighting": light_intent},
        )
