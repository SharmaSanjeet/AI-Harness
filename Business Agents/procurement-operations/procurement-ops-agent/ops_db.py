from pathlib import Path

from sqlalchemy import create_engine, text

DB_PATH = Path(__file__).resolve().parent / "ops.db"
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    future=True,
    connect_args={"check_same_thread": False},
)

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS inventory(
      sku TEXT PRIMARY KEY, name TEXT, on_hand INT, on_order INT,
      lead_time_days INT, daily_demand REAL, safety_stock INT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vendors(
      id INTEGER PRIMARY KEY, name TEXT, sku TEXT, price_usd REAL, moq INT, lead_time_days INT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pr(
      id INTEGER PRIMARY KEY, sku TEXT, qty INT, vendor TEXT, price_usd REAL,
      status TEXT, requested_by TEXT, approved_by TEXT, created_at TEXT
    )
    """,
]

SEED_INVENTORY = """
INSERT INTO inventory(sku, name, on_hand, on_order, lead_time_days, daily_demand, safety_stock) VALUES
 ('LC-100','LangChain Pro', 18, 10, 7, 2.5, 8),
 ('LI-200','LlamaIndex Suite', 6, 0, 10, 1.8, 7),
 ('HY-300','Haystack Enterprise', 30, 0, 5, 1.0, 5);
"""

SEED_VENDORS = """
INSERT INTO vendors(name, sku, price_usd, moq, lead_time_days) VALUES
 ('Alpha Supplies','LC-100',45.0,10,7),
 ('Bravo Tech','LC-100',43.5,12,9),
 ('DataWorks','LI-200',55.0,10,12),
 ('SearchCorp','HY-300',75.0,5,6);
"""


def init_db() -> None:
    """Create tables and seed demo data only when empty (PR history survives restarts)."""
    with engine.begin() as con:
        for stmt in SCHEMA:
            con.exec_driver_sql(stmt)
        if con.execute(text("SELECT COUNT(*) FROM inventory")).scalar() == 0:
            con.exec_driver_sql(SEED_INVENTORY)
        if con.execute(text("SELECT COUNT(*) FROM vendors")).scalar() == 0:
            con.exec_driver_sql(SEED_VENDORS)


def reset_demo_data() -> None:
    """Wipe and reseed — restores the exact lab state and clears PR history."""
    with engine.begin() as con:
        for stmt in SCHEMA:
            con.exec_driver_sql(stmt)
        con.exec_driver_sql("DELETE FROM pr")
        con.exec_driver_sql("DELETE FROM vendors")
        con.exec_driver_sql("DELETE FROM inventory")
        con.exec_driver_sql(SEED_INVENTORY)
        con.exec_driver_sql(SEED_VENDORS)
