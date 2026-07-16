# -*- coding: utf-8 -*-
"""
Phase B: Web dashboard for fund flow report.
    python app.py
    Open http://localhost:8899 in browser.
"""

import os, sys, math, json
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from datetime import datetime, timedelta
import pandas as pd

# Ensure we can find our modules and the DB
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from store import get_connection, init_db
from analyze import (
    analyze_market_temperature,
    analyze_sector_flow,
    analyze_siphon,
    analyze_northbound,
    analyze_margin,
    analyze_etf_position,
)
from summary import format_amount, _status_icon

def _sanitize(obj):
    """Recursively replace NaN/Infinity with None (→ null in JSON)."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


class NaNJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(_sanitize(content), ensure_ascii=False,
                          default=str, separators=(",", ":")).encode("utf-8")


app = FastAPI(title="A股资金流向监控", default_response_class=NaNJSONResponse)

# ── API ──

@app.get("/api/report")
def api_report(date: str = None):
    """Return today's analysis as JSON (or specific date)."""
    conn = get_connection()

    if date is None:
        # Find latest date across all tables
        date = None
        for t in ["sector_flow", "northbound", "margin"]:
            r = conn.execute(f"SELECT MAX(date) FROM {t}").fetchone()
            if r[0] and (date is None or r[0] > date):
                date = r[0]
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

    # Fetch sector data
    sector = pd.read_sql(
        "SELECT * FROM sector_flow WHERE date = ?", conn, params=(date,)
    )
    # Fetch market flow
    mf = pd.read_sql(
        "SELECT * FROM market_flow WHERE date = ?", conn, params=(date,)
    )
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

    # Fetch northbound
    nb = pd.read_sql(
        "SELECT * FROM northbound WHERE date = ?", conn, params=(date,)
    )
    northbound = {"sh_net": 0, "sz_net": 0, "total_net": 0}
    if len(nb) > 0:
        row = nb.iloc[0]
        northbound = {
            "sh_net": float(row.get("sh_net", 0) or 0),
            "sz_net": float(row.get("sz_net", 0) or 0),
            "total_net": float(row.get("total_net", 0) or 0),
        }

    # Fetch history relative to the selected date
    history = _get_history(conn, days=10, ref_date=date)

    # Margin change over the history window
    margin_change_5d = 0
    mg = history["margin"]
    if len(mg) >= 2:
        vals = [float(r.get("total_balance", 0) or 0) for _, r in mg.iterrows()]
        vals = [v for v in vals if v > 0]
        if len(vals) >= 2:
            margin_change_5d = vals[-1] - vals[0]

    # Run analysis
    temperature = analyze_market_temperature(market_flow, sector, northbound)
    sector_analysis = analyze_sector_flow(sector)
    siphon_alerts = analyze_siphon(sector, history)
    northbound_analysis = analyze_northbound(northbound, history)
    margin_analysis = analyze_margin(margin_change_5d)
    etf_position = analyze_etf_position(sector, siphon_alerts)

    # Sector data for charts
    sectors = []
    for _, row in sector.iterrows():
        sectors.append({
            "name": row["sector"],
            "net_inflow": float(row["net_inflow"]),
            "top_stock": str(row.get("top_stock", "")),
            "rank": int(row["rank"]),
        })
    sectors.sort(key=lambda x: x["net_inflow"], reverse=True)

    def _sf(v):
        """Safe float: NaN/None → 0."""
        try:
            f = float(v or 0)
            return 0.0 if math.isnan(f) or math.isinf(f) else f
        except (TypeError, ValueError):
            return 0.0

    # Northbound history for trend chart (only rows with real data)
    nb_history = []
    for _, row in history["northbound"].iterrows():
        net = _sf(row.get("total_net", 0))
        nb_history.append({"date": str(row["date"]), "total_net": net})

    # Margin history
    margin_history = []
    for _, row in history["margin"].iterrows():
        total = _sf(row.get("total_balance", 0))
        if total > 0:
            margin_history.append({"date": str(row["date"]), "total": total})

    conn.close()

    return {
        "date": date,
        "temperature": temperature,
        "sector_analysis": {
            "hot": sector_analysis["hot"],
            "cold": sector_analysis["cold"],
        },
        "siphon_alerts": siphon_alerts,
        "northbound_analysis": northbound_analysis,
        "margin_analysis": margin_analysis,
        "etf_position": {k: v for k, v in etf_position.items()},
        "sectors": sectors,
        "nb_history": nb_history,
        "margin_history": margin_history,
        "has_sector_data": len(sector) > 0 and sector["net_inflow"].sum() != 0,
    }


@app.get("/api/dates")
def api_dates():
    """List available dates from all tables (union)."""
    conn = get_connection()
    dates = set()
    for table in ["sector_flow", "northbound", "margin"]:
        rows = conn.execute(
            f"SELECT DISTINCT date FROM {table} ORDER BY date DESC"
        ).fetchall()
        for r in rows:
            dates.add(r[0])
    conn.close()
    return {"dates": sorted(dates, reverse=True)}


def _get_history(conn, days=10, ref_date=None):
    """Read history relative to ref_date (default: today)."""
    base = f"'{ref_date}'" if ref_date else "date('now')"

    sector = pd.read_sql(
        f"SELECT * FROM sector_flow WHERE date <= {base} ORDER BY date DESC, rank LIMIT {days * 90}",
        conn
    )
    northbound = pd.read_sql(
        f"SELECT * FROM northbound WHERE date <= {base} ORDER BY date DESC LIMIT {days}",
        conn
    )
    margin = pd.read_sql(
        f"SELECT * FROM margin WHERE date <= {base} ORDER BY date DESC LIMIT {days}",
        conn
    )
    return {"sector": sector, "northbound": northbound, "margin": margin}


# ── HTML page ──

@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_PAGE


# ── Static files (if any) ──

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股资金流向日报</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
  :root {
    --bg: #0f1117;
    --card: #1a1d27;
    --border: #2a2d37;
    --text: #c9cdd4;
    --muted: #6b7080;
    --green: #22c55e;
    --red: #ef4444;
    --orange: #f59e0b;
    --blue: #3b82f6;
    --accent: #a78bfa;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    background: var(--bg); color: var(--text);
    font-family: -apple-system, "Microsoft YaHei", sans-serif;
    line-height: 1.6; padding: 20px;
  }
  h1 { font-size:1.5rem; margin-bottom:8px; }
  h2 { font-size:1rem; color:var(--muted); margin-bottom:16px; font-weight:400; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(360px,1fr)); gap:16px; margin-bottom:20px; }
  .card {
    background:var(--card); border:1px solid var(--border);
    border-radius:12px; padding:20px;
  }
  .card h3 { font-size:0.9rem; color:var(--muted); margin-bottom:12px; font-weight:500; text-transform:uppercase; letter-spacing:0.5px; }
  .temp-badge {
    display:inline-block; padding:4px 16px; border-radius:20px;
    font-size:0.85rem; font-weight:600;
  }
  .temp-hot { background:#7f1d1d; color:#fca5a5; }
  .temp-warm { background:#78350f; color:#fcd34d; }
  .temp-cool { background:#1e3a5f; color:#93c5fd; }
  .temp-cold { background:#1e293b; color:#94a3b8; }
  .flow-list { list-style:none; }
  .flow-list li {
    display:flex; justify-content:space-between; align-items:center;
    padding:6px 0; border-bottom:1px solid var(--border); font-size:0.88rem;
  }
  .flow-list li:last-child { border-bottom:none; }
  .inflow { color:var(--red); font-weight:600; }
  .outflow { color:var(--green); font-weight:600; }
  .siphon-card {
    background:rgba(239,68,68,0.08); border:1px solid rgba(239,68,68,0.2);
    border-radius:8px; padding:12px; margin-top:8px;
  }
  .siphon-card .arrow { color:var(--red); font-weight:700; }
  .etf-row {
    display:flex; align-items:center; gap:10px; padding:8px 0;
    border-bottom:1px solid var(--border); font-size:0.88rem;
  }
  .etf-row:last-child { border-bottom:none; }
  .etf-dot { width:10px; height:10px; border-radius:50%; flex-shrink:0; }
  .etf-dot.strong { background:var(--green); }
  .etf-dot.ok { background:var(--orange); }
  .etf-dot.soft { background:#f97316; }
  .etf-dot.weak { background:var(--red); }
  .etf-dot.neutral { background:var(--muted); }
  .chart-box { width:100%; height:320px; }
  .wide { grid-column:1/-1; }
  .date-nav { display:flex; gap:8px; align-items:center; margin-bottom:20px; flex-wrap:wrap; }
  .date-nav select {
    background:var(--card); color:var(--text); border:1px solid var(--border);
    padding:6px 12px; border-radius:8px; font-size:0.9rem;
  }
  .date-nav button {
    background:var(--accent); color:#fff; border:none;
    padding:6px 16px; border-radius:8px; cursor:pointer; font-size:0.9rem;
  }
  .date-nav button:hover { opacity:0.85; }
  .oneline {
    font-size:0.95rem; padding:12px 16px; background:rgba(167,139,250,0.08);
    border-left:3px solid var(--accent); border-radius:0 8px 8px 0;
  }
  .note {
    font-size:0.8rem; color:var(--muted); text-align:center;
    padding:16px;
  }
</style>
</head>
<body>

<h1>A股资金流向日报</h1>
<h2 id="subtitle">加载中...</h2>

<div class="date-nav">
  <select id="datePicker" onchange="loadDate(this.value)"></select>
  <button onclick="loadDate('latest')">最新</button>
  <span style="color:var(--muted);font-size:0.8rem;" id="autoNote"></span>
</div>

<div class="grid" id="dashboard"></div>

<div class="note">
  数据来源：AKShare | 每日收盘后自动更新 |
  <a href="https://github.com/akfamily/akshare" style="color:var(--accent)" target="_blank">AKShare</a>
</div>

<script>
let currentData = null;

async function loadDate(d) {
  let url = '/api/report';
  if (d && d !== 'latest') url += '?date=' + d;
  const resp = await fetch(url);
  currentData = await resp.json();
  render(currentData);
  document.getElementById('subtitle').textContent = currentData.date;
  if (d === 'latest') {
    document.getElementById('autoNote').textContent = '(自动最新)';
  } else {
    document.getElementById('autoNote').textContent = '';
  }
}

async function loadDates() {
  const resp = await fetch('/api/dates');
  const data = await resp.json();
  const sel = document.getElementById('datePicker');
  sel.innerHTML = '<option value="latest">最新</option>';
  for (const d of data.dates) {
    sel.innerHTML += '<option value="' + d + '">' + d + '</option>';
  }
}

function render(d) {
  const el = document.getElementById('dashboard');
  const hasSector = d.has_sector_data;
  const hasMargin = d.margin_history && d.margin_history.length > 1;
  const hasNB = d.nb_history && d.nb_history.some(x => x.total_net !== 0);
  let html = '';

  // ── Temperature ──
  html += '<div class="card"><h3>市场温度</h3>';
  if (hasSector) {
    const t = d.temperature;
    html += '<span class="temp-badge temp-' + t.temperature + '">' + t.label + '</span>';
    html += '<p style="margin-top:8px;font-size:0.88rem;color:var(--muted)">' + t.desc + '</p>';
  } else {
    html += '<span class="temp-badge temp-cold">板块数据暂缺</span>';
    html += '<p style="margin-top:8px;font-size:0.88rem;color:var(--muted)">板块资金流仅当日可查，历史数据从周一开始积累。以下为其他可用数据。</p>';
  }
  html += '</div>';

  // ── Money flow ──
  if (hasSector && d.sector_analysis.hot.length > 0) {
    html += '<div class="card"><h3>钱去哪了 (流入最多)</h3><ul class="flow-list">';
    for (const h of d.sector_analysis.hot) {
      html += '<li><span>' + h.sector + '</span><span class="inflow">+' + (h.net_inflow/1e8).toFixed(1) + '亿</span></li>';
    }
    html += '</ul></div>';
  }
  if (hasSector && d.sector_analysis.cold.length > 0) {
    html += '<div class="card"><h3>钱从哪跑了 (流出最多)</h3><ul class="flow-list">';
    for (const c of d.sector_analysis.cold) {
      html += '<li><span>' + c.sector + '</span><span class="outflow">-' + (Math.abs(c.net_inflow)/1e8).toFixed(1) + '亿</span></li>';
    }
    html += '</ul></div>';
  }

  // ── Northbound ──
  html += '<div class="card"><h3>外资 (北向资金)</h3>';
  if (hasNB) {
    html += '<p style="font-size:0.9rem">' + d.northbound_analysis.signal + '</p>';
    html += '<p style="font-size:0.8rem;color:var(--muted);margin-top:4px">连续' + d.northbound_analysis.consecutive_days + '天净' + (d.northbound_analysis.direction==="buy"?"买入":"卖出") + '</p>';
  } else {
    html += '<p style="font-size:0.9rem;color:var(--muted)">北向资金数据暂不可用（近期数据待交易日更新）</p>';
  }
  html += '</div>';

  // ── Margin ──
  html += '<div class="card"><h3>杠杆资金 (融资融券)</h3>';
  if (hasMargin) {
    const last = d.margin_history[d.margin_history.length - 1];
    const prev = d.margin_history.length > 1 ? d.margin_history[d.margin_history.length - 2] : null;
    html += '<p style="font-size:0.9rem">' + d.margin_analysis.signal + '</p>';
    if (last && last.total > 0) {
      html += '<p style="font-size:0.8rem;color:var(--muted);margin-top:4px">最新融资融券余额：' + (last.total/1e8).toFixed(0) + '亿</p>';
    }
  } else {
    html += '<p style="font-size:0.9rem;color:var(--muted)">融资融券数据暂不可用</p>';
  }
  html += '</div>';

  // ── Siphon ──
  if (hasSector) {
    const active = (d.siphon_alerts||[]).filter(s=>s.active);
    html += '<div class="card"><h3>虹吸预警</h3>';
    if (active.length > 0) {
      for (const sp of active) {
        html += '<div class="siphon-card"><span class="arrow">' + sp.sucker + ' ← 吸 ← ' + sp.bled + '</span>';
        html += '<span style="display:block;font-size:0.8rem;color:var(--muted);margin-top:4px">已持续 ' + sp.consecutive_days + ' 天，强度：' + sp.intensity + '</span></div>';
      }
    } else {
      html += '<p style="font-size:0.88rem;color:var(--muted)">未检测到明显虹吸</p>';
    }
    html += '</div>';
  }

  // ── ETF ──
  if (hasSector) {
    html += '<div class="card"><h3>你的持仓</h3>';
    for (const [code, info] of Object.entries(d.etf_position)) {
      html += '<div class="etf-row"><span class="etf-dot ' + info.status + '"></span><strong>' + code + '</strong> ' + info.name;
      html += '<span style="color:var(--muted);font-size:0.8rem;margin-left:auto">排名' + info.rank + '</span></div>';
      html += '<div style="font-size:0.82rem;color:var(--muted);padding:2px 0 8px 24px">' + info.signal + '</div>';
    }
    html += '</div>';
  }

  // ── One-liner ──
  html += '<div class="card wide oneline"><strong>一句话：</strong>' + smartOneLiner(d) + '</div>';

  // Clear old charts first
  const oldCharts = el.querySelectorAll('.chart-box');
  oldCharts.forEach(c => { try { echarts.getInstanceByDom(c)?.dispose(); } catch(e){} });

  el.innerHTML = html;

  // Charts — use timestamp to ensure unique container IDs
  const ts = Date.now();
  if (hasSector) setTimeout(() => renderSectorChart(d, ts), 100);
  if (hasMargin) setTimeout(() => renderMarginChart(d, ts), 100);
  if (hasNB && d.nb_history.filter(x=>x.total_net!==0).length >= 2) setTimeout(() => renderNBChart(d, ts), 100);
}

function smartOneLiner(d) {
  const hasSector = d.has_sector_data;
  const hasMargin = d.margin_history && d.margin_history.length > 1;
  const parts = [];

  if (hasSector) {
    const t = d.temperature.temperature;
    if (t==='hot') parts.push('市场很热，追高需谨慎');
    else if (t==='warm') parts.push('市场温和，资金有序流动');
    else if (t==='cool') parts.push('市场偏冷，资金在撤退');
    else parts.push('市场冰冷，保持冷静观察');

    const active = (d.siphon_alerts||[]).filter(s=>s.active);
    if (active.length>0) {
      const s = active[0];
      parts.push(s.sucker+'在吸'+s.bled+'的血(已'+s.consecutive_days+'天)');
    }

    for (const [code, info] of Object.entries(d.etf_position||{})) {
      if (info.status==='strong'||info.role==='sucker') parts.push(info.name+'安全');
      else if (info.status==='weak'||info.role==='bled') parts.push(info.name+'承压');
    }
  }

  if (hasMargin) {
    const vals = d.margin_history.map(x=>x.total).filter(x=>x>0);
    if (vals.length >= 3) {
      const trend = vals[vals.length-1] > vals[vals.length-4] ? '上升' : '下降';
      parts.push('近几日融资余额趋势：' + trend);
    }
  }

  if (!hasSector && !hasMargin) {
    return '暂无可用数据。等周一交易日跑 python main.py 就有了。';
  }
  if (!hasSector && hasMargin) {
    return '板块资金数据尚未积累（等周一），融资融券数据正常。' + (parts.length ? parts.join('。') + '。' : '');
  }
  return parts.join('。') + '。';
}

function renderSectorChart(d, ts) {
  const container = document.createElement('div');
  container.className = 'card wide';
  const cid = 'sectorChart_' + ts;
  container.innerHTML = '<h3>板块资金流向排名 (' + d.date + ')</h3><div id="' + cid + '" class="chart-box" style="height:500px"></div>';
  document.getElementById('dashboard').appendChild(container);

  const chart = echarts.init(document.getElementById(cid));
  const sectors = d.sectors;
  chart.setOption({
    tooltip: { trigger:'axis', axisPointer:{type:'shadow'} },
    grid: { left:'3%', right:'4%', bottom:'3%', containLabel:true },
    xAxis: { type:'value', axisLabel:{formatter:'{value}亿'} },
    yAxis: { type:'category', data:sectors.map(s=>s.name), axisLabel:{fontSize:11}, inverse:true },
    series: [{
      name:'主力净流入', type:'bar',
      data: sectors.map(s=>({value:(s.net_inflow/1e8).toFixed(1), itemStyle:{color:s.net_inflow>=0?'#ef4444':'#22c55e'}})),
    }]
  });
}

function renderMarginChart(d, ts) {
  const container = document.createElement('div');
  container.className = 'card wide';
  const cid = 'marginChart_' + ts;
  container.innerHTML = '<h3>融资融券余额趋势 (' + d.date + ' 往前10日)</h3><div id="' + cid + '" class="chart-box"></div>';
  document.getElementById('dashboard').appendChild(container);

  const chart = echarts.init(document.getElementById(cid));
  const data = d.margin_history.filter(x => x.total > 0).slice(-10);
  chart.setOption({
    tooltip: { trigger:'axis' },
    grid: { left:'3%', right:'4%', bottom:'3%', containLabel:true },
    xAxis: { type:'category', data:data.map(x=>x.date.slice(5)) },
    yAxis: { type:'value', axisLabel:{formatter: v => (v/1e8).toFixed(0) + '亿'} },
    series: [{
      name:'两融余额', type:'line',
      data: data.map(x => x.total),
      lineStyle:{color:'#a78bfa', width:2},
      itemStyle:{color:'#a78bfa'},
      symbol:'circle', symbolSize:6,
      areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,
        colorStops:[{offset:0,color:'rgba(167,139,250,0.2)'},{offset:1,color:'rgba(167,139,250,0)'}]}}
    }]
  });
}

function renderNBChart(d, ts) {
  const container = document.createElement('div');
  container.className = 'card wide';
  const cid = 'nbChart_' + ts;
  container.innerHTML = '<h3>北向资金趋势 (' + d.date + ' 往前10日)</h3><div id="' + cid + '" class="chart-box"></div>';
  document.getElementById('dashboard').appendChild(container);

  const chart = echarts.init(document.getElementById(cid));
  const data = d.nb_history.slice(-10);
  chart.setOption({
    tooltip: { trigger:'axis' },
    grid: { left:'3%', right:'4%', bottom:'3%', containLabel:true },
    xAxis: { type:'category', data:data.map(x=>x.date.slice(5)) },
    yAxis: { type:'value', axisLabel:{formatter:'{value}亿'} },
    series: [{
      name:'北向净流入', type:'bar',
      data: data.map(x=>({value:x.total_net===0?null:(x.total_net/1e8).toFixed(1),
             itemStyle:{color:(x.total_net||0)>=0?'#ef4444':'#22c55e'}})),
    }]
  });
}

// Init
loadDates();
loadDate('latest');
</script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    init_db()
    print("Dashboard ready: http://localhost:8899")
    uvicorn.run(app, host="127.0.0.1", port=8899, log_level="warning")
