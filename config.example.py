"""
示例配置。复制为 config.local.py 后填入你的真实持仓。
CI 和公开预览使用此文件。
"""
import os

# 你持有的ETF（示例用虚构数据，请替换为真实持仓）
WATCH_ETFS = {
    "000001": {"name": "消费ETF", "sector": "食品饮料"},
    "000002": {"name": "医疗ETF", "sector": "医药生物"},
}

# 计划建仓/关注的ETF（示例数据）
WATCHLIST_ETFS = {
    "000003": {"name": "科技ETF", "sector": "计算机"},
    "000004": {"name": "新能源ETF", "sector": "电力设备"},
}

# 关注的板块
WATCH_SECTORS = [
    "半导体",
    "电力",
    "白酒",
    "银行",
    "医药生物",
]

# 虹吸监控
SIPHON_PAIRS = [
    ("半导体", "银行"),
    ("电力", "煤炭"),
]

HOT_SECTOR_COUNT = 5
COLD_SECTOR_COUNT = 5
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_flow.db")
