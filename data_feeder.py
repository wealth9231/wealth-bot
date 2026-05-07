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

# ================== 加载外部配置 ==================
def load_config():
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except:
        return {
            "dry_run": True,
            "max_risk_per_trade": 0.8,
            "max_daily_trades": 5,
            "allow_short": True,
            "trading_enabled": True
        }

config = load_config()

# ================== 交易所初始化 ==================
exchange = ccxt.gateio({
    'apiKey': API_KEY,
    'secret': API_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'},
})

# ================== 风控参数 ==================
ACCOUNT_BALANCE = 70.0
MAX_LEVERAGE = 4
MAX_RISK_PER_TRADE = config["max_risk_per_trade"]
TARGET_PROFIT_PCT = 0.05
MAX_DAILY_TRADES = config["max_daily_trades"]

TRADING_ENABLED = config["trading_enabled"]
ALLOW_SHORT = config["allow_short"]
DRY_RUN = config["dry_run"]

CONTRACT_SIZES = {
    'BTC/USDT': 0.0001,
    'ETH/USDT': 0.01,
    'SOL/USDT': 1,
    'BNB/USDT': 0.01,
    'DOGE/USDT': 100
}

today_trades = 0
simulated_positions = {}

# ================== 数据库 ==================
def init_db():
    conn = sqlite3.connect('trades.db')
    conn.execute('''CREATE TABLE IF NOT EXISTS trades
        (id INTEGER PRIMARY KEY AUTOINCREMENT,
         symbol TEXT, direction TEXT,
         entry_price REAL, exit_price REAL,
         qty REAL, pnl REAL,
         entry_time TEXT, exit_time TEXT,
         status TEXT)''')
    conn.commit()
    return conn

def save_trade(symbol, direction, entry_price, qty):
    conn = init_db()
    conn.execute('INSERT INTO trades (symbol, direction, entry_price, qty, entry_time, status) VALUES (?,?,?,?,?,?)',
                 (symbol, direction, entry_price, qty, time.strftime('%Y-%m-%d %H:%M:%S'), 'OPEN'))
    conn.commit()
    conn.close()

# ================== Telegram 推送 ==================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'disable_web_page_preview': True}, timeout=10)
    except Exception as e:
        print(f"Telegram 发送失败: {e}")

# ================== 远程指令 ==================
def check_telegram_commands():
    if not TELEGRAM_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        resp = requests.get(url, params={'limit': 1, 'timeout': 10}).json()
        if not resp.get('ok') or not resp.get('result'):
            return
        update = resp['result'][0]
        msg = update.get('message', {})
        text = msg.get('text', '')
        chat_id = str(msg.get('chat', {}).get('id', ''))
        if chat_id != TELEGRAM_CHAT_ID:
            return
        if text.startswith('/'):
            update_id = update.get('update_id', 0)
            handle_command(text, update_id)
    except Exception as e:
        print(f"指令检查异常: {e}")

def handle_command(text, update_id):
    global TRADING_ENABLED, ALLOW_SHORT, MAX_RISK_PER_TRADE
    cmd = text.strip().lower()
    response = None
    if cmd == '/stop':
        TRADING_ENABLED = False
        response = "🛑 交易已暂停"
    elif cmd == '/start':
        TRADING_ENABLED = True
        response = "🟢 交易已恢复"
    elif cmd == '/status':
        response = get_status_report()
    elif cmd == '/closeall':
        close_all_positions()
        response = "🔒 已平掉所有仓位"
    elif cmd == '/mode safe':
        ALLOW_SHORT = False
        response = "🛡️ 已切换保守模式"
    elif cmd == '/mode aggressive':
        ALLOW_SHORT = True
        response = "⚔️ 已切换激进模式"
    elif cmd.startswith('/risk '):
        try:
            MAX_RISK_PER_TRADE = max(0.1, min(float(cmd.split()[-1]), 2.0))
            response = f"⚙️ 亏损上限已调至 {MAX_RISK_PER_TRADE}U"
        except:
            response = "❌ 格式错误"
    elif cmd == '/help':
        response = "📋 /stop /start /status /closeall /mode /risk /help"
    if response:
        send_telegram(response)
        requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates", params={'offset': update_id + 1, 'timeout': 1})

def fetch_real_balance():
    if DRY_RUN:
        total_pnl = sum(p['pnl'] for p in simulated_positions.values())
        equity = 70.0 + total_pnl
        free = 70.0 - sum(p['qty'] * p['entry_price'] * CONTRACT_SIZES.get(p['symbol'], 0) / MAX_LEVERAGE for p in simulated_positions.values())
        return equity, max(free, 0), 0.0
    try:
        balance = exchange.fetch_balance({'type': 'swap'})
        usdt = balance.get('USDT', {})
        total = usdt.get('total', 0)
        free = usdt.get('free', 0)
        if total == 0:
            accounts = exchange.privateGetFuturesUsdtAccounts()
            if isinstance(accounts, list) and len(accounts) > 0:
                acc = accounts[0]
                total = float(acc.get('total', 0))
                free = float(acc.get('available', 0))
        return total, free, total - free
    except:
        return 0, 0, 0

def fetch_real_positions():
    if DRY_RUN:
        return [{'symbol': p['symbol'], 'contracts': p['qty'], 'unrealizedPnl': p['pnl'], 'entryPrice': p['entry_price']} for p in simulated_positions.values()]
    try:
        return exchange.fetch_positions()
    except:
        return []

def update_simulated_pnl(current_prices):
    for symbol, pos in list(simulated_positions.items()):
        if symbol in current_prices:
            price = current_prices[symbol]
            if pos['direction'] == 'buy':
                pos['pnl'] = (price - pos['entry_price']) * pos['qty'] * CONTRACT_SIZES.get(symbol, 0)
            else:
                pos['pnl'] = (pos['entry_price'] - price) * pos['qty'] * CONTRACT_SIZES.get(symbol, 0)

def get_status_report():
    total, free, _ = fetch_real_balance()
    positions = fetch_real_positions()
    unrealized_pnl = sum(float(p.get('unrealizedPnl', 0)) for p in positions)
    pos_list = [f"{p['symbol']}: {p['contracts']}张 盈亏{p.get('unrealizedPnl', 0):.2f}U" for p in positions if float(p.get('contracts', 0)) != 0]
    pos_text = "\n".join(pos_list) if pos_list else "无持仓"
    mode_text = "🧪模拟" if DRY_RUN else "💰实盘"
    return f"""📊 状态 ({mode_text})
权益: {total:.2f}U | 浮动盈亏: {unrealized_pnl:+.2f}U
可用: {free:.2f}U
今日开仓: {today_trades}/{MAX_DAILY_TRADES}
持仓:
{pos_text}"""

def close_all_positions():
    global simulated_positions
    if DRY_RUN:
        simulated_positions = {}
        send_telegram("🧪 [模拟] 一键清仓已触发")
        return
    positions = fetch_real_positions()
    for p in positions:
        contracts = abs(float(p.get('contracts', 0)))
        if contracts > 0:
            side = 'sell' if float(p['contracts']) > 0 else 'buy'
            exchange.create_order(p['symbol'], 'market', side, contracts, None, {'reduce_only': True})

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
    dx_sum, count = 0, 0
    for i in range(len(tr_list) - period, len(tr_list)):
        if atr_val == 0: continue
        pdi = plus_di / atr_val * 100
        mdi = minus_di / atr_val * 100
        dx = abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) != 0 else 0
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
    if avg_loss == 0: return 50
    return 100 - (100 / (1 + avg_gain / avg_loss))

def get_klines(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=100)
        if not ohlcv or len(ohlcv) < 50: return None
        closes = [c[4] for c in ohlcv]
        highs = [c[2] for c in ohlcv]
        lows = [c[3] for c in ohlcv]
        price = closes[-1]
        ema12 = sum(closes[-12:]) / 12
        ema26 = sum(closes[-26:]) / 26
        adx = compute_adx(highs, lows, closes)
        rsi = compute_rsi(closes)
        tr_list = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1, min(15, len(closes)))]
        atr = sum(tr_list) / len(tr_list) if tr_list else 0
        middle = sum(closes[-20:]) / 20
        std = (sum([(x-middle)**2 for x in closes[-20:]]) / 20) ** 0.5
        return {
            'symbol': symbol,
            'price': price,
            'ema12': ema12,
            'ema26': ema26,
            'adx': adx,
            'rsi': rsi,
            'atr': atr,
            'bb_lower': middle - 2*std,
            'bb_upper': middle + 2*std,
        }
    except Exception as e:
        print(f"获取 {symbol} K线失败: {e}")
        return None

# ================== 参数自适应（已放宽） ==================
def adaptive_parameters(adx, atr, price, market_state):
    atr_pct = atr / price if price > 0 else 0.01
    if market_state == "趋势市":
        if adx > 40:
            stop_mult, tp_mult, position_pct = 2.5, 3.5, TARGET_PROFIT_PCT * 1.3
            rsi_buy_max, rsi_sell_min, min_rr = 75, 25, 1.1
        elif adx > 30:
            stop_mult, tp_mult, position_pct = 2.0, 3.0, TARGET_PROFIT_PCT
            rsi_buy_max, rsi_sell_min, min_rr = 70, 30, 1.2
        else:
            stop_mult, tp_mult, position_pct = 1.5, 2.5, TARGET_PROFIT_PCT * 0.7
            rsi_buy_max, rsi_sell_min, min_rr = 65, 35, 1.3
    elif market_state == "震荡市":
        if atr_pct < 0.01:
            stop_mult, position_pct, min_rr = 1.2, TARGET_PROFIT_PCT * 2.0, 1.0
        else:
            stop_mult, position_pct, min_rr = 1.5, TARGET_PROFIT_PCT * 1.5, 1.0
        tp_mult, rsi_buy_max, rsi_sell_min = 0, 40, 60
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

# ================== 下单 ==================
def place_order(symbol, side, qty, leverage, stop_loss, take_profit):
    global simulated_positions
    if DRY_RUN:
        kline = get_klines(symbol)
        entry_price = kline['price'] if kline else 0
        simulated_positions[symbol] = {
            'symbol': symbol,
            'direction': side,
            'entry_price': entry_price,
            'qty': int(qty),
            'pnl': 0.0,
            'stop_loss': stop_loss,
            'take_profit': take_profit
        }
        send_telegram(f"🧪 [模拟] {side.upper()} {symbol} {int(qty)}张 止损{stop_loss:.6f} 止盈{take_profit:.6f}")
        return int(qty)
    try:
        exchange.set_leverage(leverage, symbol)
        order_size = max(int(qty), 1)
        exchange.create_order(symbol, 'market', side, order_size, None, {'tif': 'ioc'})
        if stop_loss > 0:
            sl_side = 'sell' if side == 'buy' else 'buy'
            exchange.create_order(symbol, 'stop', sl_side, order_size, stop_loss,
                                  {'stopPrice': stop_loss, 'reduce_only': True})
        if take_profit > 0:
            tp_side = 'sell' if side == 'buy' else 'buy'
            exchange.create_order(symbol, 'limit', tp_side, order_size, take_profit,
                                  {'reduce_only': True})
        return order_size
    except Exception as e:
        print(f"下单失败: {e}")
        return 0

# ================== 市场简报（美化版） ==================
def format_brief(coins_data):
    current_prices = {d['symbol']: d['price'] for d in coins_data}
    update_simulated_pnl(current_prices)

    total, free, _ = fetch_real_balance()
    positions = fetch_real_positions()
    unrealized_pnl = sum(float(p.get('unrealizedPnl', 0)) for p in positions)
    total_pnl = unrealized_pnl
    pnl_str = f"+{total_pnl:.2f}" if total_pnl >= 0 else f"{total_pnl:.2f}"

    lines = []
    lines.append("╔══════════════════════╗")
    lines.append(f"║   Wealth Bot 市场简报  ║")
    lines.append(f"║   {time.strftime('%Y-%m-%d %H:%M UTC')}  ║")
    lines.append("╚══════════════════════╝")
    lines.append("")

    lines.append("┌─ 📈 资产概览")
    lines.append(f"│ 权益 {total:.2f}U   浮动 {pnl_str}U   可用 {free:.2f}U")
    lines.append("└─────────────────────")
    lines.append("")

    if DRY_RUN and simulated_positions:
        lines.append("┌─ 🧪 模拟持仓")
        for symbol, pos in simulated_positions.items():
            side_text = "🟢多" if pos['direction'] == 'buy' else "🔴空"
            pnl_str_pos = f"+{pos['pnl']:.4f}" if pos['pnl'] >= 0 else f"{pos['pnl']:.4f}"
            lines.append(f"│ {side_text} {symbol} {pos['qty']}张  盈亏{pnl_str_pos}U")
        lines.append("└─────────────────────")
        lines.append("")

    lines.append("┌─ 🔍 行情扫描")
    sorted_data = sorted(coins_data, key=lambda x: x['adx'], reverse=True)
    for d in sorted_data:
        symbol = d['symbol'].replace('/', '').replace('USDT', '')
        price = d['price']
        adx = d['adx']
        rsi = d['rsi']
        ema12, ema26 = d['ema12'], d['ema26']

        if adx > 40:
            trend = "🔥强趋势"
        elif adx > 25:
            trend = "📈趋势"
        elif adx < 20:
            trend = "🔄震荡"
        else:
            trend = "⏸️过渡"

        direction = "多头" if ema12 > ema26 else ("空头" if ema12 < ema26 else "整理")
        rsi_note = "⚠️超买" if rsi > 70 else ("💧超卖" if rsi < 30 else "●")

        if price >= 1000:
            price_str = f"${price:,.2f}"
        elif price >= 1:
            price_str = f"${price:.2f}"
        else:
            price_str = f"${price:.6f}"

        lines.append(f"│")
        lines.append(f"│  {trend} {symbol:<5} {price_str}")
        lines.append(f"│  {direction}   ADX {adx:.1f}   RSI {rsi:.1f} {rsi_note}")
    lines.append("└─────────────────────")
    lines.append("")

    lines.append("┌─ 🛡️ 风控状态")
    risk_remaining = MAX_DAILY_TRADES - today_trades
    lines.append(f"│ 单笔上限 ≤{MAX_RISK_PER_TRADE}U   今日剩{risk_remaining}次")
    mode_text = "🧪 模拟" if DRY_RUN else "💰 实盘"
    if TRADING_ENABLED:
        lines.append(f"│ 🟢 {mode_text}中  /status 查详情")
    else:
        lines.append(f"│ 🔴 已暂停  /start 恢复")
    lines.append("└─────────────────────")
    lines.append("")
    lines.append("💡 发送 /help 查看所有指令")

    return "\n".join(lines)

# ================== 主策略（ADX阈值已放宽） ==================
def run_strategy():
    global today_trades
    check_telegram_commands()
    if not TRADING_ENABLED:
        send_telegram("⏸️ 交易已暂停，发送 /start 恢复")
        return
    if today_trades >= MAX_DAILY_TRADES:
        send_telegram(f"⚠️ 今日已开仓 {MAX_DAILY_TRADES} 次，触发熔断")
        return

    coins = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'DOGE/USDT']
    all_data = []
    signals_sent = 0

    for c in coins:
        if signals_sent >= 2:
            break
        data = get_klines(c)
        if not data:
            continue
        all_data.append(data)
        adx, rsi, price = data['adx'], data['rsi'], data['price']
        atr, ema12, ema26 = data['atr'], data['ema12'], data['ema26']
        bb_lower, bb_upper = data['bb_lower'], data['bb_upper']

        if adx > 20:
            market_state, strategy = "趋势市", "趋势跟踪"
        elif adx < 15:
            market_state, strategy = "震荡市", "网格交易"
        else:
            continue

        adaptive = adaptive_parameters(adx, atr, price, market_state)
        if not adaptive:
            continue

        if market_state == "趋势市":
            if ema12 > ema26 and price > ema12 and rsi < adaptive['rsi_buy_max']:
                direction = "buy"
                stop_loss = price - adaptive['stop_mult'] * atr
                take_profit = price + adaptive['tp_mult'] * atr
            elif ema12 < ema26 and price < ema12 and rsi > adaptive['rsi_sell_min'] and ALLOW_SHORT:
                direction = "sell"
                stop_loss = price + adaptive['stop_mult'] * atr
                take_profit = price - adaptive['tp_mult'] * atr
            else:
                continue
        elif market_state == "震荡市":
            if price <= bb_lower * 1.02 and rsi < adaptive['rsi_buy_max']:
                direction = "buy"
                stop_loss = price - adaptive['stop_mult'] * atr
                take_profit = price * 1.005
            elif price >= bb_upper * 0.98 and rsi > adaptive['rsi_sell_min'] and ALLOW_SHORT:
                direction = "sell"
                stop_loss = price + adaptive['stop_mult'] * atr
                take_profit = price * 0.995
            else:
                continue
        else:
            continue

        contract_size = CONTRACT_SIZES.get(c, 0)
        if contract_size == 0:
            continue
        position_value = ACCOUNT_BALANCE * adaptive['position_pct']
        qty = position_value / (contract_size * price)
        max_qty = MAX_RISK_PER_TRADE / (abs(price - stop_loss) * contract_size)
        final_qty = int(min(qty, max_qty))
        if final_qty < 1:
            continue

        size = place_order(c, direction, final_qty, MAX_LEVERAGE, stop_loss, take_profit)
        if size > 0:
            prefix = "🧪 [模拟]" if DRY_RUN else "🔔 [实盘]"
            msg = f"""╔══════════════════════╗
║  {'🟢' if direction == 'buy' else '🔴'} {direction.upper()} {c}  x{size}张  {prefix}
╠══════════════════════╣
║ 📊 ADX:{adx:.1f} | RSI:{rsi:.1f}
║ 🧠 {strategy} | 止损{adaptive['stop_mult']}x
╠══════════════════════╣
║ 💰 入场:{price:.6f}
║ 🛑 止损:{stop_loss:.6f}
║ 🎯 止盈:{take_profit:.6f}
╚══════════════════════╝"""
            send_telegram(msg)
            save_trade(c, direction, price, size)
            signals_sent += 1
            today_trades += 1
            if today_trades >= MAX_DAILY_TRADES:
                send_telegram("⚠️ 今日开仓已达上限，后续信号将跳过")
                break

    if signals_sent == 0 and all_data:
        brief = format_brief(all_data)
        send_telegram(brief)

if __name__ == "__main__":
    init_db()
    run_strategy()
