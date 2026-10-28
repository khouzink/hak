"""Small compatibility layer for the existing parameterized store queries."""
import psycopg


class PostgresConnection:
    def __init__(self, dsn):
        self.connection = psycopg.connect(dsn, connect_timeout=5)

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, *args):
        return self.connection.__exit__(*args)

    def execute(self, sql, params=()):
        if sql == 'BEGIN IMMEDIATE':
            # Serializes simulated inventory updates across all app processes.
            return self.connection.execute('SELECT pg_advisory_xact_lock(1869967201)')
        sql = sql.replace('?', '%s').replace(' REAL ', ' DOUBLE PRECISION ')
        return self.connection.execute(sql, params)
