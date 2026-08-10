# Acceptance Gate Status

Generated against the current HeatReserve prototype. `PASS` means the repository contains executable or directly inspectable proof. `PARTIAL` means the remaining item is a submission/production activity rather than hidden unfinished code.

| Gate | Status | Evidence |
|---|---|---|
| G0 Evidence | PASS | Claim ledger updated; evidence classes visible; no partnership/health-outcome overclaim |
| G1 Policy core | PASS | deterministic evaluator, per-episode cap, atomic reserve, idempotency and concurrency tests |
| G2 Replay | PASS | hash manifest, raw snapshot binding, source-to-episode reconstruction, network-disabled test |
| G3 Exposure/planning primitives | PASS | missing humidity/hourly facts rejected, timezone-aware replay, relative-burden model only |
| G4 AI | PASS | strict raw JSON gate, adversarial verifier, unverified-context isolation, deterministic fallback, AI cannot affect payout |
| G5 Allocator | PASS | fixed-budget strategies, conservation tests, per-worker commitment cap, zone-fairness explanation |
| G6 Receipt | PASS | canonical SHA-256, full-plan SHA, deterministic decision/reason/idempotency binding, immutable plan/receipt IDs, tamper test, source/version provenance |
| G7 UX | PASS | 360/375/1440 browser render checks, ≥44px visible buttons, keyboard focus, evidence labels, Judge Mode |
| G8 Evaluation | PASS | one-command report, warning/support/HeatReserve ablation, 50 policy repeats, failure matrix |
| G9 Submission | PARTIAL | fresh-copy verification is performed in the release audit; video script/deck outline exist, but recording/upload and final submission links are human submission actions |

## Important claim boundary

A green engineering gate does not turn SIMULATED replay output into real-world impact. HeatReserve still does **not** claim measured illness reduction, lives saved, a real payout rail, live worker deployment, organizer endorsement or production-scale performance.
