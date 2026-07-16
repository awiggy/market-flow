# -*- coding: utf-8 -*-
"""
A-share fund flow tracker. Run daily after market close (after 15:30):
    python main.py

Output:
  1. Beginner-friendly fund flow report printed to terminal
  2. Data saved to SQLite for history accumulation

Upgrade path:
  Phase A (now)  -> python main.py
  Phase B (later) -> python app.py (FastAPI web server)
"""

import sys
import io

# Fix GBK encoding on Windows terminal
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from fetch import fetch_all
from store import init_db, save_all, get_history
from analyze import (
    analyze_market_temperature,
    analyze_sector_flow,
    analyze_siphon,
    analyze_northbound,
    analyze_margin,
    analyze_etf_position,
)
from summary import generate


def run():
    print("[1/5] Init database...")
    init_db()

    print("[2/5] Fetching data (network, ~10-20s)...")
    data = fetch_all()

    print("[3/5] Saving data...")
    save_all(data)

    print("[4/5] Reading history...")
    history = get_history(days=10)
    n_days = len(history["sector"]["date"].unique())
    print(f"      {n_days} trading days in history")

    # Fallback: if today's data is empty (e.g. non-trading day / API down),
    # use most recent day from history
    sector_empty = len(data["sector_flow"]) == 0
    if sector_empty:
        print("      Today's data is empty. Falling back to most recent historical data.")
        hist_sector = history["sector"]
        if len(hist_sector) > 0:
            latest_date = hist_sector["date"].max()
            fallback = hist_sector[hist_sector["date"] == latest_date].copy()
            data["sector_flow"] = fallback
            data["date"] = latest_date
            # Also try to get northbound from history
            hist_nb = history["northbound"]
            if len(hist_nb) > 0:
                nb_latest = hist_nb[hist_nb["date"] == latest_date]
                if len(nb_latest) > 0:
                    nb_row = nb_latest.iloc[0]
                    data["northbound"] = {
                        "sh_net": nb_row.get("sh_net", 0),
                        "sz_net": nb_row.get("sz_net", 0),
                        "total_net": nb_row.get("total_net", 0),
                    }
            print(f"      Using data from {latest_date}")

    print("[5/5] Analyzing & generating report...")
    temperature = analyze_market_temperature(
        data["market_flow"], data["sector_flow"], data["northbound"]
    )
    sector_analysis = analyze_sector_flow(data["sector_flow"])
    siphon_alerts = analyze_siphon(data["sector_flow"], history)
    northbound_analysis = analyze_northbound(data["northbound"], history)
    margin_analysis = analyze_margin(data["margin_change_5d"])
    etf_position = analyze_etf_position(data["sector_flow"], siphon_alerts)

    analysis = {
        "temperature": temperature,
        "sector_flow_analysis": sector_analysis,
        "siphon_alerts": siphon_alerts,
        "northbound_analysis": northbound_analysis,
        "margin_analysis": margin_analysis,
        "etf_position": etf_position,
    }

    print()
    report = generate(data, analysis)
    print(report)

    return data, analysis


if __name__ == "__main__":
    run()
