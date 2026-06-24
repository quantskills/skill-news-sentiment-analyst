# News Sentiment Analyst — 设计评审与质量分析

## 项目概览

| 维度 | 评级 | 说明 |
|------|:----:|------|
| 架构设计 | ⭐⭐⭐⭐⭐ | 三层清晰：AKShare(采集) → Skill(结构化) → PandaAI(验证) |
| 代码质量 | ⭐⭐⭐⭐☆ | 类型提示较好，错误处理到位，认证模块简洁 |
| 测试覆盖 | ⭐⭐⭐⭐⭐ | 10 测试模块 30+ 用例，覆盖全链路 |
| Skill 规范 | ⭐⭐⭐⭐⭐ | SKILL.md 含 5 步执行流程，含 PandaAI 交叉验证 |
| 文档完整度 | ⭐⭐⭐⭐⭐ | README + SKILL + SUMMARY + API 指南 + 数据源 + PandaAI 目录 |
| 生产就绪度 | ⭐⭐⭐⭐☆ | 核心 + 验证完备，未加 API 限流 |

---

## 架构设计

```
                      ┌─ 数据采集 ─┐  ┌─ 信号验证 ──────────────┐
                      │  AKShare    │  │  PandaAI                  │
                      │  3源新闻    │  │  get_stock_daily  价格    │
                      │  股票映射   │  │  get_margin       融资    │
                      │  指数/板块  │  │  get_hsgt_hold    北向    │
                      │  (免费)     │  │  get_lhb_list     龙虎榜  │
                      └─────┬──────┘  │  (付费, ¥63-153/月)       │
                            │         └──────────┬───────────────┘
                            ▼                    ▼
┌─ build.py ────────────────────┐  ┌─ pandaai_integration.py ───┐
│  validate_input()             │  │  verify_signal()   4维验证  │
│  collect_news()     ← 3源    │  │  backtest()        批量回测 │
│  extract_stock_codes_from_text│  │  market_scan()     市场全景 │
│  extract_sectors_from_text()  │  │  _get_client()     auth模块 │
│  extract_key_entities()       │  └────────────────────────────┘
│  structure_news_for_ai()      │
│  save_to_parquet()            │  ┌─ sentiment.py ─────────────┐
│  score_single_news()          │  │  generate_llm_prompt()     │
│  generate_signal_list()       │  │  parse_llm_response()      │
│  run() / run_full_pipeline()  │  │  FEW_SHOT_EXAMPLES         │
└───────────────────────────────┘  │  SYSTEM_PROMPT             │
                                   └────────────────────────────┘
┌─ auth.py ─────────────────┐  ┌─ test.py ─────────────────────┐
│  init_pandaai()           │  │  10 模块 30+ 用例              │
│  require_panda()          │  │  含输入校验 → LLM解析全链路   │
│  .env 自动加载            │  └───────────────────────────────┘
└───────────────────────────┘
```

**核心设计决策：**
- **Skill 不做决策，只做数据** — 采集和结构化由 Python 完成，分析和打分由 LLM/Agent 完成
- **Parquet 作为 Skill↔Agent 契约** — 10 字段 schema，`pending_ai_analysis` → `data_ready` 状态机
- **验证层与采集层解耦** — 各层独立可替换，PandaAI 未配置时降级跳过
- **凭证单一来源** — 环境变量 + `.env` 文件，无硬编码，已 gitignore

---

## 模块清单

| 文件 | 行数 | 职责 |
|------|:----:|------|
| `scripts/build.py` | 700 | 核心引擎：采集、提取、结构化、Parquet 读写、信号生成、市场背景 |
| `scripts/sentiment.py` | 202 | LLM prompt 生成（含 4 Few-shot + 7步CoT）+ 响应解析（4格式降级） |
| `scripts/auth.py` | 124 | PandaAI 凭证管理：`.env` 加载 → `panda_data.init_token()` |
| `scripts/pandaai_integration.py` | 399 | 交叉验证引擎：verify_signal / backtest / market_scan |
| `scripts/test.py` | 470 | 10 模块测试，覆盖输入校验到 LLM 解析全链路 |
| `SKILL.md` | ~195 | Claude Code skill 定义：5 步执行流程 |
| `README.md` | ~350 | 完整项目文档：安装 / 快速开始 / 架构 / 验证 / 测试 |
| `references/api_guide.md` | 171 | API 调用示例、字段说明、选股信号接口 |
| `references/data_sources.md` | 66 | AKShare 接口速查 |
| `references/pandaai_api_list.md` | 148 | PandaAI 80+ 函数完整目录 + 相关性标注 |

---

## 亮点

### 1. 三层数据架构
AKShare（免费采集） → Skill（结构化） → PandaAI（付费验证），每层独立可替换。

### 2. LLM Prompt 工程
7 步 CoT + 4 Few-shot（利好/利空/中性/反直觉），置信度 4 档标准。

### 3. LLM 响应解析鲁棒性
`parse_llm_response()` 支持 4 种格式降级：纯 JSON → markdown 代码块 → 混合文本提取 → 安全默认值。字段值自动标准化。

### 4. 凭证管理设计
- `.env.example` 提交（空模板），`.env` gitignore
- `auth.py` 自动从环境变量或 `.env` 加载
- 未配置时打印带路径的友好提示框
- `panda_data.init_token(username="86手机号", password="密码")` 唯一登录方式

### 5. 交叉验证引擎
`backtest()` 用实际股价逐条验证 LLM 信号，输出 confidence 分桶胜率对照表。

### 6. 容错设计
每个数据源独立 try/except；PandaAI 不可用时交叉验证静默跳过。

---

## 接口契约

```
# 核心管线
run(input_data, config?) → result
run_full_pipeline(trade_date, ...) → { parquet_path, news_count, prompts, summary }
score_single_news(parquet_path, idx, llm_response) → score
generate_signal_list(parquet_path, min_confidence?) → signals

# PandaAI 验证
init_pandaai() → bool
verify_signal(symbol, sentiment, confidence, date) → 4维验证结果
backtest(parquet_path) → pd.DataFrame (confidence分桶胜率表)
market_scan(trade_date) → 指数+北向+龙虎榜全景
```

---

## 依赖

| 包 | 版本 | 用途 | 必需 |
|----|------|------|:----:|
| `akshare` | >= 1.10.0 | A 股新闻+行情+映射 | ✓ |
| `pandas` | >= 1.5.0 | 数据处理 + Parquet | ✓ |
| `pyarrow` | >= 10.0.0 | Parquet 引擎 | ✓ |
| `panda_data` | latest | 价格/融资/北向/龙虎榜 | ✓ |

---

## 改进状态

| # | 问题 | 状态 |
|---|------|:----:|
| 1 | AKShare 无内置限流 | ⬜ TODO |
| 2 | `stock_news_em` pyarrow 兼容性 | ⬜ TODO |
| 3 | API 错误聚合返回 | ⬜ TODO |
| 4 | 日志级别可配置 | ⬜ TODO |
| 5 | 板块关键词提取为配置 | ⬜ TODO |
| 6 | `collect_news()` 拆分 | ⬜ TODO |
| 7 | 股票映射缓存 | ⬜ TODO |
| 8 | 英文版 README | ⬜ TODO |
| 9 | 信号验证引擎 | ✅ 已完成 (PandaAI) |
| 10 | 凭证管理 | ✅ 已完成 (auth.py + .env) |

---

## 设计原则验证

- ✅ **单一职责**：Skill 做数据，AI 做分析，PandaAI 做验证
- ✅ **容错降级**：单源失败不影响整体，PandaAI 不可用时静默降级
- ✅ **契约驱动**：Parquet schema 是 Skill↔Agent 的稳定接口
- ✅ **可观测性**：logging 覆盖所有关键路径
- ✅ **可测试性**：每个模块独立可测，30 用例覆盖全链路
- ✅ **安全性**：凭证不入库，`.env` gitignore
- ✅ **零歧义**：PandaAI 认证只有一种方式，无选择负担

---

## 总结

**v1.2 — 从"新闻打分工具"升级为"信号验证平台"。**

核心改进：增加了 PandaAI 交叉验证层，解决了原始设计中"LLM confidence 无法验证"的根本缺陷。`backtest()` 函数用实际股价逐条对照信号，输出 confidence 分桶胜率 — 用户可以直接看到 LLM 的 0.85 到底值多少钱。

架构保持三层解耦：免费采集（AKShare）→ 结构化 + LLM 推理（Skill）→ 付费验证（PandaAI）。每一层可独立使用或替换。
