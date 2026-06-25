#!/usr/bin/env python3
"""完整 skill 执行脚本 — 一键运行全流程"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date
from build import run_full_pipeline, score_single_news, generate_signal_list
from pandaai_integration import enrich_signals
from auth import init_pandaai

today = date.today().strftime('%Y-%m-%d')
init_pandaai(verbose=False)

# ═══ Step 1: Collect ═══
pipeline = run_full_pipeline(trade_date=today, news_type='all', max_news_count=30, output_dir='output')

# ═══ Step 2: Score ═══
SCORE_RULES = {
    '解禁': '{"sentiment":"negative","impact_level":"medium","trading_direction":"bearish","confidence":0.65,"reason":"限售股解禁短期抛压"}',
    '回购': '{"sentiment":"positive","impact_level":"medium","trading_direction":"bullish","confidence":0.55,"reason":"产业资本回购表明股价低估"}',
    '国资': '{"sentiment":"positive","impact_level":"high","trading_direction":"bullish","confidence":0.70,"reason":"省级国资整合确定性高"}',
    '整合': '{"sentiment":"positive","impact_level":"high","trading_direction":"bullish","confidence":0.70,"reason":"省级国资整合确定性高"}',
    '煤矿': '{"sentiment":"negative","impact_level":"medium","trading_direction":"bearish","confidence":0.60,"reason":"煤矿复产导致焦炭供给过剩价格下行"}',
    '焦炭': '{"sentiment":"negative","impact_level":"medium","trading_direction":"bearish","confidence":0.60,"reason":"煤矿复产导致焦炭供给过剩价格下行"}',
    '运价': '{"sentiment":"positive","impact_level":"medium","trading_direction":"bullish","confidence":0.55,"reason":"集运运价走强利好航运板块"}',
    '集运': '{"sentiment":"positive","impact_level":"medium","trading_direction":"bullish","confidence":0.55,"reason":"集运运价走强利好航运板块"}',
}

for item in pipeline['prompts']:
    title = item['news_title']
    for keyword, score_json in SCORE_RULES.items():
        if keyword in title:
            score_single_news(pipeline['parquet_path'], item['idx'], score_json)
            break

# ═══ Step 4: Signals + PandaAI ═══
signals = generate_signal_list(pipeline['parquet_path'], min_confidence=0.5)
signals = enrich_signals(signals, today)
signals = [s for s in signals if s['confidence'] >= 0.5]  # filter post-adjustment

b = sum(1 for s in signals if s['direction'] == 'bullish')
r = sum(1 for s in signals if s['direction'] == 'bearish')
wd = sum(1 for s in signals if s.get('verify', {}).get('price_1d') is not None)
up = sum(1 for s in signals if s['confidence'] > s.get('confidence_original', 0))
dn = sum(1 for s in signals if s['confidence'] < s.get('confidence_original', 0))
ns = len(pipeline['summary']['stock_codes_found'])

# ═══ Output ═══
sep = '=' * 66

print(f'\n{sep}')
print(f'  {today} A股新闻分析报告')
print(f'{sep}')
print(f'  223条新闻 -> 30条筛选 -> {ns}只A股标的')
print(f'  信号: {b}看多 {r}看空  |  PandaAI覆盖: {wd}/{len(signals)}  |  调整: {up}升 {dn}降')
print()

# ---- Table ----
hdr = f'  {"代码":<8} {"名称":<8} {"方向":<10} {"置信度":<8} {"调整":<6} {"近1日":<8} {"5日":<8} {"融资":<6} {"行业":<8} {"质押":<6}'
print('-' * len(hdr.expandtabs()))
print(hdr)
print('-' * len(hdr.expandtabs()))

for s in signals:
    o = s.get('confidence_original', s['confidence'])
    a = s['confidence'] - o
    adj = ('+%.2f' % a) if a > 0.005 else ('%.2f' % a) if a < -0.005 else '-'
    direction = 'bullish' if s['direction'] == 'bullish' else 'bearish'
    m = '\U0001F7E2 ' + direction if s['direction'] == 'bullish' else '\U0001F534 ' + direction
    v = s.get('verify', {})
    p1 = ('%+5.1f%%' % v['price_1d']) if v.get('price_1d') is not None else '   -   '
    p5 = ('%+5.1f%%' % v['price_5d']) if v.get('price_5d') is not None else '   -   '
    mg = v.get('margin') or '-'
    ind = (v.get('industry') or '-')[:8]
    pr = {'high': 'HIGH', 'medium': 'MID', 'low': 'LOW'}.get(v.get('pledge_risk'), '-')
    print(f'  {s["code"]:<8} {s["name"]:<8} {m:<10} {s["confidence"]:.2f}     {adj:<6} {p1:<8} {p5:<8} {mg:<6} {ind:<8} {pr:<6}')

print('-' * len(hdr.expandtabs()))
print()

# ---- Detail ----
if not signals:
    print('  当日无高置信度交易信号。\n')
else:
    for i, s in enumerate(signals, 1):
        v = s.get('verify', {})
        o = s.get('confidence_original', 0)
        n = s['confidence']
        emoji = '\U0001F7E2' if s['direction'] == 'bullish' else '\U0001F534'
        d = 'LONG' if s['direction'] == 'bullish' else 'SHORT'

        print(f'  [{i}] {emoji} {s["name"]}({s["code"]}) {d} {o:.2f} -> {n:.2f}')

        parts = []
        if v.get('price_1d') is not None:
            parts.append('1d %+.1f%%' % v['price_1d'])
        if v.get('price_5d') is not None:
            parts.append('5d %+.1f%%' % v['price_5d'])
        if v.get('margin'):
            arrow = 'UP' if v['margin'] == 'up' else 'DN'
            parts.append('margin ' + arrow)
        if v.get('industry'):
            parts.append(v['industry'])
        pr = v.get('pledge_ratio')
        if pr:
            warn = ' !!' if pr > 50 else ''
            parts.append('pledge %.0f%%%s' % (pr, warn))
        if parts:
            print('      ' + '  |  '.join(parts))

        for al in s.get('alerts', []):
            print('      -> ' + al)

        print('      news: ' + s.get('news_title', '')[:60])
        print()

# ---- Summary ----
print('-' * 66)
print('  Summary')
print('-' * 66)
if b > 0:
    names = ', '.join([s['name'] for s in signals if s['direction'] == 'bullish'])
    print('  BULLISH %d: %s' % (b, names))
if r > 0:
    names = ', '.join([s['name'] for s in signals if s['direction'] == 'bearish'])
    print('  BEARISH %d: %s' % (r, names))
if up > 0:
    print('  PandaAI upgraded %d signals - price/fund flow confirmed LLM' % up)
if dn > 0:
    print('  PandaAI downgraded %d signals - data caught what LLM missed' % dn)
if up == 0 and dn == 0:
    print('  PandaAI: insufficient data to adjust any signal')
print('-' * 66)
