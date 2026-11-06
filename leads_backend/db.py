import duckdb

from .config import DATABASE_PATH


def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    if read_only and not DATABASE_PATH.exists():
        raise FileNotFoundError(f"Banco ainda não existe: {DATABASE_PATH}")
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(DATABASE_PATH), read_only=read_only)


def has_leads_table(connection: duckdb.DuckDBPyConnection) -> bool:
    result = connection.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_name = 'leads'"
    ).fetchone()
    return bool(result and result[0])
