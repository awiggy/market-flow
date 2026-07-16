# -*- coding: utf-8 -*-
"""
Beginner-friendly summary generator.
Core principle: no jargon, no raw numbers, tell a story.
"""

from datetime import datetime


def format_amount(yi: float) -> str:
    """格式化金额（亿），50亿以下省略具体数字，只给体感"""
    yi = yi / 1e8
    if abs(yi) < 10:
        return "少量"
    if abs(yi) < 30:
        return f"{abs(yi):.0f}亿"
    if abs(yi) < 100:
        return f"{abs(yi):.0f}亿"
    return f"{abs(yi):.0f}亿"


def generate(data: dict, analysis: dict) -> str:
    """生成完整摘要报告"""

    date_str = data["date"]
    market = data["market_flow"]
    sector = data["sector_flow"]
    nb = data["northbound"]

    temp = analysis["temperature"]
    sec = analysis["sector_flow_analysis"]
    siphons = analysis["siphon_alerts"]
    nb_a = analysis["northbound_analysis"]
    margin_a = analysis["margin_analysis"]
    etf_a = analysis["etf_position"]

    # Detect if we have real sector data
    has_sector_data = len(sector) > 0 and sector["net_inflow"].sum() != 0
    is_weekend = _is_weekend(date_str)

    lines = []
    lines.append("=" * 56)
    if not has_sector_data and is_weekend:
        lines.append(f"  📊 A股资金流向周报 — {date_str}（周末·休市）")
    elif not has_sector_data:
        lines.append(f"  📊 A股资金流向日报 — {date_str}（数据暂缺）")
    else:
        lines.append(f"  📊 A股资金流向日报 — {date_str}")
    lines.append("=" * 56)
    lines.append("")

    if not has_sector_data:
        lines.append("  ⚠️  今日为非交易日或板块数据暂不可用。以下为其他维度的可用数据：")
        lines.append("")

    # ── 1. 市场温度 ──
    if has_sector_data:
        lines.append(f"  🌡  市场温度：{temp['label']}")
        lines.append(f"     {temp['desc']}")
        lines.append("")

    # ── 2. 钱去哪了 / 钱从哪跑了 ──
    if has_sector_data:
        lines.append("  ── 💰 钱去哪了？ ──")
        hot = sec.get("hot", [])
        if hot:
            for i, h in enumerate(hot):
                amount = format_amount(h["net_inflow"])
                lines.append(f"     {i+1}. {h['sector']}（流入 {amount}）")
        else:
            lines.append("     今日无板块获资金净流入")

        lines.append("")
        lines.append("  ── 💸 钱从哪跑了？ ──")
        cold = sec.get("cold", [])
        if cold:
            for i, c in enumerate(cold):
                amount = format_amount(abs(c["net_inflow"]))
                lines.append(f"     {i+1}. {c['sector']}（流出 {amount}）")
        else:
            lines.append("     今日无板块资金净流出")
        lines.append("")

    # ── 3. 全市场水位 ──
    if has_sector_data:
        main_net = market.get("main_net", 0)
        mf_label = "净流入" if main_net > 0 else "净流出"
        lines.append(f"  ── 📈 全市场大资金动向 ──")
        lines.append(f"     今日主力（大机构）资金：{mf_label}")
        lines.append("")

    # ── 4. 外资 ──
    lines.append(f"  ── 🌏 外资在干嘛？ ──")
    lines.append(f"     {nb_a['signal']}")
    lines.append("")

    # ── 5. 杠杆资金 ──
    lines.append(f"  ── 🔧 借钱炒股的人 ──")
    lines.append(f"     {margin_a['signal']}")
    lines.append("")

    # ── 6. 虹吸预警 ──
    if has_sector_data:
        active_siphons = [s for s in siphons if s.get("active")]
        lines.append(f"  ── ⚠️ 虹吸预警 ──")
        if active_siphons:
            lines.append(f"     （解释：钱持续从一个板块跑到另一个板块，像吸管一样）")
            lines.append("")
            for sp in active_siphons:
                lines.append(f"     🔴 {sp['sucker']} ← 吸 ← {sp['bled']}")
                lines.append(f"        已持续 {sp['consecutive_days']} 天，强度：{sp['intensity']}")
                lines.append("")
        else:
            lines.append(f"     今日未检测到明显的板块间虹吸现象")
            lines.append("")

    # ── 7. 你的ETF ──
    if has_sector_data:
        lines.append(f"  ── 📋 你的持仓分析 ──")
        for code, info in etf_a.items():
            icon = _status_icon(info["status"])
            lines.append(f"     {icon} {code} {info['name']}")
            lines.append(f"        行业板块：{info['sector']}（排名第{info['rank']}）")
            lines.append(f"        {info['signal']}")
            lines.append("")

    # ── 8. 一句话总结 ──
    if has_sector_data:
        lines.append(f"  ── 📝 一句话总结 ──")
        lines.append(f"     {_one_liner(analysis)}")
        lines.append("")
    else:
        lines.append(f"  ── 📝 提示 ──")
        lines.append(f"     今天是周末/非交易日，板块资金数据不可用。")
        north_word = "买" if nb_a.get("direction") == "buy" else "卖"
        lines.append(f"     从已有的外资数据看，外资最近在北向通道上是净{north_word}入的。")
        lines.append(f"     下次交易日前，可先关注周末是否有重大政策或消息。")
        lines.append("")

    lines.append("=" * 56)
    lines.append("  数据来源：AKShare | 生成时间：" + datetime.now().strftime("%H:%M:%S"))
    lines.append("=" * 56)

    return "\n".join(lines)


def _is_weekend(date_str: str) -> bool:
    """Check if date is Saturday or Sunday."""
    from datetime import datetime as dt
    try:
        d = dt.strptime(date_str, "%Y-%m-%d")
        return d.weekday() >= 5
    except Exception:
        return False


def _status_icon(status: str) -> str:
    icons = {
        "strong": "🟢",
        "ok": "🟡",
        "soft": "🟠",
        "weak": "🔴",
        "neutral": "⚪",
    }
    return icons.get(status, "⚪")


def _one_liner(analysis: dict) -> str:
    """生成最后的一句话总结"""
    temp = analysis["temperature"]["temperature"]
    siphons = analysis["siphon_alerts"]
    active = [s for s in siphons if s.get("active")]
    etf = analysis["etf_position"]

    parts = []

    # 市场温度
    if temp == "hot":
        parts.append("市场很热，钱很多，但追高有风险")
    elif temp == "warm":
        parts.append("市场温和，资金有序流动")
    elif temp == "cool":
        parts.append("市场偏冷，钱在撤退")
    else:
        parts.append("市场冰冷，保持冷静观察")

    # 虹吸状态
    if active:
        strongest = active[0]
        parts.append(f"目前{strongest['sucker']}在吸{strongest['bled']}的血（已{strongest['consecutive_days']}天）")

    # ETF 状态
    etf_signals = []
    for code, info in etf.items():
        if info["status"] in ("strong", "ok") or info["role"] == "sucker":
            etf_signals.append(f"{info['name']}({code})相对安全")
        elif info["status"] in ("weak", "soft") or info["role"] == "bled":
            etf_signals.append(f"{info['name']}({code})短期承压")
    if etf_signals:
        parts.append("、".join(etf_signals))

    return "。" if not parts else "。".join(parts) + "。"
