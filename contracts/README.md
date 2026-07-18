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
├── fixtures/           Realistic data built from ../data/*.json (frontend/fixtures -> here)
│   ├── research-result.longform.json
│   ├── research-result.shorts.json
│   ├── progress-events.jsonl
│   ├── adapters.json · history.json · config.json
└── build_fixtures.py   Normalizes data/*.json into the unified Video schema + fixtures
```

Regenerate + validate fixtures:

```bash
make fixtures            # or: backend/.venv/bin/python contracts/build_fixtures.py
```

`build_fixtures.py` both *produces* the fixtures and *validates* them against the
JSON Schemas, so running it doubles as a check that the normalizer and the
contracts agree.
