# Threat Model

## Assets
- reserve balance / commitment integrity;
- worker privacy;
- source warning authenticity/provenance;
- policy immutability/versioning;
- receipt integrity;
- admin authorization;
- evidence credibility.

## Threats and mitigations

### T1 Duplicate trigger / retry causes double commitment
Mitigation: deterministic idempotency key + DB unique constraint + atomic transaction.

### T2 Concurrent commitments overspend reserve
Mitigation: row/version lock or serializable transaction; check balance inside transaction; property/concurrency test.

### T3 Attacker edits warning fixture to force qualification
Mitigation: manifest hashes; replay boot verifies all source files; source IDs embedded in receipt.

### T4 Admin silently changes published policy
Mitigation: published policy immutable; changes create new version/hash; receipt pins version.

### T5 LLM invents cooling center
Mitigation: planner may only return IDs from tool output; verifier rejects unknown IDs.

### T6 Prompt injection via place/source text
Mitigation: unverified cooling points never enter model context; verified records are serialized as structured JSON data; the system prompt forbids following instructions embedded in tool data; the deterministic verifier checks every returned fact/location ID.

### T7 AI manipulates payout
Mitigation: financial engine receives no planner output as an authorization input.

### T8 Cross-tenant data leak
Mitigation in this synthetic judge sandbox: deterministic policy/repository boundaries require matching tenant IDs and tests prove cross-tenant spending fails closed. The public demo intentionally has no end-user authentication because it contains one synthetic tenant and no real PII or funds. A production deployment must add authenticated identity plus tenant authorization before any real multi-tenant use.

### T9 Worker surveillance
Mitigation: no continuous GPS required; coarse zone; minimize PII; aggregation; explicit purpose limitation.

### T10 Judge Mode relies on remote API and fails
Mitigation: immutable local replay bundle + deterministic fallback planner.

### T11 Fake impact claims
Mitigation: evidence-class field on every metric + claim ledger + submission claim audit.

### T12 Secrets in repository
Mitigation: `.env.example`, secret scanner, no credentials in fixtures, CI check.

## Security tests
- duplicate request race;
- tenant-consistency isolation;
- receipt mutation;
- manifest mutation;
- prompt injection fixture;
- malformed JSON;
- dependency outage;
- invalid policy version;
- SQL injection defaults/framework tests;
- XSS in cooling-point names / worker strings.
