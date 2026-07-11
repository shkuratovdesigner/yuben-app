"""Pipeline wrapper (B3): wrap the Gen-2 research scripts -> unified ``Video[]`` + meta.

Public API (imported by B4 orchestrator and B1's config router):
  * ``run_pipeline(request, *, keywords=None, compute_medians=False)``
        -> ``(list[Video-dict], meta-dict)`` — deterministic source of truth.
  * ``test_youtube_key()`` -> ``{"ok": bool, "message": str}`` — cheap key probe.

Importing this package installs an in-memory ``youtube_research`` namespace
package pointing at the repo root, so the scripts' ``from youtube_research.* ...``
imports resolve without a sibling repo or an on-disk symlink (see ``_paths.py``).
This side effect is intentionally light — it touches only ``sys.modules`` /
``sys.path`` and imports none of the pipeline deps or the YouTube key, so
``import app.pipeline`` is always safe (e.g. Wave-1 defensive imports).
"""
from __future__ import annotations

from ._paths import REPO_ROOT, install_youtube_research_alias

# Side effect: make `import youtube_research.youtube_api` (etc.) resolve now.
install_youtube_research_alias()

from .keytest import test_youtube_key  # noqa: E402
from .normalize import duration_label, normalize_video, normalize_videos  # noqa: E402
from .params import PipelineParams, map_request_to_params  # noqa: E402
from .runner import PipelineError, run_pipeline  # noqa: E402

__all__ = [
    "run_pipeline",
    "test_youtube_key",
    "PipelineError",
    "PipelineParams",
    "map_request_to_params",
    "normalize_video",
    "normalize_videos",
    "duration_label",
    "REPO_ROOT",
    "install_youtube_research_alias",
]
