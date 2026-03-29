"""Hide UI via game console commands (UE5/Unity with console access)."""

import logging
import socket
import time

from ui_hiders.base import UIHider, UIHideResult

logger = logging.getLogger(__name__)

# Common console commands to hide UI per engine
UE5_HIDE_COMMANDS = [
    "ShowFlag.PostProcessing 2",
    "stat none",
    "ShowHUD 0",
]
UE5_RESTORE_COMMANDS = [
    "ShowHUD 1",
]

UNITY_HIDE_COMMAND = '{"cmd":"set_ui_visible","visible":false}'
UNITY_RESTORE_COMMAND = '{"cmd":"set_ui_visible","visible":true}'


class ConsoleUIHider(UIHider):
    """Hide UI by sending console commands over TCP.

    Works with UE5 games that have console access via the captureAIshi
    bridge DLL, or Unity games with the companion BepInEx plugin.
    """

    def __init__(
        self,
        engine: str = "ue5",
        host: str = "127.0.0.1",
        port: int = 9998,
        timeout: float = 3.0,
    ):
        super().__init__()
        self.engine = engine
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None

    def name(self) -> str:
        return f"console_{self.engine}"

    def _get_socket(self) -> socket.socket | None:
        """Get or create a persistent TCP connection."""
        if self._sock is not None:
            try:
                # Check if socket is still alive
                self._sock.sendall(b"")
                return self._sock
            except OSError:
                self._close_socket()

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))
            self._sock = sock
            return self._sock
        except (ConnectionRefusedError, socket.timeout, OSError) as e:
            logger.debug(f"Console connection failed: {e}")
            return None

    def _close_socket(self):
        """Close the persistent socket."""
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _send_commands(self, commands: list) -> bool:
        """Send console commands over TCP. Returns True on success."""
        sock = self._get_socket()
        if sock is None:
            return False
        try:
            for cmd in commands:
                sock.sendall((cmd + "\n").encode("utf-8"))
                time.sleep(0.05)
            return True
        except (ConnectionRefusedError, socket.timeout, OSError) as e:
            logger.debug(f"Console command failed: {e}")
            self._close_socket()
            return False

    def _try_hide(self) -> UIHideResult:
        if self.engine == "ue5":
            commands = UE5_HIDE_COMMANDS
        elif self.engine == "unity":
            commands = [UNITY_HIDE_COMMAND]
        else:
            logger.debug(f"[CONSOLE_HIDE] Unknown engine: {self.engine}")
            return UIHideResult(
                success=False, method=self.name(),
                message=f"Unknown engine: {self.engine}",
            )

        logger.debug(f"[CONSOLE_HIDE] Sending {len(commands)} hide commands to "
                     f"{self.engine} at {self.host}:{self.port}")
        ok = self._send_commands(commands)
        if ok:
            logger.info(f"UI hidden via {self.engine} console commands")
            return UIHideResult(success=True, method=self.name())

        logger.debug(f"[CONSOLE_HIDE] Failed to connect to {self.engine} console")
        return UIHideResult(
            success=False, method=self.name(),
            message="Could not connect to game console",
        )

    def _try_restore(self) -> UIHideResult:
        if self.engine == "ue5":
            commands = UE5_RESTORE_COMMANDS
        elif self.engine == "unity":
            commands = [UNITY_RESTORE_COMMAND]
        else:
            self._close_socket()
            return UIHideResult(success=False, method=self.name())

        ok = self._send_commands(commands)
        self._close_socket()
        return UIHideResult(success=ok, method=self.name())
