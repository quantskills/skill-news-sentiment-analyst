# 📰 News Sentiment Analyst

A 股财经新闻 → 结构化数据 → LLM 情感分析 → 多维度交叉验证

[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://www.python.org/)
[![akshare](https://img.shields.io/badge/akshare-latest-green)](https://github.com/akfamily/akshare)
[![pandas](https://img.shields.io/badge/pandas-latest-green)](https://pandas.pydata.org/)
[![pyarrow](https://img.shields.io/badge/pyarrow-latest-green)](https://arrow.apache.org/)
[![tests](https://img.shields.io/badge/tests-30%20passed-success)]()
[![license](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE.txt)

[安装](#-安装)  |  [快速开始](#-快速开始)  |  [架构](#-架构)  |  [信号验证](#-信号验证)  |  [测试](#-测试)

---

## 🎯 功能概述

```
 东方财富(200)                           ┌──────────────┐
 富途牛牛(50)       ──→  提取实体  ──→   │  Parquet 输出  │  ──→  Agent + LLM  ──→  交易信号
 同花顺(20)            (股票/板块/实体)   │  (结构化数据)  │       (7步因果推理)
                                         └──────┬───────┘
                                                │
                              ┌─────────────────▼─────────────────┐
                              │  PandaAI 交叉验证（可选增强）       │
                              │  价格回测 │ 融资融券 │ 北向 │ 龙虎榜 │
                              └───────────────────────────────────┘
```

**设计原则：** Skill 负责数据采集和结构化，AI 负责分析和决策，PandaAI 负责信号验证。

---

## ✨ 核心能力

### 🔍 多源采集
| 数据源 | API | 条数 | 特点 |
|--------|-----|------|------|
| 东方财富 | `ak.stock_info_global_em()` | 200 | 全球快讯，覆盖广 |
| 富途牛牛 | `ak.stock_info_global_futu()` | 50 | 港美股视角 |
| 同花顺 | `ak.stock_info_global_ths()` | 20 | 实时直播，时效性强 |

按标题自动去重，约 225 条独立新闻。

### 🧠 智能提取
- **股票代码：** 正则 + 5500 只股票名称匹配
- **板块识别：** 10 大板块关键词匹配
- **实体提取：** 数字 / 日期 / 政策 / 事件
- **关联新闻：** 跨板块自动关联

### 📈 LLM Prompt
- 15 年 A 股量化分析师人设
- 7 步因果推理 Chain-of-Thought
- 4 个 Few-shot 示例（含反直觉案例）
- 结构化 JSON 输出 + 置信度评分

### 📦 标准输出
- Parquet 格式，10 个标准字段
- `result_json` 包含完整 prompt
- 支持增量打分写回
- 稳定主键设计

### 📶 选股信号
- 基于新闻情感自动生成买卖信号
- 股票代码 + 公司名称严格对应
- 置信度过滤（默认 >= 0.5）
- 按置信度降序排列

### 🔬 信号验证（PandaAI 可选增强）
- **价格回测：** 次日实际涨跌 vs LLM 预测方向
- **资金流向：** 融资余额 + 北向资金是否同向
- **内部人信号：** 业绩预告 / 回购 / 增减持
- **游资动向：** 龙虎榜上榜情况

---

## 🚀 安装

> 仓库本身即是 skill 目录 — clone 后直接复制到 Claude Code 的 skills 路径即可。

### 方式一：openskills（推荐）

```bash
npm install -g openskills
openskills install quantskills/news-sentiment-analyst
```

### 方式二：全局安装

```bash
git clone https://github.com/quantskills/news-sentiment-analyst.git
cp -r news-sentiment-analyst ~/.claude/skills/
pip install -r ~/.claude/skills/news-sentiment-analyst/requirements.txt
```

### 方式三：项目级安装

```bash
git clone https://github.com/quantskills/news-sentiment-analyst.git
mkdir -p .claude/skills
cp -r news-sentiment-analyst .claude/skills/
pip install -r .claude/skills/news-sentiment-analyst/requirements.txt
```

> ℹ️ 安装后重启 Claude Code，skill 将被自动发现。

### PandaAI 增强（可选）

```bash
# 安装 SDK + 配置凭证
pip install panda_data
cp ~/.claude/skills/news-sentiment-analyst/.env.example ~/.claude/skills/news-sentiment-analyst/.env
# 编辑 .env 填入手机号和密码
```

> Elite 套餐(¥153/月)含融资融券+北向资金+龙虎榜+财务数据。

### 验证安装

```bash
ls ~/.claude/skills/news-sentiment-analyst/
# 应显示：SKILL.md  scripts/  references/  .env.example  ...

cd ~/.claude/skills/news-sentiment-analyst/scripts
python test.py
```

---

## ⚡ 快速开始

### 通过 Claude Code

安装后，直接对 Claude 说：

> "分析今日 A 股新闻及其对交易的影响"

Claude 会自动触发 skill：采集 → 提取 → 打分 → 报告。

### 通过 Python 代码

```python
import sys, os
sys.path.insert(0, os.path.expanduser("~/.claude/skills/news-sentiment-analyst/scripts"))

from build import run_full_pipeline, score_single_news

# 1. 采集新闻 + 市场背景，生成 prompt
pipeline = run_full_pipeline(
    trade_date="2026-05-29",
    news_type="all",
    max_news_count=50,
    output_dir="output"
)

# 2. 逐条 LLM 打分
for item in pipeline["prompts"]:
    prompt = item["prompt"]
    llm_response = "<LLM JSON response>"
    score = score_single_news(pipeline["parquet_path"], item["idx"], llm_response)
    print(f"  {item['news_title'][:30]}... → {score['sentiment']} {score['trading_direction']}")

# 3. 回测信号胜率（需配置 PandaAI）
from pandaai_integration import backtest
backtest(pipeline["parquet_path"])
```

---

## 🧠 LLM 分析框架

每条新闻的 prompt 要求 LLM 按 **7 步因果推理** 分析：

| 步骤 | 内容 | 说明 |
|------|------|------|
| 1 | 核心事件 | 事实还是传闻？新信息还是旧信息？ |
| 2 | 传导路径 | 事件 → 板块 → 个股，如何传导？ |
| 3 | 时效性 | 即时影响还是滞后？已反映在股价中？ |
| 4 | 确定性 | 官方公告 > 媒体报道 > 市场传闻 |
| 5 | 市场背景 | 当前环境下是雪上加霜还是逆势利好？ |
| 6 | 交叉关联 | 和其他新闻形成共振还是对冲？ |
| 7 | 反直觉检查 | 表面利好实际利空？"利好出尽"？ |

### 输出格式

```json
{
    "sentiment": "positive / negative / neutral",
    "impact_level": "high / medium / low",
    "trading_direction": "bullish / bearish / hold",
    "confidence": 0.85,
    "reason": "100字以内的因果推理"
}
```

---

## 🏗️ 架构

```
┌─ AKShare (免费新闻) ────────────┐  ┌─ PandaAI (付费验证) ──────────┐
│  stock_info_global_em()  200条  │  │  get_stock_daily()   日线回测  │
│  stock_info_global_futu() 50条  │  │  get_margin()        融资融券  │
│  stock_info_global_ths()  20条  │  │  get_hsgt_hold()     北向资金  │
│  stock_board_industry_name_em() │  │  get_lhb_list()      龙虎榜    │
└───────────┬─────────────────────┘  └────────────┬───────────────────┘
            │                                     │
            ▼                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│  build.py — 核心引擎                                                 │
│  validate → collect → extract → structure → prompt → save → score   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Agent 层 (Claude / LLM)                                            │
│  读取 prompt → 7步CoT推理 → 写回评分 → generate_signal_list()       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  pandaai_integration.py — 交叉验证                                   │
│  verify_signal() → backtest() → confidence vs 实际胜率对照表         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📤 输出格式

### Parquet 输出目录

```
output/news_trading_YYYY-MM-DD.parquet
```

默认输出到 `output/` 目录，可通过 `output_dir` 参数自定义。

### Parquet 字段

| 字段 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `trade_date` | 视情况 | string | 交易日期 YYYY-MM-DD |
| `build_id` | ✓ | string | NSA |
| `build_name` | ✓ | string | News Sentiment Analyst |
| `target_id` | | string | 股票代码或 板块_news_id |
| `result_type` | ✓ | string | news_analysis / summary |
| `result_value` | ✓ | string | pending_ai_analysis → data_ready |
| `result_json` | | string | 完整新闻数据 + LLM prompt + llm_score |
| `source_data_date` | | string | 原始数据日期 |
| `data_version` | ✓ | string | 1.0.0 |
| `update_time` | ✓ | string | 结果生成时间 |

### 选股信号列表

```python
from build import generate_signal_list

signals = generate_signal_list("output/news_trading_2026-05-30.parquet", min_confidence=0.5)
```

输出格式：

```json
[
    {
        "code": "300750",
        "name": "宁德时代",
        "direction": "bullish",
        "confidence": 0.75,
        "sentiment": "positive",
        "impact_level": "high",
        "reason": "换电站扩张超预期，验证商业模式可行性",
        "news_title": "宁德时代：巧克力换电累计落站..."
    }
]
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | string | 股票代码（6 位） |
| `name` | string | 公司名称 |
| `direction` | string | bullish / bearish |
| `confidence` | float | 置信度 0.0-1.0 |
| `sentiment` | string | positive / negative / neutral |
| `impact_level` | string | high / medium / low |
| `reason` | string | 分析理由（截断 80 字） |
| `news_title` | string | 来源新闻标题（截断 30 字） |

---

## 🔬 信号验证（PandaAI 增强）

**解决核心问题：LLM 的 confidence 是自我感觉还是真有预测力？**

### 4 维度交叉验证

| 维度 | PandaAI 函数 | 验证什么 |
|------|-------------|---------|
| 价格 | `get_stock_daily` | LLM 说 bullish，次日真的涨了吗？ |
| 资金 | `get_margin` / `get_hsgt_hold` | 杠杆资金和北向是否同向？ |
| 内部人 | `get_fina_forecast` / `get_repurchase` | 有业绩预告/回购/增减持支撑吗？ |
| 游资 | `get_lhb_list` | 龙虎榜上榜了吗？ |

### 使用

```bash
# 配置凭证
cp .env.example .env
# 编辑 .env 填入手机号和密码

# 单股验证
python scripts/pandaai_integration.py --verify --symbol 000001.SZ --date 2026-06-25

# 市场全景
python scripts/pandaai_integration.py --market-scan --date 2026-06-25

# 批量回测
python scripts/pandaai_integration.py --backtest output/news_trading_2026-06-25.parquet
```

### 回测输出示例

```
================================================================
  回 测 结 果
================================================================
  信号总数: 45
  整体胜率: 53.3%

     bullish:   28 条  胜率 50.0%
     bearish:   17 条  胜率 58.8%

  confidence 分桶:
  [0.8-1.0):   12 条  胜率 58.3%  ███████████
  [0.5-0.8):   22 条  胜率 54.5%  ██████████
  [0.2-0.5):    8 条  胜率 37.5%  ███████
  [0.0-0.2):    3 条  胜率 66.7%  █████████████
================================================================
```

> `.env` 已加入 `.gitignore`，不会被提交。详细 API 列表见 [pandaai_api_list.md](references/pandaai_api_list.md)。

---

## 🗃️ 项目结构

```
news-sentiment-analyst/
├── SKILL.md                       ← Claude Code skill 定义（必需）
├── README.md                      ← 项目文档
├── SUMMARY.md                     ← 设计评审与质量分析
├── LICENSE.txt                    ← Apache 2.0 许可证
├── .openskills.json               ← openskills 元数据
├── .env.example                   ← PandaAI 凭证模板（.env 已 gitignore）
├── .gitignore
├── requirements.txt               ← Python 依赖
├── scripts/
│   ├── build.py                   ← 核心引擎：采集 + 提取 + 结构化 + Parquet
│   ├── sentiment.py               ← LLM prompt 生成 + 响应解析
│   ├── auth.py                    ← PandaAI 凭证管理
│   ├── pandaai_integration.py     ← 交叉验证 + 批量回测引擎
│   └── test.py                    ← 测试脚本（30 个用例）
├── references/
│   ├── api_guide.md               ← API 调用文档
│   ├── data_sources.md            ← AKShare 数据源说明
│   └── pandaai_api_list.md       ← PandaAI 完整 API 目录
└── output/                         ← Parquet 输出（已 gitignore）
```

---

## 🧪 测试

```bash
cd scripts
python test.py
```

```
======================================================================
测试汇总
======================================================================
  通过: 30
  失败: 0
  总计: 30

  ✓ 所有测试通过！
```

| 测试 | 覆盖内容 |
|------|----------|
| `test_validate_input` | 正常输入、缺少字段、错误格式、错误类型 |
| `test_stock_code_extraction` | 正则提取、名称匹配、无代码文本 |
| `test_sector_extraction` | 10 大板块关键词匹配、无板块回退 |
| `test_entity_extraction` | 数字 / 日期 / 政策 / 事件 |
| `test_news_structuring` | 完整结构化流水线 + prompt 生成 |
| `test_parquet_output` | Parquet 字段完整性验证 |
| `test_agent_call` | run() 标准入口 |
| `test_full_flow` | 端到端流水线 |
| `test_llm_prompt_generation` | CoT 引导 + few-shot + JSON 格式 |
| `test_llm_response_parsing` | 标准 JSON / markdown / 混合文本 / 无效输入 / 字段标准化 |

---

## ⚙️ 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `trade_date` | string | 必填 | 交易日期 YYYY-MM-DD |
| `news_type` | string | `all` | macro / industry / company / all |
| `target_id` | string | None | 股票代码（获取个股新闻） |
| `max_news_count` | int | 50 | 最大新闻条数 |
| `output_dir` | string | `output` | 输出目录 |

---

## 🌏 数据源

### 新闻采集（AKShare — 免费，无需注册）

| 数据源 | API | 条数 |
|--------|-----|:----:|
| 东方财富 | `ak.stock_info_global_em()` | 200 |
| 富途牛牛 | `ak.stock_info_global_futu()` | 50 |
| 同花顺 | `ak.stock_info_global_ths()` | 20 |

详见 [data_sources.md](references/data_sources.md)。

### 信号验证（PandaAI — 可选付费）

| 套餐 | 月费 | 包含数据 |
|------|:----:|------|
| Pro | ¥63 | A股日线 + 指数 + 公司行为 |
| Elite | ¥153 | 含融资融券 + 北向 + 龙虎榜 + 财务 |

详见 [pandaai_api_list.md](references/pandaai_api_list.md)。

---

## ⚠️ 注意事项

- AKShare 接口有频率限制，建议请求间隔 1-2 秒
- 新闻为实时快照，不支持历史数据
- 按标题自动去重，跨源同一条新闻只保留一条
- 市场背景自动采集（免费数据来自 AKShare，增强数据来自 PandaAI）
- 关联新闻自动匹配（同板块或同股票的其他新闻）
- PandaAI 为可选增强，未配置时不影响核心新闻采集
- `.env` 文件已加入 `.gitignore`，凭证不会被提交

> **免责声明：** 本项目不构成任何形式的证券投资咨询或建议。项目所有输出，包括但不限于任何交易方向、标的筛选，仅为算法逻辑的示例性展示，不代表任何投资建议或承诺。明确反对使用者将本项目输出用于真实交易。任何使用者因参考本项目代码、逻辑或示例输出而进行真实交易，必须自行承担由此产生的全部盈亏和法律风险。本项目的作者的实盘操作与任何公开的代码及示例无关。本项目不提供任何形式的实时信号推送服务，不建立任何投资交流群组。

---

## 📄 许可证

[Apache 2.0](LICENSE.txt)
