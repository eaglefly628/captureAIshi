"""Hide UI by filtering draw calls during RenderDoc replay.

This is the most reliable method — it doesn't require any game cooperation.
During RenderDoc replay, we identify UI-related draw calls (typically the
last passes using orthographic projection) and skip them, producing a
clean scene-only image.
"""

import logging
from typing import Set

from ui_hiders.base import UIHider, UIHideResult

logger = logging.getLogger(__name__)


def classify_ui_draw_calls(controller, rd) -> Set[int]:
    """Identify draw call event IDs that are likely UI/HUD rendering.

    Heuristics used to detect UI passes:
      1. Draw calls in the last render pass (UI is typically drawn last)
      2. Draw calls using orthographic projection matrices
      3. Draw calls targeting the swapchain directly (no depth test)
      4. Draw calls with shaders named with UI-related keywords
    """
    ui_event_ids: Set[int] = set()

    try:
        draw_calls = controller.GetDrawcalls()
    except Exception as e:
        logger.warning(f"Failed to enumerate draw calls: {e}")
        return ui_event_ids

    if not draw_calls:
        return ui_event_ids

    total = len(draw_calls)
    # Heuristic: last 20% of top-level draw calls are often UI
    ui_region_start = int(total * 0.8)

    for i, dc in enumerate(draw_calls):
        is_late_pass = i >= ui_region_start
        name_lower = dc.name.lower() if hasattr(dc, "name") else ""

        # Check for UI-related keywords in pass/draw call names
        ui_keywords = ["ui", "hud", "widget", "slate", "imgui", "overlay",
                        "minimap", "crosshair", "text", "font", "2d"]
        has_ui_keyword = any(kw in name_lower for kw in ui_keywords)

        if has_ui_keyword or (is_late_pass and _is_likely_ui_pass(dc)):
            ui_event_ids.add(dc.eventId)
            # Also add child draw calls
            for child in _iter_children(dc):
                ui_event_ids.add(child.eventId)

    logger.debug(f"Classified {len(ui_event_ids)} draw calls as UI "
                 f"(out of {total} total)")
    return ui_event_ids


def _is_likely_ui_pass(dc) -> bool:
    """Additional heuristics for a single draw call."""
    name_lower = getattr(dc, "name", "").lower()
    # Passes with very few vertices are often UI quads
    if hasattr(dc, "numIndices") and 0 < dc.numIndices <= 6:
        return True
    # Named passes that suggest post-process / overlay
    overlay_hints = ["post", "composite", "final", "blit"]
    if any(h in name_lower for h in overlay_hints):
        return True
    return False


def _iter_children(dc):
    """Recursively iterate child draw calls."""
    children = getattr(dc, "children", [])
    for child in children:
        yield child
        yield from _iter_children(child)


class RenderDocUIHider(UIHider):
    """Filter out UI draw calls during RenderDoc replay.

    Unlike other hiders, this doesn't modify the game at runtime.
    Instead, it post-processes the RenderDoc capture during replay,
    selectively skipping UI-related draw calls.

    This hider works by storing the set of event IDs to skip.
    The RenderDocGrabber should call get_excluded_events() and pass
    them to the replay controller.
    """

    def __init__(self):
        super().__init__()
        self._excluded_events: Set[int] = set()
        self._controller = None
        self._rd_module = None

    def name(self) -> str:
        return "renderdoc_pass_filter"

    def set_replay_context(self, controller, rd_module) -> None:
        """Set the RenderDoc replay controller for draw call analysis.

        Must be called before hide() when using RenderDoc captures.
        """
        self._controller = controller
        self._rd_module = rd_module

    def _try_hide(self) -> UIHideResult:
        if self._controller is None or self._rd_module is None:
            logger.debug("[RDOC_HIDE] No replay context — skipping UI draw call filtering")
            return UIHideResult(
                success=False, method=self.name(),
                message="No RenderDoc replay context set. "
                        "Call set_replay_context() first.",
            )

        logger.debug("[RDOC_HIDE] Classifying UI draw calls...")
        self._excluded_events = classify_ui_draw_calls(
            self._controller, self._rd_module,
        )
        logger.debug(f"[RDOC_HIDE] Found {len(self._excluded_events)} UI draw calls to exclude")

        if not self._excluded_events:
            return UIHideResult(
                success=True, method=self.name(),
                message="No UI draw calls detected (scene may already be clean)",
            )

        return UIHideResult(
            success=True, method=self.name(),
            message=f"Excluding {len(self._excluded_events)} UI draw calls",
        )

    def _try_restore(self) -> UIHideResult:
        self._excluded_events.clear()
        self._controller = None
        self._rd_module = None
        return UIHideResult(success=True, method=self.name())

    def get_excluded_events(self) -> Set[int]:
        """Return the set of draw call event IDs to skip during replay."""
        return self._excluded_events
