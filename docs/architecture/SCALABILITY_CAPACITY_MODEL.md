# Scalability and Capacity Model

**Evidence class: TARGET / CAPACITY MODEL.** Nothing in this document is presented as a measured production benchmark.

HeatReserve's scaling strategy is based on a simple architectural fact: weather and warning evidence is **zone-scoped**, while eligibility and commitments are **worker-scoped**. The system therefore ingests and verifies shared environmental facts once per zone and reuses them across workers instead of fetching weather independently for every worker.

## Reference scenarios

| Scenario | Enrolled workers | Active zones | Average workers / zone | Runtime profile |
|---|---:|---:|---:|---|
| Judge sandbox | 12 | 3 | 4 | SQLite + one FastAPI process |
| Pilot target | 1,000 | 10 | 100 | Managed PostgreSQL, stateless API |
| City target | 25,000 | 100 | 250 | PostgreSQL/PostGIS + queue workers |
| Regional target | 100,000 | 500 | 200 | Horizontal API + queue + object-store snapshots |

These are planning scenarios, not achieved deployments.

## Why zone-level evidence matters

At the 100,000-worker / 500-zone target, the average zone contains 200 enrolled workers. A 24-hour weather replay therefore needs roughly **12,000 zone-hour facts per day** (`500 × 24`) rather than 2.4 million worker-hour weather fetches (`100,000 × 24`). That is a **200× reduction in duplicated environmental fact acquisition** under the stated even-distribution assumption.

This does **not** mean the entire system is 200× faster. It isolates one scaling advantage: source acquisition and verification can be amortized across workers in the same zone.

## Event workload model

For a heat episode affecting a zone, the computational stages are:

1. verify one warning/source snapshot per source update;
2. build one canonical zone episode;
3. batch-evaluate deterministic eligibility for workers attached to that zone;
4. atomically reserve commitments for qualified workers;
5. generate plans lazily or through a bounded queue;
6. generate one receipt for each completed consequential decision.

The policy evaluator is intentionally small and deterministic. AI planning is not in the financial authorization path, so a model outage cannot block the commitment engine.

## Storage growth model

A qualified worker can create approximately these durable records per episode:

- one commitment;
- one ledger entry;
- one adaptation plan;
- one Decision Receipt.

If all 100,000 target workers qualified in one hypothetical region-wide episode, that implies roughly **400,000 consequential rows** before indexes/audit metadata. This is a sizing assumption, not a throughput result. Production storage should therefore use managed PostgreSQL with partitioning/indexing appropriate to episode, tenant, worker and reserve lookups rather than the judge sandbox's SQLite file.

## Deployment phases

### Phase A: judge / replay

- FastAPI process;
- SQLite WAL ledger;
- frozen SHA-256 fixture bundle;
- deterministic planner by default;
- no real identities or funds.

### Phase B: pilot target

- stateless API containers behind a load balancer;
- managed PostgreSQL as the transaction authority;
- source snapshots in versioned object storage;
- authenticated tenant/worker identity;
- background queue for non-financial planning work;
- database-enforced idempotency remains authoritative.

### Phase C: city target

- PostGIS for zone/cooling-point spatial queries;
- zone-level event fan-out;
- queue autoscaling for planning;
- cache immutable source facts and episode objects;
- aggregate sponsor views separated from worker identity records;
- distributed rate limiting and centralized observability.

### Phase D: regional target

- shard/partition operational data by tenant/region where justified by measured load;
- multi-region snapshot replication only after data-residency requirements are known;
- disaster recovery, key management and audited payment-rail integration;
- explicit SLOs based on production load tests, not hackathon-machine latency.

## Scaling invariants that must not change

1. **AI never authorizes funds.**
2. **Idempotency is enforced by the transaction store, not by cache.**
3. **A commitment never spends an unverified source event.**
4. **A receipt pins exact policy, source, plan and software/prompt/verifier provenance.**
5. **Worker-level raw location history is not required for the core mechanism.**
6. **Production capacity claims remain TARGET until measured under production-like load.**

## What the current repository actually measures

The checked-in evaluation report measures local replay latency, 50-run deterministic policy equality, receipt verification, adversarial planner behavior and fixed-budget conservation. Those measurements are useful regression signals but are **not** used as evidence that the 100,000-worker target has already been achieved.
