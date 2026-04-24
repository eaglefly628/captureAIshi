"""v4 extractor: brace-scope aware.

Walk each registrar function's decompile text and track a stack of
"currently active game contexts" driven by `if (cVar1 != '\0') { ... }`
blocks that immediately follow a game-tag literal.

Handles both:
  1) simple  : cVar1 = strcmp(s, "Game-Win"); if (cVar1 != '\0') { body }
  2) OR-join : cVar1 = strcmp(s, "A"); if (cVar1 == '\0') { cVar1 = strcmp(s, "B"); if (cVar1 == '\0') goto L; } body L:
               → body attributed to BOTH A and B until L.

A pattern+name pair encountered while the stack is non-empty is attributed to
every game in the stack; otherwise it is "Shared".
"""
import re, json, urllib.parse, urllib.request
from collections import defaultdict, OrderedDict

BASE = "http://127.0.0.1:8080/"

def get(ep, **p):
    url = BASE + ep + ("?" + urllib.parse.urlencode(p) if p else "")
    return urllib.request.urlopen(url, timeout=60).read().decode("utf-8","replace").splitlines()

def post(ep, data):
    body = data.encode("utf-8") if isinstance(data,str) else urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(BASE+ep, data=body, method="POST")
    return urllib.request.urlopen(req, timeout=120).read().decode("utf-8","replace")

# ---------- 1) gather strings (paginated) ----------
all_strings = []
for off in range(0, 20000, 2000):
    chunk = get("strings", offset=off, limit=2000)
    if not chunk: break
    all_strings.extend(chunk)
    if len(chunk) < 2000: break

STR_RE = re.compile(r'^([0-9a-fA-F]+):\s*"(.*)"\s*$')

aob_name_addr = {}
for ln in all_strings:
    m = STR_RE.match(ln)
    if not m: continue
    addr, val = m.group(1), m.group(2)
    if re.match(r"^AOB_[A-Z0-9_]+$", val):
        aob_name_addr[addr] = val

# ---------- 2) hard-coded game tag -> canonical game name ----------
# These are the string arguments passed to strcmp in registrar bodies.
# Derived by grep'ing decompile output of every registrar for FUN_1800cd250/290 args.
GAME_TAGS = {
    "Avowed-Win":                "Avowed",
    "b1-Win64-Shipping":         "Borderlands 4",
    "Banishers-Win64-Shipping":  "Banishers: Ghosts of New Eden",
    "Borderlands4":              "Borderlands 4",
    "CodeVein2-Win":             "Code Vein II",
    "Hellblade2-Win64-Shipping": "Hellblade II",
    "M1-Win64-Shipping":         "Unknown (UE codename M1)",
    "MafiaTheOldCountry":        "Mafia: The Old Country",
    "OblivionRemastered-Win":    "Oblivion Remastered",
    "Polaris-Win64-Shipping":    "Tekken 8 (codename Polaris)",
    "SHf-Win64-Shipping":        "Silent Hill f",
    "Stalker2-Win":              "S.T.A.L.K.E.R. 2",
    "TheOuterWorlds2":           "The Outer Worlds 2",
    "TheOuterWorlds2-Win":       "The Outer Worlds 2",
    "TQ2-Win64-Shipping":        "Unknown (UE codename TQ2)",
}
tag_literals = set(GAME_TAGS.keys())

# ---------- 3) collect registrar functions: anything that calls an addAOB wrapper
ADDAOB_WRAPPERS = ["180107fe0", "180107c40", "180107ab0", "180107cf0"]
XREF_RE = re.compile(r"From\s+([0-9a-fA-F]+)\s+in\s+(FUN_[0-9a-fA-F]+)")
registrar_funcs = set()
for w in ADDAOB_WRAPPERS:
    for ln in get("xrefs_to", address="0x"+w, limit=500):
        m = XREF_RE.search(ln)
        if m: registrar_funcs.add(m.group(2))
# Also include any function that xrefs an AOB_* name (belt & braces)
for addr in aob_name_addr:
    for ln in get("xrefs_to", address="0x"+addr, limit=50):
        m = XREF_RE.search(ln)
        if m: registrar_funcs.add(m.group(2))
print(f"[*] registrar functions: {len(registrar_funcs)}")

# ---------- 4) regex primitives ----------
STR_LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')
AOB_NAME_RE = re.compile(r"^AOB_[A-Z0-9_]+$")
PAT_RE      = re.compile(r"^[0-9A-Fa-f ?|]+$")

def is_pattern(s):
    return (PAT_RE.match(s) is not None and len(s) >= 8
            and " " in s and s.count(" ") >= 3)

# ---------- 5) brace-scope parser ----------
# Strategy: tokenize the decomp into a simple stream of events:
#   (pos, kind, payload)
# where kind is one of: 'game_tag', 'pat', 'name', 'brace_open', 'brace_close',
# 'if_notz', 'if_eqz', 'goto_label', 'label'
#
# We then replay events and maintain a stack of (brace_depth_when_pushed, [games]).
# When we see a game_tag, we tentatively mark it as "pending"; if the NEXT
# relevant structural event is `if (cVar1 != '\0') {`, push the game at the
# new brace depth. If the next events are `if (cVar1 == '\0') { if (game_tag)
# if (cVar1 == '\0') goto Lx; }` then the body after the close-brace (up to
# label Lx) is attributed to multiple games (a disjunction).
#
# To keep implementation robust, we use a simpler heuristic that captures the
# essential cases: after each game_tag, we scan forward up to a small window
# and, if we see `if (cVar1 != '\0') {`, we push that game at that depth. We
# also handle the OR-pattern by noticing `if (cVar1 == '\0') {` immediately
# after a game_tag, then collecting subsequent game_tags until the pattern
# `goto LAB_xxxx` appears; those games are grouped as a disjunction, with
# the attributed region starting at the first statement after the outer
# close-brace and ending at `LAB_xxxx:` where that goto target is defined.

def parse_and_attribute(src):
    """Yield (games_list, pattern, aob_name) tuples found in `src`."""
    # tokenize to events
    lines = src.splitlines()
    # we need character positions for brace matching; easier: work on flat text
    text = src
    # scan structural tokens
    events = []  # list of (pos, type, payload)

    # literals (string strings)
    for m in STR_LITERAL.finditer(text):
        lit = m.group(1)
        if lit in tag_literals:
            events.append((m.start(), "game_tag", lit))
        elif AOB_NAME_RE.match(lit):
            events.append((m.start(), "name", lit))
        elif is_pattern(lit):
            events.append((m.start(), "pat", lit))

    # braces
    for m in re.finditer(r"[{}]", text):
        events.append((m.start(), "brace", m.group(0)))

    # if statements (detect `if (cVar1 != '\0')` and `if (cVar1 == '\0')`)
    for m in re.finditer(r"if\s*\(\s*\w+\s*(!=|==)\s*'\\0'\s*\)", text):
        events.append((m.start(), "if_ne" if m.group(1) == "!=" else "if_eq", None))

    # gotos
    for m in re.finditer(r"goto\s+(LAB_[0-9a-fA-F]+)", text):
        events.append((m.start(), "goto", m.group(1)))
    # labels (target of goto)
    for m in re.finditer(r"^(LAB_[0-9a-fA-F]+):", text, re.MULTILINE):
        events.append((m.start(), "label", m.group(1)))

    events.sort(key=lambda e: e[0])

    # now walk events and maintain a stack: list of dicts:
    #   {"games": [g1, g2, ...], "depth": int_when_entered, "end_label": label_or_None}
    stack = []
    brace_depth = 0
    pending_tags = []   # accumulated game tags before the next if
    # for OR-pattern: once we see `if (ne == 0) {` immediately after a tag,
    # we consider this a disjunction. Subsequent `if (X == 0) goto LAB;` inside
    # accumulate the tag set. The body after the outer `}` up to LAB is attributed
    # to the full tag set.
    or_building = None  # dict with 'games', 'goto_label', or None

    # pattern/name pairing
    last_pattern = None
    results = []  # (games_list_at_time, pattern, name)

    i = 0
    while i < len(events):
        pos, kind, payload = events[i]
        if kind == "brace":
            if payload == "{":
                brace_depth += 1
                # if the IMMEDIATELY preceding tokens were `tag ... if_ne`,
                # push a new game context
                if pending_tags and or_building is None:
                    # look back: was the most recent structural event an if_ne?
                    # (safer: check within window of prior events)
                    if any(e[1] == "if_ne" for e in events[max(0,i-6):i]):
                        stack.append({"games": list(pending_tags), "depth": brace_depth,
                                       "end_label": None})
                        pending_tags = []
                    elif any(e[1] == "if_eq" for e in events[max(0,i-6):i]):
                        # start OR-building
                        or_building = {"games": list(pending_tags), "goto_label": None,
                                        "outer_depth": brace_depth}
                        pending_tags = []
            else:  # "}"
                # pop any context whose depth equals current brace_depth (before decrement)
                while stack and stack[-1]["depth"] == brace_depth and stack[-1]["end_label"] is None:
                    stack.pop()
                # handle OR-building's end: the outer `}` closes, after which a
                # `label:` (end_label) marks the end of the combined body
                if or_building is not None and brace_depth == or_building["outer_depth"]:
                    # the or_building block just ended. The disjunction body starts
                    # AFTER this `}` and runs until or_building["goto_label"]:
                    if or_building["goto_label"]:
                        stack.append({"games": or_building["games"],
                                       "depth": -1,                 # sentinel: controlled by label
                                       "end_label": or_building["goto_label"]})
                    or_building = None
                brace_depth -= 1
        elif kind == "game_tag":
            if or_building is not None:
                or_building["games"].append(payload)
            else:
                pending_tags.append(payload)
        elif kind == "goto" and or_building is not None:
            or_building["goto_label"] = payload
        elif kind == "label":
            # pop any context whose end_label matches
            stack[:] = [c for c in stack if c.get("end_label") != payload]
        elif kind == "if_ne" or kind == "if_eq":
            pass  # handled when we see the following '{'
        elif kind == "pat":
            last_pattern = payload
        elif kind == "name":
            if last_pattern is not None:
                games = []
                for ctx in stack:
                    for g in ctx["games"]:
                        if g not in games:
                            games.append(g)
                results.append((games, last_pattern, payload))
            last_pattern = None
        i += 1

    # if pending_tags wasn't consumed, it was a false-alarm tag (e.g. display
    # name strings). Ignore.
    return results

# ---------- 6) run across all registrar functions ----------
game_data = defaultdict(lambda: defaultdict(lambda: OrderedDict()))  # game -> aob -> {pattern -> {funcs}}

def record(game_list, pattern, name, func):
    targets = game_list if game_list else ["Shared / UE framework (all games)"]
    for g in targets:
        canonical = GAME_TAGS.get(g, g) if g in GAME_TAGS else g
        d = game_data[canonical][name]
        d.setdefault(pattern, set()).add(func)

for func in sorted(registrar_funcs):
    try:
        src = post("decompile", func)
    except Exception:
        continue
    if not src: continue
    for (games, pat, name) in parse_and_attribute(src):
        record(games, pat, name, func)

# ---------- 7) also handle game-specific registrars triggered by BL4_/SHF_ named AOBs
# If a function only registers BL4_ or SHF_ AOBs and parse_and_attribute
# attributed them to Shared (because there's no game-tag literal), move them to
# the correct game.
for aob_name_list in list(game_data["Shared / UE framework (all games)"].keys()):
    if aob_name_list.startswith("AOB_BL4_"):
        game_data["Borderlands 4"][aob_name_list] = game_data["Shared / UE framework (all games)"].pop(aob_name_list)
    elif aob_name_list.startswith("AOB_SHF_"):
        game_data["Silent Hill f"][aob_name_list] = game_data["Shared / UE framework (all games)"].pop(aob_name_list)

# ---------- 8) serialize ----------
NAMED = [g for g in game_data if not g.startswith("Unknown") and not g.startswith("Shared")]
UNKNOWN = [g for g in game_data if g.startswith("Unknown")]
SHARED = [g for g in game_data if g.startswith("Shared")]

out_games = OrderedDict()
for g in sorted(NAMED) + sorted(UNKNOWN) + sorted(SHARED):
    keys = []
    for aob_name in sorted(game_data[g].keys()):
        pats = game_data[g][aob_name]
        keys.append(OrderedDict([
            ("key", aob_name),
            ("variant_count", len(pats)),
            ("patterns", list(pats.keys())),
            ("registered_in", sorted({fn for fns in pats.values() for fn in fns})),
        ]))
    out_games[g] = OrderedDict([("key_count", len(keys)), ("keys", keys)])

# games explicitly present as tags but with 0 keys: declare them too
for tag, canonical in GAME_TAGS.items():
    if canonical not in out_games:
        out_games[canonical] = OrderedDict([("key_count", 0), ("keys", []),
                                             ("note", "detected as game id in the binary but no game-specific pattern overrides were extracted — game likely relies on the shared multi-variant pool")])

summary = OrderedDict([
    ("total_games_detected", len(set(GAME_TAGS.values()))),
    ("total_games_with_specific_overrides",
     sum(1 for g in out_games if out_games[g]["key_count"] > 0 and not g.startswith("Shared"))),
    ("total_keys", sum(g["key_count"] for g in out_games.values())),
    ("total_variants", sum(k["variant_count"] for g in out_games.values() for k in g["keys"])),
    ("per_game", {name: {"keys": d["key_count"],
                         "variants": sum(k["variant_count"] for k in d["keys"])}
                  for name, d in out_games.items()}),
])
report = OrderedDict([("summary", summary), ("games", out_games)])

OUT = r"D:\dev\uuuaobcapture\aob_patterns_by_game5.8.10.json"
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)
print(f"[+] wrote {OUT}")
print()
print(json.dumps(summary, indent=2, ensure_ascii=False))
