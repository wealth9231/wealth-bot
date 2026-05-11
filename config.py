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
LEVERAGE = 4                 # 杠杆倍数 (4倍杠杆，提高资金利用率)
MAX_POSITION = 0.001         # 最大持仓量 (BTC) (约80 USDT，提高仓位)
STOP_LOSS_PCT = -0.02        # 止损百分比 (-2%，放宽止损)
MIN_RR_RATIO = 1.2          # 最小盈亏比 (降低要求，增加交易机会)
TARGET_PROFIT_PCT = 0.02    # 目标利润 (2%，提高止盈目标)

# ==================== 网格交易配置 ====================
GRID_NUM = 20                # 网格数量 (增加网格密度)
GRID_PRICE_RANGE = 0.03     # 网格价格范围 (±3%，扩大网格范围)

# ==================== 策略参数 ====================
TREND_ADX_THRESHOLD = 20    # ADX趋势判断阈值 (降低阈值，增加趋势识别)
RSI_OVERSOLD = 30           # RSI超卖阈值 (提高门槛，减少假信号)
RSI_OVERBOUGHT = 65         # RSI超买阈值 (放宽超买条件)
BB_WIDTH_THRESHOLD = 0.03   # 布林带宽度阈值 (降低阈值，更多震荡市交易机会)

# ==================== Telegram通知配置 ====================
# 注意：GitHub Actions 使用 GitHub Secrets 中的配置，这里只是默认值
# @GateWoBuy_bot 的 Token（从 @BotFather 获取）
# 已重置 Token (2025-01)
TELEGRAM_ENABLED = os.getenv('TELEGRAM_ENABLED', 'True').lower() == 'true'
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8746796223:AAGR4wryx4Zj4TARb9yeC83KOqJQJThTzMo')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '6204659239')

# 验证：确保使用正确的 Bot
# Bot Username: @GateWoBuy_bot
# Bot Token: 8746796223:AAGR4wryx4Zj4TARb9yeC83KOqJQJThTzMo
