import requests
import time
import json
import os
import sqlite3
import ccxt

# ================== 账户配置 ==================
API_KEY = os.environ.get("GATEIO_API_KEY", "").strip()
API_SECRET = os.environ.get("GATEIO_API_SECRET", "").strip()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

def load_config():
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except:
        return {"dry_run": True, "max_risk_per_trade": 2.0, "max_daily_trades": 5, "allow_short": True, "trading_enabled": True}

config = load_config()
exchange = ccxt.gateio({'apiKey': API_KEY, 'secret': API_SECRET, 'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

ACCOUNT_BALANCE = 300.0
MAX_LEVERAGE = 4
MAX_RISK_PER_TRADE = config["max_risk_per_trade"]
TARGET_PROFIT_PCT = 0.10
MAX_DAILY_TRADES = config["max_daily_trades"]
TRADING_ENABLED = config["trading_enabled"]
ALLOW_SHORT = config["allow_short"]
DRY_RUN = config["dry_run"]

CONTRACT_SIZES = {
    'BTC/USDT': 0.0001, 'ETH/USDT': 0.01, 'BNB/USDT': 0.01, 'SOL/USDT': 1,
    'DOGE/USDT': 100, 'LTC/USDT': 1, 'LINK/USDT': 1, 'AVAX/USDT': 1, 'ATOM/USDT': 1,
}

FEE_RATE = 0.0004
today_trades = 0
simulated_positions = {}

def init_db():
    conn = sqlite3.connect('trades.db')
    conn.execute('''CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, direction TEXT, entry_price REAL, exit_price REAL, qty REAL, pnl REAL, entry_time TEXT, exit_time TEXT, status TEXT)''')
    conn.commit()
    return conn

def save_trade(symbol, direction, entry_price, qty):
    conn = init_db()
    conn.execute('INSERT INTO trades (symbol, direction, entry_price, qty, entry_time, status) VALUES (?,?,?,?,?,?)', (symbol, direction, entry_price, qty, time.strftime('%Y-%m-%d %H:%M:%S'), 'OPEN'))
    conn.commit()
    conn.close()

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'disable_web_page_preview': True}, timeout=10)
    except: pass

def check_telegram_commands():
    if not TELEGRAM_TOKEN: return
    try:
        resp = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates", params={'limit': 1, 'timeout': 10}).json()
        if not resp.get('ok') or not resp.get('result'): return
        update = resp['result'][0]; msg = update.get('message', {})
        if str(msg.get('chat', {}).get('id', '')) != TELEGRAM_CHAT_ID: return
        if msg.get('text', '').startswith('/'): handle_command(msg['text'], update.get('update_id', 0))
    except: pass

def handle_command(text, update_id):
    global TRADING_ENABLED, ALLOW_SHORT
    cmd = text.strip().lower(); response = None
    if cmd == '/stop': TRADING_ENABLED = False; response = "🛑 交易已暂停"
    elif cmd == '/start': TRADING_ENABLED = True; response = "🟢 交易已恢复"
    elif cmd == '/status': response = get_status_report()
    elif cmd == '/closeall': close_all_positions(); response = "🔒 已平掉所有仓位"
    elif cmd == '/mode safe': ALLOW_SHORT = False; response = "🛡️ 保守模式"
    elif cmd == '/mode aggressive': ALLOW_SHORT = True; response = "⚔️ 激进模式"
    elif cmd == '/help': response = "📋 /stop /start /status /closeall /mode /risk /help"
    if response: send_telegram(response); requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates", params={'offset': update_id + 1, 'timeout': 1})

def fetch_real_balance():
    if DRY_RUN: return 300.0, 300.0, 0.0
    try:
        b = exchange.fetch_balance({'type': 'swap'}); usdt = b.get('USDT', {})
        return usdt.get('total', 0), usdt.get('free', 0), 0.0
    except: return 0, 0, 0

def fetch_real_positions():
    if DRY_RUN: return [{'symbol': p['symbol'], 'contracts': p['qty'], 'unrealizedPnl': p['pnl'], 'entryPrice': p['entry_price']} for p in simulated_positions.values()]
    try: return exchange.fetch_positions()
    except: return []

def update_simulated_pnl(current_prices):
    for symbol, pos in simulated_positions.items():
        if symbol in current_prices:
            price = current_prices[symbol]
            if pos['direction'] == 'buy': pos['pnl'] = (price - pos['entry_price']) * pos['qty'] * CONTRACT_SIZES.get(symbol, 0)
            else: pos['pnl'] = (pos['entry_price'] - price) * pos['qty'] * CONTRACT_SIZES.get(symbol, 0)

def get_status_report():
    total, free, _ = fetch_real_balance(); positions = fetch_real_positions()
    unrealized_pnl = sum(float(p.get('unrealizedPnl', 0)) for p in positions)
    pos_list = [f"  {p['symbol']} {p['contracts']}张 盈亏{p.get('unrealizedPnl', 0):.6f}U" for p in positions if float(p.get('contracts', 0)) != 0]
    pos_text = "\n".join(pos_list) if pos_list else "  无持仓"
    return f"📊 Wealth Bot {'🧪模拟' if DRY_RUN else '💰实盘'}\n💰 权益 {total:.2f}U | 浮动 {unrealized_pnl:+.6f}U\n📋 今日 {today_trades}/{MAX_DAILY_TRADES} 次\n{pos_text}"

def close_all_positions():
    global simulated_positions
    if DRY_RUN: simulated_positions = {}; send_telegram("🧪 模拟一键清仓"); return
    for p in exchange.fetch_positions():
        if abs(float(p.get('contracts', 0))) > 0:
            exchange.create_order(p['symbol'], 'market', 'sell' if float(p['contracts']) > 0 else 'buy', abs(float(p['contracts'])), None, {'reduce_only': True})

def compute_adx(highs, lows, closes, period=14):
    n = len(closes)
    if n < period + 1: return 0
    tr_list, plus_dm_list, minus_dm_list = [], [], []
    for i in range(1, n):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])); tr_list.append(tr)
        up_move = highs[i] - highs[i-1]; down_move = lows[i-1] - lows[i]
        plus_dm = up_move if up_move > down_move and up_move > 0 else 0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0
        plus_dm_list.append(plus_dm); minus_dm_list.append(minus_dm)
    atr_val = sum(tr_list[:period]) / period; plus_di = sum(plus_dm_list[:period]) / period; minus_di = sum(minus_dm_list[:period]) / period
    for i in range(period, len(tr_list)):
        atr_val = (atr_val * (period - 1) + tr_list[i]) / period
        plus_di = (plus_di * (period - 1) + plus_dm_list[i]) / period
        minus_di = (minus_di * (period - 1) + minus_dm_list[i]) / period
    dx_sum, count = 0, 0
    for i in range(len(tr_list) - period, len(tr_list)):
        if atr_val == 0: continue
        pdi = plus_di / atr_val * 100; mdi = minus_di / atr_val * 100
        dx = abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) != 0 else 0
        dx_sum += dx; count += 1
    return dx_sum / count if count > 0 else 0

def compute_rsi(closes, period=14):
    if len(closes) < period + 1: return 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(diff if diff > 0 else 0); losses.append(-diff if diff < 0 else 0)
    avg_gain = sum(gains[:period]) / period; avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0: return 50
    return 100 - (100 / (1 + avg_gain / avg_loss))

def get_klines(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=100)
        if not ohlcv or len(ohlcv) < 50: return None
        closes = [c[4] for c in ohlcv]; highs = [c[2] for c in ohlcv]; lows = [c[3] for c in ohlcv]
        price = closes[-1]
        ema12 = sum(closes[-12:]) / 12; ema26 = sum(closes[-26:]) / 26
        adx = compute_adx(highs, lows, closes); rsi = compute_rsi(closes)
        tr_list = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1, min(15, len(closes)))]
        atr = sum(tr_list) / len(tr_list) if tr_list else 0
        middle = sum(closes[-20:]) / 20; std = (sum([(x-middle)**2 for x in closes[-20:]]) / 20) ** 0.5
        return {'symbol': symbol, 'price': price, 'ema12': ema12, 'ema26': ema26, 'adx': adx, 'rsi': rsi, 'atr': atr, 'bb_lower': middle - 2*std, 'bb_upper': middle + 2*std}
    except: return None

def adaptive_parameters(adx, atr, price, market_state):
    atr_pct = atr / price if price > 0 else 0.01
    if market_state == "趋势市":
        if adx > 40: stop_mult, tp_mult, position_pct, rsi_buy, rsi_sell, min_rr = 2.5, 3.5, TARGET_PROFIT_PCT*1.3, 75, 25, 1.0
        elif adx > 30: stop_mult, tp_mult, position_pct, rsi_buy, rsi_sell, min_rr = 2.0, 3.0, TARGET_PROFIT_PCT, 70, 30, 1.0
        else: stop_mult, tp_mult, position_pct, rsi_buy, rsi_sell, min_rr = 1.5, 2.5, TARGET_PROFIT_PCT*0.7, 65, 35, 1.0
    elif market_state == "震荡市":
        if atr_pct < 0.01: stop_mult, position_pct, min_rr = 1.2, TARGET_PROFIT_PCT*2.0, 1.0
        else: stop_mult, position_pct, min_rr = 1.5, TARGET_PROFIT_PCT*1.5, 1.0
        tp_mult, rsi_buy, rsi_sell = 0, 40, 60
    else: return None
    return {'stop_mult': stop_mult, 'tp_mult': tp_mult, 'position_pct': position_pct, 'rsi_buy_max': rsi_buy, 'rsi_sell_min': rsi_sell, 'min_rr': min_rr}

def place_order(symbol, side, qty, leverage, stop_loss, take_profit):
    global simulated_positions
    if DRY_RUN:
        kline = get_klines(symbol)
        entry_price = kline['price'] if kline else 0
        simulated_positions[symbol] = {
            'symbol': symbol, 'direction': side, 'entry_price': entry_price,
            'qty': int(qty), 'pnl': 0.0, 'stop_loss': stop_loss, 'take_profit': take_profit
        }
        send_telegram(f"🧪 [模拟] {side.upper()} {symbol} {int(qty)}张 止损{stop_loss:.4f} 止盈{take_profit:.4f}")
        return int(qty)
    try:
        exchange.set_leverage(leverage, symbol); order_size = max(int(qty), 1)
        exchange.create_order(symbol, 'market', side, order_size, None, {'tif': 'ioc'})
        if stop_loss > 0: exchange.create_order(symbol, 'stop', 'sell' if side=='buy' else 'buy', order_size, stop_loss, {'stopPrice': stop_loss, 'reduce_only': True})
        if take_profit > 0: exchange.create_order(symbol, 'limit', 'sell' if side=='buy' else 'buy', order_size, take_profit, {'reduce_only': True})
        return order_size
    except: return 0

def format_signal_card(symbol, direction, market_state, price, adx, rsi, stop_loss, take_profit, qty, strategy, adaptive_info):
    arrow = "🟢" if direction == 'buy' else "🔴"
    dir_text = "做多" if direction == 'buy' else "做空"
    
    # 强制从 Gate.io 获取当前最新价格
    kline = get_klines(symbol)
    current_price = kline['price'] if kline else price
    price_change = ((current_price - price) / price * 100) if price > 0 else 0
    price_str = f"{current_price:.4f} ({price_change:+.2f}%)"
    
    # 用最新价格重新计算盈亏
    contract_size = CONTRACT_SIZES.get(symbol, 0)
    if contract_size > 0 and current_price > 0:
        if direction == 'buy':
            pnl = (current_price - price) * qty * contract_size
        else:
            pnl = (price - current_price) * qty * contract_size
    else:
        pnl = 0.0
    
    # 更新到 simulated_positions 里
    if symbol in simulated_positions:
        simulated_positions[symbol]['pnl'] = pnl
        simulated_positions[symbol]['entry_price'] = price
    
    pnl_str = f"+{pnl:.6f}U" if pnl >= 0 else f"{pnl:.6f}U"
    
    total_pnl = sum(p['pnl'] for p in simulated_positions.values())
    total_pnl_str = f"+{total_pnl:.6f}U" if total_pnl >= 0 else f"{total_pnl:.6f}U"
    
    if contract_size > 0 and price > 0:
        margin = (qty * price * contract_size) / MAX_LEVERAGE
        margin_str = f"{margin:.2f}U"
    else:
        margin_str = "计算中"
    
    # 预期净利润
    expected_profit = abs(take_profit - price) * qty * contract_size
    fee_cost = 2 * price * qty * contract_size * FEE_RATE
    net_profit = expected_profit - fee_cost
    
    return f"""
{arrow} {dir_text} {symbol} × {qty}张  🧪模拟

📊 ADX {adx:.1f}  |  RSI {rsi:.1f}
🧠 {strategy} · {adaptive_info}

💰 入场 {price:.4f}
💵 现价 {price_str}
🛑 止损 {stop_loss:.4f}
🎯 止盈 {take_profit:.4f}

📈 单笔浮动盈亏 {pnl_str}
💎 持仓保证金 {margin_str}
📋 总浮动盈亏 {total_pnl_str}
💰 预期净利润 {net_profit:.6f}U (扣手续费)
"""

def format_brief(coins_data):
    current_prices = {d['symbol']: d['price'] for d in coins_data}
    update_simulated_pnl(current_prices)
    total, free, _ = fetch_real_balance()
    positions = fetch_real_positions()
    unrealized_pnl = sum(float(p.get('unrealizedPnl', 0)) for p in positions)
    pnl_str = f"+{unrealized_pnl:.6f}" if unrealized_pnl >= 0 else f"{unrealized_pnl:.6f}"
    lines = []
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 Wealth Bot · {time.strftime('%H:%M UTC')}")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"💰 权益 {total:.2f}U   浮动 {pnl_str}U   可用 {free:.2f}U")
    if DRY_RUN and simulated_positions:
        lines.append("── 模拟持仓 ──")
        for sym, pos in simulated_positions.items():
            side = "多" if pos['direction']=='buy' else "空"
            pnl_str_pos = f"+{pos['pnl']:.6f}" if pos['pnl'] >= 0 else f"{pos['pnl']:.6f}"
            lines.append(f"  {side} {sym} {pos['qty']}张  盈亏{pnl_str_pos}U")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    sorted_data = sorted(coins_data, key=lambda x: x['adx'], reverse=True)
    for d in sorted_data:
        symbol = d['symbol'].replace('/', '').replace('USDT', '')
        price = d['price']; adx = d['adx']; rsi = d['rsi']
        ema12, ema26 = d['ema12'], d['ema26']
        if adx > 40: trend = "🔥强趋势"
        elif adx > 25: trend = "📈趋势"
        elif adx < 20: trend = "🔄震荡"
        else: trend = "⏸️过渡"
        direction = "多头" if ema12 > ema26 else ("空头" if ema12 < ema26 else "整理")
        rsi_note = "超买" if rsi > 70 else ("超卖" if rsi < 30 else "")
        if price >= 1000: price_str = f"${price:,.2f}"
        elif price >= 1: price_str = f"${price:.2f}"
        else: price_str = f"${price:.6f}"
        lines.append(f"{trend} {symbol:<6} {price_str}")
        lines.append(f"  {direction}  ADX {adx:.1f}  RSI {rsi:.1f} {rsi_note}")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🛡️ 风控 单笔≤{MAX_RISK_PER_TRADE}U  剩{MAX_DAILY_TRADES-today_trades}次")
    mode_text = "🧪模拟" if DRY_RUN else "💰实盘"
    lines.append(f"🟢 {mode_text}中  /status")
    lines.append("💡 /help 查看指令")
    return "\n".join(lines)

def run_strategy():
    global today_trades
    check_telegram_commands()
    if not TRADING_ENABLED: send_telegram("⏸️ 交易已暂停"); return
    if today_trades >= MAX_DAILY_TRADES: send_telegram(f"⚠️ 今日已满 {MAX_DAILY_TRADES} 次"); return

    coins = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'LTC/USDT',
             'LINK/USDT', 'DOGE/USDT', 'AVAX/USDT', 'ATOM/USDT']
    all_data = []; signals_sent = 0
    for c in coins:
        if signals_sent >= 3: break
        data = get_klines(c)
        if not data: continue
        all_data.append(data)
        adx, rsi, price = data['adx'], data['rsi'], data['price']
        atr, ema12, ema26 = data['atr'], data['ema12'], data['ema26']
        bb_lower, bb_upper = data['bb_lower'], data['bb_upper']
        if adx > 18: market_state, strategy = "趋势市", "趋势跟踪"
        elif adx < 15: market_state, strategy = "震荡市", "网格交易"
        else: continue

        adaptive = adaptive_parameters(adx, atr, price, market_state)
        if not adaptive: continue

        if market_state == "趋势市":
            if ema12 > ema26 and price > ema12 and rsi < adaptive['rsi_buy_max']:
                direction, stop_loss, take_profit = "buy", price - adaptive['stop_mult'] * atr, price + adaptive['tp_mult'] * atr
            elif ema12 < ema26 and price < ema12 and rsi > adaptive['rsi_sell_min'] and ALLOW_SHORT:
                direction, stop_loss, take_profit = "sell", price + adaptive['stop_mult'] * atr, price - adaptive['tp_mult'] * atr
            else: continue
        elif market_state == "震荡市":
            if price <= bb_lower * 1.02 and rsi < adaptive['rsi_buy_max']:
                direction, stop_loss, take_profit = "buy", price - adaptive['stop_mult'] * atr, price * 1.005
            elif price >= bb_upper * 0.98 and rsi > adaptive['rsi_sell_min'] and ALLOW_SHORT:
                direction, stop_loss, take_profit = "sell", price + adaptive['stop_mult'] * atr, price * 0.995
            else: continue
        else: continue

        contract_size = CONTRACT_SIZES.get(c, 0)
        if contract_size == 0: continue
        position_value = ACCOUNT_BALANCE * adaptive['position_pct']
        qty = position_value / (contract_size * price)
        max_qty = MAX_RISK_PER_TRADE / (abs(price - stop_loss) * contract_size)
        final_qty = int(min(qty, max_qty))
        if final_qty < 1: continue

        # 手续费过滤
        expected_profit = abs(take_profit - price) * final_qty * contract_size
        fee_cost = 2 * price * final_qty * contract_size * FEE_RATE
        if expected_profit < fee_cost * 1.2:
            continue

        size = place_order(c, direction, final_qty, MAX_LEVERAGE, stop_loss, take_profit)
        if size > 0:
            msg = format_signal_card(c, direction, market_state, price, adx, rsi, stop_loss, take_profit, size, strategy, f"止损{adaptive['stop_mult']}x")
            send_telegram(msg); save_trade(c, direction, price, size)
            signals_sent += 1; today_trades += 1
            if today_trades >= MAX_DAILY_TRADES: send_telegram("⚠️ 今日开仓已达上限"); break

    if signals_sent == 0 and all_data: send_telegram(format_brief(all_data))

if __name__ == "__main__":
    init_db()
    run_strategy()
