"""Abstract base class for UI hiding strategies."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class UIHideResult:
    """Result of a UI hide/restore operation."""

    success: bool
    method: str
    message: str = ""


class UIHider(ABC):
    """Interface for hiding in-game UI/HUD elements during capture.

    Implementations form a fallback chain: if one method fails,
    the next one in the chain is attempted.
    """

    def __init__(self):
        self._fallback: Optional["UIHider"] = None
        self._active: bool = False

    def set_fallback(self, fallback: "UIHider") -> "UIHider":
        """Chain a fallback hider. Returns the fallback for further chaining."""
        self._fallback = fallback
        return fallback

    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this hiding strategy."""

    @abstractmethod
    def _try_hide(self) -> UIHideResult:
        """Attempt to hide UI using this strategy."""

    @abstractmethod
    def _try_restore(self) -> UIHideResult:
        """Attempt to restore UI using this strategy."""

    def hide(self) -> UIHideResult:
        """Hide UI, falling back to next strategy on failure."""
        result = self._try_hide()
        if result.success:
            self._active = True
            return result

        if self._fallback:
            return self._fallback.hide()

        return result

    def restore(self) -> UIHideResult:
        """Restore UI that was previously hidden."""
        if self._active:
            self._active = False
            return self._try_restore()

        if self._fallback:
            return self._fallback.restore()

        return UIHideResult(success=True, method="none", message="Nothing to restore")

    @property
    def active_method(self) -> Optional[str]:
        """Return the name of the currently active hiding method."""
        if self._active:
            return self.name()
        if self._fallback:
            return self._fallback.active_method
        return None
