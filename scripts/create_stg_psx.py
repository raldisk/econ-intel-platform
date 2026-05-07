import duckdb

# connect to your database
con = duckdb.connect("db/duckdb_local.db")

# create staging table
con.execute("""
CREATE TABLE IF NOT EXISTS stg_psx_prices (
    date DATE,
    ticker VARCHAR,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume DOUBLE
)
""")

con.close()

print("stg_psx_prices table created (or already exists)")
