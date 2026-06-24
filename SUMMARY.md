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
| `scripts/build.py` | 713 | 核心引擎：采集→提取→PandaAI增强→结构化→Parquet→信号生成 |
| `scripts/sentiment.py` | 226 | 数据感知 LLM prompt（7步CoT含数据交叉验证 + 4 Few-shot）+ 响应解析 |
| `scripts/auth.py` | 124 | PandaAI 凭证管理：`.env` → `panda_data.init_token(phone, pw)` |
| `scripts/pandaai_integration.py` | 707 | PandaAI 全功能：市场/上下文/主动置信度调整/回测 (16 API) |
| `scripts/test.py` | 470 | 10 模块测试 |
| `SKILL.md` | 220 | 第〇步(PandaAI引导) + 4步流程 + 主动验证输出 |
| `README.md` | 453 | 完整项目文档 |
| `references/api_guide.md` | 171 | API 调用示例、字段说明 |
| `references/data_sources.md` | 65 | AKShare 接口速查 |
| `references/pandaai_api_list.md` | 147 | PandaAI 80+ 函数完整目录 |

---

## 亮点

### 1. 三层数据架构
AKShare（免费采集） → Skill（结构化） → PandaAI（付费验证），每层独立可替换。

### 2. LLM Prompt 工程
数据感知 7 步 CoT（含数据交叉验证步骤）+ 4 个数据感知 Few-shot。每步推理必须对照 PandaAI 实时数据（价格/融资/质押/筹码/财务），而非纯文本分析。置信度 4 档标准与数据支撑程度挂钩。

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

**v1.2 — 数据感知的 A 股新闻分析 Skill。**

PandaAI 贯穿全链路：
- **市场背景**：指数/北向/龙虎榜（PandaAI 主，AKShare 回退）
- **LLM Prompt**：每条新闻注入涉及股票的价格/融资/质押/筹码/财务实时数据
- **推理框架**：第 3 步"数据交叉验证"强制 LLM 对照实际盘面做判断
- **信号输出**：每条信号附带价格涨跌/融资方向/质押风险/龙虎榜明细
- **回测引擎**：`backtest()` 用历史股价验证 confidence 是否真有预测力

三层架构：AKShare(新闻采集) → Skill(结构化+数据感知推理) → PandaAI(16个API驱动全链路验证)。
