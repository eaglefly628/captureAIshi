"""Pre-UI skip survey (ported from unicap tools/capture/survey.py).

Auto-detects the FC_PreUISkipCount needed for pre-UI capture on a given
game. Game must already be running with our ReShade dxgi.dll deployed
(use UI Start with grabber=reshade first, then run this from another
terminal). The addon reads our sidecar files every frame.

Protocol (matches frame_capture.cpp sidecar reads):
  fc_skip_count.txt    Python -> addon, sets g_pre_ui_skip per-frame
  fc_pass_total.txt    addon -> Python, current frame's no-DSV-non-BB count
  fc_output_dir.txt    Python -> addon, where to drop survey_skip_NNN_*.png

Algorithm:
  Phase 1  probe with skip=0, learn pass-total from sidecar
  Phase 2  sweep skip from total-1 down to 0 (step configurable),
           wait for each survey_skip_NNN_BackBuffer.png to be written
  Phase 3  weighted frame-diff (HUD edges 2x weight); group consecutive
           "stable" pairs (diff < 3x median); pick lowest-skip end of the
           lowest stable group --> that is the last clean pre-UI frame

Usage:
  python -m tools.capture.survey \\
    --game-dir "C:/...Batman.../Binaries/Win64" \\
    --survey-dir "D:/captureAIshi/output/ue5_reshade/survey"
  Reads result from <survey-dir>/recommended_skip.txt or prints recommended
  value on stdout. Write it into unicap.ini ADDON section as
  FC_PreUISkipCount=N to make the next capture use the right value.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# cv2 / numpy are optional -- only Phase 3 needs them. Phase 1/2 (probe +
# sweep) run without them; they only fail when boundary analysis is requested.
try:
    import cv2  # type: ignore
    import numpy as np
    _HAS_CV2 = True
except ImportError:
    cv2 = None  # type: ignore
    np = None   # type: ignore
    _HAS_CV2 = False


def _write_skip(game_dir: Path, skip: int) -> None:
    (game_dir / "fc_skip_count.txt").write_text(str(skip), encoding="utf-8")


def _clear_skip(game_dir: Path) -> None:
    p = game_dir / "fc_skip_count.txt"
    try:
        p.unlink(missing_ok=True)
    except OSError:
        p.write_text("", encoding="utf-8")


def _read_pass_total(game_dir: Path) -> Optional[int]:
    p = game_dir / "fc_pass_total.txt"
    try:
        v = int(p.read_text(encoding="utf-8").strip())
        return v if v > 0 else None
    except (OSError, ValueError):
        return None


def _wait_for_bmp(survey_dir: Path, skip: int, timeout: float,
                  mtime_floor: float,
                  abort: Optional[threading.Event] = None) -> Optional[Path]:
    """Wait until survey_skip_NNN_BackBuffer.png appears with mtime >=
    mtime_floor (filters out stale files from previous runs)."""
    target_png = survey_dir / f"survey_skip_{skip:03d}_BackBuffer.png"
    target_bmp = survey_dir / f"survey_skip_{skip:03d}_BackBuffer.bmp"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if abort is not None and abort.is_set():
            return None
        for target in (target_png, target_bmp):
            try:
                if target.stat().st_mtime >= mtime_floor:
                    return target
            except OSError:
                pass
        time.sleep(0.3)
    return None


def _weighted_diff(img_a, img_b) -> float:
    """HUD-edge weighted mean abs diff. Top/bottom/left/right 1/8 weighted
    2x because that's where HUD bars typically live."""
    h, w = img_a.shape[:2]
    diff = np.abs(img_a.astype(float) - img_b.astype(float)).mean(axis=2)
    weight = np.ones((h, w), dtype=float)
    weight[: h // 8, :]      = 2.0
    weight[7 * h // 8 :, :]  = 2.0
    weight[:, : w // 10]     = 2.0
    weight[:, 9 * w // 10 :] = 2.0
    return float((diff * weight).mean())


def _find_boundary(captured: dict) -> int:
    """Pick recommended skip from captured triplets.

    Strategy: rendering tends to fall into 3 regions when sweeping skip
    from high to low: (1) very early -- mostly empty/black, low diffs;
    (2) main render region -- big diffs as geometry/lighting appears;
    (3) stable post-process region -- low diffs again, UI composites in
    the last few passes. Group consecutive "stable" diff pairs
    (diff < 3x median); reject groups that fall entirely in the upper
    half (empty early); from the remaining stable groups, pick the one
    with smallest s_lo -- that group's min s_lo is the recommended skip.
    """
    ordered = sorted(captured.keys(), reverse=True)
    images = {}
    for s in ordered:
        img = cv2.imread(str(captured[s]))
        if img is not None:
            images[s] = img

    if len(images) < 2:
        return max(images.keys()) if images else 0

    pairs = []
    for i in range(len(ordered) - 1):
        s_hi, s_lo = ordered[i], ordered[i + 1]
        if s_hi in images and s_lo in images:
            d = _weighted_diff(images[s_hi], images[s_lo])
            pairs.append((s_hi, s_lo, d))

    if not pairs:
        return ordered[-1]

    all_diffs = sorted(d for _, _, d in pairs)
    threshold = max(all_diffs[len(all_diffs) // 2] * 3.0, 3.0)

    # FF7R-like special case: if pair adjacent to skip=0 has diff much
    # larger than mid-range median, UI composites inside last non-BB RT
    # (not BB) -> skip=0 is the clean pre-UI frame.
    median_diff = all_diffs[len(all_diffs) // 2]
    adj_zero = next((p for p in pairs if p[1] == ordered[-1]), None)
    mid_diffs = sorted(d for _, _, d in pairs[1:-1]) if len(pairs) >= 3 else []
    mid_median = mid_diffs[len(mid_diffs) // 2] if mid_diffs else median_diff
    if adj_zero is not None and adj_zero[2] > 5.0 * max(mid_median, 1.0):
        return ordered[-1]

    groups = []
    current = []
    for pair in pairs:
        if pair[2] < threshold:
            current.append(pair)
        else:
            if current:
                groups.append(current)
            current = []
    if current:
        groups.append(current)

    if not groups:
        return ordered[0]

    mid = (ordered[0] + ordered[-1]) / 2
    late_groups = [g for g in groups if max(s_hi for s_hi, _, _ in g) < mid]
    if not late_groups:
        late_groups = groups

    best = min(late_groups, key=lambda g: min(s_lo for _, s_lo, _ in g))
    return min(s_lo for _, s_lo, _ in best)


def run(
    game_dir: Path,
    survey_dir: Path,
    step: int = 5,
    fps: float = 1.0,
    timeout_per_skip: float = 10.0,
    abort_event: Optional[threading.Event] = None,
) -> Optional[int]:
    """Run survey end-to-end. Returns recommended skip or None on
    failure (timeouts / abort / etc). Writes
    <survey_dir>/recommended_skip.txt on success."""
    if not _HAS_CV2:
        print("[SURVEY] opencv-python required (pip install opencv-python).",
              file=sys.stderr)
        return None

    survey_dir.mkdir(parents=True, exist_ok=True)
    capture_interval = 1.0 / max(fps, 0.1)
    wait_per_skip = max(2.5 * capture_interval, 2.0)

    fc_output_dir = game_dir / "fc_output_dir.txt"
    fc_pass_total = game_dir / "fc_pass_total.txt"
    try:
        fc_pass_total.unlink(missing_ok=True)
    except OSError:
        pass

    mtime_floor = time.time()

    # Phase 1: probe with skip=0 to learn pass total
    print("[SURVEY] Phase 1: probe (skip=0) to learn pass total ...")
    _write_skip(game_dir, 0)
    fc_output_dir.write_text(str(survey_dir.resolve()), encoding="utf-8")

    bmp_0 = _wait_for_bmp(survey_dir, 0, timeout_per_skip + wait_per_skip,
                          mtime_floor, abort_event)
    if bmp_0 is None:
        print("[SURVEY] X probe frame not received -- is the game running "
              "with our dxgi.dll? Did you start capture in the ReShade overlay?",
              file=sys.stderr)
        _clear_skip(game_dir)
        try: fc_output_dir.unlink(missing_ok=True)
        except OSError: pass
        return None

    total = None
    for _ in range(20):
        total = _read_pass_total(game_dir)
        if total:
            break
        time.sleep(0.2)

    if not total:
        print("[SURVEY] X could not read fc_pass_total.txt -- game may not "
              "be in a 3D scene (logo / menu / loading screen have no DSV "
              "passes). Move to actual gameplay first, then retry.",
              file=sys.stderr)
        _clear_skip(game_dir)
        try: fc_output_dir.unlink(missing_ok=True)
        except OSError: pass
        return None

    max_skip = total - 1
    skip_values = list(range(max_skip, 0, -step))
    print(f"[SURVEY] {total} non-BB passes -> sweep skip {max_skip}->0, "
          f"step={step}, {len(skip_values) + 1} points")
    print(f"         frames -> {survey_dir}")
    print(f"         wait {wait_per_skip:.1f}s per skip\n")

    captured = {0: bmp_0}

    # Phase 2: sweep
    try:
        for skip in skip_values:
            if abort_event is not None and abort_event.is_set():
                print("[SURVEY] abort requested; stopping sweep")
                break
            _write_skip(game_dir, skip)
            t_end = time.monotonic() + wait_per_skip
            while time.monotonic() < t_end:
                if abort_event is not None and abort_event.is_set():
                    break
                time.sleep(0.1)

            bmp = _wait_for_bmp(survey_dir, skip, timeout_per_skip,
                                mtime_floor, abort_event)
            if bmp is None:
                if abort_event is not None and abort_event.is_set():
                    break
                print(f"  skip={skip:3d}: X TIMEOUT")
                continue

            kb = bmp.stat().st_size // 1024
            print(f"  skip={skip:3d}: ok {kb} KB")
            captured[skip] = bmp
    finally:
        _clear_skip(game_dir)
        try: fc_pass_total.unlink(missing_ok=True)
        except OSError: pass
        try: fc_output_dir.unlink(missing_ok=True)
        except OSError: pass

    if abort_event is not None and abort_event.is_set():
        print("\n[SURVEY] aborted; skipping analysis")
        return None

    if total == 1 and 0 in captured:
        print("\n[SURVEY] WARN: game has only 1 non-BB pass; cannot do "
              "boundary analysis. skip=0 is the only option; whether pre-UI "
              "capture works depends on the game's pipeline. Open "
              "survey_skip_000_BackBuffer.png and check if it contains UI; "
              "if so, post-UI mode (FC_PreUICapture=0) is the only option "
              "for this game.")
        (survey_dir / "recommended_skip.txt").write_text("0", encoding="utf-8")
        return 0

    if len(captured) < 2:
        print("\n[SURVEY] insufficient frames; cannot analyze")
        return None

    # Phase 3: analyse
    print("\n[SURVEY] Phase 3: analyse diffs ...")
    recommended = _find_boundary(captured)
    (survey_dir / "recommended_skip.txt").write_text(str(recommended), encoding="utf-8")

    ordered = sorted(captured.keys(), reverse=True)
    images = {s: cv2.imread(str(captured[s])) for s in ordered}
    images = {s: img for s, img in images.items() if img is not None}
    print(f"\n  {'skip':>5}  {'diff':>10}  note")
    prev = None
    for s in ordered:
        if prev is not None and prev in images and s in images:
            d = _weighted_diff(images[prev], images[s])
            if s == recommended:
                note = "<-- recommended (lower edge of stable region; no UI)"
            elif prev == recommended:
                note = "<-- UI composites within this range"
            else:
                note = ""
            print(f"  {s:5d}  {d:10.2f}  {note}")
        else:
            note = "<-- recommended" if s == recommended else "(baseline)"
            print(f"  {s:5d}  {'':>10}  {note}")
        prev = s

    print(f"\n[SURVEY] recommended skip = {recommended}")
    print(f"         written to {survey_dir / 'recommended_skip.txt'}")
    print(f"         set FC_PreUISkipCount={recommended} in unicap.ini "
          f"[ADDON] section, then enable FC_PreUICapture=1 to use pre-UI mode.")
    return recommended


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game-dir", required=True, type=Path,
                    help="Directory containing the running game exe (where "
                         "dxgi.dll lives and where sidecar files go)")
    ap.add_argument("--survey-dir", required=True, type=Path,
                    help="Where to drop survey_skip_NNN_*.png frames")
    ap.add_argument("--step", type=int, default=5,
                    help="Skip value step (default 5)")
    ap.add_argument("--fps", type=float, default=1.0,
                    help="Survey FPS -- lower = more time to settle (default 1)")
    ap.add_argument("--timeout-per-skip", type=float, default=10.0,
                    help="Per-skip wait timeout in seconds (default 10)")
    args = ap.parse_args(argv)

    if not args.game_dir.is_dir():
        print(f"error: game_dir not found: {args.game_dir}", file=sys.stderr)
        return 2

    result = run(
        game_dir=args.game_dir,
        survey_dir=args.survey_dir,
        step=args.step,
        fps=args.fps,
        timeout_per_skip=args.timeout_per_skip,
    )
    return 0 if result is not None else 3


if __name__ == "__main__":
    sys.exit(_main())
