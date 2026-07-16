# -*- coding: utf-8 -*-
"""
Data fetching layer. All data from AKShare. Each function returns a DataFrame or dict.
On network errors, retries up to 3 times with exponential backoff.

Data sources:
  - Primary: 同花顺 (10jqka.com.cn) via ak.stock_fund_flow_industry
  - Fallback: 东方财富 (push2.eastmoney.com) via ak.stock_sector_fund_flow_rank
"""

import time
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
from config import WATCH_ETFS


def _retry(func, *args, max_retries=3, **kwargs):
    """Retry wrapper for flaky network calls."""
    last_err = None
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"    Retry {attempt + 1}/{max_retries} in {wait}s...")
                time.sleep(wait)
    raise last_err


def fetch_sector_fund_flow() -> pd.DataFrame:
    """
    Sector-level fund flow ranking.
    Primary: 同花顺行业资金流 (currently working).
    Fallback: 东方财富行业资金流 (push2 API frequently down).
    Returns empty DataFrame on total failure.
    """
    # ── Primary: 同花顺 ──
    try:
        df = _retry(ak.stock_fund_flow_industry)
        df = df.rename(columns={
            "行业": "sector",
            "净额": "net_inflow",
            "领涨股": "top_stock",
            "序号": "rank",
        })
        df["net_inflow"] = df["net_inflow"].astype(float) * 1e8  # 亿 → 元
        df = df[["sector", "net_inflow", "top_stock", "rank"]]
        print(f"    [同花顺] {len(df)} industries fetched")
        return df
    except Exception as e:
        print(f"    Warning: 同花顺 unavailable ({type(e).__name__}), trying 东方财富...")

    # ── Fallback: 东方财富 ──
    try:
        df = _retry(ak.stock_sector_fund_flow_rank, indicator="今日", sector_type="行业资金流")
        df = df.rename(columns={
            "名称": "sector",
            "今日主力净流入-净额": "net_inflow",
            "今日主力净流入最大股": "top_stock",
        })
        df["net_inflow"] = df["net_inflow"].astype(float)
        df = df[["sector", "net_inflow", "top_stock"]]
        df["rank"] = range(1, len(df) + 1)
        print(f"    [东方财富] {len(df)} industries fetched")
        return df
    except Exception as e:
        print(f"    Warning: Both sources unavailable ({type(e).__name__}), returning empty")
        return pd.DataFrame(columns=["sector", "net_inflow", "top_stock", "rank"])


def fetch_market_fund_flow() -> dict:
    """Overall market fund flow summary. Returns empty dict on failure."""
    try:
        df = _retry(ak.stock_market_fund_flow)
    except Exception:
        print("    Warning: eastmoney API unavailable, returning empty")
        return {}
    row = df.iloc[0] if len(df) > 0 else None
    if row is None:
        return {}
    return {
        "super_large_net": float(row.get("超大单净额", 0)),
        "large_net": float(row.get("大单净额", 0)),
        "mid_net": float(row.get("中单净额", 0)),
        "small_net": float(row.get("小单净额", 0)),
        "main_net": float(row.get("主力净额", 0)),
    }


def fetch_northbound_flow() -> dict:
    """Northbound capital (Shanghai + Shenzhen Connect).
    Uses stock_hsgt_fund_flow_summary_em which returns today's 4 rows:
      - 沪股通 northbound (index 0)
      - 沪股通 southbound (index 1)
      - 深股通 northbound (index 2)
      - 深股通 southbound (index 3)
    Column index 5 = "成交净买额" (net buy amount, in 亿元?).
    """
    try:
        df = _retry(ak.stock_hsgt_fund_flow_summary_em)
        if len(df) < 4:
            return {"sh_net": 0, "sz_net": 0, "total_net": 0}
        # Row 0: 沪股通 northbound, Row 2: 深股通 northbound
        sh_net = float(df.iloc[0, 5] or 0)  # column 5 = 成交净买额
        sz_net = float(df.iloc[2, 5] or 0)
        return {"sh_net": sh_net, "sz_net": sz_net, "total_net": sh_net + sz_net}
    except Exception:
        return {"sh_net": 0, "sz_net": 0, "total_net": 0}


def fetch_margin_balance() -> dict:
    """Latest margin trading balance."""
    try:
        df = _retry(ak.stock_margin_sse, start_date="20200101")
        latest = df.iloc[-1]
        return {
            "margin_balance": float(latest.get("融资余额", 0)),
            "short_balance": float(latest.get("融券余额", 0)),
            "total": float(latest.get("融资融券余额", 0)),
        }
    except Exception:
        return {"margin_balance": 0, "short_balance": 0, "total": 0}


def fetch_margin_change(days: int = 5) -> float:
    """Margin balance change over last N days."""
    try:
        df = _retry(ak.stock_margin_sse, start_date="20200101")
        recent = df.tail(days)
        if len(recent) >= 2:
            first = float(recent.iloc[0].get("融资余额", 0))
            last = float(recent.iloc[-1].get("融资余额", 0))
            return last - first
    except Exception:
        pass
    return 0


def fetch_etf_fund_flow(fund_code: str) -> dict:
    """ETF share change. Timeout after 45s — not critical for dashboard."""
    import threading
    result = {"fund_code": fund_code, "fund_size": 0}

    def _fetch():
        try:
            df = ak.fund_etf_fund_info_em(fund=fund_code)
            if len(df) > 0:
                latest = df.iloc[-1]
                result["fund_size"] = float(latest.get("基金份额", 0) or 0)
        except Exception:
            pass

    t = threading.Thread(target=_fetch, daemon=True)
    t.start()
    t.join(timeout=45)
    if t.is_alive():
        print(f"    ⚠ ETF {fund_code} fetch timeout, skipping")
    return result


def fetch_all(date_str: str = None) -> dict:
    """Fetch everything in one call."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    print(f"[fetch] Date: {date_str}")

    print("  Sector fund flow...")
    sector_flow = fetch_sector_fund_flow()

    print("  Market fund flow...")
    market_flow = fetch_market_fund_flow()

    print("  Northbound capital...")
    northbound = fetch_northbound_flow()

    print("  Margin balance...")
    margin = fetch_margin_balance()
    margin_change = fetch_margin_change()

    etfs = {}
    for code, info in WATCH_ETFS.items():
        print(f"  ETF {info['name']} ({code})...")
        etfs[code] = fetch_etf_fund_flow(code)

    return {
        "date": date_str,
        "sector_flow": sector_flow,
        "market_flow": market_flow,
        "northbound": northbound,
        "margin": margin,
        "margin_change_5d": margin_change,
        "etfs": etfs,
    }
