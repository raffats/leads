# Backend de leads CNPJ

Protótipo backend para consultar estabelecimentos por cidade, UF e CNAE. O piloto começa em Curitiba/PR e supermercados (CNAE `4711302`), mas esses valores são filtros configuráveis da API.

O projeto aceita Python 3.12 a 3.15. No Windows, use uma versão que tenha wheels disponíveis para as dependências.

## Escopo atual

- API FastAPI para consulta paginada de leads já importados.
- DuckDB local como armazenamento de desenvolvimento.
- Importador dos CSVs oficiais da Receita Federal, após extração dos ZIPs.
- Nenhum frontend de produto; a documentação interativa da API fica em `/docs`.

## Preparar o ambiente

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

## Baixar e importar dados

O downloader já vem com o link público do CNPJ da Receita e tenta localizar a pasta mensal automaticamente. Para usar o link padrão, rode:

```powershell
python downloader.py
```

Ele encontra a competência mensal mais recente com os arquivos necessários e baixa apenas CNAEs, municípios, empresas e estabelecimentos. Se a Receita trocar o link público, você pode informar outro com `RF_SHARE_URL`. Para importar os ZIPs:

```powershell
leads-import .\data\source
```

O banco filtrado será criado em `data/leads_rmc.duckdb`. A importação lê os arquivos nacionais, mas grava no DuckDB apenas os estabelecimentos e empresas dos 29 municípios oficiais da Região Metropolitana de Curitiba; os ZIPs originais ficam em `data/source` para permitir reprocessamento. O banco salvo contém a tabela final `leads` e os metadados da carga, sem as tabelas nacionais intermediárias.

## Iniciar a API

```powershell
uvicorn leads_backend.api:app --reload
```

- `GET /health`
- `GET /api/v1/leads?city=CURITIBA&state=PR&cnae=4711302`
- `GET /api/v1/leads?city=CURITIBA&state=PR&cnae=4711302&include_secondary_cnae=true`

Parâmetros: `city`, `state`, `cnae`, `include_secondary_cnae`, `active_only`, `page` e `page_size` (máximo 500). A API retorna estabelecimentos; redes com várias filiais podem aparecer em mais de uma linha, cada uma com seu próprio CNPJ.

## Publicar na Vercel

O `index.py` exporta a aplicação FastAPI e `vercel.json` inclui o banco filtrado no pacote da função. No projeto da Vercel, conecte o repositório `elem-ecossistema/dados_leads`, habilite Git LFS nas configurações Git e publique a branch `main`. Depois, valide `/health` e `/docs` no domínio gerado. Atualizações do banco exigem uma nova versão no Git LFS e uma nova implantação.

## Fonte e convenções

- Fonte: [Dados Abertos do CNPJ da Receita Federal](https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/dados-abertos/cadastros).
- Layout: [metadados oficiais do CNPJ](https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf).
- O código municipal no arquivo do CNPJ é o código da Receita (Curitiba: `7535`), não o código IBGE. A importação junta a tabela oficial de municípios para expor o nome na consulta.
- O importador preserva CNPJ e CNAEs como texto para manter zeros à esquerda e suportar os formatos alfanuméricos.

## Limitações do protótipo

O primeiro import substitui as tabelas importadas pela competência fornecida. A atualização incremental entre competências e a exposição de informações de origem/data de referência na resposta serão adicionadas numa próxima etapa.
