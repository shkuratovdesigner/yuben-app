"""Validate the committed fixtures in contracts/fixtures/ against contracts/schemas/.

``build_fixtures.py`` regenerates the fixtures from raw pipeline output in
``data/*.json`` — but that directory is gitignored and absent from a fresh
clone, so it cannot run here. This script validates whatever is committed,
independently of how it got there, so hand-edited fixtures stay contract-clean.

    python3 contracts/validate_fixtures.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCHEMAS = REPO / "contracts" / "schemas"
FIXTURES = REPO / "contracts" / "fixtures"
S = "https://yuben.dev/schemas"


def build_registry():
    from referencing import Registry, Resource

    resources = []
    for path in SCHEMAS.glob("*.schema.json"):
        schema = json.loads(path.read_text())
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def validate(instance, schema_id, registry, label) -> int:
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator({"$ref": schema_id}, registry=registry)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        print(f"  FAIL  {label}", file=sys.stderr)
        for e in errors[:8]:
            loc = "/".join(str(p) for p in e.path) or "(root)"
            print(f"          at [{loc}]: {e.message}", file=sys.stderr)
        return len(errors)
    print(f"  ok    {label}")
    return 0


def load(name):
    return json.loads((FIXTURES / name).read_text())


def check_referential_integrity(result, label) -> int:
    """Every id referenced by the narrative must exist in top_videos.

    The trust rule (PRD §8) says the app never renders a video id the model
    invented. A fixture that points watch_list or hook_breakdown at an id which
    isn't in top_videos would ship exactly that bug as demo data.
    """
    ids = {v["video_id"] for v in result.get("top_videos", [])}
    problems = 0

    def check(vid, where):
        nonlocal problems
        if vid not in ids:
            print(f"  FAIL  {label}: {where} -> {vid} not in top_videos", file=sys.stderr)
            problems += 1

    for i, w in enumerate(result.get("watch_list") or []):
        check(w["video_id"], f"watch_list[{i}]")
    for i, t in enumerate(result.get("title_formulas") or []):
        check(t["proof_video_id"], f"title_formulas[{i}]")
    sa = result.get("script_analysis") or {}
    for i, h in enumerate(sa.get("hook_breakdown") or []):
        check(h["video_id"], f"hook_breakdown[{i}]")
    if problems == 0:
        print(f"  ok    {label}: referential integrity")
    return problems


def check_derived_fields(result, label) -> int:
    """vsr, eng_per_1k, engagement_flag and duration_label are computed, not free text."""
    problems = 0
    for i, v in enumerate(result.get("top_videos", [])):
        vid = v["video_id"]
        if v["subscriber_count"] > 0 and v["vsr"] is not None:
            expected = round(v["view_count"] / v["subscriber_count"], 2)
            if abs(expected - v["vsr"]) > 0.02:
                print(f"  FAIL  {label}[{i}] {vid}: vsr={v['vsr']} but views/subs={expected}", file=sys.stderr)
                problems += 1
        if v["like_count"] is not None and v["view_count"] > 0:
            expected = round(v["like_count"] / v["view_count"] * 1000, 2)
            if abs(expected - v["eng_per_1k"]) > 0.05:
                print(f"  FAIL  {label}[{i}] {vid}: eng_per_1k={v['eng_per_1k']} but computed={expected}", file=sys.stderr)
                problems += 1
        expected_flag = "promoted" if v["eng_per_1k"] < 1.5 else "ok"
        if v["engagement_flag"] != expected_flag:
            print(f"  FAIL  {label}[{i}] {vid}: engagement_flag={v['engagement_flag']} but eng_per_1k={v['eng_per_1k']} implies {expected_flag}", file=sys.stderr)
            problems += 1
        secs = v["duration_seconds"]
        h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
        expected_label = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        if v["duration_label"] != expected_label:
            print(f"  FAIL  {label}[{i}] {vid}: duration_label={v['duration_label']} but {secs}s -> {expected_label}", file=sys.stderr)
            problems += 1
        if v["thumbnail_url"] != f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg":
            print(f"  FAIL  {label}[{i}] {vid}: thumbnail_url not derived from video_id", file=sys.stderr)
            problems += 1
        for key in ("url", "watch_url"):
            if v[key] != f"https://www.youtube.com/watch?v={vid}":
                print(f"  FAIL  {label}[{i}] {vid}: {key} not derived from video_id", file=sys.stderr)
                problems += 1
    if problems == 0:
        print(f"  ok    {label}: derived fields")
    return problems


def main() -> int:
    registry = build_registry()
    failures = 0

    print("Validating fixtures ->", FIXTURES)
    for name, fmt in (("research-result.longform.json", "longform"),
                      ("research-result.shorts.json", "shorts")):
        result = load(name)
        failures += validate(result, f"{S}/research-result.schema.json", registry, name)
        failures += check_referential_integrity(result, name)
        failures += check_derived_fields(result, name)
        if result["request"]["format"] != fmt:
            print(f"  FAIL  {name}: request.format is {result['request']['format']}, expected {fmt}", file=sys.stderr)
            failures += 1

    failures += validate(load("config.json"), f"{S}/config.schema.json", registry, "config.json")
    for i, a in enumerate(load("adapters.json")):
        failures += validate(a, f"{S}/adapter.schema.json", registry, f"adapters.json[{i}]")
    for i, h in enumerate(load("history.json")):
        failures += validate(h, f"{S}/history-item.schema.json", registry, f"history.json[{i}]")
    for i, line in enumerate((FIXTURES / "progress-events.jsonl").read_text().splitlines()):
        if line.strip():
            failures += validate(json.loads(line), f"{S}/progress-event.schema.json", registry, f"progress-events[{i}]")

    if failures:
        print(f"\n{failures} problem(s) found.", file=sys.stderr)
        return 1
    print("\nAll fixtures valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
