import os
from pathlib import Path

from sqlalchemy import create_engine, text

DB_PATH = Path(__file__).resolve().parent / "fin.db"
# Production deployments point DATABASE_URL at Postgres (see DEPLOYMENT.md);
# the lab defaults to a local SQLite file.
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")
engine = create_engine(
    DATABASE_URL,
    future=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

# brief.id must self-assign on both engines: SQLite's INTEGER PRIMARY KEY aliases
# the rowid, but Postgres needs an explicit SERIAL sequence.
_BRIEF_ID = (
    "id SERIAL PRIMARY KEY" if DATABASE_URL.startswith("postgresql") else "id INTEGER PRIMARY KEY"
)

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS company(
      ticker TEXT PRIMARY KEY, name TEXT, sector TEXT, description TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS financials(
      ticker TEXT, year INT, revenue REAL, cogs REAL, opex REAL, interest REAL,
      net_income REAL, cash REAL, receivables REAL, inventory REAL,
      current_assets REAL, current_liabilities REAL, total_debt REAL,
      total_liabilities REAL, equity REAL, total_assets REAL,
      operating_cash_flow REAL, capex REAL,
      PRIMARY KEY(ticker, year)
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS brief(
      {_BRIEF_ID}, ticker TEXT, fiscal_year INT, score REAL, grade TEXT,
      verdict TEXT, flags_count INT, status TEXT, prepared_by TEXT, reviewed_by TEXT,
      narrative TEXT, key_risks TEXT, created_at TEXT, published_at TEXT
    )
    """,
]

# Synthetic demo universe: five fictional companies across five sectors,
# three fiscal years each. AVA is deliberately distressed (red-flag demo),
# NPR deliberately sits in the watch band, the rest grade B to A.
SEED_COMPANIES = """
INSERT INTO company(ticker, name, sector, description) VALUES
 ('NST','NimbusStack Technologies','Technology',
  'Cloud-native developer platform; subscription revenue with high gross margins.'),
 ('FLI','Forgeline Industrial','Industrials',
  'Precision components manufacturer serving energy and agriculture OEMs.'),
 ('NPR','NorthPeak Retail Group','Retail',
  'Mid-market outdoor-gear retail chain; 140 stores across North America.'),
 ('AVA','AeroVista Airways','Transportation',
  'Low-cost regional carrier; leveraged fleet expansion into a soft demand cycle.'),
 ('HBT','HelixBio Therapeutics','Healthcare',
  'Commercial-stage biotech; specialty therapeutics with a growing pipeline.');
"""

SEED_FINANCIALS = """
INSERT INTO financials(ticker, year, revenue, cogs, opex, interest, net_income,
                       cash, receivables, inventory, current_assets, current_liabilities,
                       total_debt, total_liabilities, equity, total_assets,
                       operating_cash_flow, capex) VALUES
 ('NST',2023,480,168,216, 8, 72,140, 80,12,260, 90, 60,140,420,560,118,24),
 ('NST',2024,585,199,252, 9,104,170, 95,14,310,105, 70,155,505,660,152,30),
 ('NST',2025,690,228,293,10,130,210,115,15,380,120, 80,160,620,780,195,36),
 ('FLI',2023,720,504,122,22, 58, 60, 75,95,210,160,280,330,390,720, 88,55),
 ('FLI',2024,765,528,130,21, 68, 65, 80,95,228,168,265,315,435,750,105,50),
 ('FLI',2025,820,559,138,20, 78, 72, 85,98,250,175,250,320,470,790,120,48),
 ('NPR',2023,950,712,178,18, 32, 40, 30,150,240,175,260,340,300,640, 45,35),
 ('NPR',2024,985,748,192,24, 15, 35, 28,148,228,190,285,335,295,630, 38,30),
 ('NPR',2025,1010,758,190,12, 40, 38, 30,150,240,200,290,345,310,655, 48,26),
 ('AVA',2023,1250,1000,230,55,-28, 55, 60,30,180,220,780,830,190,1020, 35,60),
 ('AVA',2024,1180, 980,245,62,-95, 40, 50,28,150,260,840,870,110, 980,-12,40),
 ('AVA',2025,1090, 940,210,68,-115, 25, 40,30,120,285,880,915, 25, 940,-25,30),
 ('HBT',2023,210, 63,120, 4, 19, 85, 25, 8,130, 45, 30, 60,240,300, 26,14),
 ('HBT',2024,285, 85,158, 5, 29,105, 35,10,165, 55, 40, 70,310,380, 40,18),
 ('HBT',2025,360,108,205, 5, 30,130, 45,12,210, 68, 45, 75,385,460, 55,22);
"""


def init_db() -> None:
    """Create tables and seed demo data only when empty (brief history survives restarts)."""
    with engine.begin() as con:
        for stmt in SCHEMA:
            con.exec_driver_sql(stmt)
        if con.execute(text("SELECT COUNT(*) FROM company")).scalar() == 0:
            con.exec_driver_sql(SEED_COMPANIES)
        if con.execute(text("SELECT COUNT(*) FROM financials")).scalar() == 0:
            con.exec_driver_sql(SEED_FINANCIALS)


def reset_demo_data() -> None:
    """Wipe and reseed — restores the exact lab state and clears brief history."""
    with engine.begin() as con:
        for stmt in SCHEMA:
            con.exec_driver_sql(stmt)
        con.exec_driver_sql("DELETE FROM brief")
        con.exec_driver_sql("DELETE FROM financials")
        con.exec_driver_sql("DELETE FROM company")
        con.exec_driver_sql(SEED_COMPANIES)
        con.exec_driver_sql(SEED_FINANCIALS)
