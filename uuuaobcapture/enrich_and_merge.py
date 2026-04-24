"""Enrich 5.8.11 + 4.11.5 AOB JSONs with engine + purpose_guess, then merge.

Reads:
  - aob_patterns_by_game5.8.11.json   (UE5)
  - aob_patterns_by_game4.11.5.json   (UE4)

Writes (in place, with new fields):
  - aob_patterns_by_game5.8.11.json
  - aob_patterns_by_game4.11.5.json

Writes (merged):
  - aob_patterns_by_game.json
"""
import json
from collections import OrderedDict

ROOT = r"D:\dev\uuuaobcapture"

# ---------- purpose-guess rules ----------
GAME_PREFIXES = [
    ("AOB_FF7REBIRTH_",                         "[FF7 Rebirth]"),
    ("AOB_FF7R_",                               "[FF7 Remake]"),
    ("AOB_LSA_",                                "[Lost Soul Aside]"),
    ("AOB_SOM_",                                "[South of Midnight]"),
    ("AOB_TI_",                                 "[The Invincible]"),
    ("AOB_SB_",                                 "[Stellar Blade]"),
    ("AOB_BL4_",                                "[Borderlands 4]"),
    ("AOB_SHF_",                                "[Silent Hill f]"),
    ("AOB_PM_",                                 "[Photo-mode camera state]"),
    ("AOB_SPECIAL_CASE_HOGWARTS_LEGACY_",       "[Hogwarts Legacy]"),
    ("AOB_SPECIAL_CASE_JEDI_SURVIVOR_",         "[Jedi: Survivor]"),
    ("AOB_SPECIAL_CASE_THE_QUARRY_",            "[The Quarry]"),
    ("AOB_SPECIAL_CASE_TINA_WONDERLANDS_",      "[Tiny Tina's Wonderlands]"),
]

# Most specific first; ordered substring match against the post-prefix tail.
# Each entry: (substring-in-tail, purpose label)
PURPOSE_RULES = [
    # --- camera struct / writes / black bars
    ("CAMERA_STRUCT_INTERCEPT",                  "Camera struct copy intercept"),
    ("CAMERA_BLACKBARS_PLAYER_CAMERA_MANAGER",   "Camera black-bar removal (PlayerCameraManager)"),
    ("CAMERA_BLACKBARS_CAMERA_COMPONENT",        "Camera black-bar removal (CameraComponent)"),
    ("CAMERA_BLACKBARS_REMOVAL",                 "Camera black-bar removal"),
    ("CAMERA_MENU_WRITE_INTERCEPT",              "Camera menu-write intercept"),
    ("CAMERA_WRITE_INTERCEPT",                   "Camera write intercept"),
    ("CAMERA_LOCKED_FOV_READ",                   "Camera locked-FOV read"),
    ("CAMERA_WRITE",                             "Camera struct write"),
    ("PLAYERCAMERACONTROLLER_FOV_WRITE",         "PlayerCameraController FOV-write call"),
    # --- DoF / vignette / FOV
    ("LENSVIGNETTE",                             "Lens vignette parameter"),
    ("FSTOPOVERRIDE_READ",                       "DoF F-stop override read"),
    ("FSTOP_READ",                               "DoF F-stop read"),
    ("FOV_WRITE",                                "FOV write"),
    ("FOV_READ",                                 "FOV read"),
    ("READ_FOV",                                 "FOV read"),
    ("INTERCEPT_FOV",                            "FOV intercept"),
    # --- HUD / widgets / Slate
    ("HUD_DRAW",                                 "HUD draw hook"),
    ("HUD_SCALE_FACTOR",                         "HUD scale-factor calc"),
    ("HUDSIZE_READ",                             "HUD size read"),
    ("WIDGETOPACITYSET",                         "UMG widget opacity set"),
    ("WIDGETPAINT_OPACITYREAD",                  "UMG widget paint opacity read"),
    ("SVIEWPORT_ONPAINT_CALL_COMPOUNDWIDGET",    "SViewport::OnPaint call to SCompoundWidget::OnPaint"),
    ("SVIRTUALWINDOW_ONPAINT_CALL_SCOMPOUNDWIDGET", "SVirtualWindow::OnPaint call to SCompoundWidget::OnPaint"),
    ("FSLATEAPPLICATION_APP_ACTIVATION",         "FSlateApplication app-activation hook"),
    # --- aspect ratio / atmospherics / postprocess
    ("ASPECTRATIO_CONSTRAINT",                   "Aspect-ratio constraint"),
    ("ASPECT_CONSTRAINT",                        "Aspect-ratio constraint"),
    ("WRITEATMOSPHERICS",                        "Atmospheric component write hook"),
    ("POSTPROCESSWRITE",                         "Post-process settings write"),
    # --- skeletal mesh
    ("FILLCOMPONENTSPACETRANSFORMS",             "USkeletalMeshComponent::FillComponentSpaceTransforms hook"),
    ("REQUIREDBONESOFFSET",                      "USkeletalMeshComponent RequiredBones offset"),
    # --- input / pause / time
    ("BLOCK_GAMEPAD_INPUT",                      "Gamepad input blocking"),
    ("GAMEPAD_INPUT_READ",                       "Gamepad input read"),
    ("GAMEPAD_INPUT",                            "Gamepad input"),
    ("TIMEDILATION_CLAMPJMP",                    "Time-dilation clamp jump"),
    ("TIMEDILATION4VALUES",                      "TimeDilation 4-values pointer"),
    ("GET_TIMEDILATION",                         "Get TimeDilation"),
    ("TIMEDILATION",                             "Time-dilation control"),
    ("GAMECLOCK_TICK_PREVENTION",                "Game-clock tick prevention (pause)"),
    ("TIMER_STRUCT",                             "Timer subsystem struct"),
    ("TIMER_TICKS_WRITE",                        "Timer ticks write"),
    ("UWORLD_ISPAUSE",                           "UWorld::IsPaused hook"),
    ("UWORLD_SPAWNACTOR",                        "UWorld::SpawnActor hook"),
    # --- core engine / objects / console
    ("UOBJECT_PROCESSEVENT",                     "UObject::ProcessEvent hook"),
    ("STATICCONSTRUCTOBJECT",                    "StaticConstructObject_Internal call"),
    ("FCONSOLEMANAGER",                          "FConsoleManager pointer"),
    ("ENABLE_SET_COMMAND",                       "Enable Set console command"),
    ("ALLOWCHEATSCALL",                          "AllowCheats call (console enable)"),
    ("ENGINEVERSION",                            "Engine version string"),
    ("GENGINE",                                  "GEngine global pointer"),
    ("NAMESSTORE",                               "GNames (FName store) pointer"),
    ("OBJECTSSTORE",                             "GUObjectArray (UObject store) pointer"),
    # --- BL4 / misc
    ("MAINTHREAD_CALL_INTERCEPT",                "Main-thread call intercept"),
    ("COORDS_WRITE",                             "Camera coordinates write"),
    ("ANGLES_WRITE",                             "Camera angles write"),
]


def purpose_guess(name: str) -> str:
    """Map an AOB_* identifier to a short human-readable purpose."""
    upper = name.upper()
    prefix_label = ""
    tail = upper
    for prefix, label in GAME_PREFIXES:
        if upper.startswith(prefix):
            prefix_label = label
            tail = upper[len(prefix):]
            break
    else:
        if upper.startswith("AOB_"):
            tail = upper[4:]
    for substr, label in PURPOSE_RULES:
        if substr in tail:
            return f"{prefix_label} {label}".strip() if prefix_label else label
    # _411 / _427 etc are version-tagged variants of preceding family;
    # fall back: strip trailing _NNN and retry.
    import re
    stripped = re.sub(r"_\d+$", "", tail)
    if stripped != tail:
        for substr, label in PURPOSE_RULES:
            if substr in stripped:
                return f"{prefix_label} {label}".strip() if prefix_label else label
    return f"{prefix_label} (uncategorized)".strip() if prefix_label else "(uncategorized)"


# ---------- per-file enrichment ----------
def enrich(path: str, engine: str) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f, object_pairs_hook=OrderedDict)
    # inject top-level engine
    new = OrderedDict()
    new["engine"] = engine
    new["summary"] = data["summary"]
    new["games"] = OrderedDict()
    for game, gd in data["games"].items():
        ng = OrderedDict()
        ng["engine"] = engine
        for k, v in gd.items():
            if k == "keys":
                new_keys = []
                for entry in v:
                    ne = OrderedDict()
                    ne["key"] = entry["key"]
                    ne["purpose_guess"] = purpose_guess(entry["key"])
                    for subk, subv in entry.items():
                        if subk == "key":
                            continue
                        ne[subk] = subv
                    new_keys.append(ne)
                ng["keys"] = new_keys
            else:
                ng[k] = v
        new["games"][game] = ng
    with open(path, "w", encoding="utf-8") as f:
        json.dump(new, f, indent=2, ensure_ascii=False)
    return new


ue5 = enrich(ROOT + r"\aob_patterns_by_game5.8.11.json", "UE5")
ue4 = enrich(ROOT + r"\aob_patterns_by_game4.11.5.json", "UE4")


# ---------- merge ----------
# UE4 and UE5 game rosters are disjoint except for "Shared / UE framework (all games)"
# which we relabel per engine.
def per_engine_section(blob: dict, engine: str) -> dict:
    out = OrderedDict()
    out["engine"] = engine
    out["source"] = ("aob_patterns_by_game5.8.11.json" if engine == "UE5"
                     else "aob_patterns_by_game4.11.5.json")
    out["binary"] = ("UniversalUE5Unlocker5.8.11.dll" if engine == "UE5"
                     else "UniversalUE4Unlocker4.11.5.dll")
    out["summary"] = blob["summary"]
    out["games"] = blob["games"]
    return out


merged = OrderedDict()
merged["meta"] = OrderedDict([
    ("description", "Merged AOB pattern catalog across UE4 and UE5 unlocker builds"),
    ("engines", ["UE4", "UE5"]),
])

# grand totals
def grand(b1, b2):
    return OrderedDict([
        ("total_games_detected",
         b1["summary"]["total_games_detected"] + b2["summary"]["total_games_detected"]),
        ("total_games_with_specific_overrides",
         b1["summary"]["total_games_with_specific_overrides"]
         + b2["summary"]["total_games_with_specific_overrides"]),
        ("total_keys", b1["summary"]["total_keys"] + b2["summary"]["total_keys"]),
        ("total_variants",
         b1["summary"]["total_variants"] + b2["summary"]["total_variants"]),
    ])


merged["totals"] = grand(ue4, ue5)
merged["UE4"] = per_engine_section(ue4, "UE4")
merged["UE5"] = per_engine_section(ue5, "UE5")

OUT = ROOT + r"\aob_patterns_by_game.json"
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(merged, f, indent=2, ensure_ascii=False)

print(f"[+] enriched {ROOT}\\aob_patterns_by_game5.8.11.json (engine=UE5)")
print(f"[+] enriched {ROOT}\\aob_patterns_by_game4.11.5.json (engine=UE4)")
print(f"[+] wrote merged {OUT}")
print()
print(json.dumps(merged["totals"], indent=2))
