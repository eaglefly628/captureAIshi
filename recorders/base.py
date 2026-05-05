"""Abstract recorder + null fallback."""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class BaseRecorder(ABC):
    """Interface for gameplay video recorders.

    Lifecycle mirrors FrameGrabber: ``__enter__`` connects/launches, ``start``
    begins recording, ``stop`` finalises and writes ``video_metadata.json``,
    ``__exit__`` disconnects/kills.
    """

    @abstractmethod
    def start(self, session_name: str) -> None:
        """Begin recording. Must be idempotent if already recording."""

    @abstractmethod
    def stop(self) -> Optional[Path]:
        """Finalise recording. Returns the saved video file path, or None."""

    @property
    @abstractmethod
    def is_recording(self) -> bool:
        ...

    def get_status(self) -> dict:
        return {"recording": self.is_recording}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.is_recording:
            try:
                self.stop()
            except Exception as e:
                logger.warning(f"[VIDEO] stop() during __exit__ failed: {e}")
        return False


class NullRecorder(BaseRecorder):
    """No-op recorder used when video is disabled or OBS is unreachable."""

    def __init__(self, reason: str = "disabled"):
        self._reason = reason

    def start(self, session_name: str) -> None:
        logger.info(f"[VIDEO] disabled: {self._reason}")

    def stop(self) -> Optional[Path]:
        return None

    @property
    def is_recording(self) -> bool:
        return False
