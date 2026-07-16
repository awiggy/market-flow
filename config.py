"""
配置加载：
  正常模式：读取 config.local.py（本地真实持仓），不存在则报错
  演示模式：设置环境变量 MARKET_FLOW_PROFILE=demo 后读取 config.example.py
"""
import os
import sys

_profile = os.environ.get("MARKET_FLOW_PROFILE", "").strip()

if _profile == "demo":
    try:
        from config_example import *  # type: ignore
    except ImportError:
        print("错误：config.example.py 不存在")
        sys.exit(1)
else:
    try:
        from config_local import *  # type: ignore
    except ImportError:
        print(
            "错误：未找到 config.local.py。\n"
            "请复制 config.example.py 为 config.local.py 并填入你的真实持仓。\n"
            "或设置环境变量 MARKET_FLOW_PROFILE=demo 使用演示配置。"
        )
        sys.exit(1)
