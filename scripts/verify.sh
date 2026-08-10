#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo '[1/7] Python syntax'
python3 -m compileall -q src scripts tests

echo '[2/7] Frontend JavaScript syntax'
node --check web/app.js

echo '[3/7] Fixture integrity + offline judge path'
python3 scripts/judge_mode_check.py

echo '[4/7] Reversible migration'
DB="$(mktemp -t heatreserve-migration-XXXXXX.db)"
HEATRESERVE_DATABASE_PATH="$DB" python3 scripts/migrate.py up >/dev/null
HEATRESERVE_DATABASE_PATH="$DB" python3 scripts/migrate.py down >/dev/null
rm -f "$DB" "$DB-wal" "$DB-shm"

echo '[5/7] Test suite'
pytest --tb=short -q

echo '[6/7] Evaluation report'
python3 scripts/evaluate.py >/dev/null

echo '[7/7] Hygiene sweeps'
if grep -RInE '(sk-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16})' src web scripts fixtures .env.example README.md; then
  echo 'Potential secret detected.' >&2
  exit 1
fi
if grep -RInE '/(Users|home)/[A-Za-z0-9_-]+/' src web scripts fixtures README.md; then
  echo 'Personal absolute path detected.' >&2
  exit 1
fi

echo 'verify: PASS'
