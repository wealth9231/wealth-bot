#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测系统 - 使用历史数据验证策略有效性
初始资金: 100 USDT
测试周期: 过去7天
"""

import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Tuple

# ==================== 配置部分 ====================
import os
from config import *

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

# ==================== 回测引擎 ====================
class BacktestEngine:
    """回测引擎 - 模拟交易"""
    
    def __init__(self, initial_balance: float = 100.0, symbol: str = "BTC/USDT"):
        """
        初始化回测引擎
        
        Args:
            initial_balance: 初始资金（USDT）
            symbol: 交易对
        """
        self.initial_balance = initial_balance
        self.balance = initial_balance  # 可用USDT
        self.symbol = symbol
        self.position = None  # 持仓数量
        self.entry_price = None  # 入场价格
        self.entry_time = None  # 入场时间
        
        # 交易记录
        self.trades: List[Dict] = []
        self.balance_history: List[Tuple[datetime, float, float]] = []  # (时间, 余额, 持仓市值)
        
        logger.info(f"回测引擎初始化: 初始资金={initial_balance} USDT, 交易对={symbol}")
    
    def buy(self, price: float, timestamp: datetime, regime: str):
        """
        买入
        
        Args:
            price: 买入价格
            timestamp: 买入时间
            regime: 市场状态
        """
        if self.position is not None:
            logger.warning(f"已有持仓，跳过买入")
            return
        
        # 使用60%资金买入
        amount = (self.balance * 0.6) / price
        
        # 考虑手续费（Gate.io 现货手续费 0.2%）
        fee = amount * price * 0.002
        self.balance -= (amount * price + fee)
        self.position = amount
        self.entry_price = price
        self.entry_time = timestamp
        
        trade = {
            'type': 'buy',
            'timestamp': timestamp,
            'price': price,
            'amount': amount,
            'fee': fee,
            'balance': self.balance,
            'regime': regime
        }
        self.trades.append(trade)
        
        logger.info(f"🟢 买入: {amount:.6f} @ {price:.2f}, 手续费={fee:.4f} USDT, 余额={self.balance:.2f}")
    
    def sell(self, price: float, timestamp: datetime, regime: str, reason: str = "normal"):
        """
        卖出
        
        Args:
            price: 卖出价格
            timestamp: 卖出时间
            regime: 市场状态
            reason: 卖出原因 (normal/stop_loss/take_profit/trailing_stop)
        """
        if self.position is None:
            logger.warning(f"无持仓，跳过卖出")
            return
        
        # 计算收益
        revenue = self.position * price
        fee = revenue * 0.002
        revenue -= fee
        
        profit = revenue - (self.position * self.entry_price)
        profit_pct = (price - self.entry_price) / self.entry_price * 100
        
        self.balance += revenue
        
        trade = {
            'type': 'sell',
            'timestamp': timestamp,
            'price': price,
            'amount': self.position,
            'fee': fee,
            'profit': profit,
            'profit_pct': profit_pct,
            'balance': self.balance,
            'regime': regime,
            'reason': reason,
            'hold_duration': (timestamp - self.entry_time).total_seconds() / 60  # 分钟
        }
        self.trades.append(trade)
        
        emoji = "📈" if profit >= 0 else "📉"
        logger.info(f"{emoji} 卖出 ({reason}): {self.position:.6f} @ {price:.2f}, "
                   f"盈亏={profit:+.4f} USDT ({profit_pct:+.2f}%), 余额={self.balance:.2f}")
        
        # 重置持仓
        self.position = None
        self.entry_price = None
        self.entry_time = None
    
    def calculate_total_value(self, current_price: float) -> float:
        """
        计算总资产价值
        
        Args:
            current_price: 当前价格
            
        Returns:
            总资产（USDT）
        """
        position_value = self.position * current_price if self.position else 0
        return self.balance + position_value
    
    def record_balance(self, timestamp: datetime, current_price: float):
        """
        记录余额历史
        
        Args:
            timestamp: 当前时间
            current_price: 当前价格
        """
        total_value = self.calculate_total_value(current_price)
        self.balance_history.append((timestamp, self.balance, total_value))
    
    def get_statistics(self) -> Dict:
        """
        计算回测统计数据
        
        Returns:
            统计字典
        """
        if not self.trades:
            return {'error': '无交易记录'}
        
        # 分离买入和卖出
        sell_trades = [t for t in self.trades if t['type'] == 'sell']
        
        if not sell_trades:
            return {'error': '无完整交易（只有买入）'}
        
        # 基础统计
        total_trades = len(sell_trades)
        profitable_trades = len([t for t in sell_trades if t['profit'] > 0])
        win_rate = profitable_trades / total_trades * 100
        
        total_profit = sum([t['profit'] for t in sell_trades])
        total_profit_pct = total_profit / self.initial_balance * 100
        
        # 计算最大回撤
        balance_values = [bh[2] for bh in self.balance_history]
        peak = balance_values[0]
        max_drawdown = 0
        for value in balance_values:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        # 平均持仓时间
        avg_hold_time = sum([t['hold_duration'] for t in sell_trades]) / len(sell_trades)
        
        # 按卖出原因分类
        reasons = {}
        for t in sell_trades:
            reason = t['reason']
            if reason not in reasons:
                reasons[reason] = {'count': 0, 'profit': 0}
            reasons[reason]['count'] += 1
            reasons[reason]['profit'] += t['profit']
        
        return {
            'initial_balance': self.initial_balance,
            'final_balance': self.balance,
            'total_profit': total_profit,
            'total_profit_pct': total_profit_pct,
            'total_trades': total_trades,
            'profitable_trades': profitable_trades,
            'win_rate': win_rate,
            'max_drawdown': max_drawdown,
            'avg_hold_time_minutes': avg_hold_time,
            'reasons': reasons
        }


# ==================== 策略封装（用于回测）====================
class StrategyForBacktest:
    """用于回测的策略封装"""
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.position = None
        self.entry_price = None
        self.highest_price = None
    
    def run(self, df: pd.DataFrame) -> str:
        """
        运行策略，返回信号
        
        Args:
            df: K线数据
            
        Returns:
            信号 ('buy', 'sell', 'hold')
        """
        try:
            # 1. 识别市场状态
            regime, indicators = MarketRegimeDetector.detect_market_regime(df)
            current_price = df['close'].iloc[-1]
            
            # 2. 检查止损
            if self.entry_price and self.position:
                loss_pct = (current_price - self.entry_price) / self.entry_price
                
                # 固定止损
                if loss_pct <= STOP_LOSS_PCT:
                    logger.info(f"触发止损: {loss_pct*100:.2f}%")
                    return 'sell_stop_loss'
                
                # 追踪止损
                if self.highest_price is None or current_price > self.highest_price:
                    self.highest_price = current_price
                
                drawdown = (current_price - self.highest_price) / self.highest_price
                if drawdown <= -0.02:
                    logger.info(f"触发追踪止损: 回撤={drawdown*100:.2f}%")
                    return 'sell_trailing_stop'
                
                # 止盈
                profit_pct = (current_price - self.entry_price) / self.entry_price
                if profit_pct >= TARGET_PROFIT_PCT:
                    logger.info(f"触发止盈: {profit_pct*100:.2f}%")
                    return 'sell_take_profit'
            
            # 3. 根据市场状态生成信号
            signal = 'hold'
            
            if regime in ['强势上涨', '趋势向上']:
                if self.position is None:
                    signal = 'buy'
            
            elif regime in ['强势下跌', '趋势向下']:
                if self.position is not None:
                    signal = 'sell'
            
            elif regime == '震荡市':
                # 网格策略
                upper, middle, lower = TechnicalIndicators.calculate_bollinger_bands(df)
                grid_spacing = (upper.iloc[-1] - lower.iloc[-1]) / GRID_NUM
                grid_level = (current_price - lower.iloc[-1]) / grid_spacing
                
                if grid_level < GRID_NUM * 0.4 and self.position is None:
                    signal = 'buy'
                elif grid_level > GRID_NUM * 0.6 and self.position is not None:
                    signal = 'sell'
            
            elif regime == '反转信号_超卖':
                if self.position is None:
                    signal = 'buy'
            
            elif regime == '反转信号_超买':
                if self.position is not None:
                    signal = 'sell'
            
            return signal
            
        except Exception as e:
            logger.error(f"策略运行失败: {e}")
            return 'hold'


# ==================== 主回测程序 ====================
def run_backtest(symbol: str = "BTC/USDT", days: int = 7):
    """
    运行回测
    
    Args:
        symbol: 交易对
        days: 回测天数
    """
    logger.info("=" * 60)
    logger.info(f"开始回测: {symbol}, 过去{days}天")
    logger.info("=" * 60)
    
    # 1. 初始化交易所API（只用于获取历史数据）
    exchange = ccxt.gateio({
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })
    
    # 2. 获取历史数据
    logger.info(f"获取 {symbol} 过去{days}天的15分钟K线数据...")
    since = exchange.parse8601((datetime.now() - timedelta(days=days)).isoformat())
    ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, since=since, limit=1000)
    
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    logger.info(f"获取到 {len(df)} 根K线，时间范围: {df['timestamp'].iloc[0]} ~ {df['timestamp'].iloc[-1]}")
    
    # 3. 初始化回测引擎和策略
    engine = BacktestEngine(initial_balance=100.0, symbol=symbol)
    strategy = StrategyForBacktest(symbol)
    
    # 4. 逐根K线回测
    logger.info("开始回测...")
    
    for i in range(100, len(df)):  # 前100根用于计算技术指标
        # 当前K线数据
        current_df = df.iloc[:i+1]
        current_price = current_df['close'].iloc[-1]
        current_time = current_df['timestamp'].iloc[-1]
        
        # 运行策略
        signal = strategy.run(current_df)
        
        # 执行信号
        if signal == 'buy':
            engine.buy(current_price, current_time, 'unknown')  # 简化，不传regime
            strategy.position = engine.position
            strategy.entry_price = engine.entry_price
        
        elif signal in ['sell', 'sell_stop_loss', 'sell_take_profit', 'sell_trailing_stop']:
            reason = signal.replace('sell_', '')
            engine.sell(current_price, current_time, 'unknown', reason)
            strategy.position = None
            strategy.entry_price = None
            strategy.highest_price = None
        
        # 记录余额
        engine.record_balance(current_time, current_price)
    
    # 5. 回测结束，强制平仓（如果还有持仓）
    if engine.position:
        final_price = df['close'].iloc[-1]
        final_time = df['timestamp'].iloc[-1]
        logger.info(f"回测结束，强制平仓...")
        engine.sell(final_price, final_time, 'unknown', 'backtest_end')
    
    # 6. 生成统计报告
    stats = engine.get_statistics()
    
    logger.info("=" * 60)
    logger.info("回测报告")
    logger.info("=" * 60)
    logger.info(f"初始资金: {stats['initial_balance']:.2f} USDT")
    logger.info(f"最终资金: {stats['final_balance']:.2f} USDT")
    logger.info(f"总盈亏: {stats['total_profit']:+.4f} USDT ({stats['total_profit_pct']:+.2f}%)")
    logger.info(f"总交易次数: {stats['total_trades']}")
    logger.info(f"盈利交易: {stats['profitable_trades']}")
    logger.info(f"胜率: {stats['win_rate']:.2f}%")
    logger.info(f"最大回撤: {stats['max_drawdown']:.2f}%")
    logger.info(f"平均持仓时间: {stats['avg_hold_time_minutes']:.1f} 分钟")
    
    logger.info("\n按卖出原因分类:")
    for reason, data in stats['reasons'].items():
        logger.info(f"  {reason}: {data['count']}次, 盈亏={data['profit']:+.4f} USDT")
    
    logger.info("=" * 60)
    
    # 7. 保存交易记录到CSV
    trades_df = pd.DataFrame([t for t in engine.trades if t['type'] == 'sell'])
    if not trades_df.empty:
        trades_df.to_csv('backtest_trades.csv', index=False)
        logger.info(f"交易记录已保存到 backtest_trades.csv")
    
    # 8. 保存余额历史到CSV
    balance_df = pd.DataFrame(engine.balance_history, columns=['timestamp', 'cash', 'total_value'])
    balance_df.to_csv('backtest_balance.csv', index=False)
    logger.info(f"余额历史已保存到 backtest_balance.csv")
    
    return stats


if __name__ == "__main__":
    # 运行回测
    stats = run_backtest(symbol="BTC/USDT", days=7)
    
    # 打印简化报告
    print("\n" + "=" * 60)
    print("回测完成！")
    print("=" * 60)
    print(f"收益率: {stats['total_profit_pct']:+.2f}%")
    print(f"胜率: {stats['win_rate']:.2f}%")
    print(f"最大回撤: {stats['max_drawdown']:.2f}%")
    print(f"详细报告请查看 backtest.log")
    print("=" * 60)
