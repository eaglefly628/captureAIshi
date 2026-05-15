"""Tests for the UI hider fallback chain."""

import pytest

from ui_hiders.base import UIHider, UIHideResult
from ui_hiders.noop_hider import NoopUIHider
from ui_hiders.chain import build_ui_hider_chain


class SuccessHider(UIHider):
    """Test hider that always succeeds."""

    def name(self):
        return "success"

    def _try_hide(self):
        return UIHideResult(success=True, method=self.name())

    def _try_restore(self):
        return UIHideResult(success=True, method=self.name())


class FailHider(UIHider):
    """Test hider that always fails."""

    def name(self):
        return "fail"

    def _try_hide(self):
        return UIHideResult(success=False, method=self.name(), message="nope")

    def _try_restore(self):
        return UIHideResult(success=False, method=self.name())


class TestFallbackChain:
    def test_single_success(self):
        hider = SuccessHider()
        result = hider.hide()
        assert result.success
        assert result.method == "success"

    def test_fallback_on_failure(self):
        head = FailHider()
        head.set_fallback(SuccessHider())

        result = head.hide()
        assert result.success
        assert result.method == "success"

    def test_all_fail_returns_last_failure(self):
        h1 = FailHider()
        h2 = FailHider()
        h1.set_fallback(h2)

        result = h1.hide()
        assert not result.success

    def test_restore_only_active(self):
        head = FailHider()
        tail = SuccessHider()
        head.set_fallback(tail)

        head.hide()
        assert tail._active
        assert not head._active

        result = head.restore()
        assert result.success
        assert result.method == "success"

    def test_active_method(self):
        head = FailHider()
        tail = SuccessHider()
        head.set_fallback(tail)

        head.hide()
        assert head.active_method == "success"

    def test_noop_always_succeeds(self):
        hider = NoopUIHider()
        result = hider.hide()
        assert result.success
        assert result.method == "noop"


class TestBuildChain:
    def test_no_engine_no_renderdoc(self):
        """With nothing available, should get noop."""
        chain = build_ui_hider_chain(engine=None, use_renderdoc=False)
        assert isinstance(chain, NoopUIHider)

    def test_with_engine_builds_console_first(self):
        chain = build_ui_hider_chain(engine="ue5", use_renderdoc=False)
        assert chain.name() == "console_ue5"
        assert chain._fallback is not None
        assert isinstance(chain._fallback, NoopUIHider)

    def test_with_renderdoc(self):
        chain = build_ui_hider_chain(engine=None, use_renderdoc=True)
        assert chain.name() == "renderdoc_pass_filter"

    def test_full_chain(self):
        chain = build_ui_hider_chain(engine="unity", use_renderdoc=True)
        assert chain.name() == "console_unity"
        assert chain._fallback.name() == "renderdoc_pass_filter"
        assert isinstance(chain._fallback._fallback, NoopUIHider)
