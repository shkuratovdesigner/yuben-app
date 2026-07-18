"""Build the demo fixtures for contracts/fixtures/ from a curated video list.

Why this exists alongside ``build_fixtures.py``: that script derives fixtures
from raw pipeline output in ``data/*.json``, which is gitignored and absent from
a fresh clone — so it cannot run here. This script takes a hand-curated list of
REAL, oEmbed-verified videos instead, and derives every computed field
(vsr, eng_per_1k, engagement_flag, duration_label, urls, thumbnails) the same
way the pipeline does, so the fixtures stay internally consistent.

    python3 contracts/build_mock_fixtures.py
    python3 contracts/validate_fixtures.py     # always run after

Video ids, titles and channel names are real and verified. View/subscriber/like
counts are representative demo values, not live API readings.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "contracts" / "fixtures"
CURATED = Path(__file__).resolve().parent / "mock_videos"


# ---------------------------------------------------------------------------
# Derived-field helpers — mirror the production pipeline's computations.
# ---------------------------------------------------------------------------
def duration_label(secs: int) -> str:
    h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def build_video(raw: dict) -> dict:
    vid = raw["video_id"]
    views, subs = raw["view_count"], raw["subscriber_count"]
    likes = raw["like_count"]
    eng = round(likes / views * 1000, 2) if views else 0.0
    return {
        "video_id": vid,
        "title": raw["title"],
        "url": f"https://www.youtube.com/watch?v={vid}",
        "watch_url": f"https://www.youtube.com/watch?v={vid}",
        "thumbnail_url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        "channel_id": raw["channel_id"],
        "channel_name": raw["channel_name"],
        "subscriber_count": subs,
        "view_count": views,
        "like_count": likes,
        "comment_count": raw["comment_count"],
        "vsr": round(views / subs, 2) if subs else None,
        "multiplier": None,
        "eng_per_1k": eng,
        "engagement_flag": "promoted" if eng < 1.5 else "ok",
        "published_at": raw["published_at"],
        "duration_seconds": raw["duration_seconds"],
        "duration_label": duration_label(raw["duration_seconds"]),
        "link_status": "verified",
    }


def build_watch_list(top: list[dict], goals: list[str]) -> list[dict]:
    out = []
    for i, v in enumerate(top[:6]):
        vsr = v["vsr"]
        vsr_txt = f"{vsr:g}× its channel size" if vsr else "a large audience"
        out.append({
            "video_id": v["video_id"],
            "learning_goal": goals[i % len(goals)],
            "why": f"{v['channel_name']} — {v['view_count']:,} views at {vsr_txt}. "
                   f"Watch how “{v['title'][:70]}” is framed.",
            "rank": i + 1,
        })
    return out


def build_hook_breakdown(top: list[dict], hooks: list[str]) -> list[dict]:
    out = []
    for i, v in enumerate(top[:4]):
        vsr = v["vsr"]
        out.append({
            "rank": i + 1,
            "title": f"{v['title'][:58]} ({vsr:g}×)" if vsr else v["title"][:58],
            "hook": hooks[i % len(hooks)],
            "video_id": v["video_id"],
        })
    return out


def median_duration(videos: list[dict]) -> float:
    ds = sorted(v["duration_seconds"] for v in videos)
    n = len(ds)
    return ds[n // 2] if n % 2 else (ds[n // 2 - 1] + ds[n // 2]) / 2


def build_result(*, run_id, created_at, request, topic_title, summary, meta_extra,
                 videos, goals, hooks, title_analysis, structure_patterns,
                 what_to_avoid, title_formulas_spec, game_plan) -> dict:
    top = [build_video(v) for v in videos]
    top.sort(key=lambda v: v["view_count"], reverse=True)

    med = median_duration(top)
    shortest, longest = min(top, key=lambda v: v["duration_seconds"]), max(top, key=lambda v: v["duration_seconds"])

    formulas = [{
        "shape": spec["shape"],
        "proof_video_id": top[spec["proof_rank"]]["video_id"],
        "tailored": spec["tailored"],
    } for spec in title_formulas_spec]

    # Emotional-trigger examples quote real titles from the ranked set.
    triggers = [{
        "n": i + 1,
        "trigger": t["trigger"],
        "example": f"\"{top[t['example_rank']]['title'][:58]}\"",
    } for i, t in enumerate(title_analysis["emotional_triggers"])]

    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "created_at": created_at,
        "request": request,
        "topic_title": topic_title,
        "summary": summary,
        "meta": {
            "window": meta_extra["window"],
            "filter": meta_extra["filter"],
            "keywords": meta_extra["keywords"],
            "ranking": meta_extra["ranking"],
            "counts": {**meta_extra["counts"], "curated": len(top)},
        },
        "top_videos": top,
        "watch_list": build_watch_list(top, goals),
        # The toggles are part of what these fixtures demo: the shorts run has
        # analyze_scripts off, so its Script tab must render disabled (null).
        "title_analysis": {
            "common_features": title_analysis["common_features"],
            "emotional_triggers": triggers,
        } if request["analyze_titles"] else None,
        "script_analysis": {
            "duration_sweet_spot": [
                {"label": "Median duration of qualifying videos",
                 "value": f"{med / 60:.1f} minutes" if med >= 120 else f"{med:.0f} seconds"},
                {"label": "Range",
                 "value": f"{duration_label(shortest['duration_seconds'])} – {duration_label(longest['duration_seconds'])}"},
                {"label": "Sample size", "value": f"{meta_extra['counts'][meta_extra['sample_key']]} videos"},
            ],
            "structure_patterns": structure_patterns,
            "hook_breakdown": build_hook_breakdown(top, hooks),
            "what_to_avoid": what_to_avoid,
        } if request["analyze_scripts"] else None,
        "title_formulas": formulas,
        "game_plan": game_plan,
    }


def write(name: str, obj) -> None:
    path = FIXTURES / name
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    print(f"  wrote {name}")


def main() -> None:
    spec = json.loads((CURATED / "spec.json").read_text())
    longform = build_result(**{**spec["longform"], "videos": json.loads((CURATED / "longform.json").read_text())})
    shorts = build_result(**{**spec["shorts"], "videos": json.loads((CURATED / "shorts.json").read_text())})

    print("Writing fixtures ->", FIXTURES)
    write("research-result.longform.json", longform)
    write("research-result.shorts.json", shorts)
    write("history.json", [{
        "run_id": longform["run_id"],
        "topic_title": longform["topic_title"],
        "query": longform["request"]["query"],
        "format": "longform",
        "created_at": longform["created_at"],
        "counts": {"curated": len(longform["top_videos"])},
        "outperformance": longform["request"]["outperformance"],
    }])
    print("\nDone. Now run: python3 contracts/validate_fixtures.py")


if __name__ == "__main__":
    main()
