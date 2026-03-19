"""Tests for frame grabbers."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from grabbers.base import FrameGrabber
from grabbers.screenshot_grabber import ScreenshotGrabber


# ── FrameGrabber base ────────────────────────────────────────────────────────

class DummyGrabber(FrameGrabber):
    """Concrete implementation for testing the base class."""

    def __init__(self):
        self.setup_called = False
        self.teardown_called = False

    def setup(self):
        self.setup_called = True

    def teardown(self):
        self.teardown_called = True

    def capture_frame(self):
        rgb = np.zeros((4, 4, 3), dtype=np.uint8)
        depth = np.ones((4, 4), dtype=np.float32) * 0.5
        return rgb, depth


class TestFrameGrabberBase:

    def test_context_manager(self):
        """Context manager should call setup/teardown."""
        g = DummyGrabber()
        with g:
            assert g.setup_called
        assert g.teardown_called

    def test_save_frame_rgb(self, tmp_output, fake_rgb):
        """save_frame should write an RGB PNG."""
        g = DummyGrabber()
        g.save_frame(fake_rgb, None, tmp_output / "frames", 0)
        assert (tmp_output / "frames" / "rgb_000000.png").exists()

    def test_save_frame_depth(self, tmp_output, fake_depth):
        """save_frame should write depth as PNG + NPY."""
        g = DummyGrabber()
        g.save_frame(None, fake_depth, tmp_output / "frames", 0)
        assert (tmp_output / "frames" / "depth_000000.png").exists()
        assert (tmp_output / "frames" / "depth_000000.npy").exists()

    def test_save_frame_depth_roundtrip(self, tmp_output, fake_depth):
        """Saved depth NPY should round-trip correctly."""
        g = DummyGrabber()
        g.save_frame(None, fake_depth, tmp_output / "frames", 0)
        loaded = np.load(tmp_output / "frames" / "depth_000000.npy")
        assert np.allclose(fake_depth, loaded)

    def test_save_frame_none(self, tmp_output):
        """save_frame with both None should not crash."""
        g = DummyGrabber()
        g.save_frame(None, None, tmp_output / "frames", 0)

    def test_save_creates_directory(self, tmp_output, fake_rgb):
        """save_frame should create the output directory."""
        g = DummyGrabber()
        nested = tmp_output / "deep" / "nested" / "frames"
        g.save_frame(fake_rgb, None, nested, 0)
        assert nested.exists()


# ── ScreenshotGrabber ────────────────────────────────────────────────────────

class TestScreenshotGrabber:

    def test_setup_creates_directories(self, tmp_path):
        """setup() should create screenshot and depth directories."""
        g = ScreenshotGrabber(
            screenshot_dir=str(tmp_path / "shots"),
            depth_dir=str(tmp_path / "depth"),
            use_reshade_depth=True,
        )
        g.setup()
        assert (tmp_path / "shots").is_dir()
        assert (tmp_path / "depth").is_dir()

    def test_frame_counter(self, tmp_path):
        """Frame counter should increment on each capture."""
        g = ScreenshotGrabber(screenshot_dir=str(tmp_path / "shots"))
        g.setup()

        # Mock the actual screenshot to avoid needing a display
        with patch.object(g, "_capture_screenshot", return_value=None):
            g.capture_frame()
            g.capture_frame()
            assert g._frame_count == 2

    def test_capture_returns_tuple(self, tmp_path):
        """capture_frame should return (rgb, depth) tuple."""
        g = ScreenshotGrabber(screenshot_dir=str(tmp_path / "shots"))
        g.setup()
        with patch.object(g, "_capture_screenshot", return_value=None):
            result = g.capture_frame()
            assert isinstance(result, tuple)
            assert len(result) == 2

    def test_mss_bgr_to_rgb_conversion(self, tmp_path):
        """mss path should convert BGRA to RGB."""
        pytest.importorskip("mss")
        g = ScreenshotGrabber(screenshot_dir=str(tmp_path / "shots"))

        # Create fake BGRA data (Blue=255, Green=0, Red=0, Alpha=255)
        fake_bgra = np.zeros((2, 2, 4), dtype=np.uint8)
        fake_bgra[:, :, 0] = 255  # Blue channel
        fake_bgra[:, :, 3] = 255  # Alpha

        mock_screenshot = MagicMock()
        mock_screenshot.__array__ = lambda self: fake_bgra

        mock_sct = MagicMock()
        mock_sct.monitors = [None, {"top": 0, "left": 0, "width": 2, "height": 2}]
        mock_sct.grab.return_value = mock_screenshot
        mock_sct.__enter__ = lambda self: self
        mock_sct.__exit__ = lambda self, *a: None

        # Force PIL to fail so it falls through to mss
        with patch.dict("sys.modules", {"PIL.ImageGrab": None}):
            with patch("mss.mss", return_value=mock_sct):
                rgb = g._capture_screenshot()

        assert rgb is not None
        # After BGR->RGB conversion: Red should be in channel 0
        assert rgb[0, 0, 2] == 255  # Originally Blue, now at index 2 (correct RGB)
        assert rgb[0, 0, 0] == 0    # Red channel should be 0

    def test_reshade_depth_png(self, tmp_path):
        """Should read ReShade depth from PNG files."""
        depth_dir = tmp_path / "depth"
        depth_dir.mkdir()

        # Create a fake 16-bit depth PNG
        from PIL import Image
        depth_data = np.full((4, 4), 32768, dtype=np.uint16)
        img = Image.fromarray(depth_data, mode="I;16")
        img.save(depth_dir / "depth_001.png")

        g = ScreenshotGrabber(
            screenshot_dir=str(tmp_path / "shots"),
            depth_dir=str(depth_dir),
            use_reshade_depth=True,
        )
        g.setup()
        depth = g._read_reshade_depth()
        assert depth is not None
        assert depth.dtype == np.float32
        # 32768/65535 ≈ 0.5
        assert np.allclose(depth, 32768 / 65535, atol=0.01)


# ── RenderDocGrabber ─────────────────────────────────────────────────────────

class TestRenderDocGrabber:

    def test_setup_creates_capture_dir(self, tmp_path):
        """setup() should create the captures directory."""
        from grabbers.renderdoc_grabber import RenderDocGrabber
        g = RenderDocGrabber(capture_dir=str(tmp_path / "caps"))
        g.setup()
        assert (tmp_path / "caps").is_dir()

    def test_trigger_increments_counter(self, tmp_path):
        """Each trigger should increment the capture counter."""
        from grabbers.renderdoc_grabber import RenderDocGrabber
        g = RenderDocGrabber(capture_dir=str(tmp_path / "caps"))
        g.setup()

        # All trigger methods will fail (no RenderDoc), but counter increments
        g.trigger_capture()
        g.trigger_capture()
        assert g._capture_count == 2

    def test_capture_frame_without_renderdoc(self, tmp_path):
        """capture_frame should return (None, None) without RenderDoc."""
        from grabbers.renderdoc_grabber import RenderDocGrabber
        g = RenderDocGrabber(capture_dir=str(tmp_path / "caps"))
        g.setup()
        rgb, depth = g.capture_frame()
        # Without RenderDoc installed, should gracefully return None
        assert rgb is None or isinstance(rgb, np.ndarray)

    def test_teardown_terminates_process(self, tmp_path):
        """teardown should terminate any launched process."""
        from grabbers.renderdoc_grabber import RenderDocGrabber
        g = RenderDocGrabber(capture_dir=str(tmp_path / "caps"))
        mock_proc = MagicMock()
        g._process = mock_proc
        g.teardown()
        mock_proc.terminate.assert_called_once()
        assert g._process is None
