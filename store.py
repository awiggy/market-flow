# -*- coding: utf-8 -*-
"""
SQLite storage layer. One table per data type, incremental append by date.
"""

import sqlite3
import pandas as pd
from datetime import datetime
from config import DB_PATH


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """建表。只在首次运行时执行。"""
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS sector_flow (
            date TEXT NOT NULL,
            sector TEXT NOT NULL,
            net_inflow REAL,
            top_stock TEXT,
            rank INTEGER,
            PRIMARY KEY (date, sector)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS market_flow (
            date TEXT PRIMARY KEY,
            super_large_net REAL,
            large_net REAL,
            mid_net REAL,
            small_net REAL,
            main_net REAL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS northbound (
            date TEXT PRIMARY KEY,
            sh_net REAL,
            sz_net REAL,
            total_net REAL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS margin (
            date TEXT PRIMARY KEY,
            margin_balance REAL,
            short_balance REAL,
            total_balance REAL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS etf_flow (
            date TEXT NOT NULL,
            fund_code TEXT NOT NULL,
            fund_size REAL,
            PRIMARY KEY (date, fund_code)
        )
    """)

    conn.commit()
    conn.close()
    print("[store] Database initialized")


def save_all(data: dict):
    """将抓取结果写入各表"""
    conn = get_connection()
    date_str = data["date"]

    # 行业板块资金流
    df_sector = data["sector_flow"]
    for _, row in df_sector.iterrows():
        conn.execute("""
            INSERT OR REPLACE INTO sector_flow (date, sector, net_inflow, top_stock, rank)
            VALUES (?, ?, ?, ?, ?)
        """, (date_str, row["sector"], row["net_inflow"], row.get("top_stock", ""), row["rank"]))

    # 全市场资金流
    mf = data["market_flow"]
    if mf:
        conn.execute("""
            INSERT OR REPLACE INTO market_flow (date, super_large_net, large_net, mid_net, small_net, main_net)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (date_str, mf.get("super_large_net", 0), mf.get("large_net", 0),
              mf.get("mid_net", 0), mf.get("small_net", 0), mf.get("main_net", 0)))

    # 北向资金
    nb = data["northbound"]
    conn.execute("""
        INSERT OR REPLACE INTO northbound (date, sh_net, sz_net, total_net)
        VALUES (?, ?, ?, ?)
    """, (date_str, nb.get("sh_net", 0), nb.get("sz_net", 0), nb.get("total_net", 0)))

    # 融资融券
    mg = data["margin"]
    conn.execute("""
        INSERT OR REPLACE INTO margin (date, margin_balance, short_balance, total_balance)
        VALUES (?, ?, ?, ?)
    """, (date_str, mg.get("margin_balance", 0), mg.get("short_balance", 0), mg.get("total", 0)))

    # ETF
    for code, info in data["etfs"].items():
        conn.execute("""
            INSERT OR REPLACE INTO etf_flow (date, fund_code, fund_size)
            VALUES (?, ?, ?)
        """, (date_str, code, info.get("fund_size", 0)))

    conn.commit()
    conn.close()
    print(f"[store] {date_str} saved")


def get_history(days: int = 10) -> dict:
    """读取最近N天的数据，用于分析趋势"""
    conn = get_connection()

    sector = pd.read_sql(
        f"SELECT * FROM sector_flow WHERE date >= date('now', '-{days} days') ORDER BY date, rank",
        conn
    )
    market = pd.read_sql(
        f"SELECT * FROM market_flow WHERE date >= date('now', '-{days} days') ORDER BY date",
        conn
    )
    northbound = pd.read_sql(
        f"SELECT * FROM northbound WHERE date >= date('now', '-{days} days') ORDER BY date",
        conn
    )
    margin = pd.read_sql(
        f"SELECT * FROM margin WHERE date >= date('now', '-{days} days') ORDER BY date",
        conn
    )
    etf = pd.read_sql(
        f"SELECT * FROM etf_flow WHERE date >= date('now', '-{days} days') ORDER BY date",
        conn
    )

    conn.close()
    return {
        "sector": sector,
        "market": market,
        "northbound": northbound,
        "margin": margin,
        "etf": etf,
    }
