#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化版回测脚本 - 直接运行，快速验证策略

使用方法：
    python3 run_backtest.py

输出：
1. 回测报告（收益率、胜率、最大回撤）
2. backtest_trades.csv - 交易记录
3. backtest_balance.csv - 余额历史
"""

import sys
import os

# 添加当前目录到路径，以便导入gate_trading_bot中的类
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from gate_trading_bot import (
    TechnicalIndicators, MarketRegimeDetector,
    TREND_ADX_THRESHOLD, BB_WIDTH_THRESHOLD,
    STOP_LOSS_PCT, TARGET_PROFIT_PCT, GRID_NUM,
    RSI_OVERSOLD, RSI_OVERBOUGHT  # 方案A：反转策略需要这两个常量
)
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

# ==================== 日志配置 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('backtest.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== 简化版策略（用于回测）====================
class SimpleStrategy:
    """简化版策略 - 用于回测"""
    
    def __init__(self):
        self.position = None
        self.entry_price = None
        self.highest_price = None
    
    def run(self, df: pd.DataFrame) -> str:
        """
        运行策略（方案A - 反转策略/抄底逃顶）
        
        核心逻辑：
        - 买入信号：RSI < 35 (超卖) + 价格接近布林带下轨
        - 卖出信号：RSI > 65 (超买) + 价格接近布林带上轨
        - 适用场景：震荡市（BTC 70%时间在这里）
        
        Returns:
            'buy', 'sell', 'hold', 'sell_stop_loss', 'sell_take_profit'
        """
        try:
            # 1. 识别市场状态（用于日志）
            regime, indicators = MarketRegimeDetector.detect_market_regime(df)
            current_price = df['close'].iloc[-1]
            rsi = indicators.get('rsi', 50)
            stoch_k = indicators.get('stoch_k', 50)
            
            # 2. 检查止损/止盈（如果已持仓）
            if self.entry_price and self.position:
                # 固定止损
                loss_pct = (current_price - self.entry_price) / self.entry_price
                if loss_pct <= STOP_LOSS_PCT:
                    logger.info(f"📉 固定止损触发: 亏损={loss_pct*100:.2f}%")
                    return 'sell_stop_loss'
                
                # 止盈
                profit_pct = (current_price - self.entry_price) / self.entry_price
                if profit_pct >= TARGET_PROFIT_PCT:
                    logger.info(f"📈 止盈触发: 盈利={profit_pct*100:.2f}%")
                    return 'sell_take_profit'
                
                # 追踪止损
                if self.highest_price is None or current_price > self.highest_price:
                    self.highest_price = current_price
                
                drawdown = (current_price - self.highest_price) / self.highest_price
                if drawdown <= -0.02:
                    logger.info(f"📉 追踪止损触发: 回撤={drawdown*100:.2f}%")
                    return 'sell_trailing_stop'
            
            # 3. 【方案A】反转策略（抄底逃顶）
            signal = 'hold'
            
            # 计算布林带位置
            upper, middle, lower = TechnicalIndicators.calculate_bollinger_bands(df)
            bb_position = (current_price - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1])  # 0=下轨, 1=上轨
            
            # === 买入信号：抄底 ===
            if self.position is None:
                # 条件1：RSI 超卖 (< 35)
                # 条件2：价格接近布林带下轨 (bb_position < 0.3)
                if rsi < RSI_OVERSOLD and bb_position < 0.3:
                    logger.info(f"🟢 反转策略买入: RSI={rsi:.1f} < {RSI_OVERSOLD}, 布林带位置={bb_position:.2f} < 0.3")
                    signal = 'buy'
                
                # 特殊情况：RSI 极度超卖 (< 25) + Stoch RSI 极度超卖 (< 15)
                elif rsi < 25 and stoch_k < 15:
                    logger.info(f"🟢 反转策略买入(极度超卖): RSI={rsi:.1f}, Stoch RSI={stoch_k:.1f}")
                    signal = 'buy'
                
                else:
                    reason = f"🟡 无买入信号: RSI={rsi:.1f}, 布林带位置={bb_position:.2f}"
                    logger.info(reason)
            
            # === 卖出信号：逃顶 ===
            elif self.position is not None:
                # 条件1：RSI 超买 (> 65)
                # 条件2：价格接近布林带上轨 (bb_position > 0.7)
                if rsi > RSI_OVERBOUGHT and bb_position > 0.7:
                    logger.info(f"🔴 反转策略卖出: RSI={rsi:.1f} > {RSI_OVERBOUGHT}, 布林带位置={bb_position:.2f} > 0.7")
                    signal = 'sell'
                
                # 特殊情况：RSI 极度超买 (> 75) + Stoch RSI 极度超买 (> 85)
                elif rsi > 75 and stoch_k > 85:
                    logger.info(f"🔴 反转策略卖出(极度超买): RSI={rsi:.1f}, Stoch RSI={stoch_k:.1f}")
                    signal = 'sell'
                
                else:
                    reason = f"🟡 无卖出信号: RSI={rsi:.1f}, 布林带位置={bb_position:.2f}"
                    logger.info(reason)
            
            return signal
            
        except Exception as e:
            logger.error(f"策略运行失败: {e}")
            return 'hold'


# ==================== 回测引擎（简化版）====================
class SimpleBacktest:
    """简化版回测引擎"""
    
    def __init__(self, initial_balance: float = 100.0, symbol: str = "BTC/USDT"):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.symbol = symbol
        
        self.position = None
        self.entry_price = None
        self.entry_time = None
        self.highest_price = None
        
        self.trades = []
        self.balance_history = []
        
        logger.info(f"回测初始化: 初始资金={initial_balance} USDT, 交易对={symbol}")
    
    def buy(self, price: float, timestamp: datetime, fee_rate: float = 0.002):
        """买入"""
        if self.position is not None:
            return
        
        # 使用60%资金买入
        amount = (self.balance * 0.6) / price
        fee = amount * price * fee_rate
        
        self.balance -= (amount * price + fee)
        self.position = amount
        self.entry_price = price
        self.entry_time = timestamp
        self.highest_price = price
        
        self.trades.append({
            'type': 'buy',
            'timestamp': timestamp,
            'price': price,
            'amount': amount,
            'fee': fee,
            'balance': self.balance
        })
        
        logger.info(f"🟢 买入: {amount:.6f} @ {price:.2f}, 手续费={fee:.4f}")
    
    def sell(self, price: float, timestamp: datetime, reason: str, fee_rate: float = 0.002):
        """卖出"""
        if self.position is None:
            return
        
        revenue = self.position * price * (1 - fee_rate)
        profit = revenue - (self.position * self.entry_price)
        profit_pct = (price - self.entry_price) / self.entry_price * 100
        
        self.balance += revenue
        
        hold_duration = (timestamp - self.entry_time).total_seconds() / 60
        
        self.trades.append({
            'type': 'sell',
            'timestamp': timestamp,
            'price': price,
            'amount': self.position,
            'profit': profit,
            'profit_pct': profit_pct,
            'balance': self.balance,
            'reason': reason,
            'hold_duration': hold_duration
        })
        
        emoji = "📈" if profit >= 0 else "📉"
        logger.info(f"{emoji} 卖出 ({reason}): {self.position:.6f} @ {price:.2f}, "
                   f"盈亏={profit:+.4f} USDT ({profit_pct:+.2f}%)")
        
        self.position = None
        self.entry_price = None
        self.entry_time = None
        self.highest_price = None
    
    def record_balance(self, timestamp: datetime, current_price: float):
        """记录余额"""
        total_value = self.balance + (self.position * current_price if self.position else 0)
        self.balance_history.append({
            'timestamp': timestamp,
            'cash': self.balance,
            'total_value': total_value
        })
    
    def get_statistics(self) -> dict:
        """计算统计数据"""
        sell_trades = [t for t in self.trades if t['type'] == 'sell']
        
        if not sell_trades:
            return {'error': '无完整交易'}
        
        total_profit = sum([t['profit'] for t in sell_trades])
        total_profit_pct = total_profit / self.initial_balance * 100
        win_rate = len([t for t in sell_trades if t['profit'] > 0]) / len(sell_trades) * 100
        
        # 最大回撤
        peak = self.initial_balance
        max_drawdown = 0
        for record in self.balance_history:
            value = record['total_value']
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        return {
            'initial_balance': self.initial_balance,
            'final_balance': self.balance,
            'total_profit': total_profit,
            'total_profit_pct': total_profit_pct,
            'total_trades': len(sell_trades),
            'win_rate': win_rate,
            'max_drawdown': max_drawdown,
            'sell_trades': sell_trades
        }


# ==================== 主程序 ====================
def main():
    """运行回测"""
    symbol = "BTC/USDT"
    days = 7
    
    logger.info("=" * 60)
    logger.info(f"开始回测: {symbol}, 过去{days}天")
    logger.info("=" * 60)
    
    # 1. 获取历史数据
    logger.info("正在获取历史K线数据...")
    exchange = ccxt.gateio({
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })
    
    since = exchange.parse8601((datetime.now() - timedelta(days=days)).isoformat())
    ohlcv = exchange.fetch_ohlcv(symbol, '15m', since=since, limit=1000)
    
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    logger.info(f"获取到 {len(df)} 根K线")
    logger.info(f"时间范围: {df['timestamp'].iloc[0]} ~ {df['timestamp'].iloc[-1]}")
    
    # 2. 初始化回测引擎和策略
    engine = SimpleBacktest(initial_balance=100.0, symbol=symbol)
    strategy = SimpleStrategy()
    
    # 3. 逐根K线回测
    logger.info("开始回测...")
    
    for i in range(100, len(df)):  # 前100根用于计算指标
        current_df = df.iloc[:i+1]
        current_price = current_df['close'].iloc[-1]
        current_time = current_df['timestamp'].iloc[-1]
        
        # 运行策略
        signal = strategy.run(current_df)
        
        # 执行信号
        if signal == 'buy':
            engine.buy(current_price, current_time)
            strategy.position = engine.position
            strategy.entry_price = engine.entry_price
        
        elif signal in ['sell', 'sell_stop_loss', 'sell_take_profit', 'sell_trailing_stop']:
            reason = signal.replace('sell_', '')
            engine.sell(current_price, current_time, reason)
            strategy.position = None
            strategy.entry_price = None
            strategy.highest_price = None
        
        # 记录余额
        engine.record_balance(current_time, current_price)
    
    # 4. 回测结束，强制平仓
    if engine.position:
        final_price = df['close'].iloc[-1]
        final_time = df['timestamp'].iloc[-1]
        logger.info("回测结束，强制平仓...")
        engine.sell(final_price, final_time, 'backtest_end')
    
    # 5. 生成报告
    stats = engine.get_statistics()
    
    logger.info("=" * 60)
    logger.info("回测报告")
    logger.info("=" * 60)
    
    if 'error' in stats:
        logger.warning(f"回测失败: {stats['error']}")
        return
    
    logger.info(f"初始资金: {stats['initial_balance']:.2f} USDT")
    logger.info(f"最终资金: {stats['final_balance']:.2f} USDT")
    logger.info(f"总盈亏: {stats['total_profit']:+.4f} USDT ({stats['total_profit_pct']:+.2f}%)")
    logger.info(f"总交易次数: {stats['total_trades']}")
    logger.info(f"胜率: {stats['win_rate']:.2f}%")
    logger.info(f"最大回撤: {stats['max_drawdown']:.2f}%")
    
    # 保存交易记录
    trades_df = pd.DataFrame([t for t in engine.trades if t['type'] == 'sell'])
    if not trades_df.empty:
        trades_df.to_csv('backtest_trades.csv', index=False)
        logger.info("交易记录已保存到 backtest_trades.csv")
    
    # 保存余额历史
    balance_df = pd.DataFrame(engine.balance_history)
    balance_df.to_csv('backtest_balance.csv', index=False)
    logger.info("余额历史已保存到 backtest_balance.csv")
    
    logger.info("=" * 60)
    logger.info("回测完成！详细日志请查看 backtest.log")
    logger.info("=" * 60)
    
    # 打印简化报告
    print("\n" + "=" * 60)
    print("回测完成！")
    print("=" * 60)
    print(f"收益率: {stats['total_profit_pct']:+.2f}%")
    print(f"胜率: {stats['win_rate']:.2f}%")
    print(f"最大回撤: {stats['max_drawdown']:.2f}%")
    print(f"总交易次数: {stats['total_trades']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
