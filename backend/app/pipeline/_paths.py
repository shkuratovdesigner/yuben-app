"""Path / import plumbing for the Gen-2 research scripts (B3).

The root research scripts (``longform_research.py`` / ``shorts_research.py``) and
their helpers do::

    from youtube_research.youtube_api import ...
    from youtube_research.config import ...

which historically resolved through a ``youtube_research -> YuBen`` symlink that
lived *outside* this repo (a sibling of the repo root). That symlink does not
exist here, so the imports fail on a clean checkout.

Rather than depend on a sibling path or an on-disk symlink, we register a tiny
in-memory **namespace package** named ``youtube_research`` whose ``__path__`` is
the repo root. Then ``youtube_research.youtube_api`` resolves to
``<repo>/youtube_api.py``, ``youtube_research.config`` to ``<repo>/config.py``,
``youtube_research.transcript`` to ``<repo>/transcript.py``, etc. — no symlink,
no sibling repo, fully self-contained and commit-safe.

Importing this module also ensures the repo root is on ``sys.path`` (so the
top-level Gen-2 modules and the shared ``contracts`` package import), mirroring
what ``backend/app/main.py`` and ``backend/tests/conftest.py`` already do.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

# backend/app/pipeline/_paths.py -> parents[3] == repo root (YuBen/).
REPO_ROOT: Path = Path(__file__).resolve().parents[3]

_ALIAS = "youtube_research"


def _ensure_repo_on_path() -> None:
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def install_youtube_research_alias() -> None:
    """Register ``youtube_research`` as a namespace package rooted at the repo.

    Idempotent and side-effect-light: it only touches ``sys.modules`` /
    ``sys.path`` and imports nothing from the scripts (so importing
    ``app.pipeline`` never requires the YouTube key or the pipeline deps).
    """
    _ensure_repo_on_path()

    existing = sys.modules.get(_ALIAS)
    if existing is not None and getattr(existing, "__path__", None):
        # Already installed (ours or a real package/symlink) — leave it be.
        return

    pkg = types.ModuleType(_ALIAS)
    # A list-valued __path__ makes this a package; pointing it at the repo root
    # makes the repo-root .py files importable as youtube_research.<name>.
    pkg.__path__ = [str(REPO_ROOT)]  # type: ignore[attr-defined]
    pkg.__doc__ = (
        "YuBen shim (B3): namespace package mapping youtube_research.* onto the "
        "repo-root Gen-2 research modules. See backend/app/pipeline/_paths.py."
    )
    sys.modules[_ALIAS] = pkg


# Make the repo root importable as soon as anything in the pipeline package
# touches this module (e.g. runner importing `contracts.python.models`).
_ensure_repo_on_path()
