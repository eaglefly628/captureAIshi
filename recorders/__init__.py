"""Video recorders for captureAIshi gameplay capture.

Mirrors the ``grabbers/`` and ``drivers/`` packages: ``BaseRecorder`` is the
abstract interface, ``OBSRecorder`` drives OBS Studio over its WebSocket v5
protocol, ``NullRecorder`` is the no-op fallback used when video is disabled.
"""

from recorders.base import BaseRecorder, NullRecorder
from recorders.factory import create_recorder

__all__ = ["BaseRecorder", "NullRecorder", "create_recorder"]
