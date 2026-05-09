# Gate.io 全自动量化交易机器人

基于CCXT库的Gate.io交易所量化交易系统，支持市场状态识别、趋势/网格混合策略和完整风控管理。

## 📋 目录

- [功能特性](#功能特性)
- [环境依赖](#环境依赖)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [策略逻辑](#策略逻辑)
- [风控机制](#风控机制)
- [健康检查](#健康检查)
- [注意事项](#注意事项)

---

## 功能特性

### 1. 市场状态识别 (`detect_market_regime`)
自动判断当前市场状态，基于以下指标：

| 指标 | 用途 |
|------|------|
| **ADX** (平均趋向指数) | 判断趋势强度 (ADX > 25 为强趋势) |
| **EMA** (指数移动平均线) | 判断趋势方向 (EMA20 vs EMA50) |
| **布林带宽度** | 判断市场波动性 (宽度 < 0.05 为震荡) |
| **RSI** (相对强弱指数) | 判断超买超卖 (RSI < 30 超卖, > 70 超买) |

**市场状态分类：**
- `trending_up` - 趋势向上
- `trending_down` - 趋势向下
- `ranging` - 震荡市
- `high_volatility` - 高波动市场
- `oversold_rebound` - 超卖反弹

### 2. 策略自动切换

| 市场状态 | 执行策略 | 操作逻辑 |
|----------|----------|----------|
| `trending_up` | 趋势跟踪 | EMA20 > EMA50 且价格 > EMA20 时做多 |
| `trending_down` | 趋势跟踪 | EMA20 < EMA50 且价格 < EMA20 时平仓 |
| `ranging` | 网格交易 | 在布林带区间内低买高卖 |
| `oversold_rebound` | 逆向策略 | RSI < 30 时小仓位建仓，RSI > 70 时平仓 |
| `high_volatility` | 观望 | 暂停交易，等待市场稳定 |

### 3. 风控模块

- ✅ **止损保护**: 单笔亏损超过 -3% 自动平仓
- ✅ **仓位限制**: 最大持仓 0.005 BTC
- ✅ **分仓策略**: 正常买入使用50%资金，超卖反弹使用20%资金
- ✅ **杠杆控制**: 默认4倍杠杆 (可在配置中修改)

### 4. 健康检查接口

Flask Web服务，提供实时监控：

```
GET http://0.0.0.0:8080/health
```

**返回示例：**
```json
{
  "status": "running",
  "regime": "trending_up",
  "position": 0.003,
  "timestamp": "2024-01-15T10:30:00"
}
```

---

## 环境依赖

### 安装Python依赖

```bash
pip install ccxt pandas numpy flask
```

### 依赖库说明

| 库名 | 版本建议 | 用途 |
|------|----------|------|
| `ccxt` | >= 4.0.0 | 连接加密货币交易所API |
| `pandas` | >= 2.0.0 | 数据处理和技术指标计算 |
| `numpy` | >= 1.24.0 | 数值计算 |
| `flask` | >= 2.3.0 | 提供健康检查Web服务 |

---

## 快速开始

### 步骤 1: 配置API密钥

打开 `gate_trading_bot.py`，找到配置部分（第13-14行），替换为你自己的Gate.io API密钥：

```python
# API密钥配置 (请替换为你的实际密钥)
GATE_API_KEY = "YOUR_GATE_API_KEY"  # 替换为你的Gate.io API Key
GATE_SECRET = "YOUR_GATE_SECRET"    # 替换为你的Gate.io Secret
```

**⚠️ 安全提示：**
- 建议使用**只读+交易权限**的API Key，不要开启提现权限
- 不要将API密钥提交到公开代码仓库

### 步骤 2: 调整交易参数 (可选)

根据你的需求修改以下参数：

```python
SYMBOL = "BTC/USDT"          # 交易对 (可改为 ETH/USDT, SOL/USDT 等)
TIMEFRAME = "15m"            # K线周期 (建议 5m, 15m, 1h)
LEVERAGE = 4                 # 杠杆倍数
MAX_POSITION = 0.005         # 最大持仓量 (BTC)
STOP_LOSS_PCT = -0.03        # 止损百分比 (-3%)
```

### 步骤 3: 运行脚本

```bash
python gate_trading_bot.py
```

### 步骤 4: 检查运行状态

**方法1: 查看日志输出**
```bash
tail -f trading_bot.log
```

**方法2: 访问健康检查接口**
```bash
curl http://localhost:8080/health
```

---

## 配置说明

### 主要配置参数

#### 交易配置
```python
SYMBOL = "BTC/USDT"          # 交易对
TIMEFRAME = "15m"            # K线周期 (1m, 5m, 15m, 1h, 4h, 1d)
LEVERAGE = 4                 # 杠杆倍数 (1-10)
MAX_POSITION = 0.005         # 最大持仓量 (BTC)
```

#### 风控配置
```python
STOP_LOSS_PCT = -0.03        # 止损百分比 (-3% 表示亏损3%止损)
MIN_RR_RATIO = 1.5          # 最小盈亏比 (未启用，可扩展)
TARGET_PROFIT_PCT = 0.03    # 目标利润 (3%)
```

#### 网格交易配置
```python
GRID_NUM = 10                # 网格数量 (将价格区间分为10格)
GRID_PRICE_RANGE = 0.02     # 网格价格范围 (±2%)
```

#### 策略参数
```python
TREND_ADX_THRESHOLD = 25    # ADX趋势判断阈值 (ADX > 25 为强趋势)
RSI_OVERSOLD = 30           # RSI超卖阈值
RSI_OVERBOUGHT = 70         # RSI超买阈值
BB_WIDTH_THRESHOLD = 0.05   # 布林带宽度阈值 (宽度 < 0.05 为震荡市)
```

---

## 策略逻辑

### 市场状态识别流程

```
┌─────────────────────────────────────────────────────┐
│               detect_market_regime()                │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
         ┌────────────────────────────────────┐
         │  计算技术指标:                     │
         │  - ADX (趋势强度)                 │
         │  - RSI (超买超卖)                 │
         │  - EMA20/EMA50 (趋势方向)        │
         │  - 布林带宽度 (波动性)           │
         └────────────────────────────────────┘
                          │
                          ▼
         ┌────────────────────────────────────┐
         │  ADX > 25 ?                        │
         └────────────────────────────────────┘
              │ Yes              │ No
              ▼                  ▼
   ┌────────────────────┐  ┌────────────────────┐
   │ 判断趋势方向:      │  │ 布林带宽度 < 0.05? │
   │ - EMA20 > EMA50?   │  └────────────────────┘
   │   → trending_up    │       │ Yes    │ No
   │ - EMA20 < EMA50?   │       ▼        ▼
   │   → trending_down   │   ranging  high_volatility
   └────────────────────┘
                          │
                          ▼
         ┌────────────────────────────────────┐
         │  RSI < 30 ? (且非强下跌趋势)      │
         └────────────────────────────────────┘
                          │ Yes
                          ▼
                   oversold_rebound
```

### 策略切换逻辑

```python
if regime == 'trending_up':
    # 趋势向上 → 做多
    if current_price > EMA20 and EMA20 > EMA50:
        return 'buy'

elif regime == 'trending_down':
    # 趋势向下 → 平仓
    if current_position:
        return 'sell'

elif regime == 'ranging':
    # 震荡市 → 网格交易
    if price_in_low_grid:
        return 'buy'
    elif price_in_high_grid:
        return 'sell'

elif regime == 'oversold_rebound':
    # 超卖反弹 → 小仓位建仓
    if rsi < 30 and not current_position:
        return 'buy_small'  # 使用20%资金
```

---

## 风控机制

### 1. 止损保护

每次策略执行时，会自动检查是否触发止损：

```python
def check_stop_loss(self, current_price: float) -> bool:
    loss_pct = (current_price - self.entry_price) / self.entry_price
    
    if loss_pct <= STOP_LOSS_PCT:  # -3%
        self.execute_signal('sell', current_price)
        return True
    return False
```

### 2. 仓位限制

- **最大持仓**: `MAX_POSITION = 0.005 BTC`
- **正常买入**: 使用50%可用USDT
- **小仓位买入**: 使用20%可用USDT (用于超卖反弹)

```python
if amount > MAX_POSITION:
    amount = MAX_POSITION  # 限制最大持仓
```

### 3. 杠杆控制

默认使用4倍杠杆，可在配置中修改：

```python
LEVERAGE = 4  # 修改此项调整杠杆倍数
```

**⚠️ 警告**: 高杠杆会放大收益和亏损，请谨慎设置！

---

## 健康检查

### 启动Flask服务

脚本启动时会自动在后台启动Flask健康检查服务：

```python
# 启动健康检查服务 (后台线程)
flask_thread = threading.Thread(target=run_flask_app, daemon=True)
flask_thread.start()
```

### 访问健康检查接口

```bash
# 使用curl
curl http://localhost:8080/health

# 使用浏览器
打开 http://localhost:8080/health
```

### 返回字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | 机器人状态 (`running` 或 `stopped`) |
| `regime` | string | 当前市场状态 (`trending_up`, `ranging`, 等) |
| `position` | float | 当前持仓量 (BTC), 无持仓为 `null` |
| `timestamp` | string | 时间戳 (ISO 8601格式) |

---

## 注意事项

### ⚠️ 风险警告

1. **量化交易有风险，入市需谨慎！**
   - 本脚本仅供学习研究使用
   - 实盘交易前请务必进行充分回测
   - 建议先使用少量资金测试

2. **API密钥安全**
   - 不要将API密钥硬编码在代码中并提交到公开仓库
   - 建议使用环境变量或配置文件存储密钥
   - 只开启必要的API权限 (交易权限，不要开启提现权限)

3. **市场风险控制**
   - 加密货币市场规模波动剧烈
   - 建议设置合理的止损和仓位管理策略
   - 不要在单一策略上投入全部资金

### 📝 扩展建议

1. **添加更多交易对**
   - 修改 `SYMBOL` 参数
   - 可扩展为多交易对并行监控 (需要使用多线程/异步)

2. **优化策略参数**
   - 使用历史数据回测，找到最优参数组合
   - 可考虑使用机器学习优化参数

3. **增强风控**
   - 添加每日最大亏损限制
   - 添加异常市场检测 (如闪崩保护)
   - 添加资金利用率监控

4. **改进日志记录**
   - 将交易记录保存到数据库
   - 添加实时监控面板 (如Grafana)

### 🐛 常见问题

**Q1: 获取K线数据失败？**
- 检查API密钥是否正确
- 检查网络连接
- 确认交易对名称正确 (如 `BTC/USDT`)

**Q2: 订单创建失败？**
- 检查账户余额是否充足
- 检查最小交易数量限制
- 检查API权限是否开启交易权限

**Q3: 健康检查接口无法访问？**
- 检查防火墙设置，确保8080端口可访问
- 检查Flask服务是否成功启动 (查看日志)

---

## 许可证

MIT License

## 作者

量化交易开发团队

## 更新日志

- **v1.0** (2024-01-15): 初始版本
  - 实现市场状态识别
  - 实现趋势/网格混合策略
  - 实现风控模块
  - 实现健康检查接口
