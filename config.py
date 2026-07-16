"""
自动加载配置：优先读取 config.local.py（不上传 Git），
不存在时回退到 config.example.py（公开演示配置）。
"""
import os

try:
    from config_local import *  # type: ignore
except ImportError:
    from config_example import *  # type: ignore
