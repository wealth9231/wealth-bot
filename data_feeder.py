import requests
import os

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

print(f"Token 长度: {len(TELEGRAM_TOKEN)}")
print(f"Chat ID: {TELEGRAM_CHAT_ID}")

if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': '测试消息 - 最简版验证'}, timeout=10)
    print(f"Telegram 返回状态码: {resp.status_code}")
    print(f"Telegram 返回内容: {resp.text}")
else:
    print("密匙缺失，请检查 GATEIO 和 TELEGRAM 的密匙配置")
