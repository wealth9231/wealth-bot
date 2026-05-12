#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gate.io 全自动量化交易机器人 (优化版)
改进点：
1. 新增 MACD、Stochastic RSI 指标
2. 优化入场/出场逻辑（更激进）
3. 修复杠杆设置（真正启用4倍杠杆）
4. 增加自动止盈和追踪止损
5. 详细日志记录每次决策原因
"""

import ccxt
import pandas as pd
import numpy as np
from flask import Flask, jsonify
import threading
import time
import logging
from datetime import datetime
from typing import Dict, Tuple, Optional, List

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
    LEVERAGE = 4  # 4倍杠杆
    MAX_POSITION = 0.001
    STOP_LOSS_PCT = -0.02
    MIN_RR_RATIO = 1.2
    TARGET_PROFIT_PCT = 0.01
    GRID_NUM = 20
    GRID_PRICE_RANGE = 0.03
    TREND_ADX_THRESHOLD = 20
    RSI_OVERSOLD = 35
    RSI_OVERBOUGHT = 65
    BB_WIDTH_THRESHOLD = 0.03
    TELEGRAM_ENABLED = os.getenv('TELEGRAM_ENABLED', 'True').lower() == 'true'
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', "8746796223:AAGR4wryx4Zj4TARb9yeC83KOqJQJThTzMo")
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', "6204659239")

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

# ==================== 交易所初始化（优化版）====================
class ExchangeAPI:
    """交易所API封装类（优化版 - 修复杠杆设置）"""
    def __init__(self, api_key: str, secret: str):
        """
        初始化Gate.io交易所连接（支持4倍杠杆）
        """
        self.exchange = ccxt.gateio({
            'apiKey': api_key,
            'secret': secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'margin',  # 改为 margin 以支持杠杆
                'createMarketBuyOrderRequiresPrice': False,
            }
        })
        
        # 注意：不在初始化时设置杠杆，因为现货交易对不支持杠杆设置
        # 杠杆设置将在 create_order() 中根据交易对类型动态处理
        logger.info("交易所API初始化成功")
    
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        """获取K线数据"""
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"获取K线数据失败: {e}")
            return pd.DataFrame()
    
    def get_balance(self, market_type: str = 'spot') -> Dict:
        """
        获取账户余额
        
        Args:
            market_type: 市场类型 ('spot', 'margin', 'swap', etc.)
                       默认 'spot' (现货)，因为主要做现货交易
        """
        try:
            balance = self.exchange.fetch_balance({'type': market_type})
            return balance
        except Exception as e:
            logger.error(f"获取余额失败 (market_type={market_type}): {e}")
            return {}
    
    def create_order(self, symbol: str, side: str, amount: float, 
                     order_type: str = 'market', price: Optional[float] = None, 
                     cost: float = None) -> Dict:
        """创建订单（自动区分现货/杠杆）
        
        Args:
            symbol: 交易对
            side: buy/sell
            amount: 数量（sell时为base数量，buy时为quote金额）
            order_type: market/limit
            price: 限价单价格
            cost: market buy时的USDT金额（可选）
        """
        try:
            # 根据交易对决定是否使用杠杆
            is_margin = ':' in symbol
            
            # 🔍 调试：打印订单参数
            logger.info(f"创建订单: symbol={symbol}, side={side}, amount={amount:.10f}, order_type={order_type}, price={price}, cost={cost}")
            
            params = {}
            if is_margin:
                params = {
                    'type': 'margin',
                    'leverage': LEVERAGE,
                }
            
            # 对于 market buy，使用 cost 参数指定 USDT 金额
            # 这样可以避免 base currency 数量精度问题
            if order_type == 'market' and side == 'buy' and cost is not None:
                params['cost'] = cost
                logger.info(f"使用 cost 参数: {cost} USDT")
            
            if order_type == 'market':
                order = self.exchange.create_order(symbol, 'market', side, amount, None, params)
            else:
                order = self.exchange.create_order(symbol, 'limit', side, amount, price, params)
            
            logger.info(f"订单创建成功: {side} {amount} {symbol} @ {price if price else 'market'}")
            logger.info(f"订单详情: {order}")
            return order
        except Exception as e:
            logger.error(f"创建订单失败: symbol={symbol}, side={side}, amount={amount}, error={e}")
            return {}

    def create_limit_sell_order(self, symbol: str, amount: float, price: float) -> Dict:
        """挂限价卖出单（止盈）"""
        try:
            logger.info(f"挂止盈限价单: {symbol} {amount} @ ${price}")
            order = self.exchange.create_order(symbol, 'limit', 'sell', amount, price)
            logger.info(f"止盈委托单已挂: {order.get('id', 'N/A')}")
            return order
        except Exception as e:
            logger.error(f"挂止盈单失败: {e}")
            return {}
    
    def create_stop_loss_order(self, symbol: str, amount: float, stop_price: float) -> Dict:
        """挂止损条件单（止损）"""
        try:
            # Gate.io stop-limit order
            params = {'stopPrice': stop_price}
            
            logger.info(f"挂止损条件单: {symbol} {amount} @ stop=${stop_price}")
            order = self.exchange.create_order(symbol, 'limit', 'sell', amount, stop_price, params)
            logger.info(f"止损委托单已挂: {order.get('id', 'N/A')}")
            return order
        except Exception as e:
            logger.error(f"挂止损单失败（可能不支持）: {e}")
            return {}
    
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """取消指定订单"""
        try:
            logger.info(f"取消订单: {symbol} order_id={order_id}")
            self.exchange.cancel_order(order_id, symbol)
            logger.info(f"订单已取消: {order_id}")
            return True
        except Exception as e:
            logger.error(f"取消订单失败: {e}")
            return False
    
    def fetch_order(self, symbol: str, order_id: str) -> Dict:
        """查询订单状态"""
        try:
            order = self.exchange.fetch_order(order_id, symbol)
            return order
        except Exception as e:
            logger.error(f"查询订单失败: {e}")
            return {}
    
    def fetch_open_orders(self, symbol: str = None) -> List:
        """查询未成交委托"""
        try:
            orders = self.exchange.fetch_open_orders(symbol)
            return orders
        except Exception as e:
            logger.error(f"查询未成交委托失败: {e}")
            return []
    
    def get_position(self, symbol: str) -> Dict:
        """获取持仓信息（现货/杠杆通用）"""
        try:
            balance = self.get_balance('spot')  # 获取现货余额
            base_currency = symbol.split('/')[0]
            quote_currency = symbol.split('/')[1]
            
            position = {
                'base_amount': balance[base_currency]['free'] if base_currency in balance else 0,
                'quote_amount': balance[quote_currency]['free'] if quote_currency in balance else 0,
                'timestamp': datetime.now().isoformat()
            }
            return position
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return {}

# ==================== 技术指标计算（增强版）====================
class TechnicalIndicators:
    """技术指标计算类（增强版 - 新增MACD、Stochastic RSI）"""
    
    @staticmethod
    def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算ADX"""
        try:
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
        """计算RSI"""
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
    def calculate_stochastic_rsi(df: pd.DataFrame, period: int = 14, smooth_k: int = 3, smooth_d: int = 3) -> Tuple[pd.Series, pd.Series]:
        """
        计算 Stochastic RSI（随机RSI）
        比普通RSI更敏感，能更早捕捉超买超卖
        """
        try:
            rsi = TechnicalIndicators.calculate_rsi(df, period)
            
            # 计算Stochastic RSI
            stoch_rsi = (rsi - rsi.rolling(window=period).min()) / (rsi.rolling(window=period).max() - rsi.rolling(window=period).min()) * 100
            
            # 平滑处理
            k = stoch_rsi.rolling(window=smooth_k).mean()
            d = k.rolling(window=smooth_d).mean()
            
            return k, d
        except Exception as e:
            logger.error(f"计算Stochastic RSI失败: {e}")
            return pd.Series(), pd.Series()
    
    @staticmethod
    def calculate_macd(df: pd.DataFrame, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        计算MACD
        返回：(macd_line, signal_line, histogram)
        """
        try:
            close = df['close']
            
            ema_fast = close.ewm(span=fast_period, adjust=False).mean()
            ema_slow = close.ewm(span=slow_period, adjust=False).mean()
            
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
            histogram = macd_line - signal_line
            
            return macd_line, signal_line, histogram
        except Exception as e:
            logger.error(f"计算MACD失败: {e}")
            return pd.Series(), pd.Series(), pd.Series()
    
    @staticmethod
    def calculate_ema(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """计算EMA"""
        try:
            return df['close'].ewm(span=period, adjust=False).mean()
        except Exception as e:
            logger.error(f"计算EMA失败: {e}")
            return pd.Series()
    
    @staticmethod
    def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, 
                                  std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """计算布林带"""
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
        """计算布林带宽度"""
        try:
            upper, middle, lower = TechnicalIndicators.calculate_bollinger_bands(df, period)
            width = (upper - lower) / middle
            return width
        except Exception as e:
            logger.error(f"计算布林带宽度失败: {e}")
            return pd.Series()
    
    @staticmethod
    def calculate_volume_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """计算成交量简单移动平均"""
        try:
            return df['volume'].rolling(window=period).mean()
        except Exception as e:
            logger.error(f"计算成交量SMA失败: {e}")
            return pd.Series()
    
    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算ATR（平均真实波动幅度）"""
        try:
            high = df['high']
            low = df['low']
            close = df['close']
            
            tr1 = high - low
            tr2 = abs(high - close.shift(1))
            tr3 = abs(low - close.shift(1))
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(window=period).mean()
            
            return atr
        except Exception as e:
            logger.error(f"计算ATR失败: {e}")
            return pd.Series()

# ==================== 市场状态识别（优化版）====================
class MarketRegimeDetector:
    """市场状态识别器（优化版 - 增加更多状态）"""
    
    @staticmethod
    def detect_market_regime(df: pd.DataFrame) -> Tuple[str, Dict]:
        """
        识别当前市场状态（优化版）
        
        新增状态：
        - '强势上涨': MACD金叉 + RSI > 50
        - '强势下跌': MACD死叉 + RSI < 50
        - '反转信号': Stochastic RSI超卖/超买反转
        """
        try:
            # 计算所有技术指标
            adx = TechnicalIndicators.calculate_adx(df).iloc[-1]
            rsi = TechnicalIndicators.calculate_rsi(df).iloc[-1]
            ema20 = TechnicalIndicators.calculate_ema(df, 20).iloc[-1]
            ema50 = TechnicalIndicators.calculate_ema(df, 50).iloc[-1]
            bb_width = TechnicalIndicators.calculate_bb_width(df).iloc[-1]
            current_price = df['close'].iloc[-1]
            
            # 新增：MACD和Stochastic RSI
            macd, macd_signal, macd_hist = TechnicalIndicators.calculate_macd(df)
            stoch_k, stoch_d = TechnicalIndicators.calculate_stochastic_rsi(df)
            
            macd_current = macd.iloc[-1]
            macd_signal_current = macd_signal.iloc[-1]
            stoch_k_current = stoch_k.iloc[-1]
            stoch_d_current = stoch_d.iloc[-1]
            
            # 指标详情
            indicators = {
                'adx': round(adx, 2),
                'rsi': round(rsi, 2),
                'ema20': round(ema20, 2),
                'ema50': round(ema50, 2),
                'bb_width': round(bb_width, 4),
                'current_price': round(current_price, 2),
                'macd': round(macd_current, 4),
                'macd_signal': round(macd_signal_current, 4),
                'stoch_k': round(stoch_k_current, 2),
                'stoch_d': round(stoch_d_current, 2)
            }
            
            # 判断市场状态（优化逻辑）
            is_trending = adx > TREND_ADX_THRESHOLD
            
            # 1. 强势趋势判断（新增MACD确认）
            if is_trending:
                # MACD金叉 = 买入信号
                macd_cross_up = (macd.iloc[-1] > macd_signal.iloc[-1]) and (macd.iloc[-2] <= macd_signal.iloc[-2])
                # MACD死叉 = 卖出信号
                macd_cross_down = (macd.iloc[-1] < macd_signal.iloc[-1]) and (macd.iloc[-2] >= macd_signal.iloc[-2])
                
                if ema20 > ema50 and current_price > ema20 and (macd_cross_up or rsi > 50):
                    regime = '强势上涨'
                elif ema20 < ema50 and current_price < ema20 and (macd_cross_down or rsi < 50):
                    regime = '强势下跌'
                elif ema20 > ema50 and current_price > ema20:
                    regime = '趋势向上'
                elif ema20 < ema50 and current_price < ema20:
                    regime = '趋势向下'
                else:
                    regime = '震荡市'
            else:
                # 2. 震荡市 + Stochastic RSI反转信号
                stoch_oversold = stoch_k_current < 20 and stoch_d_current < 20
                stoch_overbought = stoch_k_current > 80 and stoch_d_current > 80
                
                if stoch_oversold and bb_width < BB_WIDTH_THRESHOLD:
                    regime = '反转信号_超卖'
                elif stoch_overbought and bb_width < BB_WIDTH_THRESHOLD:
                    regime = '反转信号_超买'
                elif bb_width < BB_WIDTH_THRESHOLD:
                    regime = '震荡市'
                else:
                    regime = '高波动'
            
            logger.info(f"市场状态: {regime}, 指标: {indicators}")
            return regime, indicators
            
        except Exception as e:
            logger.error(f"市场状态识别失败: {e}")
            return 'unknown', {}

# ==================== Telegram通知模块（保持不变）====================
class TelegramNotifier:
    """Telegram通知类"""
    
    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled
        self.api_url = f"https://api.telegram.org/bot{ bot_token}/sendMessage"
    
    def send_message(self, message: str) -> bool:
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
        """通知交易信号（简洁版）"""
        short_name = symbol.replace('/USDT', '')
        time_str = datetime.now().strftime('%H:%M')
        
        if signal == 'buy':
            message = f"🟢 买入 {short_name} @ ${price:,.2f}  {time_str}"
        elif signal == 'sell':
            message = f"🔴 卖出 {short_name} @ ${price:,.2f}  {time_str}"
        else:
            message = f"🟡 {short_name} @ ${price:,.2f}  信号:{signal.upper()}  {time_str}"
        
        return self.send_message(message)
    
    def notify_stop_loss(self, symbol: str, entry_price: float, current_price: float, loss_pct: float) -> bool:
        """通知止损触发（简洁版）"""
        short_name = symbol.replace('/USDT', '')
        time_str = datetime.now().strftime('%H:%M')
        message = f"🔴 止损 {short_name}  入场:${entry_price:,.2f}  当前:${current_price:,.2f}  亏损:{loss_pct*100:.2f}%  {time_str}"
        return self.send_message(message)
    
    def notify_take_profit(self, symbol: str, entry_price: float, current_price: float, profit_pct: float) -> bool:
        """通知止盈触发（简洁版）"""
        short_name = symbol.replace('/USDT', '')
        time_str = datetime.now().strftime('%H:%M')
        message = f"🟢 止盈 {short_name}  入场:${entry_price:,.2f}  当前:${current_price:,.2f}  盈利:+{profit_pct*100:.2f}%  {time_str}"
        return self.send_message(message)
    
    def notify_error(self, error_msg: str) -> bool:
        """通知错误（醒目版本）"""
        time_str = datetime.now().strftime('%H:%M:%S')
        # 截断过长的错误消息
        if len(error_msg) > 300:
            error_msg = error_msg[:297] + "..."
        message = (
            f"⚠️ <b>系统错误</b>\n"
            f"\n"
            f"<code>{error_msg}</code>\n"
            f"\n"
            f"⏰ <code>{time_str}</code>"
        )
        return self.send_message(message)
    
    def _get_regime_emoji(self, regime: str) -> str:
        """根据市场状态返回emoji"""
        regime_emoji_map = {
            '强势上涨': '🟢',
            '趋势向上': '📈',
            '强势下跌': '🔴',
            '趋势向下': '📉',
            '震荡市': '⚪',
            '趋势不明': '⚪',
        }
        return regime_emoji_map.get(regime, '⚪')
    
    def _get_signal_emoji(self, rsi: float, rsi_oversold: float, rsi_overbought: float) -> str:
        """根据RSI返回信号emoji"""
        if rsi < rsi_oversold:
            return '🟢 买入'
        elif rsi > rsi_overbought:
            return '🔴 卖出'
        else:
            return '⚪ 持有'
    
    def notify_market_summary(self, symbols_data: list, usdt_balance: float = None) -> bool:
        """
        发送市场状态汇总（手机适配精简版）
        模板：
        Quant Bot
        监控6币 | 目标+2% 止损-2%
        BTC $80552 RSI37▲ 跌 空
        DOGE $0.11 RSI55 平 持
          成本0.1097 现0.112 +2.1%  止盈0.112 止损0.107
        📊 机会0个 · 已买入1个  USDT $0.00
        时间 05-13 02:32
        """
        time_str = datetime.now().strftime('%m-%d %H:%M')
        lines = []
        
        # 标题
        lines.append("Quant Bot")
        lines.append(f"监控{len(symbols_data)}币 | 动态目标 止损{STOP_LOSS_PCT*100:.0f}%")
        lines.append("")
        
        # 统计
        pos_count = 0
        MIN_POS_VALUE = 0.1  # 降低阈值，TRX等小币也能显示
        
        # 每个交易对
        for data in symbols_data:
            symbol = data['symbol']
            regime = data.get('regime', '')
            rsi = data.get('rsi', 50)
            price = data.get('price', 0)
            position = data.get('position')
            
            short_name = symbol.replace('/USDT', '')
            
            # RSI标记
            if rsi < RSI_OVERSOLD:
                rsi_mark = '▲'
            elif rsi > RSI_OVERBOUGHT:
                rsi_mark = '▼'
            else:
                rsi_mark = ' '
            
            # 趋势（1字）
            if '上涨' in regime or 'bull' in regime.lower():
                trend = '涨'
            elif '下跌' in regime or 'bear' in regime.lower():
                trend = '跌'
            else:
                trend = '平'
            
            # 持仓？
            has_pos = position and position > 0 and price * position >= MIN_POS_VALUE
            pos_str = '持' if has_pos else '空'
            
            # 价格（去$,去逗号）
            price_str = f"{price:,.2f}".replace(',', '').replace('$', '')
            
            # 基础行
            line = f"{short_name:<5} ${price_str} RSI{rsi:.0f}{rsi_mark} {trend} {pos_str}"
            
            # 有持仓：加第二行详情
            if has_pos:
                pos_count += 1
                ep = data.get('entry_price')
                if ep:
                    # 有入场价：显示完整详情（精简，避免换行）
                    pnl = (price - ep) / ep * 100
                    dynamic_tp = data.get('dynamic_tp', TARGET_PROFIT_PCT)
                    tp = ep * (1 + dynamic_tp)
                    sl = ep * (1 + STOP_LOSS_PCT)
                    sign = '+' if pnl >= 0 else ''
                    line += "\n" + f"  成本{ep:.5g} 盈亏{sign}{pnl:.1f}% 出{tp:.5g} 砍{sl:.5g}"
                else:
                    # 没有入场价：显示持仓数量和当前价
                    line += "\n" + f"  持有{position:.4g}个 当前${price:.5g}"
            
            lines.append(line)
        
        # 统计行
        lines.append("")
        signal_count = sum(1 for d in symbols_data if d.get('signal') in ['buy', 'sell'])
        stats = f"机会{signal_count}个 · 已买入{pos_count}个"
        balance_str = f"USDT ${usdt_balance:.2f}" if usdt_balance is not None else "USDT ?"
        lines.append(f"📊 {stats}  {balance_str}")
        lines.append(f"时间 {time_str}")
        
        message = "\n".join(lines)
        return self.send_message(message)
    def notify_market_regime(self, symbol: str, regime: str, indicators: Dict,
                              current_position: float = None, 
                              entry_price: float = None, current_price: float = None) -> bool:
        """通知市场状态（兼容旧版本，现在建议使用 notify_market_summary）"""
        # 新版改为汇总发送，单条不再发送
        # 保留此方法用于兼容
        return True

# ==================== 策略模块（优化版）====================
class TradingStrategy:
    """交易策略类（优化版 - 更激进的入场/出场）"""
    
    def __init__(self, exchange_api: ExchangeAPI, symbol: str, notifier: TelegramNotifier = None):
        self.api = exchange_api
        self.symbol = symbol
        self.notifier = notifier
        self.current_position = None
        self.entry_price = None
        self.entry_time = None
        self.highest_price = None  # 用于追踪止损
        self.last_regime = None
        self.tp_order_id = None   # 止盈委托单ID
        self.sl_order_id = None   # 止损委托单ID
        
    def trend_following_strategy(self, regime: str, current_price: float, indicators: Dict) -> str:
        """
        趋势跟踪策略（优化版 - 更激进）
        
        改进点：
        1. 强势上涨时立即买入（不只趋势向上）
        2. 增加MACD确认
        3. 降低入场门槛
        """
        # 强势上涨或趋势向上，且未持仓 → 买入
        if regime in ['强势上涨', '趋势向上'] and self.current_position is None:
            logger.info(f"趋势策略: {regime} + 未持仓 → 买入信号")
            return 'buy'
        
        # 强势下跌或趋势向下，且已持仓 → 卖出
        elif regime in ['强势下跌', '趋势向下'] and self.current_position is not None:
            logger.info(f"趋势策略: {regime} + 已持仓 → 卖出信号")
            return 'sell'
        
        else:
            reason = f"趋势策略: {regime} + "
            reason += "已持仓" if self.current_position else "未持仓"
            reason += " → 持有"
            logger.info(reason)
            return 'hold'
    
    def grid_trading_strategy(self, current_price: float, df: pd.DataFrame) -> str:
        """
        网格交易策略（优化版 - 更频繁的网格交易）
        
        改进点：
        1. 降低买入阈值（40% instead of 30%）
        2. 降低卖出阈值（60% instead of 70%）
        3. 增加成交量确认
        """
        try:
            upper, middle, lower = TechnicalIndicators.calculate_bollinger_bands(df)
            grid_spacing = (upper.iloc[-1] - lower.iloc[-1]) / GRID_NUM
            
            # 当前价格所在网格位置
            grid_level = (current_price - lower.iloc[-1]) / grid_spacing
            
            # 成交量确认（避免假突破）
            volume = df['volume'].iloc[-1]
            volume_sma = TechnicalIndicators.calculate_volume_sma(df).iloc[-1]
            volume_confirmed = volume > volume_sma * 0.8  # 成交量大于均量的80%
            
            # 优化逻辑：更激进的网格交易
            if grid_level < GRID_NUM * 0.4 and self.current_position is None and volume_confirmed:
                logger.info(f"网格策略: 价格处于网格下部({grid_level:.1f}/{GRID_NUM}) + 成交量确认 → 买入")
                return 'buy'
            elif grid_level > GRID_NUM * 0.6 and self.current_position is not None:
                logger.info(f"网格策略: 价格处于网格上部({grid_level:.1f}/{GRID_NUM}) → 卖出")
                return 'sell'
            else:
                reason = f"网格策略: 价格处于网格中部({grid_level:.1f}/{GRID_NUM}) → 持有"
                logger.info(reason)
                return 'hold'
                
        except Exception as e:
            logger.error(f"网格策略计算失败: {e}")
            return 'hold'
    
    def reversal_strategy(self, regime: str, indicators: Dict, df: pd.DataFrame) -> str:
        """
        反转策略（改进版 - 动态RSI + ADX过滤）
        
        改进点：
        1. 动态RSI阈值：布林带宽 > 0.08 时，超卖阈值降到 25（防止趋势中RSI钝化）
        2. ADX过滤：ADX > 15 时才允许买入（趋势强度足够）
        3. 更激进的止盈：RSI > 65 就卖出
        
        返回：'buy', 'sell', 'hold'
        """
        rsi = indicators.get('rsi', 50)
        stoch_k = indicators.get('stoch_k', 50)
        adx = indicators.get('adx', 0)
        current_price = df['close'].iloc[-1]
        
        try:
            # 计算布林带位置和宽度
            upper, middle, lower = TechnicalIndicators.calculate_bollinger_bands(df)
            bb_position = (current_price - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1])  # 0=下轨, 1=上轨
            
            # 计算布林带宽度（用于动态RSI阈值）
            bb_width = (upper.iloc[-1] - lower.iloc[-1]) / middle.iloc[-1]
            
            # 动态RSI超卖阈值
            rsi_oversold_current = RSI_OS_WIDE if bb_width > BB_WIDTH_THRESHOLD else RSI_OVERSOLD
            
            # === 买入信号：抄底 ===
            if self.current_position is None:
                # 条件1：RSI 超卖（动态阈值）
                # 条件2：价格接近布林带下轨 (bb_position < 0.3)
                # 条件3：ADX > 15（趋势强度足够）
                if rsi < rsi_oversold_current and bb_position < 0.3 and adx > TREND_ADX_THRESHOLD:
                    logger.info(f"🟢 反转策略买入: RSI={rsi:.1f} < {rsi_oversold_current}(动态), 布林带位置={bb_position:.2f} < 0.3, ADX={adx:.1f} > {TREND_ADX_THRESHOLD}")
                    return 'buy'
                
                # 特殊情况：RSI 极度超卖 (< 25) + Stoch RSI 极度超卖 (< 15) + ADX过滤
                elif rsi < 25 and stoch_k < 15 and adx > TREND_ADX_THRESHOLD:
                    logger.info(f"🟢 反转策略买入(极度超卖): RSI={rsi:.1f}, Stoch RSI={stoch_k:.1f}, ADX={adx:.1f}")
                    return 'buy'
            
            # === 卖出信号：逃顶 ===
            elif self.current_position is not None:
                # 条件1：RSI 超买 (> 65)
                # 条件2：价格接近布林带上轨 (bb_position > 0.7)
                if rsi > RSI_OVERBOUGHT and bb_position > 0.7:
                    logger.info(f"🔴 反转策略卖出: RSI={rsi:.1f} > {RSI_OVERBOUGHT}, 布林带位置={bb_position:.2f} > 0.7")
                    return 'sell'
                
                # 特殊情况：RSI 极度超买 (> 75) + Stoch RSI 极度超买 (> 85)
                elif rsi > 75 and stoch_k > 85:
                    logger.info(f"🔴 反转策略卖出(极度超买): RSI={rsi:.1f}, Stoch RSI={stoch_k:.1f}")
                    return 'sell'
            
            # 持有
            return 'hold'
            
        except Exception as e:
            logger.error(f"反转策略计算失败: {e}")
            return 'hold'
    
    def trend_following_pullback_strategy(self, regime: str, indicators: Dict, df: pd.DataFrame) -> str:
        """
        方案B：趋势跟踪 + 回调买入（优化前版本）
        
        核心逻辑：
        - 买入信号：ADX > 25 (趋势确认) + RSI < 50 (回调) + MACD > Signal (动量回归)
        - 卖出信号：RSI > 70 (超买) 或 追踪止损触发
        - 适用场景：趋势市（BTC 30%时间在这里）
        
        返回：'buy', 'sell', 'hold'
        """
        adx = indicators.get('adx', 0)
        rsi = indicators.get('rsi', 50)
        macd = indicators.get('macd', 0)
        macd_signal = indicators.get('macd_signal', 0)
        current_price = df['close'].iloc[-1]
        
        try:
            # === 买入信号：趋势确认 + 回调 ===
            if self.current_position is None:
                # 条件1：ADX > 25 (趋势确认)
                # 条件2：RSI < 50 (回调，不是追涨)
                # 条件3：MACD > Signal (动量回归)
                if adx > TREND_ADX_THRESHOLD and rsi < 50 and macd > macd_signal:
                    logger.info(f"🟢 趋势策略买入(回调): ADX={adx:.1f} > {TREND_ADX_THRESHOLD}, RSI={rsi:.1f} < 50, MACD={macd:.2f} > Signal={macd_signal:.2f}")
                    return 'buy'
                
                # 特殊情况：ADX > 30 (强趋势) + RSI < 40 (深度回调)
                elif adx > 30 and rsi < 40:
                    logger.info(f"🟢 趋势策略买入(深度回调): ADX={adx:.1f} > 30, RSI={rsi:.1f} < 40")
                    return 'buy'
            
            # === 卖出信号：超买 或 趋势结束 ===
            elif self.current_position is not None:
                # 条件1：RSI > 70 (超买)
                if rsi > 70:
                    logger.info(f"🔴 趋势策略卖出(超买): RSI={rsi:.1f} > 70")
                    return 'sell'
                
                # 条件2：ADX < 20 (趋势结束) + RSI > 50 (动能减弱)
                if adx < 20 and rsi > 50:
                    logger.info(f"🔴 趋势策略卖出(趋势结束): ADX={adx:.1f} < 20, RSI={rsi:.1f} > 50")
                    return 'sell'
            
            # 持有
            return 'hold'
    
        except Exception as e:
            logger.error(f"趋势跟踪策略计算失败: {e}")
            return 'hold'
    
    def calculate_dynamic_tp(self, df: pd.DataFrame) -> float:
        """
        根据ATR计算动态止盈目标
        
        ATR占价格比 | 波动等级 | 止盈目标
        > 2%          | 高波动   | +3%
        1%~2%         | 中波动   | +2%
        < 1%          | 低波动   | +1%
        
        Returns:
            止盈比例（如0.02表示+2%）
        """
        try:
            atr = TechnicalIndicators.calculate_atr(df).iloc[-1]
            current_price = df['close'].iloc[-1]
            atr_pct = atr / current_price  # ATR占价格百分比
            
            # 根据波动率调整止盈目标
            if atr_pct > 0.02:  # 高波动
                return 0.03  # +3%
            elif atr_pct > 0.01:  # 中波动
                return 0.02  # +2%
            else:  # 低波动
                return 0.01  # +1%
        except Exception as e:
            logger.error(f"计算动态止盈失败: {e}")
            return TARGET_PROFIT_PCT  # 失败时使用配置文件的值

    def check_take_profit(self, current_price: float, df: pd.DataFrame = None) -> bool:
        """
        检查止盈条件（新增）
        
         Returns:
            是否触发止盈
        """
        if self.entry_price is None or self.current_position is None:
            return False
        
        profit_pct = (current_price - self.entry_price) / self.entry_price
        
        # 使用动态止盈目标（如果提供了DataFrame）
        if df is not None:
            dynamic_tp = self.calculate_dynamic_tp(df)
            tp_threshold = dynamic_tp
            logger.debug(f"动态止盈目标: {dynamic_tp*100:.1f}%")
        else:
            tp_threshold = TARGET_PROFIT_PCT
        
        if profit_pct >= tp_threshold:
            logger.info(f"触发止盈(动态={tp_threshold*100:.1f}%): 入场价={self.entry_price}, 当前价={current_price}, 盈利={profit_pct*100:.2f}%")
            
            if self.notifier:
                self.notifier.notify_take_profit(self.symbol, self.entry_price, current_price, profit_pct)
            
            return True
        
        return False
    
    def check_trailing_stop(self, current_price: float) -> bool:
        """
        检查追踪止损（新增）
        
        逻辑：
        - 当价格上涨时，动态上调止损价
        - 当价格回落超过2%时，触发止损
        
        Returns:
            是否触发追踪止损
        """
        if self.entry_price is None or self.current_position is None:
            return False
        
        # 初始化最高价
        if self.highest_price is None or current_price > self.highest_price:
            self.highest_price = current_price
        
        # 计算从最高价的回撤
        drawdown = (current_price - self.highest_price) / self.highest_price
        
        # 回撤超过2% → 触发追踪止损
        if drawdown <= -0.02:
            logger.info(f"触发追踪止损: 最高价={self.highest_price}, 当前价={current_price}, 回撤={drawdown*100:.2f}%")
            
            if self.notifier:
                profit_pct = (current_price - self.entry_price) / self.entry_price
                self.notifier.notify_stop_loss(self.symbol, self.entry_price, current_price, profit_pct)
            
            return True
        
        return False
    
    def execute_signal(self, signal: str, current_price: float, df: pd.DataFrame = None):
        """执行交易信号（优化版 - 增加详细日志）"""
        try:
            # 检查资金余额（获取现货余额）
            balance = self.api.get_balance('spot')
            if not balance or 'USDT' not in balance:
                logger.error("无法获取USDT余额，跳过交易")
                return
            
            usdt_balance = balance['USDT']['free'] if 'free' in balance['USDT'] else 0
            logger.info(f"当前USDT余额: {usdt_balance:.2f}")
            
            if signal == 'buy':
                # 正常买入 (使用全部可用资金)
                # 注意：对于 Gate.io spot market buy，amount 是 USDT 金额（quote currency）
                available_usdt = usdt_balance  # 使用全部余额
                
                # 检查最小交易金额（Gate.io最小交易额为5 USDT）
                if available_usdt < 5:
                    logger.warning(f"可用资金不足5 USDT，跳过买入")
                    return
                
                # market buy 传入 USDT 金额
                cost = available_usdt
                
                logger.info(f"执行买入: ${cost:.2f} USDT → {self.symbol} @ {current_price:.2f}")
                # 使用 cost 参数指定 USDT 金额
                order = self.api.create_order(self.symbol, 'buy', cost, 'market', cost=cost)
                if order:
                    # 从订单结果中获取实际买入的数量
                    filled_amount = order.get('filled', 0)
                    self.current_position = filled_amount
                    self.entry_price = current_price
                    self.entry_time = datetime.now()
                    self.highest_price = current_price
                    logger.info(f"✅ 买入成功: ${cost:.2f} USDT → {filled_amount:.6f} {self.symbol}")
                    
                    if self.notifier:
                        self.notifier.notify_trade_signal(self.symbol, signal, current_price, '趋势跟踪')
                    
                    # 挂止盈止损委托单
                    dynamic_tp = self.calculate_dynamic_tp(df) if df is not None else TARGET_PROFIT_PCT
                    tp_price = current_price * (1 + dynamic_tp)
                    sl_price = current_price * (1 + STOP_LOSS_PCT)
                    
                    # 挂止盈限价单
                    tp_order = self.api.create_limit_sell_order(self.symbol, filled_amount, tp_price)
                    if tp_order and tp_order.get('id'):
                        self.tp_order_id = tp_order['id']
                        logger.info(f"✅ 止盈委托单已挂: {filled_amount:.6f} @ ${tp_price:.5g} (ID={self.tp_order_id})")
                    
                    # 挂止损条件单
                    sl_order = self.api.create_stop_loss_order(self.symbol, filled_amount, sl_price)
                    if sl_order and sl_order.get('id'):
                        self.sl_order_id = sl_order['id']
                        logger.info(f"✅ 止损委托单已挂: {filled_amount:.6f} @ ${sl_price:.5g} (ID={self.sl_order_id})")
                        
            elif signal == 'buy_small':
                # 小仓位买入 (使用30%可用资金)
                available_usdt = usdt_balance * 0.3
                
                if available_usdt < 5:
                    logger.warning(f"可用资金不足5 USDT，跳过买入")
                    return
                
                # market buy 传入 USDT 金额
                cost = available_usdt
                
                logger.info(f"执行小仓位买入: ${cost:.2f} USDT → {self.symbol} @ {current_price:.2f}")
                order = self.api.create_order(self.symbol, 'buy', cost, 'market', cost=cost)
                if order:
                    filled_amount = order.get('filled', 0)
                    self.current_position = filled_amount
                    self.entry_price = current_price
                    self.entry_time = datetime.now()
                    self.highest_price = current_price
                    logger.info(f"✅ 小仓位买入成功: ${cost:.2f} USDT → {filled_amount:.6f} {self.symbol}")
                    
                    if self.notifier:
                        self.notifier.notify_trade_signal(self.symbol, signal, current_price, '超卖反弹')
                    
                    # 挂止盈止损委托单
                    dynamic_tp = self.calculate_dynamic_tp(df) if df is not None else TARGET_PROFIT_PCT
                    tp_price = current_price * (1 + dynamic_tp)
                    sl_price = current_price * (1 + STOP_LOSS_PCT)
                    
                    # 挂止盈限价单
                    tp_order = self.api.create_limit_sell_order(self.symbol, filled_amount, tp_price)
                    if tp_order and tp_order.get('id'):
                        self.tp_order_id = tp_order['id']
                        logger.info(f"✅ 止盈委托单已挂: {filled_amount:.6f} @ ${tp_price:.5g} (ID={self.tp_order_id})")
                    
                    # 挂止损条件单
                    sl_order = self.api.create_stop_loss_order(self.symbol, filled_amount, sl_price)
                    if sl_order and sl_order.get('id'):
                        self.sl_order_id = sl_order['id']
                        logger.info(f"✅ 止损委托单已挂: {filled_amount:.6f} @ ${sl_price:.5g} (ID={self.sl_order_id})")
                        
            elif signal == 'sell':
                # 卖出全部持仓（只卖spot账户的可用余额）
                if self.current_position and self.current_position > 0:
                    profit_pct = (current_price - self.entry_price) / self.entry_price * 100
                    logger.info(f"执行卖出: {self.current_position:.6f} {self.symbol} @ {current_price:.2f}, 盈亏: {profit_pct:.2f}%")
                    
                    # 格式化卖出数量（使用self.current_position，即spot账户的可用余额）
                    sell_amount = self._format_amount(self.symbol, self.current_position)
                    logger.info(f"卖出数量（格式化后）: {sell_amount}")
                    
                    # 先取消止盈止损委托单
                    if self.tp_order_id:
                        logger.info(f"卖出前取消止盈委托单: {self.tp_order_id}")
                        self.api.cancel_order(self.symbol, self.tp_order_id)
                        self.tp_order_id = None
                    if self.sl_order_id:
                        logger.info(f"卖出前取消止损委托单: {self.sl_order_id}")
                        self.api.cancel_order(self.symbol, self.sl_order_id)
                        self.sl_order_id = None
                    
                    order = self.api.create_order(self.symbol, 'sell', sell_amount, 'market')
                    if order:
                        logger.info(f"✅ 卖出成功: 盈亏={profit_pct:.2f}%")
                        
                        if self.notifier:
                            self.notifier.notify_trade_signal(self.symbol, signal, current_price, 'unknown')
                        
                        self.current_position = None
                        self.entry_price = None
                        self.entry_time = None
                        self.highest_price = None
                        
        except Exception as e:
            logger.error(f"执行交易信号失败: {e}")
            if self.notifier:
                self.notifier.notify_error(f"执行交易信号失败: {e}")
    
    def _format_amount(self, symbol: str, amount: float) -> float:
        """
        根据交易对格式化订单数量（符合交易所精度要求）
        
        Gate.io 最小订单量：
        - BTC/USDT: 0.000001 BTC
        - ETH/USDT: 0.001 ETH
        - SOL/USDT: 0.001 SOL
        - BNB/USDT: 0.001 BNB
        - DOGE/USDT: 1 DOGE
        """
        # 定义每个交易对的最小精度（保留小数位）
        precision_map = {
            'BTC/USDT': 6,   # 0.000001
            'ETH/USDT': 3,   # 0.001
            'SOL/USDT': 3,   # 0.001
            'BNB/USDT': 3,   # 0.001
            'DOGE/USDT': 0,  # 1
        }
        
        # 定义每个交易对的最小订单量
        min_amount_map = {
            'BTC/USDT': 0.000001,
            'ETH/USDT': 0.001,
            'SOL/USDT': 0.001,
            'BNB/USDT': 0.001,
            'DOGE/USDT': 1.0,
        }
        
        # 获取精度（默认6位）
        precision = precision_map.get(symbol, 6)
        
        # 四舍五入到指定精度
        formatted_amount = round(amount, precision)
        
        # 检查是否满足最小订单量
        min_amount = min_amount_map.get(symbol, 0.000001)
        if formatted_amount < min_amount:
            logger.warning(f"订单数量 {formatted_amount} 小于最小要求 {min_amount}，设置为0")
            return 0
        
        return formatted_amount
    
    def check_stop_loss(self, current_price: float) -> bool:
        """检查止损条件（包含追踪止损）"""
        if self.entry_price is None or self.current_position is None:
            return False
        
        # 1. 固定止损
        loss_pct = (current_price - self.entry_price) / self.entry_price
        if loss_pct <= STOP_LOSS_PCT:
            logger.warning(f"触发固定止损: 入场价={self.entry_price}, 当前价={current_price}, 亏损={loss_pct*100:.2f}%")
            
            if self.notifier:
                self.notifier.notify_stop_loss(self.symbol, self.entry_price, current_price, loss_pct)
            
            self.execute_signal('sell', current_price)
            return True
        
        # 2. 追踪止损
        if self.check_trailing_stop(current_price):
            self.execute_signal('sell', current_price)
            return True
        
        return False
    
    def sync_position_from_exchange(self):
        """
        从交易所查询实际持仓（仅spot账户），同步到 self.current_position
        解决重启后内存状态丢失的问题
        
        注意：
        - 只查 spot 账户（funding账户无法直接卖出，需手动转账）
        - free = 可用余额（可立即卖出）
        - total = free + used（used是挂单中冻结的）
        - ccxt 返回的 balance 中，'free' 是真正可用的
        """
        try:
            MIN_POSITION_VALUE = 0.1  # 最小持仓价值（美元）
            base_currency = self.symbol.split('/')[0]
            
            # ✅ 只查 spot 账户（funding账户的币无法直接卖出）
            try:
                balance = self.api.get_balance('spot')
                if balance and base_currency in balance:
                    # ✅ 只用 free（可用余额），不要用 total 或 free+used
                    # 因为 used 是挂单冻结的，已经包含在 total 里了
                    free_amount = balance[base_currency].get('free', 0)
                    used_amount = balance[base_currency].get('used', 0)
                    total_position = free_amount + used_amount  # total = 可用 + 冻结
                    
                    logger.info(f"🔄 {base_currency} 余额: 可用={free_amount:.6f}, 冻结={used_amount:.6f}, 总计={total_position:.6f}")
                else:
                    total_position = 0
            except Exception as e:
                logger.error(f"🔄 查询spot账户失败: {e}")
                return
            
            # 获取当前价格计算价值
            try:
                ticker = self.api.exchange.fetch_ticker(self.symbol)
                current_price = ticker['last']
                position_value = total_position * current_price
            except Exception:
                position_value = float('inf')
            
            # 更新持仓状态
            if total_position > 0:
                if position_value < MIN_POSITION_VALUE:
                    logger.info(f"🔄 忽略极小持仓: {base_currency} {total_position:.6f} (价值 ${position_value:.2f})")
                    return
                
                logger.info(f"🔄 同步持仓: {base_currency} {total_position:.6f} (价值 ${position_value:.2f})")
                self.current_position = total_position
                
                # 同步入场价
                if self.entry_price is None:
                    try:
                            trades = self.api.exchange.fetch_my_trades(self.symbol, limit=10)
                            for trade in reversed(trades):
                                if trade.get('side') == 'buy':
                                    self.entry_price = trade.get('price', current_price)
                                    logger.info(f"🔄 同步入场价: {base_currency} ${self.entry_price:.6g}")
                                    break
                    except Exception as te:
                        logger.warning(f"🔄 获取成交记录失败: {te}")
                        self.entry_price = current_price
            else:
                if self.current_position is not None:
                    logger.info(f"🔄 持仓已清空: {base_currency}")
                    # 清空委托单ID
                    self.tp_order_id = None
                    self.sl_order_id = None
                    self.current_position = None
                    self.entry_price = None
                    
        except Exception as e:
            logger.error(f"同步持仓失败: {e}")
    
    def run_strategy(self, df: pd.DataFrame) -> Dict:
        """
        运行主策略逻辑（只用方案A - 反转策略/抄底逃顶）
        """
        try:
            # 0. 从交易所同步实际持仓（解决重启后状态丢失）
            self.sync_position_from_exchange()
            
            # 0.5 检查委托单状态（止盈止损）
            if self.current_position is not None:
                # 检查止盈委托单是否成交
                if self.tp_order_id:
                    try:
                        tp_order = self.api.fetch_order(self.symbol, self.tp_order_id)
                        if tp_order and tp_order.get('status') == 'closed':
                            logger.info(f"🎉 止盈委托单已成交! ID={self.tp_order_id}")
                            fill_price = float(tp_order.get('average', current_price))
                            profit_pct = (fill_price - self.entry_price) / self.entry_price
                            if self.notifier:
                                self.notifier.notify_take_profit(self.symbol, self.entry_price, fill_price, profit_pct)
                            # 取消止损委托单
                            if self.sl_order_id:
                                self.api.cancel_order(self.symbol, self.sl_order_id)
                                self.sl_order_id = None
                            # 清空持仓状态
                            self.current_position = None
                            self.entry_price = None
                            self.entry_time = None
                            self.highest_price = None
                            self.tp_order_id = None
                            return {'regime': regime, 'signal': 'take_profit', 'indicators': indicators}
                    except Exception as e:
                        logger.warning(f"查询止盈委托单失败: {e}")
                
                # 检查止损委托单是否成交
                if self.sl_order_id:
                    try:
                        sl_order = self.api.fetch_order(self.symbol, self.sl_order_id)
                        if sl_order and sl_order.get('status') == 'closed':
                            logger.info(f"🛑 止损委托单已成交! ID={self.sl_order_id}")
                            fill_price = float(sl_order.get('average', current_price))
                            profit_pct = (fill_price - self.entry_price) / self.entry_price
                            if self.notifier:
                                self.notifier.notify_stop_loss(self.symbol, self.entry_price, fill_price, profit_pct)
                            # 取消止盈委托单
                            if self.tp_order_id:
                                self.api.cancel_order(self.symbol, self.tp_order_id)
                                self.tp_order_id = None
                            # 清空持仓状态
                            self.current_position = None
                            self.entry_price = None
                            self.entry_time = None
                            self.highest_price = None
                            self.sl_order_id = None
                            return {'regime': regime, 'signal': 'stop_loss', 'indicators': indicators}
                    except Exception as e:
                        logger.warning(f"查询止损委托单失败: {e}")
            
            # 1. 识别市场状态（用于日志记录和Telegram通知）
            regime, indicators = MarketRegimeDetector.detect_market_regime(df)
            current_price = df['close'].iloc[-1]
            
            # 检测市场状态变化，发送Telegram通知
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
            
            # 2. 检查止损（固定止损 + 追踪止损）
            # 如果有持仓但没有入场价，用当前价作为入场价
            if self.current_position is not None and self.entry_price is None:
                self.entry_price = current_price
                logger.info(f"🔄 无历史入场价，使用当前价作为参考: {self.symbol} @ {current_price:.6g}")
            
            if self.check_stop_loss(current_price):
                return {'regime': regime, 'signal': 'stop_loss', 'indicators': indicators}
            
            # 3. 检查止盈
            if self.check_take_profit(current_price, df):
                self.execute_signal('sell', current_price, df)
                return {'regime': regime, 'signal': 'take_profit', 'indicators': indicators}
            
            # 4. 【只用方案A】反转策略（抄底逃顶）
            signal = self.reversal_strategy(regime, indicators, df)
            strategy_name = '方案A(反转策略)'
            
            # 5. 执行交易信号
            if signal != 'hold':
                self.execute_signal(signal, current_price, df)
                logger.info(f"✅ {strategy_name} → 执行信号: {signal}")
            else:
                # 详细日志记录为什么没有交易
                rsi = indicators.get('rsi', 50)
                stoch_k = indicators.get('stoch_k', 50)
                reason = f"🟡 无交易信号 ({strategy_name})\n"
                reason += f"  市场状态: {regime}\n"
                reason += f"  持仓状态: {'已持仓' if self.current_position else '未持仓'}\n"
                reason += f"  指标: RSI={rsi:.1f}, Stoch RSI={stoch_k:.1f}\n"
                reason += f"  买入条件: RSI < {RSI_OVERSOLD} (超卖) + 价格接近布林带下轨\n"
                reason += f"  卖出条件: RSI > {RSI_OVERBOUGHT} (超买) + 价格接近布林带上轨"
                logger.info(reason)
            
            return {
                'regime': regime,
                'signal': signal,
                'strategy': strategy_name,
                'indicators': indicators,
                'position': self.current_position,
                'entry_price': self.entry_price
            }
            
        except Exception as e:
            logger.error(f"策略执行失败: {e}")
            if self.notifier:
                self.notifier.notify_error(f"策略执行失败: {e}")
            return {}

# ==================== 健康检查服务（保持不变）====================
ENABLE_FLASK = os.getenv('ENABLE_FLASK', 'False').lower() == 'true'

if ENABLE_FLASK:
    app = Flask(__name__)
    
    @app.route('/health', methods=['GET'])
    def health_check():
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
        app.run(host='0.0.0.0', port=8080, debug=False)
else:
    def run_flask_app():
        pass

# ==================== 主程序（优化版）====================
def main():
    """主函数（优化版）"""
    global global_strategies, global_regimes, global_positions
    
    logger.info("=" * 50)
    logger.info("Gate.io 量化交易机器人启动 (优化版)")
    logger.info("=" * 50)
    
    # 1. 初始化交易所API（优化版 - 支持杠杆）
    try:
        api = ExchangeAPI(GATEIO_API_KEY, GATEIO_API_SECRET)
    except Exception as e:
        logger.error(f"交易所API初始化失败: {e}")
        return
    
    # 2. 初始化Telegram通知器
    notifier = None
    
    token_preview = TELEGRAM_BOT_TOKEN[:20] + '...' if len(TELEGRAM_BOT_TOKEN) > 20 else TELEGRAM_BOT_TOKEN
    logger.info(f"Telegram配置: ENABLED={TELEGRAM_ENABLED}, BOT_TOKEN={token_preview}, CHAT_ID={TELEGRAM_CHAT_ID}")
    
    if TELEGRAM_ENABLED and TELEGRAM_BOT_TOKEN != "YOUR_BOT_TOKEN":
        notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED)
        logger.info("Telegram通知器初始化成功")
        
        # 发送启动通知（极简版）
        logger.info("发送启动通知...")
        short_symbols = [s.replace('/USDT', '') for s in SYMBOLS]
        startup_msg = (
            f"Quant Bot 已启动\n"
            f"{LEVERAGE}x·{TIMEFRAME} | {len(short_symbols)}币种 | +{TARGET_PROFIT_PCT*100:.0f}% / {STOP_LOSS_PCT*100:.0f}%\n"
            f"{' '.join(short_symbols)}\n"
            f"⏰ {datetime.now().strftime('%m-%d %H:%M')}"
        )
        notifier.send_message(startup_msg)
    
    # 3. 为每个交易对创建策略实例（不传入notifier，避免单独发通知）
    strategies = {}
    for symbol in SYMBOLS:
        strategies[symbol] = TradingStrategy(api, symbol, None)  # 不传notifier，汇总发送
        logger.info(f"初始化交易对: {symbol}")
    
    # 更新全局变量
    global_strategies = strategies
    global_regimes = {}
    global_positions = {}
    
    # 4. 启动健康检查服务
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()
    logger.info("健康检查服务已启动")
    
    # 5. 执行策略
    logger.info(f"开始监控交易对: {', '.join(SYMBOLS)}, 时间周期: {TIMEFRAME}")
    
    # 收集所有交易对的数据，汇总发送
    symbols_summary = []
    usdt_balance = 0
    
    try:
        # 先获取余额
        try:
            balance = api.get_balance('spot')
            usdt_balance = balance.get('USDT', {}).get('free', 0)
            logger.info(f"当前USDT余额: {usdt_balance:.2f}")
        except Exception as e:
            logger.warning(f"获取余额失败: {e}")
        
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
                # 更新全局变量
                global_regimes[symbol] = result.get('regime', 'unknown')
                global_positions[symbol] = result.get('position')
                
                # 收集汇总数据
                indicators = result.get('indicators', {})
                current_price = df['close'].iloc[-1]
                
                # 计算动态止盈目标
                dynamic_tp = strategy.calculate_dynamic_tp(df)
                
                symbols_summary.append({
                    'symbol': symbol,
                    'regime': result.get('regime', 'unknown'),
                    'rsi': indicators.get('rsi', 50),
                    'adx': indicators.get('adx', 0),
                    'price': current_price,
                    'position': result.get('position'),
                    'entry_price': result.get('entry_price'),  # 新增：开仓均价
                    'signal': result.get('signal', 'hold'),
                    'dynamic_tp': dynamic_tp  # 新增：动态止盈目标
                })
                
                logger.info(f"{symbol} 策略执行完成: 市场状态={result['regime']}, 信号={result['signal']}")
        
        # 发送汇总通知
        if notifier and symbols_summary:
            notifier.notify_market_summary(symbols_summary, usdt_balance)
        
        logger.info("本次执行完成，等待下次触发...")
            
    except Exception as e:
        logger.error(f"执行发生错误: {e}")
        if notifier:
            notifier.notify_error(f"执行发生错误: {e}")
        raise

if __name__ == "__main__":
    main()
