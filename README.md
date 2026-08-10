# HeatReserve

**Anticipatory adaptation infrastructure for output-paid outdoor workers.**

> A heat warning is not useful enough when obeying it means losing the income needed that day. HeatReserve turns a verified heat episode into a deterministic support decision, a constrained lower-exposure work plan, and a tamper-evident Decision Receipt.

HeatReserve is built for the **OurPlanet.Rocks Technical Track**. It is intentionally not a weather app, insurance marketplace, medical-risk scorer, worker-surveillance tool, or chatbot wrapper.

## 60-second judge path

```bash
python3 -m pip install -e '.[dev]'
./scripts/verify.sh
./scripts/start.sh
```

Open `http://localhost:8000` and press **Run Judge Mode**.

Judge Mode runs from frozen hash-verified fixtures and does not require the internet or an AI provider. The full proof chain is:

`verified replay → deterministic commitment → grounded planning → receipt digest verification/tamper → fixed-budget allocation → evidence labels`

## Why this mechanism exists

External research is the motivation, not a claim about HeatReserve's own impact. A randomized study of 276 delivery workers in Delhi/Gurugram tested heat warnings versus the same warnings plus small forecast-triggered transfers. HeatReserve uses that evidence to motivate **adaptation liquidity**, while separately measuring only what this prototype actually does.

Every judge-visible metric is assigned one of four evidence classes:

- **RESEARCH**: external study, official guidance, or SDG source.
- **MEASURED**: behavior produced and tested by this repository.
- **SIMULATED**: deterministic replay or modeled scenario output.
- **TARGET**: future scale goal, never presented as achieved.

## What the prototype implements

### Deterministic financial control plane

The AI never decides eligibility, policy version, amount, reserve balance, commitment state, or reason codes. A versioned policy engine evaluates a verified source snapshot, worker eligibility, episode, and reserve. SQLite transactions plus a unique idempotency key prevent duplicate or negative commitments under concurrency.

### Relative heat-burden planner

Hourly replay conditions are ranked with an explicit engineering proxy. The model is for **relative planning only**, not medical clearance or occupational-safety certification. The deterministic baseline preserves required work minutes where feasible and shifts hours toward lower modeled burden.

### Optional grounded AI planner

`HEATRESERVE_PLANNER_PROVIDER=ollama` enables a local Ollama adapter. The provider receives typed hourly facts, worker constraints, and curated cooling points, then returns strict JSON. A deterministic verifier rejects unsupported locations, unavailable time windows, duplicate slots, missing caveats, and prohibited language such as “safe to work.” Any failure falls back to the deterministic planner.

Judge Mode defaults to `deterministic`, so judging cannot fail because a model or network is unavailable.

The exact runtime prompt is versioned in [`src/heatreserve/prompts.py`](src/heatreserve/prompts.py).

### Decision Receipt

Each consequential demo decision is bound to a canonical SHA-256 digest including the deterministic decision status, reason codes and idempotency key; policy version and commitment; a SHA-256 of the full plan payload; source snapshot IDs; planner/model; prompt version; verifier version; and tool fact IDs. Judge Mode changes the amount in a receipt copy and demonstrates verification failure.

This is a **tamper-evident digest**, not an asymmetric digital signature.

### Sponsor allocation scenarios

Three scenario-only strategies run over the same fixed simulated reserve:

1. equal / first-qualified;
2. impact-first;
3. impact + fairness, with a one-per-zone coverage pass before impact ranking.

These deterministic allocation heuristics cannot mutate the reserve ledger. They make budget and fairness trade-offs explicit; they are not claimed to be a globally optimal solver and must not automate production welfare denial.

## Current evaluation

Run `python3 scripts/evaluate.py` to regenerate `docs/evaluation/evaluation_report.json` and `.md` from the current code and frozen fixtures.

Current checked-in report includes:

- 50 repeated policy evaluations with identical outputs **[MEASURED]**;
- full reset/replay core-output reproducibility **[MEASURED]**;
- 35 planner adversarial cases with deterministic fallback on invalid outputs and acceptance of valid structured outputs **[MEASURED]**;
- 100/100 expected classifications in the synthetic raw JSON parser/schema gate **[MEASURED]**;
- warning-only, support-only and HeatReserve component ablation on the same frozen replay **[SIMULATED]**;
- zero unsupported cooling locations and zero prohibited safety-language outputs in that benchmark **[MEASURED]**;
- original receipt digest verifies and a protected-field tamper fails **[MEASURED]**;
- ledger reconciliation and fixed-budget conservation **[MEASURED]**;
- demo worker modeled burden change and high-heat minutes shifted **[SIMULATED]**.

Machine-specific latency in the report is labeled MEASURED and is not presented as production capacity.

## Architecture

```text
Frozen source fixtures
        │
        ▼
Manifest verifier ──► Episode / source facts
        │
        ├────────────► Deterministic policy ─► atomic reserve ledger
        │                                      │
        │                                      ▼
        └────────────► burden/tool facts ─► planner provider
                                            │
                                            ▼
                                   deterministic verifier
                                            │
                                            ▼
                                      Decision Receipt
                                            │
                         ┌──────────────────┴──────────────────┐
                         ▼                                     ▼
                    Worker UX                           Sponsor allocator
```

Editable architecture diagrams are in `docs/architecture/`.

## Repository map

```text
src/heatreserve/
  domain.py       strict domain and evidence contracts
  evidence.py     manifest verification + canonical hashing
  policy.py       pure financial policy evaluator
  storage.py      transactional SQLite ledger/repository
  burden.py       transparent relative-burden scoring
  planner.py      deterministic + Ollama planners and verifier
  allocator.py    fixed-budget allocation baselines
  receipts.py     canonical receipt digest + verification
  service.py      one canonical application service
  api.py          FastAPI routes, errors, security headers, rate limiting
web/
  index.html      accessible application shell
  styles.css      Midnight × Ember × Amber × Teal visual system
  app.js          worker, sponsor, evidence and explicit Judge Mode state machine
fixtures/judge_mode/
  manifest.json   SHA-256 evidence manifest
  *.json          synthetic replay inputs
scripts/
  verify.sh       one-command submission verification
  evaluate.py     machine-readable evaluation report generator
  judge_mode_check.py
  migrate.py
```

## API

Key endpoints:

- `GET /health/live`
- `GET /health/ready`
- `POST /v1/judge/reset`
- `POST /v1/judge/run`
- `GET /v1/episodes/{episode_id}`
- `POST /v1/workers/{worker_id}/commitments`
- `POST /v1/workers/{worker_id}/plans`
- `POST /v1/allocator/scenarios`
- `GET /v1/receipts/{receipt_id}`
- `POST /v1/receipts/verify`
- `GET /v1/evidence/sources`

Interactive OpenAPI is available at `/docs` while the API is running.

## Configuration

Copy `.env.example` into your environment as needed. No secret is required for Judge Mode.

```text
HEATRESERVE_MODE=judge|replay|safe_fallback
HEATRESERVE_DATABASE_PATH=./data/heatreserve.db
HEATRESERVE_FIXTURE_DIR=./fixtures/judge_mode
HEATRESERVE_PLANNER_PROVIDER=deterministic|ollama
HEATRESERVE_OLLAMA_URL=http://127.0.0.1:11434
HEATRESERVE_OLLAMA_MODEL=qwen3:4b
HEATRESERVE_ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
```

`live` adapters are deliberately **not** exposed by this prototype. Production source adapters are a documented TARGET, not a claimed implemented feature. `safe_fallback` always forces the deterministic planner even if an Ollama provider is configured.

## Verification

`./scripts/verify.sh` performs:

1. Python compilation;
2. frontend JavaScript syntax check;
3. hash-verified, network-blocked Judge Mode replay;
4. schema migration up/down check;
5. full pytest suite;
6. evaluation-report regeneration;
7. secret and portability sweeps.

The project-quality audit report is checked into `PROJECT_AUDIT_REPORT.md` after the final audit pass.

## Privacy and safety boundaries

- demo workers are synthetic pseudonymous records;
- no live GPS history is stored;
- sponsor views use coarse aggregate zones;
- no output claims that a work period is safe;
- no medical advice or health diagnosis is produced;
- no AI output can change money-related state;
- production deployments must add real identity/auth, verified data adapters, consent/retention policy, and production-grade managed storage before handling real workers or real funds.

## SDG alignment

Primary: **SDG 8.8**, protecting labour rights and promoting safe and secure working environments.

Secondary: **SDG 13.1**, strengthening resilience and adaptive capacity to climate-related hazards.

See `docs/evidence/` for the evidence dossier, claim ledger, references, and source manifest.

## Known prototype boundaries

The replay weather, workers, cooling points, commitment, and allocator data are synthetic. The ₹200 value is research-inspired for demonstration and is not asserted to be a universally correct production amount. HeatReserve does not claim measured health improvement, lives saved, a real payment rail, an organizer/company partnership, or a validated production heat threshold.

## License

MIT. See `LICENSE`.
