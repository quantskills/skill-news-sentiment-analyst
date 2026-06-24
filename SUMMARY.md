# News Sentiment Analyst — 设计评审与质量分析

## 项目概览

| 维度 | 评级 | 说明 |
|------|:----:|------|
| 架构设计 | ⭐⭐⭐⭐⭐ | 清晰分层：采集→提取→结构化→LLM 分析，职责边界明确 |
| 代码质量 | ⭐⭐⭐⭐☆ | 类型提示较好，错误处理到位，少量可优化点 |
| 测试覆盖 | ⭐⭐⭐⭐⭐ | 10 个测试模块 30+ 用例，覆盖输入校验到 LLM 解析全链路 |
| Skill 规范 | ⭐⭐⭐⭐⭐ | SKILL.md 符合 Claude Code 规范，Agent 可自主执行 |
| 文档完整度 | ⭐⭐⭐⭐⭐ | README + SKILL.md + API 指南 + 数据源说明，四层文档 |
| 生产就绪度 | ⭐⭐⭐⭐☆ | 核心功能完备，缺少限流和监控 |

---

## 架构设计

```
┌─ build.py ─────────────────────┐  ┌─ sentiment.py ────────────────┐
│  validate_input()              │  │  generate_llm_prompt()        │
│  collect_news()     ← 3源采集  │  │  parse_llm_response()         │
│  extract_*()        ← 实体提取  │  │  FEW_SHOT_EXAMPLES            │
│  structure_news_for_ai()       │  │  SYSTEM_PROMPT                │
│  save_to_parquet()             │  └───────────────────────────────┘
│  score_single_news()           │
│  generate_signal_list()        │  ┌─ test.py ─────────────────────┐
│  run() / run_full_pipeline()   │  │  10 模块 30+ 用例              │
└────────────────────────────────┘  └───────────────────────────────┘
```

**核心设计决策：**
- **Skill 不做决策，只做数据** — 采集和结构化由 Python 完成，分析和打分由 LLM/Agent 完成
- **Parquet 作为 Skill↔Agent 契约** — 标准化的 10 字段 schema，`pending_ai_analysis` → `data_ready` 状态机
- **FinGPT 风格 prompt** — 7 步 CoT + 4 Few-shot（含反直觉案例），置信度分 4 档

---

## 亮点（做得好的地方）

### 1. 多源采集 + 智能去重
3 个数据源（东方财富 200 条 + 富途 50 条 + 同花顺 20 条），按标题去重，约 225 条独立新闻。域名自动识别来源。

### 2. 实体提取层次丰富
- **股票代码**：正则 `688xxx/0xxxxx/3xxxxx/6xxxxx` + 5500 只 A 股名称反向匹配
- **板块**：10 大类关键词（新能源/半导体/医药/消费/金融/科技/地产/能源/军工/汽车），默认回退 `market`
- **实体**：数字(百分比/金额/价格)、日期(3 种格式)、政策关键词、事件类型(财报/政策/技术/市场/资本)

### 3. LLM Prompt 工程
- 15 年 A 股量化分析师 persona
- 7 步因果推理框架（核心事件→传导路径→时效性→确定性→市场背景→交叉关联→反直觉检查）
- 4 个 Few-shot 示例覆盖利好/利空/中性/反直觉（财报增长 50% 但低于预期 → 利空）
- 置信度 4 档标准（0.8+/0.5-0.8/0.2-0.5/0.0-0.2）

### 4. LLM 响应解析鲁棒性
`parse_llm_response()` 支持 4 种格式降级：
1. 纯 JSON
2. Markdown 代码块包裹的 JSON
3. 混合文本中的 JSON 片段（倒序匹配）
4. 完全无效 → 安全默认值

字段标准化：非法值自动映射到有效枚举，confidence clamp 到 [0, 1]

### 5. 市场背景自动增强
每条新闻自动附带当日市场背景：上证指数、创业板指、板块涨幅 Top5

### 6. 跨新闻关联
自动匹配同板块的其他新闻（最多 3 条），帮助 LLM 判断共振/对冲

### 7. 选股信号生成
`generate_signal_list()` 自动过滤 `hold`、按置信度降序、自动补全公司名称(从映射表反查)

### 8. 错误处理策略
每个数据源独立 try/except，单源失败不影响其他源；股票映射加载失败带 warning 降级

---

## 改进建议（TODO）

### 🔴 P0 — 影响稳定性
| # | 问题 | 建议 |
|---|------|------|
| 1 | AKShare 无内置限流 | 在 `collect_news()` 中 3 个 API 调用间加 `time.sleep(1)` |
| 2 | `stock_news_em` pyarrow 兼容性已知问题 | 在调用处捕获 `ArrowInvalid` 异常并降级 |

### 🟡 P1 — 提升体验
| # | 问题 | 建议 |
|---|------|------|
| 3 | API 失败时无聚合错误报告 | `run()` 返回值增加 `errors: List[str]` 字段 |
| 4 | 日志级别硬编码为 INFO | 支持 `config["log_level"]` 参数 |
| 5 | 板块关键词硬编码在函数内 | 提取为 `SECTOR_KEYWORDS` 模块级常量或 YAML 配置 |

### 🟢 P2 — 锦上添花
| # | 问题 | 建议 |
|---|------|------|
| 6 | `collect_news()` 可达 150+ 行 | 按数据源拆分为 `_collect_em()`, `_collect_futu()`, `_collect_ths()` |
| 7 | 股票名称映射每次 `run()` 都重新加载 | 考虑 pickle 缓存到本地文件，按日刷新 |
| 8 | 缺少英文版 README | 补充 `README_EN.md` |
| 9 | 无 CI/CD | 添加 GitHub Actions 运行 `test.py` |

---

## 代码统计

| 文件 | 行数 | 职责 |
|------|:----:|------|
| `scripts/build.py` | 657 | 数据采集、实体提取、结构化、Parquet 读写、信号生成 |
| `scripts/sentiment.py` | 203 | LLM prompt 生成（系统提示+少样本+待分析新闻）、响应解析 |
| `scripts/test.py` | 471 | 10 模块测试：输入校验→代码提取→板块→实体→结构化→Parquet→Agent→全流程→Prompt→LLM解析 |
| `SKILL.md` | 167 | Claude Code skill 定义：触发条件、执行步骤、参数、输出规范 |
| `references/api_guide.md` | 171 | API 调用示例、字段说明、选股信号接口 |
| `references/data_sources.md` | 66 | AKShare 接口速查、安装、频率限制 |

---

## 接口契约

```
run(input_data, config?) → result
  input_data: { trade_date, news_type?, target_id? }
  config:     { max_news_count?, save_parquet?, output_dir? }
  result:     { trade_date, news_count, structured_news, summary,
                parquet_path?, ai_instructions, data_version, update_time }

run_full_pipeline(trade_date, ...) → pipeline
  pipeline:   { parquet_path, news_count, prompts, summary }

score_single_news(parquet_path, idx, llm_response) → score
  score:      { sentiment, impact_level, trading_direction, confidence, reason }

generate_signal_list(parquet_path, min_confidence?) → signals
  signals:    [{ code, name, direction, confidence, sentiment, impact_level,
                 reason, news_title }]
```

---

## 依赖

| 包 | 版本 | 用途 |
|----|------|------|
| `akshare` | >= 1.10.0 | A 股数据 API（新闻+行情+股票映射） |
| `pandas` | >= 1.5.0 | 数据处理 + Parquet 读写 |
| `pyarrow` | >= 10.0.0 | Parquet 引擎 |

**零外部服务依赖** — AKShare 开源免费，无需 API Key。

---

## 设计原则验证

- ✅ **单一职责**：Skill 只做数据，AI 做分析
- ✅ **容错降级**：单数据源失败不影响整体
- ✅ **契约驱动**：Parquet schema 是 Skill↔Agent 的稳定接口
- ✅ **可观测性**：logging 覆盖所有关键路径
- ✅ **可测试性**：每个模块有独立测试，核心函数可单独调用
- ✅ **可复用性**：`run()` 可被 Alpha/Agent 直接调用

---

## 总结

**整体评价：生产级 A 股新闻情感分析 Skill。**

设计思路清晰 — Skill 层负责数据工程（采集→提取→结构化→Parquet），Agent 层负责智能分析（读取 prompt→推理→打分→信号）。两层通过标准 Parquet 文件解耦，契约稳定。LLM prompt 工程专业，7 步 CoT + 反直觉 Few-shot 是实盘量化分析的核心方法论。测试覆盖全面（30 用例），错误处理到位。

P0 的限流问题和 pyarrow 兼容性建议优先修复，其余可迭代推进。项目已达到可公开发布的质量标准。
