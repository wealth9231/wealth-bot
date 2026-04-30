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

def gate_request(method, path, params=None):
    url = BASE_URL + path
    timestamp = str(int(time.time()))
    query_string = ''
    body = ''
    if method == 'GET' and params:
        query_string = '?' + '&'.join([f'{k}={v}' for k, v in params.items()])
    elif method == 'POST':
        body = json.dumps(params or {})

    sign_string = f"{method}\n/api/v4{path}{query_string}\n{timestamp}\n{body}"
    signature = hmac.new(
        API_SECRET.encode(),
        sign_string.encode(),
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
            resp = requests.post(url + query_string, headers=headers, data=body, timeout=15)
        if resp.status_code != 200:
            print(f"API 错误 {resp.status_code}: {resp.text}")
            return None
        return resp.json()
    except Exception as e:
        print(f"请求异常: {e}")
        return None

def get_klines(symbol):
    params = {'currency_pair': symbol, 'interval': '1h', 'limit': 50}
    data = gate_request('GET', '/spot/candlesticks', params)
    if not data or len(data) < 26:
        print(f"{symbol} 数据不足")
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
    return {
        'symbol': symbol,
        'price': price,
        'ema12': ema12,
        'ema26': ema26,
        'atr': atr,
        'adx': adx
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
        resp = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': message}, timeout=10)
        print(f"Telegram 发送状态: {resp.status_code}")
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
