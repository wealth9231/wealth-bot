#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本 - 测试Telegram通知、多交易对支持和原有功能
"""

# 导入修改后的配置和类
import sys
sys.path.insert(0, '/workspace')

from gate_trading_bot import (
    GATE_API_KEY, GATE_SECRET, SYMBOLS, TIMEFRAME,
    TELEGRAM_ENABLED, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    ExchangeAPI, MarketRegimeDetector, TechnicalIndicators,
    TelegramNotifier, TradingStrategy
)
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_api_connection():
    """测试API连接"""
    print("\n" + "="*50)
    print("测试1: API连接")
    print("="*50)
    
    try:
        api = ExchangeAPI(GATE_API_KEY, GATE_SECRET)
        print("✅ ExchangeAPI 初始化成功")
        
        # 测试获取余额
        balance = api.get_balance()
        if balance:
            print(f"✅ 获取余额成功")
            print(f"   USDT余额: {balance.get('USDT', {}).get('free', 0)}")
            print(f"   BTC余额: {balance.get('BTC', {}).get('free', 0)}")
        else:
            print("❌ 获取余额失败")
            return False
        
        # 测试获取K线数据（第一个交易对）
        test_symbol = SYMBOLS[0]
        df = api.fetch_ohlcv(test_symbol, TIMEFRAME, limit=100)
        if not df.empty:
            print(f"✅ 获取K线数据成功 ({test_symbol})")
            print(f"   数据条数: {len(df)}")
            print(f"   最新价格: {df['close'].iloc[-1]}")
        else:
            print(f"❌ 获取K线数据失败 ({test_symbol})")
            return False
        
        return api, df
        
    except Exception as e:
        print(f"❌ API连接测试失败: {e}")
        return False

def test_technical_indicators(df):
    """测试技术指标计算"""
    print("\n" + "="*50)
    print("测试2: 技术指标计算")
    print("="*50)
    
    try:
        # 计算ADX
        adx = TechnicalIndicators.calculate_adx(df)
        print(f"✅ ADX计算成功: 最新值 = {adx.iloc[-1]:.2f}")
        
        # 计算RSI
        rsi = TechnicalIndicators.calculate_rsi(df)
        print(f"✅ RSI计算成功: 最新值 = {rsi.iloc[-1]:.2f}")
        
        # 计算EMA
        ema20 = TechnicalIndicators.calculate_ema(df, 20)
        ema50 = TechnicalIndicators.calculate_ema(df, 50)
        print(f"✅ EMA计算成功: EMA20 = {ema20.iloc[-1]:.2f}, EMA50 = {ema50.iloc[-1]:.2f}")
        
        # 计算布林带宽度
        bb_width = TechnicalIndicators.calculate_bb_width(df)
        print(f"✅ 布林带宽度计算成功: 最新值 = {bb_width.iloc[-1]:.4f}")
        
        return True
        
    except Exception as e:
        print(f"❌ 技术指标计算失败: {e}")
        return False

def test_market_regime_detection(df):
    """测试市场状态识别"""
    print("\n" + "="*50)
    print("测试3: 市场状态识别")
    print("="*50)
    
    try:
        regime, indicators = MarketRegimeDetector.detect_market_regime(df)
        
        print(f"✅ 市场状态识别成功")
        print(f"   当前市场状态: {regime}")
        print(f"   技术指标详情:")
        for key, value in indicators.items():
            print(f"     - {key}: {value}")
        
        return regime, indicators
        
    except Exception as e:
        print(f"❌ 市场状态识别失败: {e}")
        return False, False

def test_telegram_notifier():
    """测试Telegram通知功能"""
    print("\n" + "="*50)
    print("测试4: Telegram通知功能")
    print("="*50)
    
    if not TELEGRAM_ENABLED:
        print("⚠️  Telegram通知未启用，跳过测试")
        return True
    
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        print("⚠️  Telegram Bot Token未配置，跳过测试")
        return True
    
    try:
        notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED)
        print("✅ TelegramNotifier 初始化成功")
        
        # 发送测试消息
        test_message = "🧪 <b>测试消息</b>\n这是一条测试通知\n时间: " + __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        result = notifier.send_message(test_message)
        
        if result:
            print("✅ Telegram测试消息发送成功")
            print("   请检查你的Telegram是否收到消息")
        else:
            print("❌ Telegram测试消息发送失败")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Telegram通知测试失败: {e}")
        return False

def test_multi_symbol_support(api):
    """测试多交易对支持"""
    print("\n" + "="*50)
    print("测试5: 多交易对支持")
    print("="*50)
    
    try:
        # 测试为每个交易对创建策略实例
        strategies = {}
        for symbol in SYMBOLS:
            df = api.fetch_ohlcv(symbol, TIMEFRAME, limit=100)
            if df.empty:
                print(f"❌ {symbol} 获取K线数据失败")
                continue
            
            strategies[symbol] = TradingStrategy(api, symbol)
            print(f"✅ {symbol} 策略实例创建成功")
        
        if len(strategies) == 0:
            print("❌ 所有交易对初始化失败")
            return False
        
        print(f"\n✅ 成功初始化 {len(strategies)}/{len(SYMBOLS)} 个交易对")
        return True
        
    except Exception as e:
        print(f"❌ 多交易对支持测试失败: {e}")
        return False

def test_position_info(api):
    """测试持仓信息获取"""
    print("\n" + "="*50)
    print("测试6: 持仓信息")
    print("="*50)
    
    try:
        position = api.get_position(SYMBOLS[0])
        print(f"✅ 持仓信息获取成功")
        print(f"   BTC持仓: {position.get('base_amount', 0)}")
        print(f"   USDT余额: {position.get('quote_amount', 0)}")
        
        return position
        
    except Exception as e:
        print(f"❌ 持仓信息获取失败: {e}")
        return False

def main():
    """主测试函数"""
    print("\n" + "🚀"*25)
    print("Gate.io 量化交易机器人 - 功能测试")
    print("🚀"*25)
    print("\n⚠️  这是测试模式，不会实际执行交易")
    print("⚠️  测试以下功能:")
    print("   1. API连接")
    print("   2. 技术指标计算")
    print("   3. 市场状态识别")
    print("   4. Telegram通知（如已配置）")
    print("   5. 多交易对支持")
    print("   6. 持仓信息\n")
    
    # 测试1: API连接
    result = test_api_connection()
    if not result:
        print("\n❌ API连接测试失败，请检查API密钥是否正确")
        return
    
    api, df = result
    
    # 测试2: 技术指标计算
    if not test_technical_indicators(df):
        print("\n❌ 技术指标计算失败")
        return
    
    # 测试3: 市场状态识别
    regime, indicators = test_market_regime_detection(df)
    if not regime:
        print("\n❌ 市场状态识别失败")
        return
    
    # 测试4: Telegram通知
    if not test_telegram_notifier():
        print("\n⚠️  Telegram通知测试失败，但可以继续")
    
    # 测试5: 多交易对支持
    if not test_multi_symbol_support(api):
        print("\n❌ 多交易对支持测试失败")
        return
    
    # 测试6: 持仓信息
    position = test_position_info(api)
    
    # 总结
    print("\n" + "="*50)
    print("✅ 所有测试完成！")
    print("="*50)
    print(f"\n当前市场状态: {regime}")
    print(f"当前价格: {indicators.get('current_price', 'N/A')} USDT")
    print(f"你的持仓: {position.get('base_amount', 0) if position else 'N/A'} BTC")
    print(f"\n📋 已启用的功能:")
    print(f"   ✅ Telegram通知: {'已启用' if TELEGRAM_ENABLED else '未启用'}")
    print(f"   ✅ 多交易对支持: {len(SYMBOLS)}个 ({', '.join(SYMBOLS)})")
    print(f"\n💡 如果一切正常，可以运行正式脚本:")
    print(f"   python3 gate_trading_bot.py")
    print(f"\n⚠️  正式运行前，请确保:")
    print(f"   1. 已充分理解策略逻辑")
    print(f"   2. 已设置好止损和仓位管理")
    print(f"   3. 先使用小资金测试")
    print(f"   4. 监控日志输出: tail -f trading_bot.log")
    print(f"   5. 如需启用Telegram通知，请配置:")
    print(f"      - TELEGRAM_BOT_TOKEN")
    print(f"      - TELEGRAM_CHAT_ID\n")

if __name__ == "__main__":
    main()
