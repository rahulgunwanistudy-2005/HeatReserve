# System Architecture

## Design principles
1. **Policy before AI.** Financial authorization is deterministic.
2. **Evidence before inference.** Every source becomes a versioned snapshot with provenance.
3. **Replay before live.** The judge path must be reproducible without network.
4. **One canonical domain core.** API, CLI, Judge Mode and evaluation all call the same functions.
5. **Fail closed on money, fail gracefully on planning.** Unknown trigger state cannot commit funds; unavailable AI falls back to deterministic planning.
6. **Minimize worker surveillance.** Coarse work-zone + preferences are enough for the prototype.

## Recommended stack
### Frontend
- Next.js / React / TypeScript
- Tailwind CSS
- MapLibre GL for geospatial display
- Zod for client schema validation

### Backend
- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy + Alembic
- PostgreSQL + PostGIS in production profile
- SQLite allowed only for lightweight local demo if feature parity is tested

### Background work
- Simple in-process jobs for replay prototype
- Redis + RQ/Celery/Arq-style queue as scale profile, not required for core correctness

### AI
Provider-neutral `PlannerProvider` interface:
- local Ollama/Qwen option for no-key mode;
- hosted provider adapter optional;
- deterministic fallback always available.

Do not make the repository impossible to run without a paid model key.

## Logical components

### 1. Source adapters
Normalize official warning/weather/geospatial inputs into immutable snapshots.

### 2. Snapshot registry
Stores:
- source URL/provider;
- fetched/issued/valid times;
- payload hash;
- parser version;
- normalized artifact.

### 3. Episode builder
Transforms warning-day records into policy episodes. The episode algorithm is versioned and deterministic.

### 4. Policy engine
Pure function:
`decision = evaluate(policy, episode, worker_eligibility, reserve_state)`

It returns a proposed commitment and reason codes. No DB writes inside pure evaluation.

### 5. Reserve transaction service
Atomically:
- checks idempotency key;
- locks/validates reserve;
- writes commitment;
- updates reserve;
- records ledger entry.

### 6. Exposure service
Computes hourly relative burden features. It is explicitly a planning proxy, not a clinical risk engine.

### 7. Planner tool layer
Typed tools expose only verified facts to the planner.

### 8. AI planner
Produces strict JSON plan proposal.

### 9. Plan verifier
Deterministically validates proposal and either accepts, repairs through a constrained path, or uses fallback.

### 10. Budget allocator
Runs transparent fixed-budget allocation heuristics for scenario comparison. It cannot touch real commitments; a production policy/admin workflow would have to adopt any allocation separately.

### 11. Receipt service
Canonicalizes and hashes decisions/plans for audit.

### 12. Replay/Judge Mode
Loads frozen manifest, verifies hashes, seeds clean state and runs identical production domain functions.

## Suggested package boundaries
```
apps/
  web/
  api/
packages/
  domain/              # pure types + policy + episode + exposure + allocator
  evidence/            # snapshot/manifests/provenance
  planner/             # tools/providers/verifier/fallback
  receipts/            # canonicalization + digest verification
  evaluation/          # benchmark harness
fixtures/
  judge_mode/
```

## Canonical control flow
```
warning snapshot
    ↓ verify hash
build episode
    ↓
evaluate deterministic policy
    ↓
reserve transaction ─────────────→ commitment
    ↓                               ↓
hourly evidence + worker constraints + cooling points
    ↓
planner tools → AI/fallback → verifier
    ↓
verified lower-exposure plan
    ↓
canonical Decision Receipt → SHA-256
    ↓
worker card + sponsor dashboard + audit endpoint
```

## Deployment profiles
### `judge`
All fixtures local; AI uses deterministic recorded fixture or local provider; no external dependency.

### `replay`
Historical source snapshots only.

### `live` — production TARGET, not implemented in the submission sandbox
External adapters with circuit breakers, caching, authenticated identities and managed storage belong to a production deployment. The prototype rejects `live` mode rather than pretending those controls exist.

### `safe_fallback`
Policy engine and deterministic planner only.

## Failure philosophy
- source authenticity unknown → no commitment;
- reserve store unavailable → no commitment;
- duplicate request → return original result;
- AI unavailable → fallback plan;
- cooling points missing → plan without location claim;
- receipt digest/hash verification failure → action may remain in DB but must be flagged unauditable and not shown as VERIFIED;
- live weather unavailable → show stale/source status and do not silently substitute generated values.
