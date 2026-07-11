"""Link verification (B5): oEmbed + id-existence checks.

The agent is KNOWN to fabricate 11-char video ids. By the time a link reaches
this module the *fabrication* guard has already run (``assemble.py`` joins every
id to the deterministic ``pipeline_videos`` and drops unknowns), so this module's
job is narrower: classify the *health* of an already-authoritative link as
``verified`` | ``embed_disabled`` | ``dead`` using YouTube's public oEmbed
endpoint. oEmbed doubles as the existence check — a 404/410 means the id no
longer resolves.

Status mapping (CONTRACTS §4 / PRD §8):
    HTTP 200            -> "verified"        (public + embeddable)
    HTTP 401 / 403      -> "embed_disabled"  (public but embedding restricted)
    HTTP 404 / 410      -> "dead"            (gone)
    anything else / err -> None              (inconclusive; caller keeps the
                                              pipeline-provided status)

Network is injectable two ways so tests never hit YouTube and Phase-2 can batch:
  * pass a ready ``LinkVerifier`` (e.g. a stub) into ``assemble_and_verify``, or
  * construct ``OEmbedVerifier(client=...)`` with an ``httpx.Client`` wired to a
    ``httpx.MockTransport``.
"""
from __future__ import annotations

from typing import Optional

try:  # Protocol lives in typing on 3.8+, but be defensive on 3.9.
    from typing import Protocol, runtime_checkable
except ImportError:  # pragma: no cover
    from typing_extensions import Protocol, runtime_checkable  # type: ignore

import httpx

from contracts.python.models import LinkStatus

OEMBED_URL = "https://www.youtube.com/oembed"
_WATCH = "https://www.youtube.com/watch?v={video_id}"


def watch_url(video_id: str) -> str:
    """Canonical watch URL for a video id (never built from agent free-text)."""
    return _WATCH.format(video_id=video_id)


def classify_status(status_code: int) -> Optional[LinkStatus]:
    """Map an oEmbed HTTP status to a ``LinkStatus`` (``None`` = inconclusive)."""
    if status_code == 200:
        return "verified"
    if status_code in (401, 403):
        return "embed_disabled"
    if status_code in (404, 410):
        return "dead"
    return None


@runtime_checkable
class LinkVerifier(Protocol):
    """Anything with ``verify(video_id) -> Optional[LinkStatus]``.

    Returning ``None`` means "could not determine" so the caller keeps the
    authoritative pipeline status rather than downgrading a real video.
    """

    def verify(self, video_id: str) -> Optional[LinkStatus]:  # pragma: no cover
        ...


class OEmbedVerifier:
    """Default verifier: one oEmbed GET per id via ``httpx``.

    Owns its ``httpx.Client`` unless one is injected (tests inject a client bound
    to a ``MockTransport``; an injected client is never closed by us).
    """

    def __init__(self, client: Optional[httpx.Client] = None, timeout: float = 5.0):
        self._client = client
        self._owns_client = client is None
        self._timeout = timeout

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout, follow_redirects=True)
        return self._client

    def verify(self, video_id: str) -> Optional[LinkStatus]:
        try:
            resp = self._get_client().get(
                OEMBED_URL, params={"url": watch_url(video_id), "format": "json"}
            )
        except httpx.HTTPError:
            return None  # transient/network — inconclusive, don't downgrade
        return classify_status(resp.status_code)

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "OEmbedVerifier":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
