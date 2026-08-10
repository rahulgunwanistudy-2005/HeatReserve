# HeatReserve Evaluation Report

Generated: `2026-08-10T16:12:18.031541+00:00`

This report is generated from frozen replay fixtures. Modeled exposure metrics are **SIMULATED**, not health outcomes.

## Determinism and replay
- 50 repeated policy runs identical: **True** `[MEASURED]`
- Full replay core outputs identical after reset: **True** `[MEASURED]`
- Judge replay requires network: **False** `[MEASURED]`

## Planner
- Baseline relative burden: **4.9595** `[SIMULATED]`
- Recommended relative burden: **1.3288** `[SIMULATED]`
- Relative burden delta: **3.6307** `[SIMULATED]`
- Modeled high-heat minutes shifted: **360** `[SIMULATED]`
- Adversarial cases: **35**; unsupported locations: **0**; prohibited-language outputs: **0** `[MEASURED]`
- Raw structured-output gate: **100/100** expected classifications `[MEASURED]`
- Raw structured-output result is a synthetic parser/schema benchmark, not a live-model reliability claim.

## Replay component ablation
- Warning only modeled burden: **4.9595** `[SIMULATED]`
- Support only modeled burden: **4.9595** `[SIMULATED]`
- HeatReserve modeled burden: **1.3288** `[SIMULATED]`
- High-heat minutes shifted per ₹1,000 simulated support: **1800.0** `[SIMULATED]`
- The support-only arm assumes no schedule change; this is not a causal worker-behavior estimate.

## Financial and receipt invariants
- Original receipt verifies: **True** `[MEASURED]`
- Tampered receipt verifies: **False** `[MEASURED]`
- Ledger reconciles: **True** `[MEASURED]`
- Allocator conserves fixed budget: **True** `[MEASURED]`

## Local latency
- Median full replay: **11.71 ms** `[MEASURED]`
- p95 full replay: **34.29 ms** `[MEASURED]`
- Sample size: **25**

Latency is machine-specific and is not presented as a production capacity claim.
