"""Recommendation engine: score sectors on momentum, acceleration, volume, reversal.
Pure data-driven — no prediction, just "where money is flowing"."""

import sqlite3
from config import DB_PATH, WATCHLIST_ETFS

# Sector → ETF mapping (common liquid ETFs)
SECTOR_ETF_MAP = {
    "半导体": ["159516", "159995"],
    "电力": ["159611"],
    "通信设备": ["515880"],
    "消费电子": ["159997"],
    "小金属": ["512400"],
    "工业金属": ["512400"],
    "白酒": ["512690"],
    "银行": ["512800"],
    "软件开发": ["159899"],
    "IT服务": ["159899"],
    "电池": ["515030"],
    "煤炭开采加工": ["515220"],
    "证券": ["512880"],
    "光伏设备": ["515790"],
    "汽车零部件": ["515030"],
    "化学制药": ["512120"],
    "零售": ["159825"],
    "元件": ["159516"],
    "光学光电子": ["159516"],
    "电子化学品": ["159516"],
    "自动化设备": ["515080"],
    "通用设备": ["515080"],
    "专用设备": ["515080"],
    "包装印刷": ["无ETF"],
    "小家电": ["无ETF"],
    "非金属材料": ["512400"],
    "金属新材料": ["512400"],
    "能源金属": ["512400"],
    "贵金属": ["518880"],
    "军工装备": ["512660"],
    "军工电子": ["512660"],
    "电网设备": ["159611"],
    "风电设备": ["515790"],
    "其他电源设备": ["159611"],
    "汽车整车": ["515030"],
    "医疗器械": ["512170"],
    "医疗服务": ["512170"],
    "中药": ["159647"],
    "生物制品": ["512120"],
    "文化传媒": ["159805"],
    "游戏": ["159869"],
    "房地产": ["512200"],
    "建筑装饰": ["512200"],
    "建筑材料": ["512200"],
    "钢铁": ["515210"],
}


def get_recent_sectors(days=3):
    """Get sector flow data for last N trading days."""
    conn = sqlite3.connect(DB_PATH)
    dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM sector_flow ORDER BY date DESC LIMIT ?", (days + 1,)
    ).fetchall()]
    dates.sort()

    # Build per-date dict
    data = {}
    for d in dates:
        rows = conn.execute(
            "SELECT sector, net_inflow FROM sector_flow WHERE date = ?", (d,)
        ).fetchall()
        data[d] = {r[0]: r[1] / 1e8 for r in rows}

    conn.close()
    return dates, data


def score_sectors() -> dict:
    """Score all sectors and return recommendations."""
    dates, data = get_recent_sectors(days=4)

    if len(dates) < 2:
        return {"momentum": [], "reversal": [], "watch": []}

    latest = data[dates[-1]]
    prev = data[dates[-2]] if len(dates) >= 2 else {}

    momentum = []  # consecutive positive inflow + high volume
    reversal = []  # negative → positive switch
    scores = {}

    for sector, net in latest.items():
        score = 0
        signals = []

        # Signal 1: Is inflow positive?
        if net > 0:
            score += 10

        # Signal 2: Consecutive days positive
        cons = 0
        for d in reversed(dates[:-1]):  # exclude latest
            val = data.get(d, {}).get(sector, 0)
            if val > 0:
                cons += 1
            else:
                break
        if cons >= 2:
            score += 15
            signals.append(f"连续{cons}天流入")
        elif cons == 1:
            score += 5
            signals.append("连续流入")

        # Signal 3: Acceleration (today > yesterday)
        prev_net = prev.get(sector, 0)
        if prev_net > 0 and net > prev_net * 1.3:
            score += 10
            signals.append("↑加速")

        # Signal 4: Volume rank (top 10 by absolute net inflow)
        ranked = sorted(latest.items(), key=lambda x: x[1], reverse=True)
        rank = next(i for i, (s, _) in enumerate(ranked) if s == sector) + 1
        if rank <= 5:
            score += 15
            signals.append(f"流入Top{rank}")
        elif rank <= 10:
            score += 8

        # Signal 5: Reversal (was negative, now positive)
        if prev_net < 0 and net > 0:
            score += 12
            signals.append("🔄反转")
            reversal.append({
                "sector": sector,
                "net_inflow": round(net, 1),
                "prev_net": round(prev_net, 1),
                "rank": rank,
                "signals": signals,
            })

        scores[sector] = score

        if net > 0 and score >= 15:
            momentum.append({
                "sector": sector,
                "net_inflow": round(net, 1),
                "score": score,
                "rank": rank,
                "consecutive_days": cons + 1,
                "signals": signals,
                "etfs": SECTOR_ETF_MAP.get(sector, []),
            })

    momentum.sort(key=lambda x: x["score"], reverse=True)
    reversal.sort(key=lambda x: x["net_inflow"], reverse=True)

    # Watchlist status
    watch = []
    for code, info in WATCHLIST_ETFS.items():
        sec = info["sector"]
        net = latest.get(sec, 0)
        r = next(i for i, (s, _) in enumerate(
            sorted(latest.items(), key=lambda x: x[1], reverse=True)
        ) if s == sec) + 1
        watch.append({
            "code": code,
            "name": info["name"],
            "sector": sec,
            "net_inflow": round(net, 1),
            "rank": r,
            "trend": "↑" if net > 0 else "↓",
            "reason": info.get("reason", ""),
        })

    return {
        "momentum": momentum[:6],
        "reversal": reversal[:4],
        "watch": watch,
    }
