"""
COA pipeline entry point.

Orchestrates: extract → transform → load

Data source: COA Annual Audit Reports (PDF).
Manual download required from: https://www.coa.gov.ph/index.php/reports/annual-audit-reports

To activate with real data:
  1. pip install pdfplumber
  2. Download PDFs, place in a directory
  3. Set cfg.COA_PDF_DIR = Path("path/to/coa/pdfs")
  4. Run: python -m pipelines.coa.run

Without PDFs: extract() generates synthetic data covering FY2019–FY2023
for 15 major national agencies. Disbursement rates anchored to published
COA statistics.

E2E smoke (synthetic fallback):

  Row count + agency coverage:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    r = con.execute(
        'SELECT COUNT(*), COUNT(DISTINCT agency_code), '
        'MIN(fiscal_year), MAX(fiscal_year) FROM coa_budget_utilization'
    ).fetchone()
    print(f'rows={r[0]}, agencies={r[1]}, years={r[2]}–{r[3]}')
    con.close()
    "
    → expect: 75 rows (15 agencies × 5 years), years 2019–2023

  Low utilizer check:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    rows = con.execute(
        'SELECT fiscal_year, agency_code, disbursement_rate, zscore_disbursement '
        'FROM coa_low_utilizers ORDER BY fiscal_year DESC, zscore_disbursement LIMIT 10'
    ).fetchall()
    for r in rows: print(r)
    con.close()
    "
    → expect: agencies with disbursement_rate below threshold, negative z-scores

  pipeline_runs check:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    r = con.execute(
        'SELECT status, rows_affected, run_at FROM pipeline_runs '
        'WHERE pipeline = chr(99)||chr(111)||chr(97) '
        'ORDER BY run_at DESC LIMIT 1'
    ).fetchone()
    print(r)
    con.close()
    "
    → expect: ('success', 75, timestamp)
"""

from __future__ import annotations

import logging
import sys

from pipelines.coa.extract   import extract
from pipelines.coa.transform import transform
from pipelines.coa.load      import load

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run() -> None:
    logger.info("COA pipeline starting: extract → transform → load")
    try:
        extract()
        transform()
        load()
        logger.info("COA pipeline complete.")
    except Exception as exc:
        logger.error("COA pipeline failed: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    run()
