"""Baixa os ZIPs necessários da pasta pública mensal da Receita Federal."""

import argparse
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from .config import DATA_DIR

DAV_NAMESPACE = {"d": "DAV:"}
MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")
TABLE_PREFIXES = ("Cnaes", "Municipios", "Empresas", "Estabelecimentos")
DEFAULT_SHARE_URL = "https://arquivos.receitafederal.gov.br/index.php/s/YggdBLfdninEJX9"


def share_parts(share_url: str) -> tuple[str, str]:
    parsed = urlparse(share_url.strip())
    match = re.search(r"/s/([^/?#]+)", parsed.path)
    if not parsed.scheme or not parsed.netloc or not match:
        raise ValueError("Compartilhamento inválido. Esperava uma URL pública no formato https://host/index.php/s/token.")
    return f"{parsed.scheme}://{parsed.netloc}/public.php/dav/files/{match.group(1)}/", match.group(1)


def list_directory(session: requests.Session, url: str, token: str) -> list[dict]:
    response = session.request(
        "PROPFIND", url, headers={"Depth": "1"}, auth=(token, ""), timeout=(20, 120)
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)
    entries = []
    for node in root.findall("d:response", DAV_NAMESPACE):
        href = node.findtext("d:href", default="", namespaces=DAV_NAMESPACE)
        prop = None
        for propstat in node.findall("d:propstat", DAV_NAMESPACE):
            if "200" in propstat.findtext("d:status", default="", namespaces=DAV_NAMESPACE):
                prop = propstat.find("d:prop", DAV_NAMESPACE)
                break
        if not href or prop is None:
            continue
        name = unquote(href.rstrip("/").rsplit("/", 1)[-1])
        collection = prop.find("d:resourcetype/d:collection", DAV_NAMESPACE) is not None
        entries.append({"name": name, "collection": collection})
    return entries


def find_cnpj_root(session: requests.Session, root_url: str, token: str) -> str:
    candidates = (
        root_url,
        f"{root_url}Dados/Cadastros/CNPJ/",
    )
    for candidate in candidates:
        try:
            entries = list_directory(session, candidate, token)
        except requests.RequestException:
            continue
        if any(
            entry["collection"] and MONTH_PATTERN.fullmatch(entry["name"])
            for entry in entries
        ):
            return candidate
    raise RuntimeError(
        "Não encontrei as pastas mensais da base CNPJ no compartilhamento da Receita."
    )


def choose_month(session: requests.Session, root_url: str, token: str) -> tuple[str, list[str], str]:
    cnpj_root = find_cnpj_root(session, root_url, token)
    months = sorted(
        (entry["name"] for entry in list_directory(session, cnpj_root, token)
         if entry["collection"] and MONTH_PATTERN.fullmatch(entry["name"])),
        reverse=True,
    )
    for month in months:
        files = [
            entry["name"] for entry in list_directory(session, f"{cnpj_root}{month}/", token)
            if not entry["collection"] and entry["name"].lower().endswith(".zip")
        ]
        needed = [name for name in files if name.startswith(TABLE_PREFIXES)]
        if any(name.startswith("Cnaes") for name in needed) and any(
            name.startswith("Municipios") for name in needed
        ) and any(name.startswith("Empresas") for name in needed) and any(
            name.startswith("Estabelecimentos") for name in needed
        ):
            return month, sorted(needed), cnpj_root
    raise RuntimeError("Não encontrei uma competência com os arquivos necessários do CNPJ.")


def download_file(session: requests.Session, url: str, token: str, destination: Path) -> None:
    partial = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(1, 5):
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "leads-backend/0.1", "Range": f"bytes={offset}-"} if offset else {
            "User-Agent": "leads-backend/0.1"
        }
        try:
            with session.get(
                url, headers=headers, auth=(token, ""), stream=True, timeout=(20, 300)
            ) as response:
                response.raise_for_status()
                append = offset > 0 and response.status_code == 206
                if offset and not append:
                    partial.unlink(missing_ok=True)
                mode = "ab" if append else "wb"
                with partial.open(mode) as output:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            output.write(chunk)
            partial.replace(destination)
            return
        except requests.RequestException:
            if attempt == 4:
                raise
            time.sleep(attempt * 3)


def download_latest(share_url: str, destination: Path) -> str:
    root_url, token = share_parts(share_url)
    destination.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        print("Conectando ao compartilhamento da Receita e procurando a competência...", flush=True)
        month, files, cnpj_root = choose_month(session, root_url, token)
        print(f"Competência {month} encontrada: {len(files)} arquivos para baixar.", flush=True)
        month_dir = destination / month
        month_dir.mkdir(parents=True, exist_ok=True)
        for filename in files:
            target = month_dir / filename
            if target.exists() and target.stat().st_size > 0:
                continue
            url = f"{cnpj_root}{month}/{filename}"
            print(f"Baixando {filename}...")
            download_file(session, url, token, target)
            print(f"Concluído: {filename}")
    return month


def main() -> None:
    parser = argparse.ArgumentParser(description="Baixa os dados abertos do CNPJ da Receita Federal")
    parser.add_argument(
        "--share-url", default=os.getenv("RF_SHARE_URL", DEFAULT_SHARE_URL)
    )
    parser.add_argument("--destination", type=Path, default=DATA_DIR / "source")
    args = parser.parse_args()
    month = download_latest(args.share_url, args.destination)
    print(f"Arquivos da competência {month} salvos em {args.destination / month}")


if __name__ == "__main__":
    main()
