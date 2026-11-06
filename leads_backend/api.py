from fastapi import FastAPI, HTTPException, Query

from .config import DEFAULT_CITY, DEFAULT_CNAE, DEFAULT_STATE
from .db import connect, has_leads_table

app = FastAPI(
    title="Leads API",
    version="0.1.0",
    description="Consulta estabelecimentos do CNPJ com filtros de região e CNAE.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/leads")
def list_leads(
    city: str = Query(DEFAULT_CITY, min_length=2, max_length=100),
    state: str = Query(DEFAULT_STATE, min_length=2, max_length=2),
    cnae: str = Query(DEFAULT_CNAE, min_length=7, max_length=7),
    include_secondary_cnae: bool = False,
    active_only: bool = True,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    try:
        connection = connect()
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail="Base ainda não foi importada.") from error

    try:
        if not has_leads_table(connection):
            raise HTTPException(status_code=503, detail="Base ainda não foi importada.")

        metadata_row = connection.execute(
            "SELECT source_month, CAST(imported_at AS VARCHAR) "
            "FROM import_metadata LIMIT 1"
        ).fetchone()

        clauses = ["upper(municipio) = upper(?)", "upper(uf) = upper(?)"]
        parameters: list[object] = [city.strip(), state.strip()]
        if active_only:
            clauses.append("situacao_cadastral = '02'")
        if include_secondary_cnae:
            clauses.append("(cnae_principal = ? OR list_contains(cnae_secundarios, ?))")
            parameters.extend([cnae, cnae])
        else:
            clauses.append("cnae_principal = ?")
            parameters.append(cnae)

        where_sql = " AND ".join(clauses)
        total = connection.execute(
            f"SELECT count(*) FROM leads WHERE {where_sql}", parameters
        ).fetchone()[0]
        offset = (page - 1) * page_size
        cursor = connection.execute(
            f"SELECT * FROM leads WHERE {where_sql} "
            "ORDER BY razao_social, cnpj LIMIT ? OFFSET ?",
            [*parameters, page_size, offset],
        )
        column_names = [description[0] for description in cursor.description]
        rows = [dict(zip(column_names, row)) for row in cursor.fetchall()]

        return {
            "filters": {
                "city": city.strip().upper(),
                "state": state.strip().upper(),
                "cnae": cnae,
                "include_secondary_cnae": include_secondary_cnae,
                "active_only": active_only,
            },
            "page": page,
            "page_size": page_size,
            "total": total,
            "source_month": metadata_row[0] if metadata_row else None,
            "imported_at": metadata_row[1] if metadata_row and metadata_row[1] else None,
            "items": rows,
        }
    finally:
        connection.close()
