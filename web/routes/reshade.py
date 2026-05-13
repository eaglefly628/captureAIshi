"""ReShade-specific endpoints (Path B vehicle).

Currently exposes one endpoint:
    POST /api/reshade/survey  -- trigger pre-UI skip survey on the live game.

Survey replaces the F6 overlay hotkey that the addon shows as a hint but
does not yet handle (xiaoxuan domain in frame_capture.cpp). Once the
addon learns F6, this endpoint stays useful for headless / CI flows.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify

bp = Blueprint("reshade", __name__)
logger = logging.getLogger(__name__)


@bp.route("/api/reshade/survey", methods=["POST"])
def reshade_survey():
    """Run pre-UI skip survey against the active ReShade grabber's game.

    Requires a running capture session (grabber instance must be live in
    web.state). The game must already be in actual 3D gameplay -- if
    you call this from the publisher logos or main menu, the survey
    returns no recommendation and you can retry once gameplay starts.

    On success: persists the recommended skip into
    ``<game_dir>/.captureAIshi_skip.txt``, rewrites unicap.ini, and
    bounces the game so the addon reads the new FC_PreUISkipCount.
    """
    try:
        from web.state import get_active_grabber
        from grabbers.reshade_grabber import ReShadeGrabber
    except ImportError as exc:
        return jsonify({"ok": False, "error": f"import: {exc}"}), 500

    grabber = get_active_grabber()
    if grabber is None:
        return jsonify({
            "ok": False,
            "error": "no active capture session; press Start first",
        }), 409
    if not isinstance(grabber, ReShadeGrabber):
        return jsonify({
            "ok": False,
            "error": (
                f"active grabber is {type(grabber).__name__}, not "
                "ReShadeGrabber; survey is ReShade-only"
            ),
        }), 409

    recommended = grabber.run_pre_ui_survey()
    if recommended is None:
        return jsonify({
            "ok": False,
            "error": (
                "survey returned no recommendation. Game may still be at "
                "the publisher logos / main menu / loading screen, or "
                "opencv-python is missing. Move into actual 3D gameplay "
                "and try again."
            ),
        }), 503

    return jsonify({
        "ok": True,
        "recommended_skip": int(recommended),
        "message": (
            f"survey complete: FC_PreUISkipCount={recommended} persisted. "
            "Game has been restarted to apply the new value -- move back "
            "into gameplay and start capture."
        ),
    })
