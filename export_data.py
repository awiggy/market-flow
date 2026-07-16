"""Export latest analysis to dashboard_data.json for preview HTML."""
import json, math, os
import pandas as pd
from datetime import datetime
from store import get_connection
from analyze import (
    analyze_market_temperature, analyze_sector_flow, analyze_siphon,
    analyze_northbound, analyze_margin, analyze_etf_position,
)
from config import WATCH_SECTORS

def _sanitize(obj):
    if isinstance(obj, dict): return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list): return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)): return 0
    if hasattr(obj, 'item'): return obj.item()
    return obj

conn = get_connection()

# Find latest date with sector data
date = None
for t in ["sector_flow", "northbound", "margin"]:
    r = conn.execute(f"SELECT MAX(date) FROM {t}").fetchone()
    if r[0] and (date is None or r[0] > date):
        date = r[0]
if date is None:
    date = datetime.now().strftime("%Y-%m-%d")

sector = pd.read_sql("SELECT * FROM sector_flow WHERE date = ?", conn, params=(date,))
mf = pd.read_sql("SELECT * FROM market_flow WHERE date = ?", conn, params=(date,))
nb = pd.read_sql("SELECT * FROM northbound WHERE date = ?", conn, params=(date,))

market_flow = {}
if len(mf) > 0:
    row = mf.iloc[0]
    market_flow = {
        "super_large_net": float(row.get("super_large_net", 0)),
        "large_net": float(row.get("large_net", 0)),
        "mid_net": float(row.get("mid_net", 0)),
        "small_net": float(row.get("small_net", 0)),
        "main_net": float(row.get("main_net", 0)),
    }

northbound = {"sh_net": 0, "sz_net": 0, "total_net": 0}
if len(nb) > 0:
    row = nb.iloc[0]
    northbound = {
        "sh_net": float(row.get("sh_net", 0) or 0),
        "sz_net": float(row.get("sz_net", 0) or 0),
        "total_net": float(row.get("total_net", 0) or 0),
    }

nb_hist = pd.read_sql(f"SELECT * FROM northbound WHERE date <= '{date}' ORDER BY date DESC LIMIT 10", conn)
mg_hist = pd.read_sql(f"SELECT * FROM margin WHERE date <= '{date}' ORDER BY date DESC LIMIT 10", conn)
sector_hist = pd.read_sql(f"SELECT * FROM sector_flow WHERE date <= '{date}' ORDER BY date DESC, rank LIMIT 900", conn)
history = {"sector": sector_hist, "northbound": nb_hist, "margin": mg_hist}

margin_change_5d = 0
mg = history["margin"]
if len(mg) >= 2:
    vals = [float(r.get("total_balance", 0) or 0) for _, r in mg.iterrows()]
    vals = [v for v in vals if v > 0]
    if len(vals) >= 2:
        margin_change_5d = vals[-1] - vals[0]

temperature = analyze_market_temperature(market_flow, sector, northbound)
sa = analyze_sector_flow(sector)
siphon = analyze_siphon(sector, history)
nba = analyze_northbound(northbound, history)
ma = analyze_margin(margin_change_5d)
etf = analyze_etf_position(sector, siphon)

sectors = [{
    "name": row["sector"],
    "net_inflow": float(row["net_inflow"]),
    "top_stock": str(row.get("top_stock", "")),
    "rank": int(row["rank"]),
} for _, row in sector.iterrows()]
sectors.sort(key=lambda x: x["net_inflow"], reverse=True)

watch_data = [s for s in sectors if s["name"] in WATCH_SECTORS]

nb_hd = [{"date": str(r["date"]), "total_net": float(r.get("total_net", 0) or 0)} for _, r in history["northbound"].iterrows()]
mg_hd = [{"date": str(r["date"]), "total": float(r.get("total_balance", 0) or 0)} for _, r in history["margin"].iterrows() if float(r.get("total_balance", 0) or 0) > 0]

data = {
    "date": date,
    "temperature": temperature,
    "hot": sa["hot"],
    "cold": sa["cold"],
    "siphon": siphon,
    "northbound": nba,
    "margin": ma,
    "etf": {k: {"name": v["name"], "sector": v["sector"], "net_flow": v["net_flow"], "rank": v["rank"], "status": v["status"], "role": v["role"], "signal": v["signal"]} for k, v in etf.items()},
    "sectors": sectors,
    "watch_sectors": watch_data,
    "nb_history": nb_hd,
    "margin_history": mg_hd,
}

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "dashboard_data.json"), "w", encoding="utf-8") as f:
    json.dump(_sanitize(data), f, ensure_ascii=False, indent=2)

conn.close()
print(f"Exported {date} data to dashboard_data.json")
