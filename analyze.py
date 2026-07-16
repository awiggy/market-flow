# -*- coding: utf-8 -*-
"""
Analysis engine. Converts raw data into meaningful signals and conclusions.
"""

import pandas as pd
from typing import Optional
from config import WATCH_ETFS, SIPHON_PAIRS, HOT_SECTOR_COUNT, COLD_SECTOR_COUNT


def analyze_market_temperature(market_flow: dict, sector_flow: pd.DataFrame,
                               northbound: dict) -> dict:
    """
    市场温度：综合三个维度
    - 主力资金是净流入还是净流出
    - 净流入的板块有多少个
    - 外资是买是卖
    返回: hot / warm / cool / cold
    """
    score = 0

    # 维度1: 主力资金
    main_net = market_flow.get("main_net", 0)
    if main_net > 100:
        score += 2
    elif main_net > 0:
        score += 1
    elif main_net < -200:
        score -= 2
    elif main_net < 0:
        score -= 1

    # 维度2: 板块流入比例
    if len(sector_flow) > 0:
        positive_ratio = (sector_flow["net_inflow"] > 0).sum() / len(sector_flow)
        if positive_ratio > 0.6:
            score += 2
        elif positive_ratio > 0.4:
            score += 1
        elif positive_ratio < 0.2:
            score -= 2
        elif positive_ratio < 0.35:
            score -= 1

    # 维度3: 北向资金
    nb_net = northbound.get("total_net", 0)
    if nb_net > 50:
        score += 2
    elif nb_net > 0:
        score += 1
    elif nb_net < -50:
        score -= 2
    elif nb_net < 0:
        score -= 1

    if score >= 4:
        temp = "hot"
        label = "火热 🔥"
        desc = "资金大量涌入，市场情绪高涨，追高需谨慎"
    elif score >= 1:
        temp = "warm"
        label = "温和 ☀️"
        desc = "市场平稳偏暖，资金温和流入"
    elif score >= -2:
        temp = "cool"
        label = "偏冷 🌤"
        desc = "资金整体在流出，市场观望情绪浓"
    else:
        temp = "cold"
        label = "冰冷 ❄️"
        desc = "资金大幅出逃，恐慌情绪蔓延，冷静观察"

    return {"temperature": temp, "label": label, "desc": desc, "score": score}


def analyze_sector_flow(sector_flow: pd.DataFrame) -> dict:
    """板块资金流向分析"""
    if len(sector_flow) == 0:
        return {"hot": [], "cold": [], "note": "今日无数据"}

    sorted_df = sector_flow.sort_values("net_inflow", ascending=False)

    hot = []
    for _, row in sorted_df.head(HOT_SECTOR_COUNT).iterrows():
        hot.append({
            "sector": row["sector"],
            "net_inflow": row["net_inflow"],
            "top_stock": row.get("top_stock", ""),
        })

    cold = []
    for _, row in sorted_df.tail(COLD_SECTOR_COUNT).iterrows():
        cold.append({
            "sector": row["sector"],
            "net_inflow": row["net_inflow"],
            "top_stock": row.get("top_stock", ""),
        })

    return {
        "hot": hot,
        "cold": cold,
    }


def analyze_siphon(sector_flow: pd.DataFrame, history: dict) -> list:
    """
    虹吸检测：判断钱是否持续从某些板块流向另一些板块。
    所谓"虹吸" = 吸金方连续多日净流入且排名靠前，失血方连续多日净流出。
    """
    siphon_alerts = []
    if len(sector_flow) == 0:
        return siphon_alerts

    today_hot = set(s["sector"] for s in analyze_sector_flow(sector_flow)["hot"])
    today_cold = set(s["sector"] for s in analyze_sector_flow(sector_flow)["cold"])

    for sucker, bled in SIPHON_PAIRS:
        sucker_hot = sucker in today_hot
        bled_cold = bled in today_cold

        # 今日状态
        sucker_row = sector_flow[sector_flow["sector"] == sucker]
        bled_row = sector_flow[sector_flow["sector"] == bled]
        sucker_inflow = sucker_row["net_inflow"].values[0] if len(sucker_row) > 0 else 0
        bled_inflow = bled_row["net_inflow"].values[0] if len(bled_row) > 0 else 0

        # 检查历史连续天数
        consecutive_days = _count_consecutive_siphon(history, sucker, bled)

        if sucker_inflow > 0 and bled_inflow < 0:
            intensity = "强" if consecutive_days >= 5 else ("中" if consecutive_days >= 3 else "弱")
            siphon_alerts.append({
                "sucker": sucker,
                "bled": bled,
                "sucker_inflow": sucker_inflow,
                "bled_inflow": bled_inflow,
                "consecutive_days": consecutive_days,
                "intensity": intensity,
                "active": True,
            })

    return siphon_alerts


def _count_consecutive_siphon(history: dict, sucker: str, bled: str) -> int:
    """计算虹吸已持续多少天"""
    hist = history.get("sector", pd.DataFrame())
    if len(hist) == 0:
        return 0

    dates = sorted(hist["date"].unique(), reverse=True)
    count = 0
    for d in dates:
        day_data = hist[hist["date"] == d]
        suck = day_data[day_data["sector"] == sucker]
        bleed = day_data[day_data["sector"] == bled]
        suck_v = suck["net_inflow"].values[0] if len(suck) > 0 else 0
        bleed_v = bleed["net_inflow"].values[0] if len(bleed) > 0 else 0
        if suck_v > 0 and bleed_v < 0:
            count += 1
        else:
            break
    return count


def analyze_northbound(northbound: dict, history: dict) -> dict:
    """北向资金分析"""
    nb_net = northbound.get("total_net", 0)
    hist = history.get("northbound", pd.DataFrame())

    # 连续买卖天数
    if len(hist) >= 1:
        recent = hist.sort_values("date", ascending=False)
        consecutive = 0
        direction = "buy" if nb_net >= 0 else "sell"
        for _, row in recent.iterrows():
            day_net = row.get("total_net", 0)
            if day_net is None or (isinstance(day_net, float) and (day_net != day_net)):
                continue  # skip None/NaN rows
            day_net = float(day_net)
            if (direction == "buy" and day_net > 0) or (direction == "sell" and day_net < 0):
                consecutive += 1
            else:
                break
    else:
        consecutive = 1
        direction = "buy" if nb_net >= 0 else "sell"

    # 描述
    if direction == "buy":
        if consecutive >= 5:
            signal = "外资连续买入，态度积极，看好后市"
        elif consecutive >= 2:
            signal = "外资在买入，态度偏积极"
        else:
            signal = "外资今天小幅买入"
    else:
        if consecutive >= 5:
            signal = "外资连续卖出，态度偏谨慎，注意风险"
        elif consecutive >= 2:
            signal = "外资在卖出，态度偏谨慎"
        else:
            signal = "外资今天小幅卖出"

    return {
        "net_flow": nb_net,
        "direction": direction,
        "consecutive_days": consecutive,
        "signal": signal,
    }


def analyze_margin(margin_change_5d: float) -> dict:
    """融资融券分析"""
    if margin_change_5d > 0:
        trend = "increasing"
        signal = "借钱炒股的人在增加，杠杆情绪偏乐观"
    elif margin_change_5d < 0:
        trend = "decreasing"
        signal = "借钱炒股的人在减少，杠杆资金在撤退"
    else:
        trend = "flat"
        signal = "杠杆资金没有明显变动"

    return {
        "change_5d": margin_change_5d,
        "trend": trend,
        "signal": signal,
    }


def analyze_etf_position(sector_flow: pd.DataFrame, siphon_alerts: list) -> dict:
    """结合用户持仓ETF，判断各ETF是受益方还是受害方"""
    results = {}
    for code, info in WATCH_ETFS.items():
        sector_name = info["sector"]
        sector_row = sector_flow[sector_flow["sector"] == sector_name]
        net_flow = sector_row["net_inflow"].values[0] if len(sector_row) > 0 else 0
        rank = sector_row["rank"].values[0] if len(sector_row) > 0 else 0

        # 判断是否在虹吸的哪一边
        role = "neutral"
        for alert in siphon_alerts:
            if alert["sucker"] == sector_name:
                role = "sucker"  # 是吸金方，利好
            elif alert["bled"] == sector_name:
                role = "bled"    # 是被吸方，利空

        if net_flow > 0 and rank <= 5:
            status = "strong"   # 资金在进，排名靠前
        elif net_flow > 0:
            status = "ok"
        elif net_flow < 0 and rank >= len(sector_flow) - 5:
            status = "weak"     # 资金在跑，排名垫底
        elif net_flow < 0:
            status = "soft"
        else:
            status = "neutral"

        results[code] = {
            "name": info["name"],
            "sector": sector_name,
            "net_flow": net_flow,
            "rank": rank,
            "status": status,
            "role": role,
            "signal": _etf_signal(status, role, net_flow),
        }
    return results


def _etf_signal(status: str, role: str, net_flow: float) -> str:
    """生成ETF的个性化一句话信号"""
    if status == "strong":
        return "资金正在涌入你所在的板块，当前比较安全"
    elif status == "ok":
        return "所在板块有少量资金流入，问题不大"
    elif role == "bled":
        if net_flow < -50:
            return "你的板块正在被虹吸失血，短期承压较重"
        return "你的板块被虹吸影响，短期可能会被冷落"
    elif status == "weak":
        return "所在板块失血较多，排在市场末尾，短期谨慎"
    elif status == "soft":
        return "所在板块有资金流出迹象，但不算严重"
    elif role == "sucker":
        return "你的板块是市场当前的吸金池，受益于虹吸效应"
    return "所在板块资金面中性，没有明显方向"
