import json
import os
import sqlite3
from pathlib import Path
from backend.domain.errors import Conflict, JourneyNotFound


class ClosingConnection(sqlite3.Connection):
    """sqlite3's own `with` commits or rolls back but leaves the connection open; this one also closes it."""

    def __exit__(self, *exc):
        try:
            return super().__exit__(*exc)
        finally:
            self.close()


class Store:
    def __init__(self, path: str | None = None):
        self.database_url = os.getenv('DATABASE_URL', '') if path is None else ''
        self.path = path or os.getenv("DATABASE_PATH", "data/uno.sqlite3")
        if not self.database_url:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS trips (id TEXT PRIMARY KEY, owner TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL)")

    def connect(self):
        if self.database_url:
            from backend.infrastructure.postgres import PostgresConnection
            return PostgresConnection(self.database_url)
        connection = sqlite3.connect(self.path, timeout=10, factory=ClosingConnection)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def create(self, trip: dict, owner: str):
        with self.connect() as con:
            con.execute("INSERT INTO trips VALUES(?,?,?,?)", (trip["id"], owner, 0, json.dumps(trip, ensure_ascii=False)))

    def get(self, trip_id: str, owner: str) -> tuple[dict, int]:
        with self.connect() as con:
            row = con.execute("SELECT payload, revision FROM trips WHERE id=? AND owner=?", (trip_id, owner)).fetchone()
        if not row:
            raise JourneyNotFound("Поездка не найдена")
        return json.loads(row[0]), row[1]

    def save(self, trip: dict, owner: str, revision: int):
        with self.connect() as con:
            updated = con.execute("UPDATE trips SET payload=?, revision=revision+1 WHERE id=? AND owner=? AND revision=?", (json.dumps(trip, ensure_ascii=False), trip["id"], owner, revision)).rowcount
            if updated != 1:
                raise Conflict("Поездка уже изменилась. Обнови страницу и повтори действие.")
