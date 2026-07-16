"""Export ALL historical dates to dashboard_data.json for date picker support."""
import json, math, os
import pandas as pd
from datetime import datetime
from store import get_connection
from analyze import *
from config import WATCH_SECTORS

def build_date_data(date, conn):
    sector = pd.read_sql("SELECT * FROM sector_flow WHERE date = ?", conn, params=(date,))
    if len(sector) == 0: return None
    mf = pd.read_sql("SELECT * FROM market_flow WHERE date = ?", conn, params=(date,))
    nb = pd.read_sql("SELECT * FROM northbound WHERE date = ?", conn, params=(date,))
    market_flow = {}
    if len(mf) > 0:
        row = mf.iloc[0]
        market_flow = {"main_net": float(row.get("main_net", 0))}
    northbound = {"sh_net": 0, "sz_net": 0, "total_net": 0}
    if len(nb) > 0:
        row = nb.iloc[0]
        northbound = {"sh_net": float(row.get("sh_net",0)or 0), "sz_net": float(row.get("sz_net",0)or 0), "total_net": float(row.get("total_net",0)or 0)}
    nb_hist = pd.read_sql(f"SELECT * FROM northbound WHERE date <= '{date}' ORDER BY date DESC LIMIT 10", conn)
    mg_hist = pd.read_sql(f"SELECT * FROM margin WHERE date <= '{date}' ORDER BY date DESC LIMIT 10", conn)
    sector_hist = pd.read_sql(f"SELECT * FROM sector_flow WHERE date <= '{date}' ORDER BY date DESC LIMIT 900", conn)
    history = {"sector": sector_hist, "northbound": nb_hist, "margin": mg_hist}
    margin_change_5d = 0
    mg = history["margin"]
    if len(mg) >= 2:
        vals = [float(r.get("total_balance",0)or 0) for _, r in mg.iterrows()]
        vals = [v for v in vals if v > 0]
        if len(vals) >= 2: margin_change_5d = vals[-1] - vals[0]
    temperature = analyze_market_temperature(market_flow, sector, northbound)
    sa = analyze_sector_flow(sector)
    siphon = analyze_siphon(sector, history)
    nba = analyze_northbound(northbound, history)
    ma = analyze_margin(margin_change_5d)
    etf = analyze_etf_position(sector, siphon)
    sectors = [{"name": row["sector"], "net_inflow": float(row["net_inflow"]), "top_stock": str(row.get("top_stock","")), "rank": int(row["rank"])} for _, row in sector.iterrows()]
    sectors.sort(key=lambda x: x["net_inflow"], reverse=True)
    watch_data = [s for s in sectors if s["name"] in WATCH_SECTORS]
    nb_hd = [{"date": str(r["date"]), "total_net": float(r.get("total_net",0)or 0)} for _, r in history["northbound"].iterrows()]
    mg_hd = [{"date": str(r["date"]), "total": float(r.get("total_balance",0)or 0)} for _, r in history["margin"].iterrows() if float(r.get("total_balance",0)or 0) > 0]
    return {"temperature": temperature, "hot": sa["hot"], "cold": sa["cold"], "siphon": siphon, "northbound": nba, "margin": ma, "etf": {k: {"name": v["name"], "sector": v["sector"], "net_flow": v["net_flow"], "rank": v["rank"], "status": v["status"], "role": v["role"], "signal": v["signal"]} for k, v in etf.items()}, "sectors": sectors, "watch_sectors": watch_data, "nb_history": nb_hd, "margin_history": mg_hd}

conn = get_connection()
dates = [r[0] for r in conn.execute("SELECT DISTINCT date FROM sector_flow ORDER BY date").fetchall()]
all_data = {}
for date in dates:
    d = build_date_data(date, conn)
    if d: all_data[date] = d
conn.close()

# Filter out dates with no meaningful sector data (non-trading days)
valid_dates = [d for d in all_data if all_data[d]["sectors"] and sum(s["net_inflow"] for s in all_data[d]["sectors"]) != 0]
all_data = {d: all_data[d] for d in valid_dates}

latest = all_data.get(valid_dates[-1], {}) if valid_dates else {}
latest["date"] = valid_dates[-1] if valid_dates else datetime.now().strftime("%Y-%m-%d")
latest["date_list"] = sorted(all_data.keys(), reverse=True)

HERE = os.path.dirname(os.path.abspath(__file__))
# Save main data
with open(os.path.join(HERE, "dashboard_data.json"), "w", encoding="utf-8") as f:
    json.dump(latest, f, ensure_ascii=False, default=str)
# Inject all_dates
with open(os.path.join(HERE, "dashboard_data.json"), "r", encoding="utf-8") as f:
    content = f.read()
all_json = json.dumps(all_data, ensure_ascii=False, default=str)
pos = content.rfind("}")
new_content = content[:pos] + ',"all_dates":' + all_json + "}"
with open(os.path.join(HERE, "dashboard_data.json"), "w", encoding="utf-8") as f:
    f.write(new_content)
print(f"Exported {len(all_data)} dates: {latest['date_list']}")
