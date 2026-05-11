#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 配置测试脚本
用于验证 Bot Token 和 Chat ID 是否正确
"""

import requests
import os

# 从环境变量或直接使用代码中的配置
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', "8746796223:AAGR4wryx4Zj4TARb9yeC83KOqJQJThTzMo")
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', "6204659239")

def test_telegram_connection():
    """测试 Telegram Bot API 连接"""
    print(f"🔍 正在测试 Telegram 配置...")
    print(f"Bot Token: {TELEGRAM_BOT_TOKEN[:20]}...")
    print(f"Chat ID: {TELEGRAM_CHAT_ID}")
    print()
    
    # 1. 获取 Bot 信息
    print("1️⃣ 获取 Bot 信息...")
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data['ok']:
                bot_info = data['result']
                print(f"✅ Bot 用户名: @{bot_info['username']}")
                print(f"   Bot 名称: {bot_info['first_name']}")
                print(f"   Bot ID: {bot_info['id']}")
                
                if bot_info['username'] == 'GateWoBuy_bot':
                    print(f"✅ 确认：这是 @GateWoBuy_bot")
                else:
                    print(f"⚠️ 警告：这不是 @GateWoBuy_bot！")
                    print(f"   当前 Bot: @{bot_info['username']}")
                    print(f"   期望 Bot: @GateWoBuy_bot")
            else:
                print(f"❌ 获取 Bot 信息失败: {data}")
        else:
            print(f"❌ HTTP 错误: {response.status_code}")
    except Exception as e:
        print(f"❌ 请求失败: {e}")
    
    print()
    
    # 2. 测试发送消息
    print("2️⃣ 测试发送消息...")
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': '🤖 测试消息 - 如果你看到这条消息，说明配置正确！',
            'parse_mode': 'HTML'
        }
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data['ok']:
                print(f"✅ 消息发送成功！")
                print(f"   请检查 Telegram 是否收到消息")
            else:
                print(f"❌ 消息发送失败: {data}")
        else:
            print(f"❌ HTTP 错误: {response.status_code}")
            print(f"   响应: {response.text}")
    except Exception as e:
        print(f"❌ 请求失败: {e}")
    
    print()
    print("=" * 50)
    print("📝 下一步操作建议：")
    print("1. 如果 Bot 用户名不是 @GateWoBuy_bot，需要更新 Token")
    print("2. 如果消息发送失败，检查 Chat ID 是否正确")
    print("3. 确保在 Telegram 中点击了 /start 与 Bot 开始对话")
    print("=" * 50)

if __name__ == "__main__":
    test_telegram_connection()
