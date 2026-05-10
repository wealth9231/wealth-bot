#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置文件 - 从环境变量读取（适合GitHub Actions部署）
本地运行时会使用默认值
"""

import os

# ==================== API密钥配置 ====================
GATEIO_API_KEY = os.getenv('GATEIO_API_KEY', 'bf76ef165158c1ac42512d4849326b41')
GATEIO_API_SECRET = os.getenv('GATEIO_API_SECRET', 'a7e5e275ff75d88120af845921b176281c52901053a7ad6787a1c7db188d6e12')

# ==================== 交易配置 ====================
SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "DOGE/USDT"]  # 交易对列表
TIMEFRAME = "15m"            # K线周期
LEVERAGE = 1                 # 杠杆倍数 (首次测试用1倍，现货交易)
MAX_POSITION = 0.0005        # 最大持仓量 (BTC) (约40 USDT，极小仓位测试)
STOP_LOSS_PCT = -0.015       # 止损百分比 (-1.5%，更严格的保护)
MIN_RR_RATIO = 1.5          # 最小盈亏比
TARGET_PROFIT_PCT = 0.02    # 目标利润 (2%，更容易达到)

# ==================== 网格交易配置 ====================
GRID_NUM = 10                # 网格数量
GRID_PRICE_RANGE = 0.02     # 网格价格范围 (±2%)

# ==================== 策略参数 ====================
TREND_ADX_THRESHOLD = 25    # ADX趋势判断阈值
RSI_OVERSOLD = 30           # RSI超卖阈值
RSI_OVERBOUGHT = 70         # RSI超买阈值
BB_WIDTH_THRESHOLD = 0.05   # 布林带宽度阈值 (判断震荡/趋势)

# ==================== Telegram通知配置 ====================
# 注意：GitHub Actions 使用 GitHub Secrets 中的配置，这里只是默认值
# @GateWoBuy_bot 的 Token（从 @BotFather 获取）
TELEGRAM_ENABLED = os.getenv('TELEGRAM_ENABLED', 'True').lower() == 'true'
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8746796223:AAGBQQJUu2tMSpnUereWPOo4t3lp_o-ejg')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '6204659239')

# 验证：确保使用正确的 Bot
# Bot Username: @GateWoBuy_bot
# Bot Token: 8746796223:AAGBQQJUu2tMSpnUereWPOo4t3lp_o-ejg
