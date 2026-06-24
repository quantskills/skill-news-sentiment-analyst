import json
import re
from typing import Dict, List, Optional

FEW_SHOT_EXAMPLES = """
【示例 1】利好 + 数据全面支撑 → 高置信度
新闻：央行宣布降准0.5个百分点，释放长期资金约1万亿元
涉及股票实时数据：000001(平安银行) | 现价12.5 近1日-0.2% 近5日-1.5% | 融资减 | 银行 | 质押8% | 筹码集中 | 营收180亿 净利42亿
当日市场背景：上证3350点-0.3%，北向净流出5亿，龙虎榜28只上榜
分析：
1. 核心事件：央行降准，货币政策宽松信号
2. 传导路径：降准→银行可贷资金增加→利差扩大→直接利好银行
3. 数据验证：平安银行近5日跌1.5%尚未反映利好→存在预期差；融资减说明杠杆资金尚未先知先觉；质押8%安全；筹码集中说明机构在吸筹→基本面+筹码双重支撑
4. 市场背景：大盘缩量微跌+北向流出→降准有维稳意图，逆势出利好信号更强
5. 反直觉：降准已有市场预期，但股价尚未反应+筹码集中=还有上行空间
结论：{"sentiment":"positive","impact_level":"high","trading_direction":"bullish","confidence":0.85,"reason":"降准利好银行，平安银行近5日跌1.5%尚未反应+筹码集中+质押安全，逆势出利好有维稳意图"}

【示例 2】利空 + 数据矛盾 → 降置信度
新闻：某新能源公司获大额订单，合同金额50亿
涉及股票实时数据：300xxx | 现价35.0 近1日-3.2% 近5日8.5% | 融资增 | 电力设备 | 质押55%⚠ | 筹码分散 | 营收32亿 净利-1.2亿
分析：
1. 核心事件：50亿订单→表面利好
2. 数据验证（关键）：近5日已涨8.5%→利好可能已提前反应；质押55%⚠大股东资金链紧张→订单真实性存疑；净利亏损→公司基本面差；融资增但筹码分散→散户在追、机构在撤
3. 反直觉：表面利好但质押高危+基本面亏损+前期已大涨→大概率是"利好出货"的套路
结论：{"sentiment":"negative","impact_level":"medium","trading_direction":"bearish","confidence":0.55,"reason":"50亿订单表面利好，但质押55%高危+净利亏损+近5日已涨8.5%利好提前反应，警惕利好出货"}

【示例 3】中性 — 与市场无关
新闻：今日全国天气晴朗，适合出行
涉及股票实时数据：无
分析：与金融市场无传导路径，忽略。
结论：{"sentiment":"neutral","impact_level":"low","trading_direction":"hold","confidence":0.05,"reason":"天气事件与金融市场无传导路径，不影响交易决策"}

【示例 4】利空 + 数据印证 → 高置信度
新闻：某医药公司核心产品未通过医保谈判，将退出医保目录
涉及股票实时数据：600xxx | 现价28.0 近1日-5.1% 近5日-12.3% | 融资减 | 医药生物 | 质押22% | 筹码分散 | 营收15亿 净利3.2亿
分析：
1. 核心事件：退出医保→收入直接受损→确定性极高
2. 传导路径：医保退出→销量断崖→业绩下滑→机构出逃
3. 数据验证：近5日已跌12.3%说明市场在定价但可能未到底；融资减→杠杆资金也在撤离；筹码分散+无机构护盘→下跌可能加速；营收15亿净利3.2亿→退出医保对利润冲击巨大
4. 共振：新闻利空+价格下跌+融资撤离+筹码分散=四重利空共振
结论：{"sentiment":"negative","impact_level":"high","trading_direction":"bearish","confidence":0.92,"reason":"退出医保直接冲击营收，近5日已跌12.3%但筹码分散无护盘+融资持续撤离，四重利空共振下跌空间未释放完毕"}
"""

SYSTEM_PROMPT = """你是一位拥有15年经验的A股量化金融分析师。你会收到新闻文本和该新闻涉及股票的实时行情数据（来自 PandaAI）。你的任务是把新闻和实际盘面结合起来做判断。

分析框架（必须逐步思考，每步都要对照数据）：

1. **核心事件识别**：新闻说了什么？事实还是传闻？新闻发布时间 vs 当前股价 — 是否已被定价？
2. **传导路径分析**：事件→板块→个股。涉及的股票是否真的属于相关行业（核对 PandaAI 行业分类）？
3. **数据交叉验证**（关键步骤）：
   - 价格：新闻方向与近1日/5日涨跌幅是否一致？若利好但近5日已大涨，警惕"利好出尽"
   - 融资：杠杆资金方向是否与新闻方向一致？若利好但融资在减，说明聪明钱不跟
   - 质押：质押比例 >50% 的股票，利好信号打折扣（大股东资金链可能有问题）
   - 筹码：股东人数在集中还是分散？集中=机构吸筹（信号增强），分散=散户接盘（信号减弱）
   - 财务：营收/净利润趋势是否支撑新闻逻辑？若利好但基本面恶化，信号不可靠
4. **时效性判断**：影响是即时还是滞后？已经反映在股价里了吗？
5. **确定性评估**：官方公告 > 媒体报道 > 市场传闻
6. **市场背景关联**：当日大盘+北向+龙虎榜背景，这条新闻是顺势还是逆势？
7. **反直觉检查**：表面利好实际利空？有无"利好出尽"或"利空出尽"？

confidence 评分标准（必须结合数据）：
- 0.8-1.0：官方公告 + 数据全面支撑（价格同向+融资同向+基本面OK+低质押）
- 0.5-0.8：逻辑合理但数据有部分矛盾（如利好但融资反向）
- 0.2-0.5：模糊描述+传闻+数据不支持或缺失
- 0.0-0.2：与市场无关+数据明显矛盾+信息不足

输出规则：
- reason 控制在 100 字以内，必须包含因果推理 + 至少一个数据参照
- 如果提示中包含 PandaAI 数据，必须在分析中引用（例如"近5日已涨X%，警惕利好出尽"）
- 如果新闻与市场无关，直接给 neutral/low/hold/0.0-0.2"""


def generate_llm_prompt(
    title: str,
    content: str,
    stock_codes: Optional[List] = None,
    sectors: Optional[List] = None,
    entities: Optional[Dict] = None,
    market_context: Optional[str] = None,
    related_news: Optional[List[str]] = None,
    stock_context: Optional[Dict] = None,
) -> str:
    stock_str = (
        ", ".join([f"{s.get('name', '')}({s.get('code', '')})" for s in stock_codes])
        if stock_codes
        else "无明确个股"
    )
    sector_str = ", ".join(sectors) if sectors else "无明确板块"

    entity_parts = []
    entities = entities or {}
    if entities.get("numbers"):
        nums = [f"{n['value']}{n.get('type', '')}" for n in entities["numbers"][:3]]
        entity_parts.append(f"关键数字: {', '.join(nums)}")
    if entities.get("policies"):
        entity_parts.append(f"政策关键词: {', '.join(entities['policies'][:3])}")
    if entities.get("events"):
        entity_parts.append(f"事件类型: {', '.join(entities['events'][:3])}")
    entity_str = "; ".join(entity_parts) if entity_parts else "无"

    # PandaAI 股票上下文: 价格、融资、行业、质押、筹码、财务
    stock_ctx_section = ""
    if stock_context:
        lines = []
        for code, ctx in stock_context.items():
            parts = [code]
            if ctx.get("price"):
                px = ctx["price"]
                parts.append(f"现价{px.get('latest')} 近1日{px.get('change_1d')}% 近5日{px.get('change_5d')}%")
            if ctx.get("margin"):
                parts.append(f"融资{'增' if ctx['margin'] == 'up' else '减'}")
            if ctx.get("industry"):
                parts.append(f"{ctx['industry']}")
            if ctx.get("pledge_ratio"):
                parts.append(f"质押{ctx['pledge_ratio']}%{'⚠' if ctx['pledge_ratio'] > 50 else ''}")
            if ctx.get("holder_trend"):
                parts.append(f"筹码{ctx['holder_trend']}")
            if ctx.get("fina"):
                f = ctx["fina"]
                parts.append(f"营收{f.get('revenue')} 净利{f.get('net_profit')}")
            lines.append("  " + " | ".join(parts))
        if lines:
            stock_ctx_section = "\n【涉及股票实时数据（来自 PandaAI）】\n" + "\n".join(lines) + "\n"

    context_section = ""
    if market_context:
        context_section = f"\n【当日市场背景】\n{market_context}\n"

    related_section = ""
    if related_news:
        related_items = "\n".join(f"  - {n}" for n in related_news[:5])
        related_section = f"\n【关联新闻（可能影响判断）】\n{related_items}\n"

    return f"""{SYSTEM_PROMPT}

{FEW_SHOT_EXAMPLES}
{stock_ctx_section}{context_section}{related_section}
【待分析新闻】
标题：{title}
内容：{content[:500]}
涉及股票：{stock_str}
相关板块：{sector_str}
关键信息：{entity_str}

请按以下步骤逐步分析后输出 JSON：
1. 这条新闻的核心事件是什么？是事实还是传闻？
2. 传导路径：事件 → 板块 → 个股，具体怎么传导？
3. 时效性：影响是即时的还是滞后的？已经反映在股价里了吗？
4. 结合当日市场背景，这条新闻在当前环境下意味着什么？
5. 和其他新闻有没有关联？形成共振还是对冲？
6. 有没有反直觉的可能？表面利好实际利空？
7. 给出最终判断

输出格式（只输出 JSON）：
{{"sentiment":"positive/negative/neutral","impact_level":"high/medium/low","trading_direction":"bullish/bearish/hold","confidence":0.0-1.0,"reason":"100字以内的因果推理"}}"""


def parse_llm_response(response_text: str) -> Dict:
    default = {
        "sentiment": "neutral",
        "impact_level": "low",
        "trading_direction": "hold",
        "confidence": 0.0,
        "reason": "LLM 响应解析失败",
        "method": "llm_parse_error",
    }

    if not response_text or not response_text.strip():
        return default

    data = None

    try:
        data = json.loads(response_text.strip())
    except json.JSONDecodeError:
        pass

    if data is None:
        code_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if code_match:
            try:
                data = json.loads(code_match.group(1))
            except json.JSONDecodeError:
                pass

    if data is None:
        json_matches = re.findall(r'\{[^{}]*\}', response_text, re.DOTALL)
        if json_matches:
            for match in reversed(json_matches):
                try:
                    data = json.loads(match)
                    break
                except json.JSONDecodeError:
                    continue

    if data is None:
        return default

    sentiment = str(data.get("sentiment", "neutral")).lower()
    if sentiment not in ("positive", "negative", "neutral"):
        sentiment = "neutral"

    impact = str(data.get("impact_level", "low")).lower()
    if impact not in ("high", "medium", "low"):
        impact = "low"

    direction = str(data.get("trading_direction", "hold")).lower()
    if direction not in ("bullish", "bearish", "hold"):
        direction = "hold"

    try:
        confidence = float(data.get("confidence", 0.0))
        confidence = round(max(0.0, min(1.0, confidence)), 2)
    except (ValueError, TypeError):
        confidence = 0.0

    reason = str(data.get("reason", ""))[:150]

    return {
        "sentiment": sentiment,
        "impact_level": impact,
        "trading_direction": direction,
        "confidence": confidence,
        "reason": reason,
        "method": "llm",
    }
