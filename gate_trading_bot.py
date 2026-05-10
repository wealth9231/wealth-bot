#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gate.io 全自动量化交易机器人
功能：市场状态识别 + 趋势/网格混合策略 + 风控管理
交易所：Gate.io (通过CCXT库)
交易对：BTC/USDT (可扩展至ETH/SOL/BNB/DOGE)
杠杆：4倍 (现货/杠杆)
"""

import ccxt
import pandas as pd
import numpy as np
from flask import Flask, jsonify
import threading
import time
import logging
from datetime import datetime
from typing import Dict, Tuple, Optional

# ==================== 配置部分 ====================
import os

# 从config.py读取配置（优先使用环境变量）
try:
    from config import *
except ImportError:
    # 如果config.py不存在，使用默认值
    GATEIO_API_KEY = os.getenv('GATEIO_API_KEY', "bf76ef165158c1ac42512d4849326b41")
    GATEIO_API_SECRET = os.getenv('GATEIO_API_SECRET', "a7e5e275ff75d88120af845921b176281c52901053a7ad6787a1c7db188d6e12")
    SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "DOGE/USDT"]
    TIMEFRAME = "15m"
    LEVERAGE = 1
    MAX_POSITION = 0.0005
    STOP_LOSS_PCT = -0.015
    MIN_RR_RATIO = 1.5
    TARGET_PROFIT_PCT = 0.02
    GRID_NUM = 10
    GRID_PRICE_RANGE = 0.02
    TREND_ADX_THRESHOLD = 25
    RSI_OVERSOLD = 30
    RSI_OVERBOUGHT = 70
    BB_WIDTH_THRESHOLD = 0.05
    TELEGRAM_ENABLED = os.getenv('TELEGRAM_ENABLED', 'True').lower() == 'true'
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', "8746796223:AAGBQQJUu2tMSpnUereWPOo4t3lp_o-ejg")  # @GateWoBuy_bot
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', "6204659239")  # 请确保此 Chat ID 正确

# ==================== 日志配置 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== 交易所初始化 ====================
class ExchangeAPI:
    """交易所API封装类"""
    def __init__(self, api_key: str, secret: str):
        """
        初始化Gate.io交易所连接
        
        Args:
            api_key: Gate.io API Key
            secret: Gate.io Secret Key
        """
        self.exchange = ccxt.gateio({
            'apiKey': api_key,
            'secret': secret,
            'enableRateLimit': True,  # 启用请求频率限制
            'options': {
                'defaultType': 'spot',  # 现货交易
                'leverage': LEVERAGE,  # 设置杠杆
                'createMarketBuyOrderRequiresPrice': False,  # Gate.io 市价买单不需要价格参数
            }
        })
        logger.info("交易所API初始化成功")
    
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        """
        获取K线数据
        
        Args:
            symbol: 交易对
            timeframe: 时间周期
            limit: 获取数量
            
        Returns:
            DataFrame包含OHLCV数据
        """
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"获取K线数据失败: {e}")
            return pd.DataFrame()
    
    def get_balance(self) -> Dict:
        """
        获取账户余额
        
        Returns:
            账户余额字典
        """
        try:
            balance = self.exchange.fetch_balance()
            return balance
        except Exception as e:
            logger.error(f"获取余额失败: {e}")
            return {}
    
    def create_order(self, symbol: str, side: str, amount: float, 
                     order_type: str = 'market', price: Optional[float] = None) -> Dict:
        """
        创建订单
        
        Args:
            symbol: 交易对
            side: 买卖方向 ('buy' or 'sell')
            amount: 数量
            order_type: 订单类型 ('market' or 'limit')
            price: 价格 (限价单使用)
            
        Returns:
            订单信息字典
        """
        try:
            # CCXT正确用法: create_order(symbol, type, side, amount, price, params)
            order = self.exchange.create_order(symbol, order_type, side, amount, price)
            logger.info(f"订单创建成功: {side} {amount} {symbol} @ {price if price else 'market'}")
            return order
        except Exception as e:
            logger.error(f"创建订单失败: {e}")
            return {}
    
    def get_position(self, symbol: str) -> Dict:
        """
        获取持仓信息
        
        Args:
            symbol: 交易对
            
        Returns:
            持仓信息字典
        """
        try:
            # 获取当前持仓 (现货持仓在balance中)
            balance = self.get_balance()
            base_currency = symbol.split('/')[0]  # 基础货币 (如BTC)
            quote_currency = symbol.split('/')[1]  # 计价货币 (如USDT)
            
            position = {
                'base_amount': balance[base_currency]['free'] if base_currency in balance else 0,
                'quote_amount': balance[quote_currency]['free'] if quote_currency in balance else 0,
                'timestamp': datetime.now().isoformat()
            }
            return position
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return {}

# ==================== 技术指标计算 ====================
class TechnicalIndicators:
    """技术指标计算类"""
    
    @staticmethod
    def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        计算ADX (平均趋向指数)
        
        Args:
            df: 包含OHLC的DataFrame
            period: ADX周期
            
        Returns:
            ADX值序列
        """
        try:
            # 计算+DI和-DI
            high = df['high']
            low = df['low']
            close = df['close']
            
            tr1 = high - low
            tr2 = abs(high - close.shift(1))
            tr3 = abs(low - close.shift(1))
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            
            up_move = high - high.shift(1)
            down_move = low.shift(1) - low
            
            pos_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
            neg_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
            
            tr_smooth = tr.rolling(window=period).mean()
            pos_di = 100 * pd.Series(pos_dm).rolling(window=period).mean() / tr_smooth
            neg_di = 100 * pd.Series(neg_dm).rolling(window=period).mean() / tr_smooth
            
            dx = 100 * abs(pos_di - neg_di) / (pos_di + neg_di)
            adx = dx.rolling(window=period).mean()
            
            return adx
        except Exception as e:
            logger.error(f"计算ADX失败: {e}")
            return pd.Series()
    
    @staticmethod
    def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        计算RSI (相对强弱指数)
        
        Args:
            df: 包含close的DataFrame
            period: RSI周期
            
        Returns:
            RSI值序列
        """
        try:
            close = df['close']
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            return rsi
        except Exception as e:
            logger.error(f"计算RSI失败: {e}")
            return pd.Series()
    
    @staticmethod
    def calculate_ema(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """
        计算EMA (指数移动平均线)
        
        Args:
            df: 包含close的DataFrame
            period: EMA周期
            
        Returns:
            EMA值序列
        """
        try:
            return df['close'].ewm(span=period, adjust=False).mean()
        except Exception as e:
            logger.error(f"计算EMA失败: {e}")
            return pd.Series()
    
    @staticmethod
    def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, 
                                  std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        计算布林带
        
        Args:
            df: 包含close的DataFrame
            period: 周期
            std_dev: 标准差倍数
            
        Returns:
            (上轨, 中轨, 下轨) 元组
        """
        try:
            close = df['close']
            sma = close.rolling(window=period).mean()
            std = close.rolling(window=period).std()
            
            upper_band = sma + (std * std_dev)
            lower_band = sma - (std * std_dev)
            
            return upper_band, sma, lower_band
        except Exception as e:
            logger.error(f"计算布林带失败: {e}")
            return pd.Series(), pd.Series(), pd.Series()
    
    @staticmethod
    def calculate_bb_width(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """
        计算布林带宽度 (用于判断市场波动状态)
        
        Args:
            df: 包含close的DataFrame
            period: 周期
            
        Returns:
            布林带宽度序列
        """
        try:
            upper, middle, lower = TechnicalIndicators.calculate_bollinger_bands(df, period)
            width = (upper - lower) / middle
            return width
        except Exception as e:
            logger.error(f"计算布林带宽度失败: {e}")
            return pd.Series()

# ==================== 市场状态识别 ====================
class MarketRegimeDetector:
    """市场状态识别器"""
    
    @staticmethod
    def detect_market_regime(df: pd.DataFrame) -> Tuple[str, Dict]:
        """
        识别当前市场状态
        
        根据ADX、均线、布林带宽度和RSI，判断市场是：
        - '趋势向上': 趋势向上
        - '趋势向下': 趋势向下
        - '震荡市': 震荡市
        - '高波动': 高波动
        - '超卖反弹': 超卖反弹
        
        Args:
            df: 包含OHLCV的DataFrame
            
        Returns:
            (市场状态, 指标详情) 元组
        """
        try:
            # 计算技术指标
            adx = TechnicalIndicators.calculate_adx(df).iloc[-1]
            rsi = TechnicalIndicators.calculate_rsi(df).iloc[-1]
            ema20 = TechnicalIndicators.calculate_ema(df, 20).iloc[-1]
            ema50 = TechnicalIndicators.calculate_ema(df, 50).iloc[-1]
            bb_width = TechnicalIndicators.calculate_bb_width(df).iloc[-1]
            current_price = df['close'].iloc[-1]
            
            # 指标详情
            indicators = {
                'adx': round(adx, 2),
                'rsi': round(rsi, 2),
                'ema20': round(ema20, 2),
                'ema50': round(ema50, 2),
                'bb_width': round(bb_width, 4),
                'current_price': round(current_price, 2)
            }
            
            # 判断市场状态
            # 1. 判断趋势强度 (ADX > 25 为强趋势)
            is_trending = adx > TREND_ADX_THRESHOLD
            
            # 2. 判断趋势方向
            if is_trending:
                if ema20 > ema50 and current_price > ema20:
                    regime = '趋势向上'
                elif ema20 < ema50 and current_price < ema20:
                    regime = '趋势向下'
                else:
                    regime = '震荡市'
            else:
                # 3. 震荡市判断 (ADX低 + 布林带窄)
                if bb_width < BB_WIDTH_THRESHOLD:
                    regime = '震荡市'
                else:
                    regime = '高波动'
            
            # 4. 超卖反弹判断 (RSI < 30 且不在强下跌趋势中)
            if rsi < RSI_OVERSOLD and regime != '趋势向下':
                regime = '超卖反弹'
            
            logger.info(f"市场状态: {regime}, 指标: {indicators}")
            return regime, indicators
            
        except Exception as e:
            logger.error(f"市场状态识别失败: {e}")
            return 'unknown', {}
        
# ==================== Telegram通知模块 ====================
class TelegramNotifier:
    """Telegram通知类"""
    
    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True):
        """
        初始化Telegram通知器
        
        Args:
            bot_token: Telegram Bot Token
            chat_id: 接收通知的Chat ID
            enabled: 是否启用通知
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled
        self.api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    def send_message(self, message: str) -> bool:
        """
        发送消息到Telegram
        
        Args:
            message: 要发送的消息内容
            
        Returns:
            是否发送成功
        """
        if not self.enabled:
            return False
        
        try:
            import requests
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }
            response = requests.post(self.api_url, json=payload, timeout=10)
            
            if response.status_code == 200:
                logger.info("Telegram通知发送成功")
                return True
            else:
                logger.error(f"Telegram通知发送失败: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"发送Telegram通知失败: {e}")
            return False
    
    def notify_trade_signal(self, symbol: str, signal: str, price: float, regime: str) -> bool:
        """
        通知交易信号
        
        Args:
            symbol: 交易对
            signal: 交易信号 (buy/sell/hold)
            price: 当前价格
            regime: 市场状态
            
        Returns:
            是否发送成功
        """
        emoji = "🟢" if signal == 'buy' else "🔴" if signal == 'sell' else "🟡"
        message = (
            f"{emoji} <b>交易信号</b>\n"
            f"交易对: {symbol}\n"
            f"信号: {signal.upper()}\n"
            f"价格: {price:.2f} USDT\n"
            f"市场状态: {regime}\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return self.send_message(message)
    
    def notify_stop_loss(self, symbol: str, entry_price: float, current_price: float, loss_pct: float) -> bool:
        """
        通知止损触发
        
        Args:
            symbol: 交易对
            entry_price: 入场价格
            current_price: 当前价格
            loss_pct: 亏损百分比
            
        Returns:
            是否发送成功
        """
        message = (
            f"🔴 <b>止损触发</b>\n"
            f"交易对: {symbol}\n"
            f"入场价: {entry_price:.2f}\n"
            f"当前价: {current_price:.2f}\n"
            f"亏损: {loss_pct*100:.2f}%\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return self.send_message(message)
    
    def notify_error(self, error_msg: str) -> bool:
        """
        通知错误
        
        Args:
            error_msg: 错误信息
            
        Returns:
            是否发送成功
        """
        message = (
            f"⚠️ <b>系统错误</b>\n"
            f"{error_msg}\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return self.send_message(message)
    
    def notify_market_regime(self, symbol: str, regime: str, indicators: Dict,
                              current_position: float = None, 
                              entry_price: float = None, current_price: float = None) -> bool:
        """
        通知市场状态变化和持仓状态（合并为一条消息）
        
        Args:
            symbol: 交易对
            regime: 市场状态
            indicators: 技术指标字典
            current_position: 当前持仓数量
            entry_price: 入场价格
            current_price: 当前价格
            
        Returns:
            是否发送成功
        """
        # 持仓状态信息
        position_status = "已开仓 ✅" if current_position else "未开仓 ⭕"
        profit_info = ""
        if current_position and entry_price and current_price:
            profit_pct = (current_price - entry_price) / entry_price * 100
            profit_emoji = "📈" if profit_pct >= 0 else "📉"
            profit_info = f"{profit_emoji} 盈亏: {profit_pct:+.2f}% ({'盈利' if profit_pct >= 0 else '亏损'})\n"
        
        # 合并为一条消息
        message = (
            f"📊 <b>市场状态更新</b>\n"
            f"交易对: {symbol}\n"
            f"市场状态: {regime}\n"
            f"持仓状态: {position_status}\n"
            f"持仓数量: {current_position or 0:.6f} {symbol.split('/')[0]}\n"
            f"入场价格: {entry_price or 'N/A'}\n"
            f"当前价格: {current_price or 'N/A'}\n"
            f"{profit_info}"
            f"ADX: {indicators.get('adx', 'N/A')}\n"
            f"RSI: {indicators.get('rsi', 'N/A')}\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return self.send_message(message)
        
# ==================== 策略模块 ====================
class TradingStrategy:
    """交易策略类（支持多交易对和Telegram通知）"""
    
    def __init__(self, exchange_api: ExchangeAPI, symbol: str, notifier: TelegramNotifier = None):
        """
        初始化策略
        
        Args:
            exchange_api: 交易所API对象
            symbol: 交易对（每个交易对一个策略实例）
            notifier: Telegram通知器对象
        """
        self.api = exchange_api
        self.symbol = symbol  # 关联交易对
        self.notifier = notifier  # Telegram通知器
        self.current_position = None
        self.entry_price = None
        self.grid_orders = []  # 网格订单列表
        self.last_regime = None  # 上次市场状态（用于检测变化）
        
    def trend_following_strategy(self, regime: str, current_price: float) -> str:
        """
        趋势跟踪策略
        
        Args:
            regime: 市场状态
            current_price: 当前价格
            
        Returns:
            操作信号 ('buy', 'sell', or 'hold')
        """
        if regime == '趋势向上' and self.current_position is None:
            return 'buy'
        elif regime == '趋势向下' and self.current_position is not None:
            return 'sell'
        else:
            return 'hold'
    
    def grid_trading_strategy(self, current_price: float, df: pd.DataFrame) -> str:
        """
        网格交易策略 (震荡市使用)
        
        Args:
            current_price: 当前价格
            df: K线数据
            
        Returns:
            操作信号 ('buy', 'sell', or 'hold')
        """
        try:
            # 计算网格价格区间
            upper, middle, lower = TechnicalIndicators.calculate_bollinger_bands(df)
            grid_spacing = (upper.iloc[-1] - lower.iloc[-1]) / GRID_NUM
            
            # 判断当前价格在哪个网格位置
            grid_level = (current_price - lower.iloc[-1]) / grid_spacing
            
            # 低价区买入，高价区卖出
            if grid_level < GRID_NUM * 0.3 and self.current_position is None:
                return 'buy'
            elif grid_level > GRID_NUM * 0.7 and self.current_position is not None:
                return 'sell'
            else:
                return 'hold'
        except Exception as e:
            logger.error(f"网格策略计算失败: {e}")
            return 'hold'
    
    def oversold_rebound_strategy(self, regime: str, rsi: float) -> str:
        """
        超卖反弹策略 (小仓位逆向建仓)
        
        Args:
            regime: 市场状态
            rsi: RSI值
            
        Returns:
            操作信号 ('buy_small', 'sell', or 'hold')
        """
        if regime == '超卖反弹' and rsi < RSI_OVERSOLD:
            if self.current_position is None:
                return 'buy_small'  # 小仓位买入
            elif rsi > RSI_OVERBOUGHT:
                return 'sell'  # RSI超买时卖出
        return 'hold'
    
    def execute_signal(self, signal: str, current_price: float):
        """
        执行交易信号
        
        Args:
            signal: 交易信号
            current_price: 当前价格
        """
        try:
            if signal == 'buy':
                # 正常买入 (使用50%可用资金)
                balance = self.api.get_balance()
                usdt_balance = balance['USDT']['free'] if 'USDT' in balance else 0
                # 多交易对时，平均分配资金
                available_usdt = usdt_balance / len(SYMBOLS) if 'SYMBOLS' in globals() else usdt_balance
                amount = (available_usdt * 0.5) / current_price
                
                # 检查最大持仓限制
                if amount > MAX_POSITION:
                    amount = MAX_POSITION
                
                if amount > 0:
                    order = self.api.create_order(self.symbol, 'buy', amount, 'market')
                    if order:
                        self.current_position = amount
                        self.entry_price = current_price
                        logger.info(f"买入成功: {amount} {self.symbol} @ {current_price}")
                        
                        # 发送Telegram通知
                        if self.notifier:
                            # 获取当前市场状态
                            try:
                                df_regime = self.api.fetch_ohlcv(self.symbol, TIMEFRAME, limit=100)
                                regime = MarketRegimeDetector.detect_market_regime(df_regime)[0]
                            except:
                                regime = 'unknown'
                            self.notifier.notify_trade_signal(self.symbol, signal, current_price, regime)
            
            elif signal == 'buy_small':
                # 小仓位买入 (使用20%可用资金，用于超卖反弹)
                balance = self.api.get_balance()
                usdt_balance = balance['USDT']['free'] if 'USDT' in balance else 0
                available_usdt = usdt_balance / len(SYMBOLS) if 'SYMBOLS' in globals() else usdt_balance
                amount = (available_usdt * 0.2) / current_price
                
                if amount > MAX_POSITION * 0.5:
                    amount = MAX_POSITION * 0.5
                
                if amount > 0:
                    order = self.api.create_order(self.symbol, 'buy', amount, 'market')
                    if order:
                        self.current_position = amount
                        self.entry_price = current_price
                        logger.info(f"小仓位买入: {amount} {self.symbol} @ {current_price}")
                        
                        # 发送Telegram通知
                        if self.notifier:
                            self.notifier.notify_trade_signal(self.symbol, signal, current_price, '超卖反弹')
            
            elif signal == 'sell':
                # 卖出全部持仓
                if self.current_position and self.current_position > 0:
                    order = self.api.create_order(self.symbol, 'sell', self.current_position, 'market')
                    if order:
                        profit_pct = (current_price - self.entry_price) / self.entry_price * 100
                        logger.info(f"卖出成功: {self.current_position} {self.symbol} @ {current_price}, 利润: {profit_pct:.2f}%")
                        
                        # 发送Telegram通知
                        if self.notifier:
                            self.notifier.notify_trade_signal(self.symbol, signal, current_price, 'unknown')
                        
                        self.current_position = None
                        self.entry_price = None
                        
        except Exception as e:
            logger.error(f"执行交易信号失败: {e}")
            # 发送错误通知
            if self.notifier:
                self.notifier.notify_error(f"执行交易信号失败: {e}")
    
    def check_stop_loss(self, current_price: float) -> bool:
        """
        检查止损条件
        
        Args:
            current_price: 当前价格
            
        Returns:
            是否触发止损
        """
        if self.entry_price is None or self.current_position is None:
            return False
        
        loss_pct = (current_price - self.entry_price) / self.entry_price
        
        if loss_pct <= STOP_LOSS_PCT:
            logger.warning(f"触发止损: 入场价={self.entry_price}, 当前价={current_price}, 亏损={loss_pct*100:.2f}%")
            
            # 发送Telegram通知
            if self.notifier:
                self.notifier.notify_stop_loss(self.symbol, self.entry_price, current_price, loss_pct)
            
            self.execute_signal('sell', current_price)
            return True
        
        return False
    
    def run_strategy(self, df: pd.DataFrame) -> Dict:
        """
        运行主策略逻辑
        
        Args:
            df: K线数据
            
        Returns:
            策略执行结果字典
        """
        try:
            # 1. 识别市场状态
            regime, indicators = MarketRegimeDetector.detect_market_regime(df)
            current_price = df['close'].iloc[-1]
            
            # 检测市场状态变化，发送Telegram通知（合并为一条消息）
            if self.notifier and self.last_regime != regime:
                self.notifier.notify_market_regime(
                    self.symbol, 
                    regime, 
                    indicators,
                    self.current_position, 
                    self.entry_price, 
                    current_price
                )
                self.last_regime = regime
            
            # 2. 检查止损
            if self.check_stop_loss(current_price):
                return {'regime': regime, 'signal': 'stop_loss', 'indicators': indicators}
            
            # 3. 根据市场状态选择策略
            signal = 'hold'
            
            if regime in ['趋势向上', '趋势向下']:
                # 趋势跟踪策略
                signal = self.trend_following_strategy(regime, current_price)
            
            elif regime == '震荡市':
                # 网格交易策略
                signal = self.grid_trading_strategy(current_price, df)
            
            elif regime == '超卖反弹':
                # 超卖反弹策略
                signal = self.oversold_rebound_strategy(regime, indicators['rsi'])
            
            elif regime == '高波动':
                # 高波动市场，暂时观望
                signal = 'hold'
                logger.info("高波动市场，暂时观望")
            
            # 4. 执行交易信号
            if signal != 'hold':
                self.execute_signal(signal, current_price)
            
            return {
                'regime': regime,
                'signal': signal,
                'indicators': indicators,
                'position': self.current_position,
                'entry_price': self.entry_price
            }
            
        except Exception as e:
            logger.error(f"策略执行失败: {e}")
            # 发送错误通知
            if self.notifier:
                self.notifier.notify_error(f"策略执行失败: {e}")
            return {}

# ==================== 健康检查服务 ====================
# 注意：在GitHub Actions中不需要Flask服务，禁用以避免挂起
# 如需本地运行或Docker部署，可以启用下面的代码
ENABLE_FLASK = os.getenv('ENABLE_FLASK', 'False').lower() == 'true'

if ENABLE_FLASK:
    app = Flask(__name__)
    
    @app.route('/health', methods=['GET'])
    def health_check():
        """
        健康检查接口（支持多交易对）
        
        Returns:
            JSON包含status、各交易对的状态和持仓信息
        """
        # 构建每个交易对的状态
        symbols_status = {}
        for symbol in global_regimes:
            symbols_status[symbol] = {
                'regime': global_regimes.get(symbol, 'unknown'),
                'position': global_positions.get(symbol)
            }
        
        return jsonify({
            'status': 'running',
            'symbols': symbols_status,
            'timestamp': datetime.now().isoformat()
        })
        
    def run_flask_app():
        """运行Flask应用 (健康检查服务)"""
        app.run(host='0.0.0.0', port=8080, debug=False)
else:
    # 禁用Flask时，提供空函数
    def run_flask_app():
        pass

# ==================== 主程序 ====================

def main():
    """主函数（支持多交易对和Telegram通知）"""
    global global_strategies, global_regimes, global_positions
    
    logger.info("=" * 50)
    logger.info("Gate.io 量化交易机器人启动")
    logger.info("=" * 50)
    
    # 1. 初始化交易所API
    api = ExchangeAPI(GATEIO_API_KEY, GATEIO_API_SECRET)
    
    # 2. 初始化Telegram通知器
    notifier = None
    if TELEGRAM_ENABLED and TELEGRAM_BOT_TOKEN != "YOUR_BOT_TOKEN":
        notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED)
        logger.info("Telegram通知器初始化成功")
    
    # 3. 为每个交易对创建策略实例
    strategies = {}
    for symbol in SYMBOLS:
        strategies[symbol] = TradingStrategy(api, symbol, notifier)
        logger.info(f"初始化交易对: {symbol}")
    
    # 更新全局变量
    global_strategies = strategies
    global_regimes = {}
    global_positions = {}
    
    # 4. 启动健康检查服务 (Flask, 后台线程)
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()
    logger.info("健康检查服务已启动: http://0.0.0.0:8080/health")
    
    # 5. 执行策略（每次运行一次，不循环，由GitHub Actions定时触发）
    logger.info(f"开始监控交易对: {', '.join(SYMBOLS)}, 时间周期: {TIMEFRAME}")
    
    try:
        for symbol in SYMBOLS:
            logger.info(f"\n处理交易对: {symbol}")
            
            # 获取K线数据
            df = api.fetch_ohlcv(symbol, TIMEFRAME, limit=100)
            
            if df.empty:
                logger.warning(f"{symbol} 获取K线数据失败，跳过")
                continue
            
            # 执行策略
            strategy = strategies[symbol]
            result = strategy.run_strategy(df)
            
            if result:
                # 更新全局变量 (用于健康检查)
                global_regimes[symbol] = result.get('regime', 'unknown')
                global_positions[symbol] = result.get('position')
                
                logger.info(f"{symbol} 策略执行完成: 市场状态={result['regime']}, 信号={result['signal']}")
        
        logger.info("本次执行完成，等待下次触发...")
            
    except Exception as e:
        logger.error(f"执行发生错误: {e}")
        if notifier:
            notifier.notify_error(f"执行发生错误: {e}")
        raise  # 重新抛出异常，让GitHub Actions知道失败了

if __name__ == "__main__":
    main()
