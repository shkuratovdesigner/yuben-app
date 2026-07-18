#!/usr/bin/env python3
"""
build_fixtures.py — normalize the repo's real research JSON into the unified
contract shapes, then validate every fixture against the JSON Schemas.

Running this doubles as a check that the normalizer and the contracts agree:
it *produces* contracts/fixtures/*.json AND *validates* them, failing loudly on
any drift. This is the same normalization the backend pipeline wrapper (B3) will
perform on live script output — kept here so the frontend has authentic content
on day one (CONTRACTS.md §8).

Sources (real data/*.json):
  longform  <- data/property_raw.json      (Airbnb / short-term-rental marketing)
  shorts    <- data/airbnb_promo_raw.json  (Airbnb tour / promo Shorts)

LEGACY — NOT the path that produced the committed fixtures. ``data/`` is
gitignored and absent from a fresh clone, so this script cannot run there; it
also rebuilds the old Airbnb-themed demo, which would overwrite the current
YouTube-growth fixtures. Kept for when raw pipeline output is on hand.

The committed fixtures are built by ``build_mock_fixtures.py`` from the curated,
oEmbed-verified video set in ``contracts/mock_videos/`` and checked by
``validate_fixtures.py`` — that pair is what ``make fixtures`` runs.

Usage:  python contracts/build_fixtures.py          (from repo root, needs data/)
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
SCHEMAS = REPO / "contracts" / "schemas"
OUT = REPO / "contracts" / "fixtures"

YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


# ---------------------------------------------------------------------------
# Derivations (mirror the pipeline + report builders)
# ---------------------------------------------------------------------------
def duration_label(seconds: int) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _num(x):
    if x is None:
        return None
    try:
        f = float(x)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return None


def normalize_video(raw: dict, *, keep_multiplier: bool) -> dict | None:
    """Raw Gen-2 row -> unified Video. Returns None if the id is unusable."""
    vid = str(raw.get("video_id", ""))
    if not YT_ID_RE.match(vid):
        return None

    view = int(_num(raw.get("view_count")) or 0)
    like = _num(raw.get("like_count"))
    comment = _num(raw.get("comment_count"))
    eng_per_1k = round((like / view) * 1000, 2) if (like and view) else 0.0

    vsr = _num(raw.get("views_to_subs"))
    multiplier = _num(raw.get("outlier_multiplier")) if keep_multiplier else None

    watch = f"https://www.youtube.com/watch?v={vid}"
    return {
        "video_id": vid,
        "title": raw.get("title", "") or "(untitled)",
        "url": watch,
        "watch_url": watch,
        "thumbnail_url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        "channel_id": raw.get("channel_id", "") or "",
        "channel_name": raw.get("channel_name", "") or "",
        "subscriber_count": int(_num(raw.get("subscriber_count")) or 0),
        "view_count": view,
        "like_count": int(like) if like is not None else None,
        "comment_count": int(comment) if comment is not None else None,
        "vsr": vsr,
        "multiplier": multiplier,
        "eng_per_1k": eng_per_1k,
        "engagement_flag": "promoted" if eng_per_1k < 1.5 else "ok",
        "published_at": raw.get("published_at", "") or "1970-01-01T00:00:00Z",
        "duration_seconds": int(_num(raw.get("duration_seconds")) or 0),
        "duration_label": duration_label(int(_num(raw.get("duration_seconds")) or 0)),
        "link_status": "verified",
    }


def load_videos(filename: str, *, keep_multiplier: bool) -> tuple[list[dict], dict]:
    src = json.loads((DATA / filename).read_text())
    videos = []
    for raw in src.get("videos", []):
        v = normalize_video(raw, keep_multiplier=keep_multiplier)
        if v is not None:
            videos.append(v)
    videos.sort(key=lambda v: v["view_count"], reverse=True)
    return videos, src


# ---------------------------------------------------------------------------
# Narrative builders — reference REAL video_ids from the curated set so every
# link resolves. (In production this narrative comes from the agent; here it is
# authored so screens look real without a live run.)
# ---------------------------------------------------------------------------
_WATCH_GOALS = [
    "See the highest-ceiling example in the space",
    "Study a specific, personal marketing system",
    "Model a direct-booking / get-found playbook",
    "Copy a content-engine format that compounds",
    "Learn the hook that broke this creator out",
    "Understand what over-saturation looks like",
]


def build_watch_list(top: list[dict]) -> list[dict]:
    out = []
    for i, v in enumerate(top[:6]):
        vsr = v["vsr"]
        vsr_txt = f"{vsr:g}× its channel size" if vsr else "a large audience"
        out.append(
            {
                "video_id": v["video_id"],
                "learning_goal": _WATCH_GOALS[i % len(_WATCH_GOALS)],
                "why": f"{v['channel_name']} — {v['view_count']:,} views at {vsr_txt}. "
                f"Watch how “{v['title'][:70]}” is framed.",
                "rank": i + 1,
            }
        )
    return out


def build_title_analysis(all_videos: list[dict]) -> dict:
    titles = [v["title"].lower() for v in all_videos]
    n_total = len(titles) or 1

    def count(pred) -> int:
        return sum(1 for t in titles if pred(t))

    features = [
        ("How-to / explainer", "Names the payoff up front ('how to …').",
         count(lambda t: "how to" in t or t.startswith("how "))),
        ("Money / real number", "A concrete $ or figure signals proof.",
         count(lambda t: "$" in t or re.search(r"\d", t) is not None)),
        ("Names the platform", "Puts 'airbnb' / 'short-term rental' in the title.",
         count(lambda t: "airbnb" in t or "short term" in t or "str" in t)),
        ("Question hook", "Opens a curiosity gap with a question.",
         count(lambda t: t.strip().endswith("?"))),
    ]
    features.sort(key=lambda f: f[2], reverse=True)
    common_features = [
        {"n": i + 1, "pattern": p, "note": note, "count": c}
        for i, (p, note, c) in enumerate(features)
    ]

    def example(pred, fallback):
        for v in all_videos:
            if pred(v["title"].lower()):
                return f'"{v["title"][:60]}"'
        return fallback

    emotional_triggers = [
        {"n": 1, "trigger": "Curiosity / secret reveal",
         "example": example(lambda t: "secret" in t or "truth" in t, '"The secret behind…"')},
        {"n": 2, "trigger": "Aspiration (wealth / freedom)",
         "example": example(lambda t: "million" in t or "$" in t or "rich" in t, '"…$250K/month"')},
        {"n": 3, "trigger": "Fear of getting it wrong",
         "example": example(lambda t: "mistake" in t or "avoid" in t or "collapse" in t, '"…before it\'s too late"')},
        {"n": 4, "trigger": "Social proof / transformation",
         "example": example(lambda t: "how i" in t or "how she" in t or "how he" in t, '"How I …"')},
    ]
    return {"common_features": common_features, "emotional_triggers": emotional_triggers}


def build_script_analysis(all_videos: list[dict], top: list[dict]) -> dict:
    durs = [v["duration_seconds"] for v in all_videos if v["duration_seconds"] > 0]
    median_min = round(statistics.median(durs) / 60, 1) if durs else 0.0
    shortest = min(durs) if durs else 0
    longest = max(durs) if durs else 0

    duration_sweet_spot = [
        {"label": "Median duration of qualifying videos", "value": f"{median_min} minutes"},
        {"label": "Range", "value": f"{duration_label(shortest)} – {duration_label(longest)}"},
        {"label": "Sample size", "value": f"{len(durs)} videos"},
    ]
    structure_patterns = [
        {"name": "\"Show my setup\" (highest engagement)",
         "note": "Screen/room walkthroughs of a real listing beat talking-head advice."},
        {"name": "One specific number, early",
         "note": "A concrete result ($/month, occupancy %) in the first 30s earns the watch."},
        {"name": "Problem → system → proof",
         "note": "Name the pain, show the repeatable system, then the receipts."},
    ]
    hook_breakdown = []
    for i, v in enumerate(top[:4]):
        vsr = v["vsr"]
        tag = f" ({vsr:g}×)" if vsr else ""
        hook_breakdown.append(
            {
                "rank": i + 1,
                "title": f"{v['title'][:60]}{tag}",
                "hook": "Opens by naming the outcome the viewer wants, then promises the exact steps.",
                "video_id": v["video_id"],
            }
        )
    what_to_avoid = [
        "Generic 'grow your Airbnb' advice — the market is saturated with it.",
        "Burying the payoff; the first 30 seconds decide retention.",
        "No proof — claims without a real number read as fluff.",
    ]
    return {
        "duration_sweet_spot": duration_sweet_spot,
        "structure_patterns": structure_patterns,
        "hook_breakdown": hook_breakdown,
        "what_to_avoid": what_to_avoid,
    }


def build_title_formulas(top: list[dict]) -> list[dict]:
    proof = top[0]["video_id"] if top else "00000000000"
    return [
        {"shape": "How to [outcome] on Airbnb (without [pain])",
         "proof_video_id": proof, "tailored": "How to Fill Your Airbnb Calendar Without Discounting"},
        {"shape": "The [surprising number] behind [result]",
         "proof_video_id": top[1]["video_id"] if len(top) > 1 else proof,
         "tailored": "The 3 Reels That Booked My Airbnb Solid"},
    ]


def build_game_plan() -> dict:
    return {
        "outline": [
            {"t": "0:00", "beat": "Hook: name the outcome (a full calendar) + the one number."},
            {"t": "0:30", "beat": "Show the real listing / setup on screen."},
            {"t": "3:00", "beat": "The repeatable system, step by step."},
            {"t": "8:00", "beat": "Proof: bookings / occupancy after applying it."},
            {"t": "10:30", "beat": "CTA: the free direct-booking checklist."},
        ],
        "title_options": [
            "How I Fill My Airbnb Without Airbnb Fees",
            "The Reel Formula That Booked My Rental Solid",
            "Direct Bookings 101: Get Found Without Getting Banned",
        ],
        "thumbnail_concepts": [
            "Split screen: empty calendar → fully booked.",
            "Host on camera + bold '£0 in ads' overlay.",
        ],
        "do": "Show a real listing and one concrete result on screen.",
        "dont": "Ship another generic 'grow your STR' explainer.",
    }


# ---------------------------------------------------------------------------
# Result assembly
# ---------------------------------------------------------------------------
def build_result(*, run_id, created_at, request, topic_title, summary,
                 videos, src, filter_label, curated=15,
                 with_scripts=True) -> dict:
    top = videos[:curated]
    counts_key = "longform" if request["format"] == "longform" else "shorts"
    n_kept = src.get("total_longform") or src.get("total_shorts") or len(videos)
    meta = {
        "window": "All time",
        "filter": filter_label,
        "keywords": src.get("keywords", []),
        "ranking": "by views; VSR shown",
        "counts": {
            "unique": src.get("total_search_unique", len(videos)),
            counts_key: int(n_kept),
            "curated": len(top),
        },
    }
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "created_at": created_at,
        "request": request,
        "topic_title": topic_title,
        "summary": summary,
        "meta": meta,
        "top_videos": top,
        "watch_list": build_watch_list(top),
        "title_analysis": build_title_analysis(videos) if request["analyze_titles"] else None,
        "script_analysis": build_script_analysis(videos, top) if (with_scripts and request["analyze_scripts"]) else None,
        "title_formulas": build_title_formulas(top),
        "game_plan": build_game_plan(),
    }


def build_progress_events(run_id: str) -> list[dict]:
    def ev(phase, label, pct, detail, counts, secs):
        e = {"run_id": run_id, "phase": phase, "label": label, "pct": pct,
             "ts": f"2026-07-11T10:00:{secs:02d}Z"}
        if detail is not None:
            e["detail"] = detail
        if counts is not None:
            e["counts"] = counts
        return e

    return [
        ev("queued", "Queued", 0, None, None, 0),
        ev("expanding", "Expanding your topic into search terms", 8, "18 keywords", None, 2),
        ev("searching", "Searching YouTube", 30, "keyword 7 / 18", {"found": 214}, 7),
        ev("searching", "Searching YouTube", 48, "keyword 14 / 18", {"found": 356}, 12),
        ev("enriching", "Pulling channel sizes & stats", 62, "212 channels", {"found": 412, "longform": 180}, 18),
        ev("scoring", "Scoring outliers (views vs. channel size)", 74, None, {"found": 412, "longform": 180}, 22),
        ev("analyzing", "Analyzing titles & scripts", 86, None, {"longform": 180, "curated": 15}, 27),
        ev("verifying", "Verifying every link", 95, "verifying 15 links", {"curated": 15}, 31),
        ev("done", "Done", 100, None, {"curated": 15}, 33),
    ]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def build_registry():
    from referencing import Registry, Resource

    resources = []
    for path in SCHEMAS.glob("*.schema.json"):
        schema = json.loads(path.read_text())
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def validate(instance, schema_id, registry, label):
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator({"$ref": schema_id}, registry=registry)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        print(f"\nFIXTURE VALIDATION FAILED: {label}", file=sys.stderr)
        for e in errors[:8]:
            loc = "/".join(str(p) for p in e.path)
            print(f"  at [{loc}]: {e.message}", file=sys.stderr)
        raise SystemExit(1)
    print(f"  ok  {label}")


def write(name: str, obj) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    return path


# ---------------------------------------------------------------------------
def main() -> None:
    S = "https://yuben.dev/schemas"

    # --- Long-form: Airbnb / STR marketing (property_raw) ---
    lf_videos, lf_src = load_videos("property_raw.json", keep_multiplier=True)
    lf_request = {
        "schema_version": "1.0",
        "query": "how to promote your airbnb",
        "format": "longform",
        "upload_date": "all",
        "outperformance": "highest",
        "analyze_titles": True,
        "analyze_scripts": True,
        "model": {"adapter": "claude-code", "model": "default"},
        "max_results": 15,
    }
    longform = build_result(
        run_id="r_fixture_longform",
        created_at="2026-07-10T15:39:00Z",
        request=lf_request,
        topic_title="How to Promote Your Airbnb: Marketing, Direct Bookings & Content That Converts",
        summary="Across the long-form field, specific and personal marketing systems win — "
                "direct-booking playbooks and repeatable content engines beat generic "
                "'grow your short-term rental' advice.",
        videos=lf_videos, src=lf_src,
        filter_label="long-form ≥120s",
    )

    # --- Shorts: Airbnb tour / promo reels (airbnb_promo_raw). Scripts OFF so the
    #     UI's disabled-Script-tab state is exercised by a real fixture. ---
    sh_videos, sh_src = load_videos("airbnb_promo_raw.json", keep_multiplier=False)
    sh_request = {
        "schema_version": "1.0",
        "query": "aesthetic airbnb tour reels",
        "format": "shorts",
        "upload_date": "all",
        "outperformance": "highest",
        "analyze_titles": True,
        "analyze_scripts": False,
        "model": {"adapter": "claude-code", "model": "default"},
        "max_results": 15,
    }
    shorts = build_result(
        run_id="r_fixture_shorts",
        created_at="2026-07-10T15:39:30Z",
        request=sh_request,
        topic_title="Airbnb Tours & Promo Shorts: What Makes a Rental Reel Go Viral",
        summary="Emotional, story-driven Shorts ('what guests left', cozy-cabin escapes) "
                "massively outperform their channels — the top clips clear 60×+ VSR on a "
                "single hook.",
        videos=sh_videos, src=sh_src,
        filter_label="Shorts ≤65s",
        with_scripts=False,
    )

    # --- Config / adapters / history / progress ---
    config = {
        "schema_version": "1.0",
        "adapter": "claude-code",
        "model": "default",
        "youtube_key_present": True,
        "anthropic_key_present": True,
        "onboarding_complete": True,
    }
    adapters = [
        {"id": "anthropic-api", "name": "Anthropic API", "installed": True,
         "version": "0.116.0",
         "models": ["default", "claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5", "claude-fable-5"]},
        {"id": "claude-code", "name": "Claude Code", "installed": True,
         "version": "1.0.0", "models": ["default", "claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"]},
        {"id": "gemini-cli", "name": "Gemini CLI", "installed": False, "version": None, "models": []},
    ]
    history = [
        {"run_id": "r_fixture_longform", "topic_title": longform["topic_title"],
         "query": lf_request["query"], "format": "longform",
         "created_at": longform["created_at"], "counts": {"curated": 15}, "outperformance": "highest"},
        {"run_id": "r_fixture_shorts", "topic_title": shorts["topic_title"],
         "query": sh_request["query"], "format": "shorts",
         "created_at": shorts["created_at"], "counts": {"curated": 15}, "outperformance": "highest"},
        {"run_id": "r_fixture_older", "topic_title": "Best Niches for New Creators in 2026",
         "query": "best youtube niches 2026", "format": "longform",
         "created_at": "2026-07-08T23:52:00Z", "counts": {"curated": 12}, "outperformance": "5x"},
    ]
    progress = build_progress_events("r_fixture_longform")

    # --- Write ---
    print("Writing fixtures ->", OUT)
    write("research-result.longform.json", longform)
    write("research-result.shorts.json", shorts)
    write("config.json", config)
    write("adapters.json", adapters)
    write("history.json", history)
    (OUT / "progress-events.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in progress) + "\n"
    )

    # --- Validate everything against the schemas ---
    print("Validating against contracts/schemas …")
    registry = build_registry()
    validate(longform, f"{S}/research-result.schema.json", registry, "research-result.longform.json")
    validate(shorts, f"{S}/research-result.schema.json", registry, "research-result.shorts.json")
    validate(config, f"{S}/config.schema.json", registry, "config.json")
    for i, a in enumerate(adapters):
        validate(a, f"{S}/adapter.schema.json", registry, f"adapters.json[{i}]")
    for i, h in enumerate(history):
        validate(h, f"{S}/history-item.schema.json", registry, f"history.json[{i}]")
    for i, e in enumerate(progress):
        validate(e, f"{S}/progress-event.schema.json", registry, f"progress-events[{i}]")

    print(f"\nAll fixtures written and validated. "
          f"longform top={len(longform['top_videos'])} of {len(lf_videos)}, "
          f"shorts top={len(shorts['top_videos'])} of {len(sh_videos)}.")


if __name__ == "__main__":
    main()
