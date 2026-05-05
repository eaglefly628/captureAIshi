"""Record mouse and keyboard events with timestamps.

Usage::
    rec = InputRecorder(output_dir=Path("output/ue5_obs"))
    rec.start()
    # ... user plays game ...
    path = rec.stop()  # returns Path to saved JSON
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


class InputRecorder:
    """Listens to system mouse + keyboard events and saves them to JSON.

    Falls back to a no-op stub when pynput is unavailable so the server
    still starts cleanly on machines without pynput installed.
    """

    def __init__(self, output_dir: Path = Path("output/ue5_obs")) -> None:
        self.output_dir = Path(output_dir)
        self._events: List[dict] = []
        self._t0: Optional[float] = None
        self._mouse_listener = None
        self._kbd_listener = None
        self._lock = threading.Lock()
        self._recording = False
        self._last_mouse: Optional[tuple] = None

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def event_count(self) -> int:
        with self._lock:
            return len(self._events)

    @property
    def elapsed(self) -> float:
        if self._t0 is None:
            return 0.0
        return time.monotonic() - self._t0

    def start(self) -> None:
        if self._recording:
            return
        self._events = []
        self._t0 = time.monotonic()
        self._last_mouse = None
        self._recording = True
        self._attach_listeners()

    def stop(self) -> Optional[Path]:
        if not self._recording:
            return None
        self._recording = False
        self._detach_listeners()
        return self._save()

    # ── Listener attachment ───────────────────────────────────────────────────

    def _attach_listeners(self) -> None:
        try:
            from pynput import mouse as _mouse, keyboard as _kbd  # type: ignore
        except ImportError:
            return  # no pynput → silent no-op; events stay empty

        self._mouse_listener = _mouse.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self._kbd_listener = _kbd.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._mouse_listener.start()
        self._kbd_listener.start()

    def _detach_listeners(self) -> None:
        for listener in (self._mouse_listener, self._kbd_listener):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:
                    pass
        self._mouse_listener = None
        self._kbd_listener = None

    # ── Event callbacks ───────────────────────────────────────────────────────

    def _ts(self) -> float:
        return round(time.monotonic() - (self._t0 or 0), 4)

    def _push(self, ev: dict) -> None:
        with self._lock:
            self._events.append(ev)

    def _on_move(self, x: int, y: int) -> None:
        if not self._recording:
            return
        prev = self._last_mouse
        self._last_mouse = (x, y)
        if prev is None:
            return
        dx, dy = x - prev[0], y - prev[1]
        if dx == 0 and dy == 0:
            return
        self._push({"t": self._ts(), "type": "mouse_move", "dx": dx, "dy": dy})

    def _on_click(self, x: int, y: int, button, pressed: bool) -> None:
        if not self._recording:
            return
        try:
            btn_name = button.name
        except AttributeError:
            btn_name = str(button)
        self._push({
            "t": self._ts(),
            "type": "mouse_down" if pressed else "mouse_up",
            "button": btn_name,
        })

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        if not self._recording:
            return
        self._push({"t": self._ts(), "type": "scroll", "dx": dx, "dy": dy})

    def _on_key_press(self, key) -> None:
        if not self._recording:
            return
        self._push({"t": self._ts(), "type": "key_down", "key": _key_name(key)})

    def _on_key_release(self, key) -> None:
        if not self._recording:
            return
        self._push({"t": self._ts(), "type": "key_up", "key": _key_name(key)})

    # ── Serialisation ─────────────────────────────────────────────────────────

    def _save(self) -> Optional[Path]:
        with self._lock:
            events = list(self._events)
        if not events:
            return None
        duration = events[-1]["t"] if events else 0.0
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"input_{ts}.json"
        payload = {
            "type": "input_recording",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "duration_s": duration,
            "event_count": len(events),
            "events": events,
        }
        path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        return path


def _key_name(key) -> str:
    try:
        return key.char or key.name
    except AttributeError:
        try:
            return key.name
        except AttributeError:
            return str(key)
