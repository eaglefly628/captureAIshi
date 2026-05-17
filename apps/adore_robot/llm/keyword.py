"""Offline keyword fallback: heuristic NL -> tool_call mapping.

Activated when no provider API key is detected. Allows demo to run
without internet / API costs. Pattern: lookup table of (regex -> param
delta) per scene_id. Returns same ChatResult shape as real providers.
"""

from __future__ import annotations

import re
import time

from .base import BaseLLMClient, ChatResult, ToolCall, ToolSpec

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
}


def _clamp(name: str, val):
    lo, hi = RANGES.get(name, (None, None))
    if lo is None:
        return val
    if isinstance(val, int):
        return max(int(lo), min(int(hi), val))
    return max(lo, min(hi, float(val)))


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


class KeywordFallbackClient(BaseLLMClient):
    provider = "keyword"
    model = "offline-heuristic-v1"

    def chat_with_tools(
        self,
        system: str,
        user: str,
        tools: list[ToolSpec],
        force_tool: str | None = None,
        max_tokens: int = 1024,
    ) -> ChatResult:
        t0 = time.time()

        match = re.search(r'scene_id["\s:=]+(\w+)', user)
        scene_id = match.group(1) if match else "warehouse"

        current = {}
        try:
            import json as _json
            cur_match = re.search(r"current_spec[^{]*({.*?})(?=\n|$)", user, re.DOTALL)
            if cur_match:
                current = _json.loads(cur_match.group(1)).get("pcg_params", {})
        except Exception:
            pass

        intents = _match_intents(user)
        delta = _apply_delta(scene_id, current, intents)

        light_intent = _lighting_intent(user)
        if light_intent == "warm":
            delta["lighting_preset"] = LIGHTING_WARM.get(scene_id, "mixed")
        elif light_intent == "cool":
            delta["lighting_preset"] = LIGHTING_COOL.get(scene_id, "cool_white")
        elif light_intent == "default":
            delta["lighting_preset"] = LIGHTING_DEFAULT.get(scene_id, "warehouse_sodium")

        num_match = re.search(r"(\d+)\s*(?:台|个|只|份)", user)
        if num_match:
            n = int(num_match.group(1))
            if "forklift" in user or "叉车" in user:
                delta["forklift_count"] = _clamp("forklift_count", n)
            elif "machine" in user or "机器" in user:
                delta["machine_count"] = _clamp("machine_count", n)
            elif "crate" in user or "工具箱" in user or "板箱" in user:
                delta["crate_count"] = _clamp("crate_count", n)

        rationale_parts = []
        if intents:
            rationale_parts.append(f"intents: {', '.join(intents)}")
        if light_intent:
            rationale_parts.append(f"lighting: {light_intent}")
        if not delta:
            rationale_parts.append("no actionable keyword matched; spec unchanged")

        tool_name = force_tool or (tools[0].name if tools else "update_scene")
        args = {
            "scene_id": scene_id,
            "pcg_params": delta,
            "rationale": "; ".join(rationale_parts) + " [keyword fallback]",
        }

        return ChatResult(
            provider=self.provider,
            model=self.model,
            tool_calls=[ToolCall(name=tool_name, arguments=args, rationale=args["rationale"])],
            text="",
            elapsed_ms=int((time.time() - t0) * 1000),
            raw={"intents": intents, "lighting": light_intent},
        )
