# -*- coding: utf-8 -*-
"""
Backfill historical northbound capital & margin balance data.
Run once: python backfill.py

Sector fund flow data cannot be backfilled (AKShare only provides today's data).
It will accumulate naturally when you run main.py on trading days.
"""

import os, sys, time
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

import akshare as ak
import pandas as pd
from store import init_db, get_connection


def _retry(func, *args, max_retries=3, **kwargs):
    last_err = None
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                time.sleep(wait)
    raise last_err


def backfill_northbound(conn):
    """
    Backfill northbound daily net flow from AKShare.
    Uses stock_hsgt_hist_em which returns full history.
    Fetches Shanghai + Shenzhen separately, combines into total.
    """
    print("[backfill] Northbound capital (daily history)...")

    # Fetch Shanghai Connect
    print("  Fetching Shanghai Connect...")
    df_sh = _retry(ak.stock_hsgt_hist_em, symbol="沪股通")

    # Fetch Shenzhen Connect
    print("  Fetching Shenzhen Connect...")
    df_sz = _retry(ak.stock_hsgt_hist_em, symbol="深股通")

    count = 0
    # Process Shanghai
    for _, row in df_sh.iterrows():
        date_str = _parse_date(row["日期"])
        if date_str is None:
            continue
        sh_net = float(row.get("当日成交净买额", 0) or 0)

        _upsert_nb(conn, date_str, sh_net=sh_net)
        count += 1

    # Process Shenzhen
    for _, row in df_sz.iterrows():
        date_str = _parse_date(row["日期"])
        if date_str is None:
            continue
        sz_net = float(row.get("当日成交净买额", 0) or 0)

        _upsert_nb(conn, date_str, sz_net=sz_net)
        count += 1

    conn.commit()
    n_dates = conn.execute("SELECT COUNT(*) FROM northbound").fetchone()[0]
    print(f"  Done: {n_dates} distinct dates, covering ~{n_dates//5} trading weeks")


def _parse_date(val) -> str | None:
    """Parse various date formats to YYYY-MM-DD."""
    s = str(val).strip()
    if not s or s == "nan":
        return None
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if "-" in s:
        return s[:10]
    return None


def _upsert_nb(conn, date_str: str, sh_net: float = 0, sz_net: float = 0):
    """Insert or update northbound row."""
    existing = conn.execute(
        "SELECT sh_net, sz_net FROM northbound WHERE date=?",
        (date_str,)
    ).fetchone()

    if existing:
        old_sh = existing["sh_net"] or 0
        old_sz = existing["sz_net"] or 0
        new_sh = sh_net if sh_net != 0 else old_sh
        new_sz = sz_net if sz_net != 0 else old_sz
        conn.execute(
            "UPDATE northbound SET sh_net=?, sz_net=?, total_net=? WHERE date=?",
            (new_sh, new_sz, new_sh + new_sz, date_str)
        )
    else:
        conn.execute(
            "INSERT INTO northbound (date, sh_net, sz_net, total_net) VALUES (?, ?, ?, ?)",
            (date_str, sh_net, sz_net, sh_net + sz_net)
        )


def backfill_margin(conn):
    """
    Backfill margin trading balance from AKShare.
    Uses macro_china_market_margin_sh which returns years of daily data.
    """
    print("[backfill] Margin balance (daily history)...")

    df = _retry(ak.macro_china_market_margin_sh)
    print(f"  Got {len(df)} rows")

    count = 0
    for _, row in df.iterrows():
        date_str = _parse_date(row["日期"])
        if date_str is None:
            continue

        margin_bal = float(row.get("融资余额", 0) or 0)
        short_bal = float(row.get("融券余量金额", 0) or 0)
        total_bal = float(row.get("融资融券余额", 0) or 0)

        conn.execute(
            """INSERT OR REPLACE INTO margin
               (date, margin_balance, short_balance, total_balance)
               VALUES (?, ?, ?, ?)""",
            (date_str, margin_bal, short_bal, total_bal),
        )
        count += 1

    conn.commit()
    print(f"  Done: {count} dates")


def main():
    init_db()
    conn = get_connection()

    print("Backfilling historical data...")
    print("(Sector fund flow only available for TODAY - will accumulate going forward)")
    print()

    backfill_northbound(conn)
    backfill_margin(conn)

    # Verify
    print()
    print("=== Database status ===")
    for table, desc in [
        ("sector_flow", "Sector fund flow"),
        ("northbound", "Northbound capital"),
        ("margin", "Margin balance"),
    ]:
        count = conn.execute(
            f"SELECT COUNT(DISTINCT date) FROM {table}"
        ).fetchone()[0]
        latest_row = conn.execute(f"SELECT MAX(date) FROM {table}").fetchone()
        latest = latest_row[0] if latest_row else "N/A"
        print(f"  {desc}: {count} trading days, latest = {latest}")

    conn.close()
    print()
    print("Backfill complete!")
    print("Next steps:")
    print("  1. Run 'python main.py' every trading day after 15:30")
    print("  2. Open http://localhost:8899 to view the dashboard")
    print("  3. Charts will have trend lines from day 1 thanks to this backfill")


if __name__ == "__main__":
    main()
