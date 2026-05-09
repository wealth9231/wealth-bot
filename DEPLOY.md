# Gate.io 量化交易机器人 - 部署指南

## 架构说明

```
┌─────────────────┐   触发   ┌─────────────────┐   运行   ┌─────────────────┐
│   腾讯元宝     │ ──────> │  GitHub Actions  │ ──────> │  gate_trading   │
│  （定时任务）  │   HTTP  │   workflow_dispatch│          │  _bot.py        │
└─────────────────┘          └─────────────────┘          └────────┬────────┘
                                                                     │
                                                        ┌────────────▼────────┐
                                                        │   Telegram 通知    │
                                                        │   @GateWoBuy_bot   │
                                                        └────────────────────┘
```

---

## 快速部署步骤

### 第1步：Fork或创建GitHub仓库

```bash
# 在你的电脑上
git clone https://github.com/你的用户名/gate-trading-bot.git
cd gate-trading-bot

# 把以下文件复制到仓库目录：
# - gate_trading_bot.py
# - requirements.txt
# - .github/workflows/trading-bot.yml
```

### 第2步：配置GitHub Secrets

在GitHub仓库 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

添加以下4个Secrets：

| Secret名称 | 值 | 说明 |
|------------|-----|------|
| `GATE_API_KEY` | `bf76ef165158c1ac42512d4849326b41` | Gate.io API Key |
| `GATE_SECRET` | `a7e5e275ff75d88120af845921b176281c52901053a7ad6787a1c7db188d6e12` | Gate.io API Secret |
| `TELEGRAM_BOT_TOKEN` | `8746796223:AAGBQQJUu2tMSpnUereWPOo4t3lp_o-ejg` | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | `6204659239` | Telegram Chat ID |

### 第3步：修改代码中的配置读取方式

在 `gate_trading_bot.py` 开头添加环境变量读取（替换硬编码）：

```python
import os

GATE_API_KEY = os.getenv('GATE_API_KEY', 'YOUR_GATE_API_KEY')
GATE_SECRET = os.getenv('GATE_SECRET', 'YOUR_GATE_SECRET')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', 'YOUR_CHAT_ID')
```

### 第4步：推送代码到GitHub

```bash
git add .
git commit -m "部署：Gate.io量化交易机器人"
git push origin main
```

### 第5步：启用GitHub Actions

1. 进入GitHub仓库 → **Actions** 标签页
2. 如果看到 "Workflows-all" 提示，点击 **"I understand my workflows, go ahead and enable them"**
3. 工作流文件：`.github/workflows/trading-bot.yml`

### 第6步：配置腾讯元宝定时触发（每15分钟）

腾讯元宝通过HTTP请求触发GitHub Actions的`workflow_dispatch`事件：

**在腾讯元宝中配置定时任务：**

```
请求URL: 
POST https://api.github.com/repos/你的用户名/gate-trading-bot/actions/workflows/trading-bot.yml/dispatches

请求头:
  Accept: application/vnd.github.v3+json
  Authorization: token ghp_你的GitHub_Personal_Access_Token
  Content-Type: application/json

请求体:
  {
    "ref": "main"
  }
```

**获取GitHub Personal Access Token：**
1. GitHub → **Settings** → **Developer settings** → **Personal access tokens** → **Generate new token (Classic)**
2. 勾选 `repo` 权限
3. 生成后复制Token（以 `ghp_` 开头）

**在腾讯元宝中配置：**
- 定时：每15分钟
- 动作：发送上述HTTP POST请求

### 第7步：手动触发测试

```bash
# 使用GitHub CLI测试触发
gh workflow run trading-bot.yml

# 或在GitHub仓库 → Actions → 选择工作流 → Run workflow
```

检查Telegram是否收到通知！

---

## 健康检查时序

```
每隔15分钟：
1. 腾讯元宝 → 发送HTTP POST → GitHub Actions
2. GitHub Actions启动Runner
3. 运行 gate_trading_bot.py
4. 检查市场状态 + 执行策略
5. 发送Telegram通知
6. 超时14分钟后自动停止（等待下一次触发）
```

---

## Telegram通知测试

**在本地测试（需要先解决网络问题）：**

如果你的服务器在国内，无法直接访问 `api.telegram.org`：

### 方案1：使用代理
```python
# 在 TelegramNotifier 类中添加代理
def send_message(self, message: str) -> bool:
    import requests
    proxies = {
        'https': 'http://你的代理地址:端口'
    }
    response = requests.post(self.api_url, json=payload, timeout=10, proxies=proxies)
```

### 方案2：部署到国外服务器
- 将代码部署到国外VPS
- 直接运行，无需代理

### 方案3：使用GitHub Actions（推荐）
- GitHub Actions的Runner在国外
- 可以直接访问 `api.telegram.org`
- **无需代理，Telegram通知开箱即用！**

---

## 常见问题

### Q1：GitHub Actions运行超时？
**A**：工作流设置了 `timeout-minutes: 14`，每隔15分钟会由腾讯元宝重新触发。

### Q2：Telegram收不到通知？
**A**：
1. 确认已向Bot发送过消息（`/start`）
2. 确认Chat ID正确
3. 如果在国内服务器运行，需要配置代理

### Q3：如何查看运行日志？
**A**：
- GitHub仓库 → **Actions** → 选择最近一次运行 → 查看日志
- 日志文件 `trading_bot.log` 会上传为Artifact

### Q4：如何停止交易机器人？
**A**：
1. 在GitHub Actions中禁用工作流
2. 或删除腾讯元宝中的定时任务

---

## 文件清单

```
gate-trading-bot/
├── gate_trading_bot.py        # 主程序
├── test_trading_bot.py        # 测试脚本
├── requirements.txt           # Python依赖
├── README.md                 # 使用说明
├── DEPLOY.md                 # 本文档
└── .github/
    └── workflows/
        └── trading-bot.yml  # GitHub Actions工作流
```

---

## 下一步

1. ✅ 完成GitHub Secrets配置
2. ✅ 修改代码支持环境变量读取
3. ✅ 推送代码到GitHub
4. ✅ 测试GitHub Actions手动触发
5. ✅ 配置腾讯元宝定时触发
6. ✅ 监控Telegram通知

如有问题，随时联系我！ 😊
