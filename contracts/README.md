# contracts/

The **frozen interface** between frontend, backend, and the agent. Everything
downstream builds against this so the two tracks never block each other.

Single source of truth: [../docs/CONTRACTS.md](../docs/CONTRACTS.md).

```
contracts/
├── schemas/            JSON Schema (draft 2020-12) — one file per object
│                       (research-request, progress-event, video, research-result,
│                        config, adapter, history-item, agent-result)
├── python/             Pydantic models mirroring the schemas (imported by backend)
├── ts/                 Generated TypeScript types (also copied to frontend/src/lib/types.ts)
├── fixtures/           Demo data the mock-mode UI runs on (frontend/fixtures -> here)
│   ├── research-result.longform.json   <- built by build_mock_fixtures.py
│   ├── research-result.shorts.json     <- built by build_mock_fixtures.py
│   ├── history.json                    <- built by build_mock_fixtures.py
│   ├── progress-events.jsonl           <- hand-maintained
│   ├── adapters.json · config.json     <- hand-maintained
├── mock_videos/            Curated, oEmbed-verified video set the fixtures build from
├── build_mock_fixtures.py  Builds the research-result + history fixtures
├── validate_fixtures.py    Contract-checks every committed fixture
└── normalize_reference.py  Reference normalizer — writes nothing; see below
```

Regenerate + validate fixtures:

```bash
make fixtures            # build_mock_fixtures.py, then validate_fixtures.py
```

Note that `make fixtures` only rebuilds the research-result and history fixtures.
**`adapters.json`, `config.json` and `progress-events.jsonl` are hand-maintained** —
edit them directly, then run `make validate-fixtures` to contract-check the result.

### normalize_reference.py

Despite living next to the builders, this one **generates nothing**. It is a
second, independent implementation of raw-row → `Video` normalization that
`backend/tests/test_pipeline.py` diffs against the backend's real normalizer in
`backend/app/pipeline/normalize.py`. Two implementations agreeing is a stronger
signal than one checked against itself, so the duplication is intentional — if
they drift, fix whichever is wrong rather than copying one over the other.

Those parity tests skip unless `data/` is present (it is gitignored and absent
from a fresh clone).
