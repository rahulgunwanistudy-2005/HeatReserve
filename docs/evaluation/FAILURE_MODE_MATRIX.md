# Failure-Mode Matrix

This matrix maps the credibility-critical failure modes to executable proof in the current repository.

| Failure mode | Expected behavior | Proof | Status |
|---|---|---|---|
| Duplicate commitment retry | return the original commitment; do not double spend | `tests/test_storage.py::test_duplicate_commitment_returns_existing_without_double_spend` | PASS |
| 20 concurrent retries | exactly one commitment | `tests/test_storage.py::test_concurrent_same_key_creates_one_commitment` | PASS |
| Concurrent different workers exceed reserve | reserve stops at zero; no overspend | `tests/test_storage.py::test_concurrent_different_workers_cannot_overspend` | PASS |
| Cross-tenant policy/reserve mismatch | fail closed | `tests/test_policy.py::test_cross_tenant_policy_cannot_spend_reserve` | PASS |
| Unverified warning source | no commitment | `tests/test_policy.py::test_unverified_warning_fails_closed` | PASS |
| Wrong warning source type | no commitment | `tests/test_policy.py::test_warning_source_type_must_match_policy` | PASS |
| Fixture byte changes | manifest verification fails | `tests/test_evidence.py::test_one_byte_mutation_breaks_manifest` | PASS |
| Malformed manifest | readiness reports error rather than crashing liveness | evidence/API tests | PASS |
| Fixture path traversal | source path rejected | `tests/test_evidence.py::test_snapshot_binding_rejects_fixture_path_escape` | PASS |
| Weather/cooling fact has wrong provenance | startup fails | `tests/test_evidence.py` fact-source binding tests | PASS |
| Frozen episode drifts from source warning | startup fails | `tests/test_evidence.py::test_episode_fixture_is_rebuilt_from_warning` | PASS |
| AI invents a cooling point | verifier rejects; deterministic fallback | planner adversarial tests/evaluation | PASS |
| Unverified place contains prompt injection | place never reaches provider context | `tests/test_planner.py::test_unverified_cooling_point_never_reaches_provider_context` | PASS |
| AI returns malformed JSON | strict parser rejects | parser test + 100-case structured-output benchmark | PASS |
| AI uses prohibited safety language | verifier rejects; fallback | adversarial benchmark | PASS |
| AI provider is unavailable | deterministic fallback remains usable | safe-fallback/planner tests | PASS |
| Missing hourly facts | planner fails loudly | `tests/test_planner.py::test_planner_fails_loudly_when_hourly_facts_are_missing` | PASS |
| Cooling point is closed | no cooling stop scheduled there | planner test | PASS |
| Worker zone lacks replay facts | planning fails rather than using another zone's data | service/planner tests | PASS |
| Plan row is altered under same ID | write rejected | storage immutability test | PASS |
| Receipt row is altered under same ID | write rejected | storage immutability test | PASS |
| Receipt protected field changes | SHA-256 verification fails | `tests/test_receipts.py` | PASS |
| Full plan payload changes | receipt's plan SHA no longer matches | `tests/test_receipts.py::test_receipt_binds_full_plan_payload` | PASS |
| Judge network unavailable | replay still runs | `tests/test_replay.py::test_judge_mode_requires_no_network` | PASS |
| Mobile/desktop rendering regression | no overflow, console/page errors or undersized visible buttons | `docs/evaluation/browser_check.json` | PASS |

The matrix deliberately does not claim real payment-rail, authentication, production database, real worker outcome or live-source failure tests because those components are outside the synthetic judge sandbox.
