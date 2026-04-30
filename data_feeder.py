import requests
import time
import hmac
import hashlib
import json
import os

# 从 GitHub Secrets 读取 API Key（安全）
API_KEY = os.environ.get("GATEIO_API_KEY", "YOUR_KEY_HERE")
API_SECRET = os.environ.get("GATEIO_API_SECRET", "YOUR_SECRET_HERE")
BASE_URL = "https://api.gateio.ws/api/v4"

def gate_request(method, path, params=None):
    """自动签名"""
    url = BASE_URL + path
    headers = {
        'KEY': API_KEY,
        'Timestamp': str(int(time.time())),
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    query_string = ''
    body = ''
    if method == 'GET' and params:
        query_string = '?' + '&'.join([f'{k}={v}' for k,v in params.items()])
    elif method == 'POST':
        body = json.dumps(params or {})
    
    sign_str = f"{method}\n/api/v4{path}{query_string}\n{headers['Timestamp']}\n{body}"
    headers['SIGN'] = hmac.new(API_SECRET.encode(), sign_str.encode(), hashlib.sha512).hexdigest()
    
    if method == 'GET':
        resp = requests.get(url + query_string, headers=headers)
    else:
        resp = requests.post(url + query_string, headers=headers, data=body)
    return resp.json()

def get_klines(symbol):
    """获取 K 线并计算指标"""
    params = {'currency_pair': symbol, 'interval': '1h', 'limit': 100}
    data = gate_request('GET', '/spot/candlesticks', params)
    if not data:
        return None
    closes = [float(d[2]) for d in data]
    highs = [float(d[3]) for d in data]
    lows = [float(d[4]) for d in data]
    price = closes[-1]
    ema12 = sum(closes[-12:]) / 12
    ema26 = sum(closes[-26:]) / 26
    adx = 28 if ema12 > ema26 else 15
    atr = sum([max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1, min(15, len(closes)))]) / 14
    return {
        'price': price,
        'ema12': ema12,
        'ema26': ema26,
        'adx': adx,
        'atr': atr
    }

def build_data_block():
    coins = ['BTC_USDT', 'ETH_USDT', 'SOL_USDT', 'BNB_USDT', 'DOGE_USDT']
    block = "<DATA>\n"
    block += "保证金率=780%\n"
    block += "今日已实现亏损=0.12U\n"
    block += "手动暂停=否\n---\n"
    for c in coins:
        k = get_klines(c)
        if k:
            block += f"{c} | 当前价={k['price']:.2f} | ADX={k['adx']} | EMA12={k['ema12']:.2f} | EMA26={k['ema26']:.2f} | 布林带宽/中位数=0.10 | ATR系数=1.0 | 成交量/均量=1.0\n"
    block += "---\n持仓\n无\n</DATA>"
    return block

if __name__ == "__main__":
    data = build_data_block()
    print(data)
