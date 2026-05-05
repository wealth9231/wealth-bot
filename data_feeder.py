import requests
import time
import hmac
import hashlib
import json
import os

API_KEY = os.environ.get("GATEIO_API_KEY", "").strip()
API_SECRET = os.environ.get("GATEIO_API_SECRET", "").strip()
BASE_URL = "https://api.gateio.ws/api/v4"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

MAX_LEVERAGE = 4
MAX_RISK_PER_TRADE = 0.225
MIN_RISK_REWARD = 1.5
TARGET_PROFIT_PCT = 0.03

CONTRACT_SIZES = {
    'BTC_USDT': 0.0001,
    'ETH_USDT': 0.01,
    'SOL_USDT': 1,
    'BNB_USDT': 0.01,
    'DOGE_USDT': 100
}

def gate_request(method, path, params=None):
    url = BASE_URL + path
    timestamp = str(int(time.time()))
    
    # 处理查询参数
    query_string = ''
    if method == 'GET' and params:
        # 按key排序
        sorted_params = sorted(params.items())
        query_string = '?' + '&'.join([f'{k}={v}' for k, v in sorted_params])
    
    # 处理请求体
    body_str = ''
    if method == 'POST':
        if params:
            # POST 参数同样排序
            sorted_params = sorted(params.items())
            body_str = json.dumps(dict(sorted_params))
        else:
            body_str = ''
    
    # 构建签名串（严格按照 Gate.io 格式）
    sign_string = f"{method}\n/api/v4{path}{query_string}\n{timestamp}\n{body_str}"
    
    # 使用 HMAC-SHA512 签名
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
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'disable_web_page_preview': True}, timeout=10)
    except Exception as e:
        print(f"Telegram 发送失败: {e}")

def get_klines(symbol):
    params = {'currency_pair': symbol, 'interval': '1h', 'limit': 50}
    data = gate_request('GET', '/spot/candlesticks', params)
    if not data or len(data) < 26:
        return None
    closes = [float(d[2]) for d in data]
    highs = [float(d[3]) for d in data]
    lows = [float(d[4]) for d in data]
    price = closes[-1]
    ema12 = sum(closes[-12:]) / 12
    ema26 = sum(closes[-26:]) / 26
    tr_list = []
    for i in range(1, min(15, len(closes))):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        tr_list.append(tr)
    atr = sum(tr_list) / len(tr_list) if tr_list else 0
    middle = sum(closes[-20:]) / 20
    std = (sum([(x-middle)**2 for x in closes[-20:]]) / 20) ** 0.5
    return {
        'symbol': symbol.replace('_', ''),
        'price': price,
        'ema12': ema12,
        'ema26': ema26,
        'atr': atr,
        'bb_lower': middle - 2*std,
        'bb_upper': middle + 2*std
    }

def run_strategy():
    send_telegram("🤖 Wealth Bot 全自动模式已启动")
    coins = ['BTC_USDT', 'ETH_USDT', 'SOL_USDT', 'BNB_USDT', 'DOGE_USDT']
    traded = False
    for c in coins:
        if traded:
            break
        data = get_klines(c)
        if not data:
            continue
        symbol = data['symbol']
        price = data['price']
        atr = data['atr']
        ema12 = data['ema12']
        ema26 = data['ema26']
        
        if ema12 > ema26 and price > ema12:
            direction = "long"
            stop_loss = price - 2 * atr
            take_profit = price + 3 * atr
            risk_reward = (take_profit - price) / (price - stop_loss) if (price - stop_loss) > 0 else 0
            if risk_reward < MIN_RISK_REWARD:
                send_telegram(f"ℹ️ {symbol} 风险收益比不足 ({risk_reward:.2f})，跳过")
                continue
            contract_size = CONTRACT_SIZES.get(c, 0)
            if contract_size == 0:
                continue
            position_value = 50 * TARGET_PROFIT_PCT
            qty = position_value / (contract_size * price)
            if qty < 1:
                send_telegram(f"ℹ️ {symbol} 仓位不足 (计算{qty:.2f}张)，跳过")
                continue
            max_qty = MAX_RISK_PER_TRADE / ((price - stop_loss) * contract_size)
            final_qty = int(min(qty, max_qty))
            if final_qty < 1:
                continue
            # 实际下单部分暂时注释，先确保行情能通
            # size = place_order(symbol, direction, final_qty, MAX_LEVERAGE, stop_loss, take_profit)
            send_telegram(f"🔔 <EXECUTE> {direction.upper()} {symbol} {final_qty}张")
            traded = True
            
        elif ema12 < ema26 and price < ema12:
            direction = "short"
            stop_loss = price + 2 * atr
            take_profit = price - 3 * atr
            risk_reward = (price - take_profit) / (stop_loss - price) if (stop_loss - price) > 0 else 0
            if risk_reward < MIN_RISK_REWARD:
                send_telegram(f"ℹ️ {symbol} 风险收益比不足 ({risk_reward:.2f})，跳过")
                continue
            contract_size = CONTRACT_SIZES.get(c, 0)
            if contract_size == 0:
                continue
            position_value = 50 * TARGET_PROFIT_PCT
            qty = position_value / (contract_size * price)
            if qty < 1:
                send_telegram(f"ℹ️ {symbol} 仓位不足 (计算{qty:.2f}张)，跳过")
                continue
            max_qty = MAX_RISK_PER_TRADE / ((stop_loss - price) * contract_size)
            final_qty = int(min(qty, max_qty))
            if final_qty < 1:
                continue
            # size = place_order(symbol, direction, final_qty, MAX_LEVERAGE, stop_loss, take_profit)
            send_telegram(f"🔔 <EXECUTE> {direction.upper()} {symbol} {final_qty}张")
            traded = True
            
    if not traded:
        send_telegram("ℹ️ Wealth Bot: 当前无满足条件的交易信号")

if __name__ == "__main__":
    run_strategy()
