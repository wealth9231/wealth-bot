import requests
import time
import hmac
import hashlib
import json
import os

API_KEY = os.environ.get("2968615408018ad943b0d09784e6895f", "").strip()
API_SECRET = os.environ.get("0332122120b2e4df7a788219acb05e3221bd60a8981251549cccff78ff5ea95f", "").strip()
BASE_URL = "https://api.gateio.ws/api/v4"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

def gate_request(method, path, params=None):
    url = BASE_URL + path
    timestamp = str(int(time.time()))
    headers = {
        'KEY': API_KEY,
        'Timestamp': timestamp,
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    query_string = ''
    body = ''
    if method == 'GET' and params:
        query_string = '?' + '&'.join([f'{k}={v}' for k, v in params.items()])
    elif method == 'POST':
        body = json.dumps(params or {})

    sign_str = f"{method}\n/api/v4{path}{query_string}\n{timestamp}\n{body}"
    headers['SIGN'] = hmac.new(API_SECRET.encode(), sign_str.encode(), hashlib.sha512).hexdigest()

    if method == 'GET':
        resp = requests.get(url + query_string, headers=headers)
    else:
        resp = requests.post(url + query_string, headers=headers, data=body)
    return resp.json()

def get_klines(symbol):
    params = {'currency_pair': symbol, 'interval': '1h', 'limit': 100}
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
    adx = 28 if ema12 > ema26 else 15
    if len(closes) >= 20:
        middle = sum(closes[-20:]) / 20
        std = (sum([(x-middle)**2 for x in closes[-20:]]) / 20) ** 0.5
        bb_upper = middle + 2*std
        bb_lower = middle - 2*std
        bb_width = (bb_upper - bb_lower) / middle
    else:
        bb_width = 0.1
    return {
        'symbol': symbol,
        'price': price,
        'ema12': ema12,
        'ema26': ema26,
        'atr': atr,
        'adx': adx,
        'bb_width': bb_width
    }

def generate_signal(coin_data):
    if not coin_data:
        return None
    if coin_data['ema12'] > coin_data['ema26'] and coin_data['price'] > coin_data['ema12']:
        direction = "BUY"
    elif coin_data['ema12'] < coin_data['ema26'] and coin_data['price'] < coin_data['ema12']:
        direction = "SELL"
    else:
        direction = "HOLD"
    if direction != "HOLD":
        return f"{direction} {coin_data['symbol']} | 价格:{coin_data['price']:.2f} | EMA12:{coin_data['ema12']:.2f} EMA26:{coin_data['ema26']:.2f} | ATR:{coin_data['atr']:.4f}"
    return None

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram 未配置")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': message}, timeout=10)
    except Exception as e:
        print(f"Telegram 发送失败: {e}")

def main():
    coins = ['BTC_USDT', 'ETH_USDT', 'SOL_USDT', 'BNB_USDT', 'DOGE_USDT']
    signals = []
    for c in coins:
        data = get_klines(c)
        if data:
            sig = generate_signal(data)
            if sig:
                signals.append(sig)
    message = "🤖 Wealth Bot 信号提醒:\n" + "\n".join(signals) if signals else "🤖 Wealth Bot: 当前无明显趋势信号。"
    print(message)
    send_telegram_message(message)

if __name__ == "__main__":
    main()
