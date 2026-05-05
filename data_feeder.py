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

# ================== 风控参数（可远程调整） ==================
ACCOUNT_BALANCE = 70
MAX_LEVERAGE = 4
MAX_RISK_PER_TRADE = 0.5          # 单笔最大亏损（U）
DAILY_LOSS_LIMIT = 3.5            # 单日最大亏损
TARGET_PROFIT_PCT = 0.03          # 基础仓位比例
MAX_DAILY_TRADES = 3              # 每日最大开仓次数

# 运行模式（可通过 Telegram 指令切换）
TRADING_ENABLED = True
ALLOW_SHORT = True

# 合约面值
CONTRACT_SIZES = {
    'BTC_USDT': 0.0001,
    'ETH_USDT': 0.01,
    'SOL_USDT': 1,
    'BNB_USDT': 0.01,
    'DOGE_USDT': 100
}

# 当日状态
today_trades = 0
today_pnl = 0.0

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

    # 请求体哈希
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
        requests.post(url, data={
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'disable_web_page_preview': True
        }, timeout=10)
    except Exception as e:
        print(f"Telegram 发送失败: {e}")

# ================== 远程遥控模块（已修复） ==================
def check_telegram_commands():
    """读取 Telegram 消息，解析远程指令"""
    if not TELEGRAM_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        resp = requests.get(url, params={'limit': 5, 'timeout': 10}).json()
        if not resp.get('ok'):
            return
        for update in resp.get('result', []):
            msg = update.get('message', {})
            text = msg.get('text', '')
            chat_id = str(msg.get('chat', {}).get('id', ''))
            if chat_id != TELEGRAM_CHAT_ID:
                continue
            update_id = update.get('update_id', 0)
            handle_command(text, update_id)
    except Exception as e:
        print(f"遥控检查异常: {e}")

def handle_command(text, update_id):
    """解析并执行远程指令"""
    global TRADING_ENABLED, ALLOW_SHORT, MAX_RISK_PER_TRADE, TARGET_PROFIT_PCT, MAX_DAILY_TRADES

    cmd = text.strip().lower()
    response = None

    if cmd == '/stop':
        TRADING_ENABLED = False
        response = "🛑 交易已暂停"
    elif cmd == '/start':
        TRADING_ENABLED = True
        response = "🟢 交易已恢复"
    elif cmd == '/closeall':
        close_all_positions()
        response = "🔒 已平掉所有仓位"
    elif cmd == '/status':
        response = get_status_report()
    elif cmd == '/mode safe':
        ALLOW_SHORT = False
        response = "🛡️ 已切换保守模式（只多不空）"
    elif cmd == '/mode aggressive':
        ALLOW_SHORT = True
        response = "⚔️ 已切换激进模式（多空皆可）"
    elif cmd.startswith('/risk '):
        try:
            val = float(cmd.replace('/risk ', ''))
            MAX_RISK_PER_TRADE = max(0.1, min(val, 2.0))
            response = f"⚙️ 单笔亏损上限已调至 {MAX_RISK_PER_TRADE}U"
        except:
            response = "❌ 格式错误，例：/risk 0.5"
    elif cmd.startswith('/trades '):
        try:
            val = int(cmd.replace('/trades ', ''))
            MAX_DAILY_TRADES = max(1, min(val, 10))
            response = f"⚙️ 每日最大交易次数已调至 {MAX_DAILY_TRADES}"
        except:
            response = "❌ 格式错误，例：/trades 3"
    elif cmd == '/help':
        response = """📋 可用命令：
/stop - 暂停交易
/start - 恢复交易
/status - 查看状态
/mode safe - 保守模式
/mode aggressive - 激进模式
/risk 0.5 - 调整亏损上限
/trades 3 - 调整每日最大交易数
/closeall - 平掉所有仓位"""

    if response:
        send_telegram(response)
        mark_command_processed(update_id)

def mark_command_processed(update_id):
    """标记指令已处理，防止重复响应"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    requests.get(url, params={'offset': update_id + 1, 'timeout': 1})

def close_all_positions():
    """市价平掉所有合约仓位"""
    positions = gate_request('GET', '/futures/usdt/positions')
    if not positions:
        return
    for pos in positions:
        size = abs(float(pos.get('size', 0)))
        if size > 0:
            contract = pos['contract']
            gate_request('POST', '/futures/usdt/orders', {
                'contract': contract,
                'size': -int(size) if float(pos.get('size', 0)) > 0 else int(size),
                'price': '0',
                'tif': 'ioc',
                'reduce_only': True,
                'text': 't-bot-closeall'
            })

def get_status_report():
    """生成当前状态报告"""
    positions = gate_request('GET', '/futures/usdt/positions') or []
    pos_list = []
    for p in positions:
        size = float(p.get('size', 0))
        if size != 0:
            pos_list.append(f"{p['contract']}: {size}张")
    pos_text = "\n".join(pos_list) if pos_list else "无持仓"

    return f"""📊 Wealth Bot V5.1 状态
本金: {ACCOUNT_BALANCE}U
交易: {'🟢开启' if TRADING_ENABLED else '🔴暂停'}
模式: {'保守' if not ALLOW_SHORT else '激进'}
今日交易: {today_trades}/{MAX_DAILY_TRADES}
亏损上限: {MAX_RISK_PER_TRADE}U
持仓:
{pos_text}"""

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

    atr_val = sum(tr_list[:period]) / period
    plus_di = sum(plus_dm_list[:period]) / period
    minus_di = sum(minus_dm_list[:period]) / period

    for i in range(period, len(tr_list)):
        atr_val = (atr_val * (period - 1) + tr_list[i]) / period
        plus_di = (plus_di * (period - 1) + plus_dm_list[i]) / period
        minus_di = (minus_di * (period - 1) + minus_dm_list[i]) / period

    dx_sum = 0
    count = 0
    for i in range(len(tr_list) - period, len(tr_list)):
        if atr_val == 0:
            continue
        pdi = plus_di / atr_val * 100
        mdi = minus_di / atr_val * 100
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

# ================== 参数自适应模块 ==================
def adaptive_parameters(adx, atr, price, market_state):
    """根据市场状态动态调整止损倍数、仓位比例、RSI 阈值"""
    atr_pct = atr / price if price > 0 else 0.01

    if market_state == "趋势市":
        if adx > 40:
            stop_mult = 2.5
            tp_mult = 3.5
            position_pct = TARGET_PROFIT_PCT * 1.3
            rsi_buy_max = 75
            rsi_sell_min = 25
            min_rr = 1.3
        elif adx > 30:
            stop_mult = 2.0
            tp_mult = 3.0
            position_pct = TARGET_PROFIT_PCT
            rsi_buy_max = 70
            rsi_sell_min = 30
            min_rr = 1.5
        else:
            stop_mult = 1.5
            tp_mult = 2.5
            position_pct = TARGET_PROFIT_PCT * 0.7
            rsi_buy_max = 65
            rsi_sell_min = 35
            min_rr = 1.8

    elif market_state == "震荡市":
        if atr_pct < 0.01:
            stop_mult = 1.2
            position_pct = TARGET_PROFIT_PCT * 1.5
            min_rr = 1.1
        else:
            stop_mult = 1.5
            position_pct = TARGET_PROFIT_PCT
            min_rr = 1.2
        tp_mult = 0
        rsi_buy_max = 40
        rsi_sell_min = 60
    else:
        return None

    return {
        'stop_mult': stop_mult,
        'tp_mult': tp_mult,
        'position_pct': position_pct,
        'rsi_buy_max': rsi_buy_max,
        'rsi_sell_min': rsi_sell_min,
        'min_rr': min_rr
    }

# ================== 下单模块 ==================
def place_order(symbol, side, qty, leverage, stop_loss, take_profit):
    """市价开仓 + 自动挂止损止盈"""
    contract = symbol.replace('_USDT', '_USDT')
    settle = 'usdt'

    gate_request('POST', f'/futures/{settle}/contracts/{contract}/leverage', {'leverage': str(leverage)})

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
        return 0

    if stop_loss > 0:
        sl_price = int(stop_loss) if side == "LONG" else int(stop_loss) + 1
        gate_request('POST', f'/futures/{settle}/price_orders', {
            'contract': contract,
            'size': -order_size,
            'price': str(sl_price),
            'close': True,
            'tif': 'gtc',
            'text': 't-bot-sl'
        })

    if take_profit > 0:
        tp_price = int(take_profit) if side == "LONG" else int(take_profit) - 1
        gate_request('POST', f'/futures/{settle}/price_orders', {
            'contract': contract,
            'size': -order_size,
            'price': str(tp_price),
            'close': True,
            'tif': 'gtc',
            'text': 't-bot-tp'
        })

    return order_size

# ================== 格式化输出 ==================
def format_signal(symbol, direction, market_state, price, adx, rsi, stop_loss, take_profit, qty, risk_reward, strategy, adaptive_info):
    arrow = "🟢" if direction == "LONG" else "🔴"
    state_emoji = "📈" if market_state == "趋势市" else "🔄"
    msg = f"""
╔══════════════════════╗
║  {arrow} {direction} {symbol}  x{qty}张
╠══════════════════════╣
║ {state_emoji} 市场: {market_state}
║ 📊 ADX: {adx:.1f}  |  RSI: {rsi:.1f}
║ 📉 策略: {strategy}
║ 🧠 自适应: {adaptive_info}
╠══════════════════════╣
║ 💰 入场: {price:.2f}
║ 🛑 止损: {stop_loss:.2f}
║ 🎯 止盈: {take_profit:.2f}
╠══════════════════════╣
║ ⚖️ 风控: 风险收益比 {risk_reward:.2f}
║ 💎 杠杆: {MAX_LEVERAGE}x
╚══════════════════════╝
"""
    return msg.strip()

def format_brief(coins_data):
    lines = []
    lines.append("━━━━━━━━━━━━━━━━━")
    lines.append(f"  📊 市场扫描 · {time.strftime('%H:%M UTC')}")
    lines.append(f"  🧠 V5.1 自适应 | 交易:{'🟢' if TRADING_ENABLED else '🔴'}")
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
    lines.append(f" 💡 发送 /help 查看遥控指令")
    lines.append("━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

# ================== 主策略 ==================
def run_strategy():
    global today_trades

    # 检查远程指令
    check_telegram_commands()

    if not TRADING_ENABLED:
        send_telegram("⏸️ 交易已暂停，发送 /start 恢复")
        return

    if today_trades >= MAX_DAILY_TRADES:
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

        # 市场状态判断
        if adx > 25:
            market_state = "趋势市"
            strategy = "趋势跟踪"
        elif adx < 20:
            market_state = "震荡市"
            strategy = "网格交易"
        else:
            continue

        # 获取自适应参数
        adaptive = adaptive_parameters(adx, atr, price, market_state)
        if not adaptive:
            continue

        # 趋势跟踪策略
        if market_state == "趋势市":
            if ema12 > ema26 and price > ema12 and rsi < adaptive['rsi_buy_max']:
                direction = "LONG"
                stop_loss = price - adaptive['stop_mult'] * atr
                take_profit = price + adaptive['tp_mult'] * atr
            elif ema12 < ema26 and price < ema12 and rsi > adaptive['rsi_sell_min']:
                if not ALLOW_SHORT:
                    continue
                direction = "SHORT"
                stop_loss = price + adaptive['stop_mult'] * atr
                take_profit = price - adaptive['tp_mult'] * atr
            else:
                continue

            risk_reward = abs(take_profit - price) / abs(price - stop_loss) if abs(price - stop_loss) > 0 else 0
            if risk_reward < adaptive['min_rr']:
                continue

        # 震荡市网格策略
        elif market_state == "震荡市":
            if price <= bb_lower * 1.02 and rsi < adaptive['rsi_buy_max']:
                direction = "LONG"
                stop_loss = price - adaptive['stop_mult'] * atr
                take_profit = price * 1.005
            elif price >= bb_upper * 0.98 and rsi > adaptive['rsi_sell_min']:
                if not ALLOW_SHORT:
                    continue
                direction = "SHORT"
                stop_loss = price + adaptive['stop_mult'] * atr
                take_profit = price * 0.995
            else:
                continue

            risk_reward = abs(take_profit - price) / abs(price - stop_loss) if abs(price - stop_loss) > 0 else 0
            if risk_reward < adaptive['min_rr']:
                continue
        else:
            continue

        # 仓位计算
        contract_size = CONTRACT_SIZES.get(c, 0)
        if contract_size == 0:
            continue

        position_value = ACCOUNT_BALANCE * adaptive['position_pct']
        qty = position_value / (contract_size * price)
        max_qty = MAX_RISK_PER_TRADE / (abs(price - stop_loss) * contract_size)
        final_qty = int(min(qty, max_qty))

        if final_qty < 1:
            continue

        # 自适应信息
        adaptive_info = f"止损{adaptive['stop_mult']}x 止盈{adaptive['tp_mult']}x" if market_state == "趋势市" else f"网格{adaptive['stop_mult']}x"

        # 下单
        size = place_order(symbol, direction, final_qty, MAX_LEVERAGE, stop_loss, take_profit)
        if size > 0:
            msg = format_signal(symbol, direction, market_state, price, adx, rsi, stop_loss, take_profit, size, risk_reward, strategy, adaptive_info)
            send_telegram(msg)
            signals_sent += 1
            today_trades += 1

            if today_trades >= MAX_DAILY_TRADES:
                send_telegram("⚠️ 今日开仓已达上限，后续信号将跳过")
                break

    # 无信号时发送市场简报
    if signals_sent == 0 and all_data:
        brief = format_brief(all_data)
        send_telegram(brief)

if __name__ == "__main__":
    run_strategy()
