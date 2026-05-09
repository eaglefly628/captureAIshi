"""Tests for grabbers.reshade_grabber.ReShadeGrabber.

Covers the parts that don't need a real running game:
  - sidecar write / cleanup
  - newest-prefix detection in the output dir
  - quiescence wait correctly distinguishes growing-file from stable-file
  - save_frame copies addon-produced files instead of re-encoding arrays
  - readiness gate honours the timeout when the bridge port is closed

The frame load path (PIL/cv2 reading real BMP/EXR) is left for an
integration test that runs after a Phase 2 build on Windows.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from grabbers.reshade_grabber import ReShadeGrabber


# ── helpers ──────────────────────────────────────────────────────────────


def _make_grabber(tmp_path: Path, *, bridge_port=None, **kw) -> ReShadeGrabber:
    game = tmp_path / "game"
    out = tmp_path / "out"
    game.mkdir()
    return ReShadeGrabber(
        output_dir=out, game_dir=game,
        bridge_port=bridge_port,
        readiness_timeout_s=0.05,
        poll_interval_s=0.005,
        poll_timeout_s=0.5,
        **kw,
    )


def _touch(path: Path, content: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


# ── lifecycle ─────────────────────────────────────────────────────────────


def test_setup_writes_sidecar_and_teardown_removes_it(tmp_path):
    g = _make_grabber(tmp_path)
    g.setup()

    sidecar = g.game_dir / "fc_output_dir.txt"
    assert sidecar.exists()
    assert sidecar.read_text(encoding="utf-8").strip() == str(g.output_dir.resolve())

    g.teardown()
    assert not sidecar.exists()


def test_setup_warns_when_sidecar_targets_different_dir(tmp_path, caplog):
    g = _make_grabber(tmp_path)
    sidecar = g.game_dir / "fc_output_dir.txt"
    sidecar.write_text("D:/some/other/dir", encoding="utf-8")

    import logging
    with caplog.at_level(logging.WARNING):
        g.setup()
    assert any("already targets" in rec.message for rec in caplog.records)
    # And we still overwrote it.
    assert sidecar.read_text(encoding="utf-8").strip() == str(g.output_dir.resolve())


def test_setup_raises_when_game_dir_missing(tmp_path):
    g = ReShadeGrabber(
        output_dir=tmp_path / "out",
        game_dir=tmp_path / "does-not-exist",
        bridge_port=None,
    )
    with pytest.raises(FileNotFoundError):
        g.setup()


# ── prefix detection ─────────────────────────────────────────────────────


def test_latest_prefix_returns_newest_color_file(tmp_path):
    g = _make_grabber(tmp_path)
    g.output_dir.mkdir()

    # Two triplets, one older one newer (mtimes set explicitly).
    older_color = g.output_dir / "Game.exe 2026-05-09 10-00-00 000 BackBuffer.png"
    newer_color = g.output_dir / "Game.exe 2026-05-09 10-00-01 500 BackBuffer.png"
    _touch(older_color)
    _touch(newer_color)

    now = time.time()
    older_color.touch()
    import os
    os.utime(older_color, (now - 10, now - 10))
    os.utime(newer_color, (now, now))

    assert g._latest_prefix() == "Game.exe 2026-05-09 10-00-01 500"


def test_latest_prefix_ignores_non_color_files(tmp_path):
    g = _make_grabber(tmp_path)
    g.output_dir.mkdir()
    _touch(g.output_dir / "stray.txt")
    _touch(g.output_dir / "Game.exe 2026-05-09 10-00-00 000 DepthBuffer.exr")
    assert g._latest_prefix() is None


def test_latest_prefix_handles_bmp_and_png(tmp_path):
    g = _make_grabber(tmp_path)
    g.output_dir.mkdir()
    _touch(g.output_dir / "Game.exe T1 BackBuffer.bmp")
    _touch(g.output_dir / "Game.exe T2 BackBuffer.png")
    import os, time as _t
    os.utime(g.output_dir / "Game.exe T1 BackBuffer.bmp", (_t.time() - 10,) * 2)
    assert g._latest_prefix() == "Game.exe T2"


# ── candidate paths ──────────────────────────────────────────────────────


def test_candidate_paths_includes_only_existing_files(tmp_path):
    g = _make_grabber(tmp_path)
    g.output_dir.mkdir()
    prefix = "Game.exe T1"
    _touch(g.output_dir / f"{prefix} BackBuffer.png")
    _touch(g.output_dir / f"{prefix} DepthBuffer.exr")
    # Normal intentionally absent.

    cand = g._candidate_paths(prefix)
    assert set(cand) == {"rgb", "depth"}
    assert cand["rgb"].name == f"{prefix} BackBuffer.png"


# ── quiescence ───────────────────────────────────────────────────────────


def test_wait_quiescent_returns_true_for_stable_files(tmp_path):
    g = _make_grabber(tmp_path, quiescence_samples=2)
    g.output_dir.mkdir()
    p = g.output_dir / "stable.bin"
    _touch(p, b"abcdefg")
    deadline = time.monotonic() + 1.0
    assert g._wait_quiescent({"rgb": p}, deadline) is True


def test_wait_quiescent_times_out_for_growing_file(tmp_path):
    g = _make_grabber(tmp_path, quiescence_samples=3)
    g.output_dir.mkdir()
    p = g.output_dir / "growing.bin"
    _touch(p, b"a")

    # Background "writer" growing the file faster than we sample.
    import threading
    stop = threading.Event()
    def grow():
        i = 0
        while not stop.is_set():
            i += 1
            try:
                with p.open("ab") as f:
                    f.write(b"x")
            except OSError:
                return
            time.sleep(0.005)
    t = threading.Thread(target=grow, daemon=True)
    t.start()
    try:
        deadline = time.monotonic() + 0.2
        ok = g._wait_quiescent({"rgb": p}, deadline)
    finally:
        stop.set()
        t.join(timeout=1.0)
    assert ok is False


def test_wait_quiescent_rejects_zero_size_file(tmp_path):
    g = _make_grabber(tmp_path, quiescence_samples=2)
    g.output_dir.mkdir()
    p = g.output_dir / "empty.bin"
    p.touch()  # 0 bytes
    deadline = time.monotonic() + 0.1
    # Two consecutive samples will still report size 0; we explicitly
    # require all sizes > 0, so this should time out.
    assert g._wait_quiescent({"rgb": p}, deadline) is False


def test_wait_quiescent_empty_dict_short_circuits(tmp_path):
    g = _make_grabber(tmp_path)
    deadline = time.monotonic() + 0.1
    assert g._wait_quiescent({}, deadline) is True


# ── save_frame override ──────────────────────────────────────────────────


def test_save_frame_copies_addon_files_when_paths_known(tmp_path):
    g = _make_grabber(tmp_path)
    g.output_dir.mkdir()
    rgb = g.output_dir / "Game.exe T BackBuffer.png"
    depth = g.output_dir / "Game.exe T DepthBuffer.exr"
    _touch(rgb, b"PNG-bytes")
    _touch(depth, b"EXR-bytes")
    g._last_paths = {"rgb": rgb, "depth": depth}

    out = tmp_path / "saved"
    saved = g.save_frame(
        rgb=None, depth=None, output_dir=out, frame_idx=0,
        base_name="pose_001",
    )

    assert saved == {"rgb": "pose_001.png", "depth": "pose_001_d.exr"}
    assert (out / "pose_001.png").read_bytes() == b"PNG-bytes"
    assert (out / "pose_001_d.exr").read_bytes() == b"EXR-bytes"


def test_save_frame_falls_back_to_base_when_no_paths(tmp_path):
    """When _last_paths is empty (e.g. arrays synthesised in tests), we
    must defer to base.save_frame which encodes via PIL."""
    import numpy as np
    g = _make_grabber(tmp_path)
    rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    out = tmp_path / "saved"
    saved = g.save_frame(
        rgb=rgb, depth=None, output_dir=out, frame_idx=7,
    )
    assert saved.get("rgb") == "rgb_000007.png"
    assert (out / "rgb_000007.png").exists()


# ── readiness gate ───────────────────────────────────────────────────────


def test_readiness_gate_returns_when_port_closed(tmp_path, caplog):
    """No server listening on the port -- gate should warn + return,
    not raise. setup() must still complete."""
    import logging, socket
    # Pick a port that's almost certainly unused.
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    closed_port = s.getsockname()[1]
    s.close()

    g = _make_grabber(tmp_path, bridge_port=closed_port)
    with caplog.at_level(logging.WARNING):
        g.setup()  # must not raise even though no bridge is up
    g.teardown()
    assert any("not reachable" in rec.message for rec in caplog.records)
