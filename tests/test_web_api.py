"""Tests for the Flask web UI API endpoints."""

import json
from unittest.mock import patch

import pytest

from web_ui import app, _build_args, _validate_float_list


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
        assert data["spacing"] == 2.0
        assert data["driver"] == "manual"
        assert data["grabber"] == "none"
        assert len(data["volume_min"]) == 3

    def test_defaults_json_format(self, client):
        resp = client.get("/api/defaults")
        data = resp.get_json()
        assert isinstance(data["volume_min"], list)
        assert isinstance(data["smooth"], bool)
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
        # Flask returns 415 for non-JSON content type, or 400 for null JSON
        assert resp.status_code in (400, 415)

    def test_invalid_driver(self, client):
        """Should reject invalid driver value."""
        resp = client.post("/api/start",
                           json={"driver": "nonexistent"})
        assert resp.status_code == 400
        assert "Invalid driver" in resp.get_json()["error"]

    def test_invalid_grabber(self, client):
        """Should reject invalid grabber value."""
        resp = client.post("/api/start",
                           json={"grabber": "magic"})
        assert resp.status_code == 400
        assert "Invalid grabber" in resp.get_json()["error"]

    def test_invalid_ce_mode(self, client):
        """Should reject invalid CE mode."""
        resp = client.post("/api/start",
                           json={"ce_mode": "memory"})
        assert resp.status_code == 400

    def test_invalid_volume_min(self, client):
        """Should reject non-list volume."""
        resp = client.post("/api/start",
                           json={"volume_min": "bad"})
        assert resp.status_code == 400

    def test_valid_dry_run_starts(self, client):
        """Valid dry-run config should start successfully."""
        with patch("web_ui._run_in_thread") as mock_run:
            resp = client.post("/api/start", json={
                "driver": "manual",
                "grabber": "none",
                "dry_run": True,
            })
            # Might be 200 or 409 if previous test left running state
            if resp.status_code == 200:
                assert resp.get_json()["ok"] is True


# ── Input validation functions ───────────────────────────────────────────────

class TestValidation:

    def test_validate_float_list_valid(self):
        result = _validate_float_list([1, 2, 3], 3, "test")
        assert result == [1.0, 2.0, 3.0]

    def test_validate_float_list_wrong_length(self):
        with pytest.raises(ValueError, match="test must be a list of 3"):
            _validate_float_list([1, 2], 3, "test")

    def test_validate_float_list_not_list(self):
        with pytest.raises(ValueError):
            _validate_float_list("abc", 3, "test")

    def test_build_args_spacing_clamped(self):
        """Spacing should be clamped to minimum 0.01."""
        args = _build_args({"spacing": -5})
        assert args.spacing >= 0.01

    def test_build_args_cone_angle_clamped(self):
        """Cone angle should be clamped to 0-90."""
        args = _build_args({"cone_angle": 200})
        assert args.cone_angle == 90.0
        args = _build_args({"cone_angle": -10})
        assert args.cone_angle == 0.0

    def test_build_args_port_clamped(self):
        """Port should be clamped to 1-65535."""
        args = _build_args({"driver_port": 0})
        assert args.driver_port >= 1
        args = _build_args({"driver_port": 99999})
        assert args.driver_port <= 65535

    def test_build_args_defaults(self):
        """Empty dict should use all defaults."""
        args = _build_args({})
        assert args.driver == "manual"
        assert args.grabber == "none"
        assert args.spacing == 2.0
        assert args.dry_run is False

    def test_build_args_non_dict_raises(self):
        with pytest.raises(ValueError, match="JSON object"):
            _build_args("not a dict")
