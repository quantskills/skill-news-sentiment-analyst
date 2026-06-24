---
name: news-sentiment-analyst
description: A-share financial news sentiment analyst. Collects news from 3 sources (Eastmoney/Futu/Tonghuashun), extracts stock codes/sectors/entities, generates FinGPT-style LLM prompts with 7-step causal reasoning, outputs structured Parquet. Use when user asks to analyze A-share news, extract stock codes from news, generate trading signals from financial news, or when Alpha/agent needs news sentiment data.
---

# News Sentiment Analyst

A 股财经新闻情感分析师 — 采集新闻 → 提取实体 → 生成 LLM prompt → 输出 Parquet

## 工具定位
- 工具类型：数据采集 + 结构化输出 + 信号验证
- 解决问题：从多源财经新闻中提取结构化数据，生成分析师级 LLM prompt，交叉验证信号与实际行情/资金的一致性
- 使用对象：agent / Alpha / 人工分析

## 何时使用

- 用户要求分析当日 A 股新闻、新闻对交易的影响
- 用户要求采集财经新闻并提取股票代码或板块
- Alpha 或 agent 需要新闻情感分析数据
- 用户要求生成新闻驱动的交易信号

## 输出目录

Parquet 文件默认输出到 `output/` 目录，文件名格式：`news_trading_YYYY-MM-DD.parquet`

可通过 `output_dir` 参数自定义输出路径。

## 执行步骤

当你触发此 skill 时，严格按以下步骤执行：

### 第〇步：检查 PandaAI 配置（首次使用）

```python
import sys, os
skill_dir = os.path.expanduser("~/.claude/skills/news-sentiment-analyst/scripts")
if not os.path.exists(skill_dir):
    skill_dir = os.path.join(os.getcwd(), ".claude/skills/news-sentiment-analyst/scripts")
sys.path.insert(0, skill_dir)

from auth import init_pandaai

panda_ok = init_pandaai(verbose=False)
```

如果 `panda_ok` 为 False，向用户说明：

> PandaAI 未配置。配置后可以获取实时股价、融资、北向资金、龙虎榜数据来验证新闻信号。请提供你在 pandaai.online 的手机号和密码，我会写入 .env（该文件不会提交到 GitHub）。

用户提供手机号和密码后，执行：

```python
env_path = os.path.join(os.path.dirname(skill_dir), ".env")
with open(env_path, "w") as f:
    f.write(f"PANDA_DATA_USERNAME={phone}\nPANDA_DATA_PASSWORD={password}\n")
# 重新初始化
init_pandaai()
```

> 用户拒绝或跳过时，直接继续第一步（使用 AKShare 回退数据）。

### 第一步：采集新闻 + 市场背景 + 生成 prompt

```python
from build import run_full_pipeline
from datetime import date

today = date.today().strftime("%Y-%m-%d")

pipeline = run_full_pipeline(
    trade_date=today,
    news_type="all",
    max_news_count=50,
    output_dir="output"
)

print(f"Parquet 路径: {pipeline['parquet_path']}")
print(f"新闻数量: {pipeline['news_count']}")
print(f"待分析 prompt 数: {len(pipeline['prompts'])}")
print(f"涉及股票: {pipeline['summary']['stock_codes_found']}")
print(f"涉及板块: {pipeline['summary']['sectors_found']}")
```

### 第二步：逐条 LLM 打分

对 `pipeline["prompts"]` 中的每条新闻，将 `item["prompt"]` 作为完整 prompt 发送给 LLM（Claude），要求 LLM 返回 JSON 格式的情感分析结果。

**LLM 输出格式要求**（必须严格遵守）：
```json
{"sentiment":"positive/negative/neutral","impact_level":"high/medium/low","trading_direction":"bullish/bearish/hold","confidence":0.0-1.0,"reason":"100字以内的因果推理"}
```

**reason 规范**：必须包含因果推理链条，不能只写"利好/利空"结论。例如：
- ✗ "储能需求增长，利好新能源"
- ✓ "储能刚需是基本面驱动，宁德H股创新高验证逻辑，资金从AI流向新能源的避风港效应正在发生"

**打分方法**：你可以自己作为分析师直接对每条新闻进行 7 步因果推理分析（核心事件→传导路径→时效性→确定性→市场背景→交叉关联→反直觉检查），然后输出 JSON。不需要实际调用外部 LLM API。

### 第三步：写回评分结果

```python
from build import score_single_news

for item in pipeline["prompts"]:
    llm_response = '{"sentiment":"positive",...}'  # 替换为实际 LLM 输出
    score = score_single_news(pipeline["parquet_path"], item["idx"], llm_response)
    print(f"  {item['news_title'][:30]}... → {score['sentiment']} {score['trading_direction']} conf={score['confidence']}")
```

### 第四步：输出选股信号 + PandaAI 验证

```python
from build import generate_signal_list
from pandaai_integration import enrich_signals

signals = generate_signal_list(pipeline['parquet_path'], min_confidence=0.5)
signals = enrich_signals(signals, today)

print(f"## {today} 选股信号列表\n")
print(f"| 股票代码 | 公司名称 | 方向 | 置信度 | 近1日 | 融资 | 龙虎榜 | 质押 | 来源新闻 |")
print(f"|----------|----------|------|--------|-------|------|--------|------|----------|")
for s in signals:
    mark = "🟢" if s["direction"] == "bullish" else "🔴"
    v = s.get("verify", {})
    px = v.get("price", {})
    price_str = f"{px.get('latest_change_pct', '-')}%"
    margin_str = v.get("margin") or "-"
    lhb_str = "🔥" if v.get("lhb") else ""
    pledge = v.get("pledge_risk")
    pledge_str = {"high": "⚠️高", "medium": "中", "low": "低"}.get(pledge, "-")
    print(f"| {s['code']} | {s['name']} | {mark} {s['direction']} | {s['confidence']:.2f} | {price_str} | {margin_str} | {lhb_str} | {pledge_str} | {s['news_title']} |")
print(f"\n共 {len(signals)} 个信号（置信度 >= 0.5）")
```

PandaAI 未配置时 `enrich_signals()` 原样返回，验证列显示 N/A。

## LLM 分析框架（7 步因果推理）

每条新闻的 prompt 要求按以下步骤分析：

1. **核心事件识别**：这条新闻到底说了什么？是事实还是传闻？
2. **传导路径分析**：事件如何传导到股价？（事件→板块→个股）
3. **时效性判断**：影响是即时的还是滞后的？已经反映在股价里了吗？
4. **确定性评估**：信息有多确定？官方公告 > 媒体报道 > 市场传闻
5. **市场背景关联**：结合当日市场背景，这条新闻在当前环境下意味着什么？
6. **交叉关联**：和其他新闻有没有关联？形成共振还是对冲？
7. **反直觉检查**：表面看是利好/利空，但实际呢？有没有"利好出尽"的可能？

## 参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| trade_date | string | 交易日期 YYYY-MM-DD（必填） |
| news_type | string | macro / industry / company / all（默认 all） |
| target_id | string | 股票代码（可选，获取个股新闻） |
| max_news_count | int | 最大新闻条数（默认 50） |
| output_dir | string | 输出目录（默认 "output"） |

## 输出结构

Parquet 字段：trade_date, build_id, build_name, target_id, result_type, result_value, result_json, source_data_date, data_version, update_time

- `news_analysis` 记录：每条新闻的提取数据 + 市场背景 + 关联新闻 + LLM prompt
- `summary` 记录：当日汇总（股票列表、板块统计）
- `result_value`：打分前为 `pending_ai_analysis`，打分后为 `data_ready`
- `result_json.llm_score`：打分后的 LLM 评分结果

详见 [references/api_guide.md](references/api_guide.md)

## 可被 Alpha 调用
- 是
- 调用限制：需联网访问 AKShare 接口；AKShare 有频率限制，建议请求间隔 1-2 秒
- 依赖数据：AKShare 实时新闻接口（东方财富/富途/同花顺）

## 是否需要生产结果
- 是否生成 `数据库.parquet`：是
- 更新频率：每日收盘后
- 文件路径：`output/news_trading_YYYY-MM-DD.parquet`（可通过 output_dir 参数自定义）

## 依赖

### 核心依赖（必需）
- akshare >= 1.10.0
- pandas >= 1.5.0
- pyarrow >= 10.0.0

安装：`pip install akshare pandas pyarrow`

### PandaAI 数据服务

```bash
# 安装 SDK
pip install panda_data

# 配置凭证
cp .env.example .env
# 编辑 .env 填入:
#   PANDA_DATA_USERNAME=86你的手机号
#   PANDA_DATA_PASSWORD=你的密码

# 验证
python scripts/pandaai_integration.py --market-scan
```

> Elite 套餐(¥153/月)含融资融券+北向资金+龙虎榜+财务数据。注册: https://www.pandaai.online/data-service

## 注意事项

- AKShare 接口有频率限制，请求间隔 1-2 秒
- 新闻为实时快照，不含历史数据
- 按标题自动去重
- 市场背景数据自动采集（大盘指数、板块涨跌）
- 关联新闻自动匹配（同板块或同股票的其他新闻）
- `.env` 文件已加入 `.gitignore`，不会被提交到 GitHub
- 数据源详见 [references/data_sources.md](references/data_sources.md)
