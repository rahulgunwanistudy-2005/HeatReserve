import sqlite3

from heatreserve.schema import DOWN_SQL, UP_SQL


EXPECTED_TABLES = {
    "workers",
    "policies",
    "reserves",
    "commitments",
    "ledger_entries",
    "plans",
    "receipts",
}


def _tables(connection: sqlite3.Connection) -> set[str]:
    query = "SELECT name FROM sqlite_master WHERE type='table'"
    return {row[0] for row in connection.execute(query)}


def test_schema_upgrade_and_downgrade(tmp_path) -> None:
    path = tmp_path / "migration.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(UP_SQL)
        assert EXPECTED_TABLES <= _tables(connection)
        connection.executescript(DOWN_SQL)
        assert not (EXPECTED_TABLES & _tables(connection))
