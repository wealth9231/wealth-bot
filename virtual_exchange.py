#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
虚拟交易所 API（模拟 Gate.io）

功能：
1. 模拟下单（市价/限价）
2. 模拟余额管理
3. 记录交易历史
4. 计算收益统计
"""

import time
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class VirtualExchangeAPI:
    """
    虚拟交易所 API（兼容 ccxt 接口）
    
    使用方式：
    api = VirtualExchangeAPI(initial_usdt=1000)
    api.create_order('BTC/USDT', 'market', 'buy', 0.001)
    balance = api.fetch_balance()
    """
    
    def __init__(self, initial_usdt: float = 1000, fee_rate: float = 0.001):
        """
        初始化虚拟交易所
        
        Args:
            initial_usdt: 初始 USDT 余额（默认 $1000）
            fee_rate: 手续费率（默认 0.1%，与 Gate.io 一致）
        """
        self.initial_usdt = initial_usdt
        self.fee_rate = fee_rate
        
        # 余额结构（兼容 ccxt）
        # free: 可用, used: 冻结, total: 总计
        self.balance = {
            'USDT': {'free': initial_usdt, 'used': 0.0, 'total': initial_usdt},
            'BTC': {'free': 0.0, 'used': 0.0, 'total': 0.0},
            'ETH': {'free': 0.0, 'used': 0.0, 'total': 0.0},
            'SOL': {'free': 0.0, 'used': 0.0, 'total': 0.0},
            'BNB': {'free': 0.0, 'used': 0.0, 'total': 0.0},
            'DOGE': {'free': 0.0, 'used': 0.0, 'total': 0.0},
            'TRX': {'free': 0.0, 'used': 0.0, 'total': 0.0},
        }
        
        # 委托单列表
        self.orders = {}
        self.order_id_counter = 1000000
        
        # 交易历史
        self.trade_history = []
        
        # 持仓成本（用于计算盈亏）
        self.position_cost = {}  # {symbol: total_cost}
        self.position_amount = {}  # {symbol: total_amount}
        
        logger.info(f"🎯 虚拟交易所初始化: ${initial_usdt:.2f} USDT")
    
    def _get_base_currency(self, symbol: str) -> str:
        """获取基础币种（如 BTC/USDT → BTC）"""
        return symbol.split('/')[0]
    
    def _get_quote_currency(self, symbol: str) -> str:
        """获取计价币种（如 BTC/USDT → USDT）"""
        return symbol.split('/')[1]
    
    def fetch_ticker(self, symbol: str) -> Dict:
        """
        获取 ticker（从 ccxt 获取真实价格）
        
        注意：这个方法需要外部传入价格，或者连接到真实 ccxt
        这里先返回模拟数据，实际使用时会从真实交易所获取价格
        """
        # 实际使用时，会从真实 ccxt 获取价格
        # 这里返回模拟数据结构（兼容 ccxt）
        return {
            'symbol': symbol,
            'last': 0.0,  # 需要外部设置
            'bid': 0.0,
            'ask': 0.0,
            'volume': 0.0,
        }
    
    def set_market_price(self, symbol: str, price: float):
        """
        设置模拟市场价格（用于回测）
        
        实际使用中，会从真实交易所获取价格，不需要手动设置
        """
        self._current_price = getattr(self, '_current_price', {})
        self._current_price[symbol] = price
    
    def fetch_balance(self, account_type: str = 'spot') -> Dict:
        """
        查询余额（兼容 ccxt 接口）
        
        Args:
            account_type: 账户类型（'spot'/'funding' 等，虚拟环境只支持 'spot'）
        
        Returns:
            余额字典（兼容 ccxt 格式）
        """
        return self.balance
    
    def create_order(self, symbol: str, order_type: str, side: str, 
                    amount: float, price: Optional[float] = None) -> Dict:
        """
        创建订单（模拟下单）
        
        Args:
            symbol: 交易对（如 'BTC/USDT'）
            order_type: 订单类型（'market'/'limit'）
            side: 方向（'buy'/'sell'）
            amount: 数量
            price: 价格（限价单需要）
        
        Returns:
            订单字典（兼容 ccxt 格式）
        """
        try:
            base = self._get_base_currency(symbol)
            quote = self._get_quote_currency(symbol)
            
            # 获取当前价格（从外部设置或模拟）
            current_price = getattr(self, '_current_price', {}).get(symbol, 0.0)
            if current_price == 0.0:
                logger.warning(f"⚠️ {symbol} 价格未设置，无法模拟成交")
                return {}
            
            # 市价单：用当前价成交
            if order_type == 'market':
                fill_price = current_price
            # 限价单：检查是否能成交
            elif order_type == 'limit':
                if price is None:
                    logger.error(f"❌ 限价单必须指定价格")
                    return {}
                fill_price = price
                # 简单模拟：如果限价单价格接近市价，就成交
                if side == 'buy' and fill_price > current_price * 1.02:
                    logger.info(f"🔄 限价买单价格过高，等待成交...")
                    return {'id': self._next_order_id(), 'status': 'open'}
                if side == 'sell' and fill_price < current_price * 0.98:
                    logger.info(f"🔄 限价卖单价格过低，等待成交...")
                    return {'id': self._next_order_id(), 'status': 'open'}
            else:
                logger.error(f"❌ 不支持的订单类型: {order_type}")
                return {}
            
            # 计算交易金额和手续费
            if side == 'buy':
                cost = amount * fill_price
                fee = cost * self.fee_rate
                
                # 检查 USDT 余额
                if self.balance[quote]['free'] < cost + fee:
                    logger.error(f"❌ 余额不足: 需要 ${cost + fee:.2f}, 可用 ${self.balance[quote]['free']:.2f}")
                    return {}
                
                # 更新余额
                self.balance[quote]['free'] -= (cost + fee)
                self.balance[quote]['used'] += 0  # 市价单不冻结
                
                # 更新持仓
                self.balance[base]['free'] += amount
                self.balance[base]['total'] = self.balance[base]['free'] + self.balance[base]['used']
                
                # 更新持仓成本和数量
                if base not in self.position_cost:
                    self.position_cost[base] = 0.0
                    self.position_amount[base] = 0.0
                self.position_cost[base] += cost
                self.position_amount[base] += amount
                
                logger.info(f"🎯 虚拟买入: {amount:.6f} {symbol} @ ${fill_price:.2f}, 成本 ${cost:.2f}, 手续费 ${fee:.2f}")
                
            elif side == 'sell':
                # 检查持仓
                if self.balance[base]['free'] < amount:
                    logger.error(f"❌ 持仓不足: 需要 {amount:.6f} {base}, 可用 {self.balance[base]['free']:.6f}")
                    return {}
                
                revenue = amount * fill_price
                fee = revenue * self.fee_rate
                
                # 更新余额
                self.balance[base]['free'] -= amount
                self.balance[base]['total'] = self.balance[base]['free'] + self.balance[base]['used']
                
                self.balance[quote]['free'] += (revenue - fee)
                
                # 计算盈亏
                if base in self.position_cost and self.position_amount[base] > 0:
                    avg_cost = self.position_cost[base] / self.position_amount[base]
                    profit = (fill_price - avg_cost) * amount
                    profit_pct = (fill_price - avg_cost) / avg_cost * 100
                    
                    # 更新持仓成本和数量
                    self.position_cost[base] -= (avg_cost * amount)
                    self.position_amount[base] -= amount
                    
                    logger.info(f"🎯 虚拟卖出: {amount:.6f} {symbol} @ ${fill_price:.2f}, 盈亏 ${profit:+.2f} ({profit_pct:+.2f}%), 手续费 ${fee:.2f}")
                else:
                    logger.warning(f"⚠️ 无法计算盈亏: {base} 持仓成本未知")
                    profit = 0.0
                    profit_pct = 0.0
                
                # 记录交易历史
                trade = {
                    'timestamp': datetime.now().isoformat(),
                    'symbol': symbol,
                    'side': side,
                    'amount': amount,
                    'price': fill_price,
                    'revenue': revenue,
                    'fee': fee,
                    'profit': profit if side == 'sell' else 0.0,
                    'profit_pct': profit_pct if side == 'sell' else 0.0,
                }
                self.trade_history.append(trade)
            
            # 返回订单信息（兼容 ccxt）
            order_id = self._next_order_id()
            order = {
                'id': order_id,
                'symbol': symbol,
                'type': order_type,
                'side': side,
                'amount': amount,
                'price': fill_price,
                'status': 'closed',  # 市价单立即成交
                'filled': amount,
                'remaining': 0.0,
                'average': fill_price,
            }
            
            logger.info(f"✅ 虚拟订单已成交: ID={order_id}")
            return order
            
        except Exception as e:
            logger.error(f"❌ 创建虚拟订单失败: {e}")
            return {}
    
    def _next_order_id(self) -> str:
        """生成下一个订单 ID"""
        self.order_id_counter += 1
        return str(self.order_id_counter)
    
    def fetch_order(self, order_id: str, symbol: str = None) -> Dict:
        """查询订单（虚拟环境，订单立即成交，直接返回 closed）"""
        return {'id': order_id, 'status': 'closed'}
    
    def fetch_open_orders(self, symbol: str = None) -> List:
        """查询未成交委托（虚拟环境，市价单立即成交，返回空列表）"""
        return []
    
    def cancel_order(self, order_id: str, symbol: str = None) -> bool:
        """取消订单（虚拟环境，订单立即成交，无需取消）"""
        logger.info(f"🔄 虚拟取消订单: ID={order_id}")
        return True
    
    def get_trade_statistics(self) -> Dict:
        """
        获取交易统计
        
        Returns:
            统计字典（总收益、胜率、交易次数等）
        """
        if not self.trade_history:
            return {
                'total_trades': 0,
                'profitable_trades': 0,
                'win_rate': 0.0,
                'total_profit': 0.0,
                'total_profit_pct': 0.0,
                'current_balance': self.balance['USDT']['free'],
            }
        
        # 计算统计
        total_trades = len([t for t in self.trade_history if t['side'] == 'sell'])
        profitable_trades = len([t for t in self.trade_history if t['side'] == 'sell' and t['profit'] > 0])
        win_rate = (profitable_trades / total_trades * 100) if total_trades > 0 else 0.0
        
        total_profit = sum([t['profit'] for t in self.trade_history if t['side'] == 'sell'])
        current_balance = self.balance['USDT']['free'] + self.balance['USDT']['used']
        total_profit_pct = (current_balance - self.initial_usdt) / self.initial_usdt * 100
        
        return {
            'total_trades': total_trades,
            'profitable_trades': profitable_trades,
            'win_rate': win_rate,
            'total_profit': total_profit,
            'total_profit_pct': total_profit_pct,
            'current_balance': current_balance,
            'initial_balance': self.initial_usdt,
        }
    
    def print_statistics(self):
        """打印交易统计（格式化输出）"""
        stats = self.get_trade_statistics()
        
        print("\n" + "=" * 50)
        print("🎯 虚拟交易统计")
        print("=" * 50)
        print(f"初始资金: ${stats['initial_balance']:.2f}")
        print(f"当前资金: ${stats['current_balance']:.2f}")
        print(f"总收益: ${stats['total_profit']:+.2f} ({stats['total_profit_pct']:+.2f}%)")
        print(f"交易次数: {stats['total_trades']}")
        print(f"盈利次数: {stats['profitable_trades']}")
        print(f"胜率: {stats['win_rate']:.1f}%")
        print("=" * 50 + "\n")
        
        logger.info(f"🎯 虚拟交易统计: 初始=${stats['initial_balance']:.2f}, 当前=${stats['current_balance']:.2f}, 收益=${stats['total_profit']:+.2f} ({stats['total_profit_pct']:+.2f}%)")
    
    def reset(self):
        """重置虚拟交易所（清空所有余额和交易记录）"""
        self.__init__(self.initial_usdt, self.fee_rate)
        logger.info(f"🔄 虚拟交易所已重置: ${self.initial_usdt:.2f} USDT")


# ==================== 测试代码 ====================
if __name__ == '__main__':
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # 创建虚拟交易所
    api = VirtualExchangeAPI(initial_usdt=1000)
    
    # 模拟设置市场价格
    api.set_market_price('BTC/USDT', 80000.0)
    api.set_market_price('ETH/USDT', 2000.0)
    api.set_market_price('DOGE/USDT', 0.10)
    
    # 测试买入
    print("\n--- 测试买入 ---")
    api.create_order('BTC/USDT', 'market', 'buy', 0.001)
    api.create_order('DOGE/USDT', 'market', 'buy', 1000)
    
    # 价格上涨
    print("\n--- 价格上涨 ---")
    api.set_market_price('BTC/USDT', 82000.0)  # +2.5%
    api.set_market_price('DOGE/USDT', 0.105)    # +5%
    
    # 测试卖出
    print("\n--- 测试卖出 ---")
    api.create_order('BTC/USDT', 'market', 'sell', 0.001)
    api.create_order('DOGE/USDT', 'market', 'sell', 1000)
    
    # 打印统计
    api.print_statistics()
    
    # 查看余额
    print("--- 最终余额 ---")
    balance = api.fetch_balance()
    for currency, data in balance.items():
        if data['total'] > 0:
            print(f"{currency}: 可用={data['free']:.6f}, 冻结={data['used']:.6f}, 总计={data['total']:.6f}")
