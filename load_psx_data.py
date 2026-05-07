import duckdb
import pandas as pd
import yfinance as yf

# connect to DB
con = duckdb.connect("db/duckdb_local.db")

# fetch data (6 months for speed)
df = yf.download("JFC.PS", period="6mo", progress=False)

if df.empty:
    raise Exception("No data fetched from Yahoo Finance")

# transform
df = df.reset_index()
df["ticker"] = "JFC"

df = df.rename(columns={
    "Date": "date",
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume"
})

df = df[["date", "ticker", "open", "high", "low", "close", "volume"]]

# clear old data
con.execute("DELETE FROM stg_psx_prices")

# insert new data
con.register("df_view", df)

con.execute("""
INSERT INTO stg_psx_prices
SELECT * FROM df_view
""")

con.close()

print(f"Loaded {len(df)} rows into stg_psx_prices")
