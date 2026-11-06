from pathlib import Path
import os


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("LEADS_DATA_DIR", ROOT / "data"))
DATABASE_PATH = Path(os.getenv("LEADS_DATABASE_PATH", DATA_DIR / "leads_rmc.duckdb"))
DEFAULT_CITY = "CURITIBA"
DEFAULT_STATE = "PR"
DEFAULT_CNAE = "4711302"  # 4711-3/02 — supermercados
CURITIBA_RFB_MUNICIPALITY_CODE = "7535"
