"""No-op UI hider — marks frames as having UI present without removing it."""

import logging

from ui_hiders.base import UIHider, UIHideResult

logger = logging.getLogger(__name__)


class NoopUIHider(UIHider):
    """Fallback that does nothing but marks frames as ui_present=True.

    Used as the terminal node in the fallback chain so the pipeline
    always has a valid hider and captured metadata accurately reflects
    that UI was NOT removed.
    """

    def name(self) -> str:
        return "noop"

    def _try_hide(self) -> UIHideResult:
        logger.warning(
            "No UI hiding method available — frames will contain HUD/UI. "
            "Metadata will be tagged with ui_removed=false."
        )
        return UIHideResult(
            success=True, method=self.name(),
            message="UI not removed (no method available)",
        )

    def _try_restore(self) -> UIHideResult:
        return UIHideResult(success=True, method=self.name())
