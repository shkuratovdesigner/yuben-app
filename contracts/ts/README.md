# contracts/ts

The generated TypeScript types live at
[`frontend/src/lib/types.ts`](../../frontend/src/lib/types.ts) — co-located with
the app that consumes them (`import { ResearchResult } from '@/lib/types'`) so
Vite resolves them without crossing the package boundary.

They are a hand-maintained mirror of `../schemas/*.json`. When a schema changes,
update `types.ts` and `../python/models.py` in the same commit, then run
`make fixtures` (schema validation) and `make test` (Pydantic + tsc) to confirm
all three agree.
