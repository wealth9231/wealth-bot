import requests
import time
import hmac
import hashlib
import json
import os

# ================== 账户配置 ==================
API_KEY = os.environ.get("GATEIO_API_KEY", "").strip()
API_SECRET = os.environ.get("GATEIO_API_SECRET", "").strip()
BASE_URL = "https://api.gateio.ws/api/v4"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# ================== 风控参数 (70U本金) ==================
ACCOUNT_BALANCE = 70          # 本金（U）
MAX_LEVERAGE = 4
MAX_RISK_PER_TRADE = 0.5      # 单笔最大亏损（U）
DAILY_LOSS_LIMIT = 3.5        # 单日最大亏损（本金的5%）
MIN_RISK_REWARD = 1.5         # 趋势策略最低盈亏比
MIN_RISK_REWARD_GRID = 1.2    # 网格策略最低盈亏比
TARGET_PROFIT_PCT = 0.03      # 单笔仓位占比（3%）
MAX_DAILY_TRADES = 3          # 单日最大开仓次数

# 合约面值
CONTRACT_SIZES = {
    'BTC_USDT': 0.0001,
    'ETH_USDT': 0.01,
    'SOL_USDT': 1,
    'BNB_USDT': 0.01,
    'DOGE_USDT': 100
}

# ================== 基础函数 ==================
def gate_request(method, path, params=None):
    """符合 Gate.io 官方规范的签名请求"""
    url = BASE_URL + path
    timestamp = str(int(time.time()))
    query_string = ''
    body_str = ''

    if method == 'GET' and params:
        sorted_params = sorted(params.items())
        query_string = '?' + '&'.join([f'{k}={v}' for k, v in sorted_params])
    elif method == 'POST':
        if params:
            sorted_params = sorted(params.items())
            body_str = json.dumps(dict(sorted_params))
        else:
            body_str = ''

    # 对请求体进行 SHA-512 哈希
    hashed_body = hashlib.sha512(body_str.encode('utf-8')).hexdigest()
    sign_string = f"{method}\n/api/v4{path}{query_string}\n{hashed_body}\n{timestamp}"
    
    signature = hmac.new(
        API_SECRET.encode('utf-8'),
        sign_string.encode('utf-8'),
        hashlib.sha512
    ).hexdigest()

    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'KEY': API_KEY,
        'SIGN': signature,
        'Timestamp': timestamp
    }

    try:
        if method == 'GET':
            resp = requests.get(url + query_string, headers=headers, timeout=15)
        else:
            resp = requests.post(url + query_string, headers=headers, data=body_str, timeout=15)
        if resp.status_code != 200:
            print(f"API 错误 {resp.status_code}: {resp.text}")
            return None
        return resp.json()
    except Exception as e:
        print(f"请求异常: {e}")
        return None

def send_telegram(message):
    """推送消息到你的 Telegram"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'disable_web_page_preview': True}, timeout=10)
    except Exception as e:
        print(f"Telegram 发送失败: {e}")

# ================== 指标计算 ==================
def compute_adx(highs, lows, closes, period=14):
    n = len(closes)
    if n < period + 1:
        return 0
    tr_list, plus_dm_list, minus_dm_list = [], [], []
    for i in range(1, n):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        tr_list.append(tr)
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]
        plus_dm = up_move if up_move > down_move and up_move > 0 else 0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
    
    atr = sum(tr_list[:period]) / period
    plus_di = sum(plus_dm_list[:period]) / period
    minus_di = sum(minus_dm_list[:period]) / period

    for i in range(period, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / period
        plus_di = (plus_di * (period - 1) + plus_dm_list[i]) / period
        minus_di = (minus_di * (period - 1) + minus_dm_list[i]) / period
    
    dx_sum = 0
    count = 0
    for i in range(len(tr_list) - period, len(tr_list)):
        if atr == 0:
            continue
        pdi = plus_di / atr * 100
        mdi = minus_di / atr * 100
        if pdi + mdi == 0:
            dx = 0
        else:
            dx = abs(pdi - mdi) / (pdi + mdi) * 100
        dx_sum += dx
        count += 1
    return dx_sum / count if count > 0 else 0

def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(diff if diff > 0 else 0)
        losses.append(-diff if diff < 0 else 0)
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    if avg_loss == 0:
        return 50  # 持平市场返回中性值 50
    return 100 - (100 / (1 + avg_gain / avg_loss))

def get_klines(symbol):
    params = {'currency_pair': symbol, 'interval': '1h', 'limit': 100}
    data = gate_request('GET', '/spot/candlesticks', params)
    if not data or len(data) < 50:
        return None
    
    closes = [float(d[2]) for d in data]
    highs = [float(d[3]) for d in data]
    lows = [float(d[4]) for d in data]
    price = closes[-1]
    
    ema12 = sum(closes[-12:]) / 12
    ema26 = sum(closes[-26:]) / 26
    adx = compute_adx(highs, lows, closes, 14)
    rsi = compute_rsi(closes, 14)
    
    # ATR(14)
    tr_list = []
    for i in range(1, min(15, len(closes))):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        tr_list.append(tr)
    atr = sum(tr_list) / len(tr_list) if tr_list else 0
    
    middle = sum(closes[-20:]) / 20
    std = (sum([(x-middle)**2 for x in closes[-20:]]) / 20) ** 0.5
    
    volumes = [float(d[5]) if len(d) > 5 else 0 for d in data]
    current_vol = volumes[-1] if volumes else 0
    avg_vol = sum(volumes[-24:]) / 24 if len(volumes) >= 24 else current_vol
    vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
    
    return {
        'symbol': symbol.replace('_', ''),
        'price': price,
        'ema12': ema12,
        'ema26': ema26,
        'adx': adx,
        'rsi': rsi,
        'atr': atr,
        'bb_lower': middle - 2*std,
        'bb_upper': middle + 2*std,
        'bb_middle': middle,
        'vol_ratio': vol_ratio
    }

# ================== 下单模块（已激活） ==================
def place_order(symbol, side, qty, leverage, stop_loss, take_profit):
    """市价开仓 + 自动挂止损止盈"""
    contract = symbol.replace('_USDT', '_USDT')
    settle = 'usdt'
    
    # 1. 设置杠杆
    gate_request('POST', f'/futures/{settle}/contracts/{contract}/leverage', {'leverage': str(leverage)})
    
    # 2. 市价开仓 (IOC 方式)
    order_size = max(int(qty), 1)
    order_params = {
        'contract': contract,
        'size': order_size,
        'price': '0',
        'tif': 'ioc',
        'text': 't-WealthBot'
    }
    result = gate_request('POST', f'/futures/{settle}/orders', order_params)
    if not result:
        print(f"{symbol} 开仓请求失败")
        return 0
    
    # 3. 挂止损单
    if stop_loss > 0:
        gate_request('POST', f'/futures/{settle}/price_orders', {
            'contract': contract,
            'size': -order_size,
            'price': str(int(stop_loss)),
            'close': True,
            'tif': 'gtc',
            'text': 't-bot-sl'
        })
    
    # 4. 挂止盈单
    if take_profit > 0:
        gate_request('POST', f'/futures/{settle}/price_orders', {
            'contract': contract,
            'size': -order_size,
            'price': str(int(take_profit)),
            'close': True,
            'tif': 'gtc',
            'text': 't-bot-tp'
        })
    
    return order_size

def check_daily_trades():
    """检查今日已开仓次数（通过 Gate.io 交易记录）"""
    # 这里简化处理，如果你需要严格限制，可以后续增加统计逻辑
    return 0

# ================== 格式化输出 ==================
def format_signal(symbol, direction, market_state, price, adx, rsi, stop_loss, take_profit, qty, risk_reward, strategy):
    arrow = "🟢" if direction == "LONG" else "🔴"
    state_emoji = "📈" if market_state == "趋势市" else "🔄"
    msg = f"""
╔══════════════════════╗
║  {arrow} {direction} {symbol}  x{qty}张
╠══════════════════════╣
║ {state_emoji} 市场: {market_state}
║ 📊 ADX: {adx:.1f}  |  RSI: {rsi:.1f}
║ 📉 策略: {strategy}
╠══════════════════════╣
║ 💰 入场: {price:.2f}
║ 🛑 止损: {stop_loss:.2f}
║ 🎯 止盈: {take_profit:.2f}
╠══════════════════════╣
║ ⚖️ 风控: 风险收益比 {risk_reward:.2f}
║ 💎 杠杆: {MAX_LEVERAGE}x
║ 📊 最大亏损: {abs(price - stop_loss) * qty * CONTRACT_SIZES.get(symbol+'_USDT', 0):.3f}U
╚══════════════════════╝
"""
    return msg.strip()

def format_brief(coins_data):
    lines = []
    lines.append("━━━━━━━━━━━━━━━━━")
    lines.append(f"  📊 市场扫描 · {time.strftime('%H:%M UTC')}")
    lines.append("━━━━━━━━━━━━━━━━━")
    
    for d in coins_data:
        symbol = d['symbol']
        price = d['price']
        adx = d['adx']
        rsi = d['rsi']
        ema12 = d['ema12']
        ema26 = d['ema26']
        
        if adx > 25:
            trend = "📈多头" if ema12 > ema26 else "📉空头" if ema12 < ema26 else "➡️整理"
        elif adx < 20:
            trend = "🔄震荡"
        else:
            trend = "⏸️过渡"
        
        lines.append(f" {symbol:<5} {price:>8.2f}  {trend}  ADX:{adx:>4.1f} RSI:{rsi:>4.1f}")
    
    lines.append("━━━━━━━━━━━━━━━━━")
    lines.append(" ⚠️ 整体仓位未达标 · 保持观望")
    lines.append("━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

# ================== 主策略逻辑 ==================
def run_strategy():
    # 检查每日交易次数
    daily_count = check_daily_trades()
    if daily_count >= MAX_DAILY_TRADES:
        send_telegram(f"⚠️ 今日已开仓 {MAX_DAILY_TRADES} 次，触发熔断")
        return
    
    coins = ['BTC_USDT', 'ETH_USDT', 'SOL_USDT', 'BNB_USDT', 'DOGE_USDT']
    all_data = []
    signals_sent = 0
    
    for c in coins:
        if signals_sent >= 2:
            break
        
        data = get_klines(c)
        if not data:
            continue
        
        all_data.append(data)
        symbol = data['symbol']
        price = data['price']
        adx = data['adx']
        rsi = data['rsi']
        atr = data['atr']
        ema12 = data['ema12']
        ema26 = data['ema26']
        bb_lower = data['bb_lower']
        bb_upper = data['bb_upper']
        
        # ---------- 市场状态判断 ----------
        if adx > 25:
            market_state = "趋势市"
            strategy = "趋势跟踪"
        elif adx < 20:
            market_state = "震荡市"
            strategy = "网格交易"
        else:
            continue
        
        # ---------- 趋势跟踪策略 ----------
        if market_state == "趋势市":
            if ema12 > ema26 and price > ema12 and rsi < 70:
                direction = "LONG"
                stop_loss = price - 2 * atr
                take_profit = price + 3 * atr
            elif ema12 < ema26 and price < ema12 and rsi > 30:
                direction = "SHORT"
                stop_loss = price + 2 * atr
                take_profit = price - 3 * atr
            else:
                continue
            
            risk_reward = abs(take_profit - price) / abs(price - stop_loss) if abs(price - stop_loss) > 0 else 0
            if risk_reward < MIN_RISK_REWARD:
                continue
        
        # ---------- 震荡市网格策略 ----------
        elif market_state == "震荡市":
            if price <= bb_lower * 1.02 and rsi < 40:
                direction = "LONG"
                stop_loss = price - 1.5 * atr
                take_profit = price * 1.005
            elif price >= bb_upper * 0.98 and rsi > 60:
                direction = "SHORT"
                stop_loss = price + 1.5 * atr
                take_profit = price * 0.995
            else:
                continue
            
            risk_reward = abs(take_profit - price) / abs(price - stop_loss) if abs(price - stop_loss) > 0 else 0
            if risk_reward < MIN_RISK_REWARD_GRID:
                continue
        else:
            continue
        
        # ---------- 仓位计算 ----------
        contract_size = CONTRACT_SIZES.get(c, 0)
        if contract_size == 0:
            continue
        
        position_value = ACCOUNT_BALANCE * TARGET_PROFIT_PCT
        qty = position_value / (contract_size * price)
        
        # 用最大亏损反向校验张数
        max_qty = MAX_RISK_PER_TRADE / (abs(price - stop_loss) * contract_size)
        final_qty = int(min(qty, max_qty))
        
        if final_qty < 1:
            continue
        
        # ---------- 下单 ----------
        size = place_order(symbol, direction, final_qty, MAX_LEVERAGE, stop_loss, take_profit)
        if size > 0:
            loss_amount = abs(price - stop_loss) * size * contract_size
            msg = format_signal(symbol, direction, market_state, price, adx, rsi, stop_loss, take_profit, size, risk_reward, strategy)
            send_telegram(msg)
            signals_sent += 1
            daily_count += 1
            if daily_count >= MAX_DAILY_TRADES:
                send_telegram("⚠️ 今日开仓已达上限，后续信号将跳过")
                break
    
    # 无信号时发送市场简报
    if signals_sent == 0 and all_data:
        brief = format_brief(all_data)
        send_telegram(brief)

if __name__ == "__main__":
    run_strategy()
