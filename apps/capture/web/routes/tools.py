"""Tools endpoints: RDC file analysis (--dump-all texture export)."""

import re
import subprocess
from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory

from grabbers.renderdoc.paths import resolve_renderdoccmd
from web.demo import canned_tools_analyze, is_demo_mode

bp = Blueprint("tools", __name__)

_ANALYZE_DIR = Path("output/_analyze")


@bp.route("/api/tools/analyze_rdc", methods=["POST"])
def tools_analyze_rdc():
    """Run renderdoccmd exportframe --dump-all on an .rdc file.

    Returns a list of color target textures with indices, formats, and
    thumbnail URLs so the UI can let the user assign rgb/normal/depth roles.

    JSON body: {rdc_path: str, renderdoc_path?: str}
    """
    if is_demo_mode():
        return jsonify(canned_tools_analyze()), 503
    body = request.get_json(silent=True) or {}
    rdc_path_str = body.get("rdc_path", "").strip()
    if not rdc_path_str:
        return jsonify({"ok": False, "error": "rdc_path required"}), 400
    rdc_path = Path(rdc_path_str)
    if not rdc_path.exists():
        return jsonify({"ok": False, "error": f"File not found: {rdc_path}"}), 404

    renderdoc_path = body.get("renderdoc_path", "renderdoccmd").strip() or "renderdoccmd"
    try:
        rdoc_cmd = resolve_renderdoccmd(renderdoc_path)
    except FileNotFoundError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    out_dir = _ANALYZE_DIR / rdc_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [rdoc_cmd, "exportframe", "--dump-all", "-o", str(out_dir), str(rdc_path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Analysis timed out (>120s)"}), 500

    stdout = result.stdout or ""
    # Parse: "OK colortarget_0 [3] 1920x1080 fmt=2 -> /path/ct_3.png"
    ct_pat = re.compile(r"OK colortarget_(\d+) \[(\d+)\] (\d+)x(\d+) fmt=(\d+) -> (.+)")
    textures = []
    for line in stdout.splitlines():
        m = ct_pat.match(line.strip())
        if m:
            ct_idx, tex_idx, w, h, fmt, fpath = m.groups()
            fname = Path(fpath).name
            textures.append({
                "ct_index": int(ct_idx),
                "tex_index": int(tex_idx),
                "width": int(w),
                "height": int(h),
                "fmt": int(fmt),
                "filename": fname,
                "img_url": f"/api/tools/analyze_img/{rdc_path.stem}/{fname}",
            })

    return jsonify({
        "ok": True,
        "textures": textures,
        "stdout": stdout[-3000:] if len(stdout) > 3000 else stdout,
        "rdc_stem": rdc_path.stem,
    })


@bp.route("/api/tools/analyze_img/<stem>/<filename>")
def tools_analyze_img(stem: str, filename: str):
    """Serve a texture image from a previous analyze_rdc run."""
    out_dir = (_ANALYZE_DIR / stem).resolve()
    base = _ANALYZE_DIR.resolve()
    if not out_dir.is_relative_to(base):
        return jsonify({"error": "Invalid path"}), 403
    return send_from_directory(str(out_dir), filename)
