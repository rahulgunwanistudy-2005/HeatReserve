UP_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS workers (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    worker_type TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    language TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policies (
    policy_id TEXT NOT NULL,
    version TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    status TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY(policy_id, version)
);
CREATE TABLE IF NOT EXISTS reserves (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    currency TEXT NOT NULL CHECK(currency = 'INR'),
    initial_minor INTEGER NOT NULL CHECK(initial_minor >= 0),
    current_minor INTEGER NOT NULL CHECK(current_minor >= 0),
    version INTEGER NOT NULL CHECK(version >= 0)
);
CREATE TABLE IF NOT EXISTS commitments (
    id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL REFERENCES workers(id),
    episode_id TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    amount_minor INTEGER NOT NULL CHECK(amount_minor >= 0),
    status TEXT NOT NULL,
    decision_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_commitments_worker_episode ON commitments(worker_id, episode_id);
CREATE TABLE IF NOT EXISTS ledger_entries (
    id TEXT PRIMARY KEY,
    reserve_id TEXT NOT NULL REFERENCES reserves(id),
    commitment_id TEXT NOT NULL UNIQUE REFERENCES commitments(id),
    entry_type TEXT NOT NULL CHECK(entry_type = 'COMMITMENT'),
    amount_minor INTEGER NOT NULL CHECK(amount_minor >= 0),
    balance_after_minor INTEGER NOT NULL CHECK(balance_after_minor >= 0),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_reserve ON ledger_entries(reserve_id, created_at);
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL REFERENCES workers(id),
    episode_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts (
    id TEXT PRIMARY KEY,
    commitment_id TEXT NOT NULL REFERENCES commitments(id),
    plan_id TEXT NOT NULL REFERENCES plans(id),
    digest_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

DOWN_SQL = """
DROP TABLE IF EXISTS receipts;
DROP TABLE IF EXISTS plans;
DROP TABLE IF EXISTS ledger_entries;
DROP TABLE IF EXISTS commitments;
DROP TABLE IF EXISTS reserves;
DROP TABLE IF EXISTS policies;
DROP TABLE IF EXISTS workers;
"""
