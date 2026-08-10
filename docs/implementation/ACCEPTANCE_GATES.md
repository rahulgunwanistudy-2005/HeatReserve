# Acceptance Gates

A phase is complete only when its gate is green.

## G0 Evidence
- Every research claim is in `docs/evidence/CLAIM_LEDGER.csv`.
- Every product-generated metric has an evidence class.
- No unverified partnership language exists.

## G1 Policy core
- Same normalized inputs produce byte-equivalent decision outputs.
- Property test: reserve never negative.
- Property test: one worker/episode/policy cannot produce duplicate commitments.
- Failure is fail-closed, with reason code.

## G2 Replay
- Every source artifact has SHA-256.
- Replay works with network disabled.
- Snapshot mutation causes manifest verification failure.

## G3 Exposure / planning primitives
- Hourly slots are reproducibly ranked.
- Unsupported clinical language is absent.
- Tests cover missing humidity, missing hourly values and timezone boundaries.

## G4 AI
- JSON schema validity >= 99% on benchmark or fallback invoked.
- 100% of invented cooling locations rejected in adversarial set.
- 100% of prohibited "safe" claims rejected or rewritten.
- AI outage does not prevent policy decision or Judge Mode.

## G5 Allocator
- Budget conservation property passes.
- Per-worker cap passes.
- Fairness constraint is testable and explained.
- Output includes why selected/not selected.

## G6 Receipt
- Canonicalization deterministic across repeated runs.
- Any digest-protected field mutation invalidates digest verification.
- Receipt records source IDs and software/policy/prompt versions.

## G7 UX
- Worker can see action in <= 2 taps after entering Judge Mode.
- Evidence labels visible before metric details.
- Mobile width 360px has no horizontal overflow.
- Keyboard navigation and contrast checks pass.

## G8 Evaluation
- Baseline and ablation report generated from one command.
- No metric lacks class/source.
- Determinism test repeated >= 50 runs.
- Failure-mode matrix green or explicitly documented.

## G9 Submission
- Fresh clone verification passes.
- Judge Mode network-disabled replay passes.
- 2–3 minute video is within limit.
- Pitch deck and app make identical claims.
- AI disclosure names build-time and runtime AI separately.
