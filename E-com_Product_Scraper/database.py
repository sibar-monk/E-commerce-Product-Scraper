"""Connect to the local catalog and create its tables when needed."""

import sqlite3
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
DATABASE_PATH = PROJECT_DIR / "products.db"
SCHEMA_PATH = PROJECT_DIR / "schema.sql"


def connect(path=DATABASE_PATH):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.create_function("casefold", 1, str.casefold, deterministic=True)
    return connection


def initialize(connection):
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    # Upgrade an earlier project database without deleting its rows or checkpoints.
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(products)")}
        if "category" not in columns:
            connection.execute("ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT '' "
                               "CHECK (length(category) <= 100)")
        if "rating" not in columns:
            connection.execute("ALTER TABLE products ADD COLUMN rating INTEGER "
                               "CHECK (rating IS NULL OR (typeof(rating) = 'integer' AND rating BETWEEN 1 AND 5))")


if __name__ == "__main__":
    connection = connect()
    try:
        initialize(connection)
        print(f"Database ready at {DATABASE_PATH}")
    finally:
        connection.close()
