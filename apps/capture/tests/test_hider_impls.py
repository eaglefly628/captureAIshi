"""Tests for UI hider implementations (console + renderdoc)."""

import time
from unittest.mock import patch, MagicMock

import pytest

from ui_hiders.console_hider import ConsoleUIHider
from ui_hiders.renderdoc_hider import (
    RenderDocUIHider,
    classify_ui_draw_calls,
    _is_likely_ui_pass,
)


# ── ConsoleUIHider ───────────────────────────────────────────────────────────

class TestConsoleUIHider:

    def test_ue5_hide_sends_commands(self, echo_server):
        """UE5 hide should send ShowHUD 0 and stat none."""
        hider = ConsoleUIHider(
            engine="ue5",
            host="127.0.0.1",
            port=echo_server.port,
            timeout=2.0,
        )
        result = hider.hide()
        assert result.success
        assert result.method == "console_ue5"

        time.sleep(0.1)
        received = echo_server.received_text
        assert "ShowHUD 0" in received

    def test_ue5_restore_sends_commands(self, echo_server):
        """UE5 restore should send ShowHUD 1."""
        hider = ConsoleUIHider(
            engine="ue5",
            host="127.0.0.1",
            port=echo_server.port,
        )
        hider.hide()
        result = hider.restore()

        time.sleep(0.1)
        assert "ShowHUD 1" in echo_server.received_text

    def test_unity_hide_sends_json(self, echo_server):
        """Unity hide should send set_ui_visible JSON."""
        hider = ConsoleUIHider(
            engine="unity",
            host="127.0.0.1",
            port=echo_server.port,
        )
        result = hider.hide()
        assert result.success

        time.sleep(0.1)
        assert "set_ui_visible" in echo_server.received_text
        assert '"visible": false' in echo_server.received_text or \
               '"visible":false' in echo_server.received_text

    def test_connection_refused_returns_failure(self):
        """Should return failure when can't connect."""
        hider = ConsoleUIHider(
            engine="ue5",
            host="127.0.0.1",
            port=1,  # unlikely to have anything here
            timeout=0.5,
        )
        result = hider.hide()
        assert not result.success

    def test_unknown_engine_returns_failure(self):
        """Unknown engine should return failure."""
        hider = ConsoleUIHider(engine="godot")
        result = hider.hide()
        assert not result.success

    def test_socket_reuse(self, echo_server):
        """Multiple hide() calls should reuse the socket."""
        hider = ConsoleUIHider(
            engine="ue5",
            host="127.0.0.1",
            port=echo_server.port,
        )
        hider.hide()
        sock1 = hider._sock

        # Force another _send_commands call
        hider._send_commands(["test"])
        sock2 = hider._sock

        # Same socket should be reused
        assert sock1 is sock2
        hider.restore()

    def test_restore_closes_socket(self, echo_server):
        """restore() should close the persistent socket."""
        hider = ConsoleUIHider(
            engine="ue5",
            host="127.0.0.1",
            port=echo_server.port,
        )
        hider.hide()
        assert hider._sock is not None
        hider.restore()
        assert hider._sock is None


# ── RenderDocUIHider ─────────────────────────────────────────────────────────

class TestRenderDocUIHider:

    def test_without_context_fails(self):
        """hide() without replay context should fail."""
        hider = RenderDocUIHider()
        result = hider.hide()
        assert not result.success
        assert "set_replay_context" in result.message

    def test_name(self):
        assert RenderDocUIHider().name() == "renderdoc_pass_filter"

    def test_with_mock_controller(self):
        """Should classify draw calls when given a replay context."""
        hider = RenderDocUIHider()

        # Create mock controller with draw calls
        mock_controller = MagicMock()
        mock_rd = MagicMock()

        # Simulate 10 draw calls, last 2 named "UI"
        draw_calls = []
        for i in range(10):
            dc = MagicMock()
            dc.eventId = i
            dc.name = f"ScenePass_{i}" if i < 8 else f"UI_Overlay_{i}"
            dc.numIndices = 1000 if i < 8 else 4
            dc.children = []
            draw_calls.append(dc)

        mock_controller.GetDrawcalls.return_value = draw_calls
        hider.set_replay_context(mock_controller, mock_rd)
        result = hider.hide()
        assert result.success

        excluded = hider.get_excluded_events()
        # Events 8 and 9 should be excluded (UI keywords)
        assert 8 in excluded
        assert 9 in excluded
        # Scene events should NOT be excluded
        assert 0 not in excluded
        assert 5 not in excluded

    def test_restore_clears_state(self):
        """_try_restore() should clear excluded events and context."""
        hider = RenderDocUIHider()
        hider._excluded_events = {1, 2, 3}
        hider._controller = MagicMock()
        hider._rd_module = MagicMock()

        # Call _try_restore directly (restore() only calls it if hide was active)
        result = hider._try_restore()
        assert result.success
        assert len(hider.get_excluded_events()) == 0
        assert hider._controller is None
        assert hider._rd_module is None


# ── Draw call classification helpers ─────────────────────────────────────────

class TestDrawCallClassification:

    def test_is_likely_ui_small_draw(self):
        """Small draws (<=6 indices) should be flagged."""
        dc = MagicMock()
        dc.name = "something"
        dc.numIndices = 4  # quad
        assert _is_likely_ui_pass(dc) is True

    def test_is_likely_ui_post_process(self):
        """Post-process passes should be flagged."""
        dc = MagicMock()
        dc.name = "PostProcess_Final"
        dc.numIndices = 1000
        assert _is_likely_ui_pass(dc) is True

    def test_is_not_ui_large_scene_draw(self):
        """Large scene draws should NOT be flagged."""
        dc = MagicMock()
        dc.name = "StaticMesh_Draw"
        dc.numIndices = 50000
        assert _is_likely_ui_pass(dc) is False
