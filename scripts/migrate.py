from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from heatreserve.config import Settings
from heatreserve.schema import DOWN_SQL, UP_SQL

parser = argparse.ArgumentParser(
    description="Apply or reverse the HeatReserve SQLite schema migration."
)
parser.add_argument("direction", choices=("up", "down"))
args = parser.parse_args()
settings = Settings.from_env()
path = Path(settings.database_path)
path.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(path) as connection:
    connection.executescript(UP_SQL if args.direction == "up" else DOWN_SQL)
print(f"migration {args.direction}: {path}")
