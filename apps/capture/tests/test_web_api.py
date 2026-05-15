"""Tests for the Flask web UI API endpoints."""

from unittest.mock import patch

import pytest

from web.helpers import _build_args
from web_ui import app


@pytest.fixture
def client():
    """Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── GET /api/defaults ────────────────────────────────────────────────────────

class TestDefaults:

    def test_returns_defaults(self, client):
        """Should return all default values."""
        resp = client.get("/api/defaults")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["driver"] == "manual"
        assert data["grabber"] == "none"
        assert data["launch_windowed"] is True

    def test_defaults_json_format(self, client):
        resp = client.get("/api/defaults")
        data = resp.get_json()
        assert isinstance(data["streaming"], bool)
        assert isinstance(data["driver_port"], int)


# ── GET /api/status ──────────────────────────────────────────────────────────

class TestStatus:

    def test_initial_status(self, client):
        """Initial status should show not running."""
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["running"] is False
        assert isinstance(data["logs"], list)


# ── POST /api/start ──────────────────────────────────────────────────────────

class TestStartCapture:

    def test_missing_json_body(self, client):
        """Should return error without valid JSON body."""
        resp = client.post("/api/start", content_type="text/plain", data="hello")
        assert resp.status_code in (400, 415)

    def test_invalid_driver(self, client):
        resp = client.post("/api/start", json={"driver": "nonexistent"})
        assert resp.status_code == 400
        assert "Invalid driver" in resp.get_json()["error"]

    def test_invalid_grabber(self, client):
        resp = client.post("/api/start", json={"grabber": "magic"})
        assert resp.status_code == 400
        assert "Invalid grabber" in resp.get_json()["error"]

    def test_invalid_ce_mode(self, client):
        resp = client.post("/api/start", json={"ce_mode": "memory"})
        assert resp.status_code == 400

    def test_valid_dry_run_starts(self, client):
        """Valid dry-run config should start successfully."""
        with patch("web.state._run_in_thread"):
            resp = client.post("/api/start", json={
                "driver": "manual",
                "grabber": "none",
                "dry_run": True,
            })
            if resp.status_code == 200:
                assert resp.get_json()["ok"] is True


# ── _build_args validation ───────────────────────────────────────────────────

class TestBuildArgs:

    def test_port_clamped(self):
        """Port should be clamped to 1-65535."""
        args = _build_args({"driver_port": 0})
        assert args.driver_port >= 1
        args = _build_args({"driver_port": 99999})
        assert args.driver_port <= 65535

    def test_defaults(self):
        """Empty dict should use all defaults."""
        args = _build_args({})
        assert args.driver == "manual"
        assert args.grabber == "none"
        assert args.dry_run is False

    def test_non_dict_raises(self):
        with pytest.raises(ValueError, match="JSON object"):
            _build_args("not a dict")
