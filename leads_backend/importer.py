"""Importa os ZIPs oficiais da Receita para DuckDB.

Os arquivos da Receita contêm CSVs sem cabeçalho, separados por ponto e vírgula
e com texto em Windows-1252.
"""

import argparse
import re
from shutil import copyfileobj
import tempfile
from pathlib import Path
from zipfile import ZipFile

import duckdb

from .config import DATABASE_PATH

RMC_MUNICIPALITIES = (
    "ADRIANOPOLIS",
    "AGUDOS DO SUL",
    "ALMIRANTE TAMANDARE",
    "ARAUCARIA",
    "BALSA NOVA",
    "BOCAIUVA DO SUL",
    "CAMPINA GRANDE DO SUL",
    "CAMPO DO TENENTE",
    "CAMPO LARGO",
    "CAMPO MAGRO",
    "CERRO AZUL",
    "COLOMBO",
    "CONTENDA",
    "CURITIBA",
    "DOUTOR ULYSSES",
    "FAZENDA RIO GRANDE",
    "ITAPERUCU",
    "LAPA",
    "MANDIRITUBA",
    "PIEN",
    "PINHAIS",
    "PIRAQUARA",
    "QUATRO BARRAS",
    "QUITANDINHA",
    "RIO BRANCO DO SUL",
    "RIO NEGRO",
    "SAO JOSE DOS PINHAIS",
    "TIJUCAS DO SUL",
    "TUNAS DO PARANA",
)

ESTABLISHMENT_COLUMNS = {
    "cnpj_base": "VARCHAR",
    "cnpj_ordem": "VARCHAR",
    "cnpj_dv": "VARCHAR",
    "identificador_matriz_filial": "VARCHAR",
    "nome_fantasia": "VARCHAR",
    "situacao_cadastral": "VARCHAR",
    "data_situacao_cadastral": "VARCHAR",
    "motivo_situacao_cadastral": "VARCHAR",
    "cidade_exterior": "VARCHAR",
    "pais": "VARCHAR",
    "data_inicio_atividade": "VARCHAR",
    "cnae_principal": "VARCHAR",
    "cnae_secundarios_raw": "VARCHAR",
    "tipo_logradouro": "VARCHAR",
    "logradouro": "VARCHAR",
    "numero": "VARCHAR",
    "complemento": "VARCHAR",
    "bairro": "VARCHAR",
    "cep": "VARCHAR",
    "uf": "VARCHAR",
    "municipio_codigo": "VARCHAR",
    "ddd1": "VARCHAR",
    "telefone1": "VARCHAR",
    "ddd2": "VARCHAR",
    "telefone2": "VARCHAR",
    "ddd_fax": "VARCHAR",
    "fax": "VARCHAR",
    "email": "VARCHAR",
    "situacao_especial": "VARCHAR",
    "data_situacao_especial": "VARCHAR",
}

COMPANY_COLUMNS = {
    "cnpj_base": "VARCHAR",
    "razao_social": "VARCHAR",
    "natureza_juridica": "VARCHAR",
    "qualificacao_responsavel": "VARCHAR",
    "capital_social": "VARCHAR",
    "porte_codigo": "VARCHAR",
    "ente_federativo_responsavel": "VARCHAR",
}

MUNICIPALITY_COLUMNS = {
    "municipio_codigo": "VARCHAR",
    "municipio": "VARCHAR",
}

CNAE_COLUMNS = {
    "cnae_codigo": "VARCHAR",
    "cnae_descricao": "VARCHAR",
}


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def read_csv_query(path: Path, columns: dict[str, str]) -> str:
    mapped = ", ".join(f"'{name}': '{kind}'" for name, kind in columns.items())
    normalized_path = str(path.resolve()).replace("\\", "/")
    return (
        f"read_csv({sql_string(normalized_path)}, "
        f"delim=';', header=false, all_varchar=true, "
        f"columns={{{mapped}}}, encoding='windows-1252-2000', ignore_errors=true)"
    )


def collect_table_files(source_dir: Path, table_prefix: str, temp_dir: Path) -> list[Path]:
    files = [
        path
        for path in source_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() == ".csv"
        and path.name.lower().startswith(table_prefix.lower())
    ]
    for archive in source_dir.rglob("*"):
        if not archive.is_file() or archive.suffix.lower() != ".zip":
            continue
        if not archive.name.lower().startswith(table_prefix.lower()):
            continue
        destination = temp_dir / archive.stem
        destination.mkdir(parents=True, exist_ok=True)
        with ZipFile(archive) as zip_file:
            for member in zip_file.infolist():
                if member.is_dir():
                    continue
                target = (destination / member.filename).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise ValueError(f"Caminho inválido dentro do ZIP: {archive.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zip_file.open(member) as source, target.open("wb") as output:
                    copyfileobj(source, output)
                files.append(target)
    return sorted(files)


def import_directory(source_dir: Path, database_path: Path) -> None:
    month_pattern = re.compile(r"^\d{4}-\d{2}$")
    source_months = sorted(
        (path.name for path in source_dir.iterdir() if path.is_dir() and month_pattern.fullmatch(path.name)),
        reverse=True,
    )
    source_month = source_months[0] if source_months else None
    import_source = source_dir / source_month if source_month else source_dir
    with tempfile.TemporaryDirectory(prefix="leads-cnpj-") as temporary:
        temp_dir = Path(temporary)
        establishments = collect_table_files(import_source, "Estabelecimentos", temp_dir)
        companies = collect_table_files(import_source, "Empresas", temp_dir)
        municipalities = collect_table_files(import_source, "Municipios", temp_dir)
        cnaes = collect_table_files(import_source, "Cnaes", temp_dir)
        _import_files(establishments, companies, municipalities, cnaes, database_path, source_month)


def _import_files(
    establishments: list[Path],
    companies: list[Path],
    municipalities: list[Path],
    cnaes: list[Path],
    database_path: Path,
    source_month: str | None,
) -> None:
    if not establishments or not companies or not municipalities or not cnaes:
        raise ValueError(
            "Não encontrei arquivos de Estabelecimentos, Empresas, Municípios e CNAEs. "
            "Coloque os ZIPs mensais na pasta, mantendo os nomes oficiais."
        )

    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database_path))
    try:
        # A Receita usa bytes Windows-1252 (incluindo caracteres como aspas curvas)
        # que não são válidos em Latin-1. DuckDB fornece essa codificação via extensão.
        connection.execute("INSTALL encodings")
        connection.execute("LOAD encodings")

        municipality_queries = [
            f"SELECT * FROM {read_csv_query(path, MUNICIPALITY_COLUMNS)}"
            for path in municipalities
        ]
        connection.execute(
            "CREATE OR REPLACE TEMP TABLE municipalities AS "
            + " UNION ALL ".join(municipality_queries)
        )
        cnae_queries = [
            f"SELECT * FROM {read_csv_query(path, CNAE_COLUMNS)}" for path in cnaes
        ]
        connection.execute(
            "CREATE OR REPLACE TEMP TABLE cnaes AS " + " UNION ALL ".join(cnae_queries)
        )

        rmc_names_sql = ", ".join(sql_string(name) for name in RMC_MUNICIPALITIES)
        rmc_code_query = (
            "SELECT municipio_codigo FROM municipalities "
            "WHERE strip_accents(upper(trim(municipio))) "
            f"IN ({rmc_names_sql})"
        )
        # Read only establishments in Paraná's 29 official RMC municipalities.
        establishment_queries = [
            f"SELECT * FROM {read_csv_query(path, ESTABLISHMENT_COLUMNS)} "
            "WHERE upper(trim(uf)) = 'PR' "
            f"AND trim(municipio_codigo) IN ({rmc_code_query})"
            for path in establishments
        ]
        connection.execute(
            "CREATE OR REPLACE TEMP TABLE establishments AS "
            + " UNION ALL ".join(establishment_queries)
        )

        # Keep company rows only when they belong to an RMC establishment.
        company_queries = [
            f"SELECT * FROM {read_csv_query(path, COMPANY_COLUMNS)} "
            "WHERE trim(cnpj_base) IN "
            "(SELECT DISTINCT trim(cnpj_base) FROM establishments)"
            for path in companies
        ]
        connection.execute(
            "CREATE OR REPLACE TEMP TABLE companies AS " + " UNION ALL ".join(company_queries)
        )
        connection.execute(
            "CREATE OR REPLACE TABLE leads AS "
            "SELECT "
            "e.cnpj_base || e.cnpj_ordem || e.cnpj_dv AS cnpj, "
            "e.cnpj_base, e.cnpj_ordem, e.identificador_matriz_filial, "
            "coalesce(nullif(trim(e.nome_fantasia), ''), c.razao_social) AS nome, "
            "c.razao_social, c.porte_codigo, c.capital_social, "
            "lpad(trim(e.situacao_cadastral), 2, '0') AS situacao_cadastral, "
            "e.data_inicio_atividade, "
            "trim(e.cnae_principal) AS cnae_principal, cn.cnae_descricao, "
            "list_transform(string_split(nullif(trim(e.cnae_secundarios_raw), ''), ','), "
            "lambda cnae: trim(cnae)) "
            "AS cnae_secundarios, "
            "e.uf, e.municipio_codigo, m.municipio, e.cep, e.bairro, "
            "trim(concat_ws(' ', nullif(e.tipo_logradouro, ''), "
            "nullif(e.logradouro, ''), nullif(e.numero, ''))) AS endereco, "
            "e.complemento, e.ddd1, e.telefone1, e.ddd2, e.telefone2, e.email "
            "FROM establishments e "
            "LEFT JOIN companies c USING (cnpj_base) "
            "LEFT JOIN municipalities m USING (municipio_codigo) "
            "LEFT JOIN cnaes cn ON trim(e.cnae_principal) = trim(cn.cnae_codigo)"
        )
        connection.execute(
            "CREATE OR REPLACE TABLE import_metadata AS "
            "SELECT ? AS source_month, current_timestamp AS imported_at, "
            "'RMC' AS geographic_scope",
            [source_month],
        )
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa os CSVs CNPJ para DuckDB")
    parser.add_argument("source_dir", type=Path, help="Pasta com CSVs já extraídos")
    parser.add_argument("--database", type=Path, default=DATABASE_PATH)
    args = parser.parse_args()
    import_directory(args.source_dir, args.database)
    print(f"Importação concluída: {args.database}")


if __name__ == "__main__":
    main()
