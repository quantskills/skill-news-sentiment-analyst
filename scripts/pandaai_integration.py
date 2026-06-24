"""
PandaAI 数据服务 — 新闻信号交叉验证引擎

认证: cp .env.example .env 并填入手机号和密码
      或 export PANDA_DATA_USERNAME=86xxx PANDA_DATA_PASSWORD=xxx

用法:
    python pandaai_integration.py --verify --symbol 000001.SZ --date 2026-06-25
    python pandaai_integration.py --market-scan --date 2026-06-25
    python pandaai_integration.py --backtest output/news_trading_2026-06-25.parquet
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Dict

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import init_pandaai, require_panda

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pandaai")


# ═══════════════════════════════════════════════════════════════
# 数据获取层
# ═══════════════════════════════════════════════════════════════

def _get_client():
    """获取已认证的 panda_data 模块"""
    require_panda()
    import panda_data
    return panda_data


def get_price_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """A股日线 — 回测信号胜率的真值"""
    pd_mod = _get_client()
    data = pd_mod.get_stock_daily(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        fields=["open", "high", "low", "close", "volume", "amount"],
        adjust="pre",
    )
    df = pd.DataFrame(data)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
    df.sort_index(inplace=True)
    df["next_return"] = df["close"].pct_change().shift(-1)
    logger.info(f"日线: {symbol} {len(df)} 条, {start_date} ~ {end_date}")
    return df


def get_price_minutes(symbol: str, trade_date: str) -> pd.DataFrame:
    """A股分钟线 — 新闻发布后分钟级反应"""
    pd_mod = _get_client()
    data = pd_mod.get_stock_min(symbol=symbol, trade_date=trade_date, freq="1min")
    df = pd.DataFrame(data)
    logger.info(f"分钟线: {symbol} {trade_date} {len(df)} 条")
    return df


def get_margin(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """融资融券 — 杠杆资金方向"""
    pd_mod = _get_client()
    data = pd_mod.get_margin(symbol=symbol, start_date=start_date, end_date=end_date)
    df = pd.DataFrame(data)
    logger.info(f"融资融券: {symbol} {len(df)} 条")
    return df


def get_northbound(start_date: str, end_date: str) -> pd.DataFrame:
    """北向资金（沪深股通）"""
    pd_mod = _get_client()
    data = pd_mod.get_hsgt_hold(start_date=start_date, end_date=end_date)
    df = pd.DataFrame(data)
    logger.info(f"北向资金: {len(df)} 条, {start_date} ~ {end_date}")
    return df


def get_lhb(trade_date: str) -> pd.DataFrame:
    """龙虎榜"""
    pd_mod = _get_client()
    data = pd_mod.get_lhb_list(trade_date=trade_date)
    df = pd.DataFrame(data)
    logger.info(f"龙虎榜: {trade_date} {len(df)} 条")
    return df


def get_financial_events(symbol: str, start_date: str, end_date: str) -> Dict:
    """内部人信号：业绩预告 + 回购 + 增减持 + 大宗交易 + 解禁"""
    pd_mod = _get_client()
    events = {}

    fetchers = {
        "fina_forecast": lambda: pd_mod.get_fina_forecast(
            symbol=symbol, start_date=start_date, end_date=end_date
        ),
        "repurchase": lambda: pd_mod.get_repurchase(
            symbol=symbol, start_date=start_date, end_date=end_date
        ),
        "shareholder_change": lambda: pd_mod.get_stock_shareholder_change(
            symbol=symbol, start_date=start_date, end_date=end_date
        ),
        "block_trade": lambda: pd_mod.get_block_trade(
            symbol=symbol, start_date=start_date, end_date=end_date
        ),
        "restricted": lambda: pd_mod.get_restricted_list(
            symbol=symbol, start_date=start_date, end_date=end_date
        ),
    }

    for name, fetcher in fetchers.items():
        try:
            events[name] = fetcher()
        except Exception as e:
            logger.debug(f"{name} 获取失败: {e}")

    logger.info(f"内部人事件: {symbol} {list(events.keys())}")
    return events


def get_stock_classification(symbol: str) -> Dict:
    """行业 + 概念分类 — 替代硬编码板块关键词"""
    pd_mod = _get_client()
    result = {}
    try:
        result["industry"] = pd_mod.get_stock_industry(symbol=symbol)
    except Exception as e:
        logger.debug(f"行业分类失败: {e}")
    return result


# ═══════════════════════════════════════════════════════════════
# 交叉验证引擎
# ═══════════════════════════════════════════════════════════════

def verify_signal(
    symbol: str,
    news_sentiment: str,
    news_confidence: float,
    news_date: str,
    lookback: int = 20,
    lookahead: int = 3,
) -> Dict:
    """
    4 维度交叉验证一条新闻信号:

    价格   — 次日实际涨跌 vs LLM 预测方向
    杠杆   — 融资余额变化方向
    内部人 — 业绩预告/回购/增减持
    游资   — 龙虎榜上榜情况
    """
    start = (datetime.strptime(news_date, "%Y-%m-%d") - timedelta(days=lookback)).strftime("%Y-%m-%d")
    end = (datetime.strptime(news_date, "%Y-%m-%d") + timedelta(days=lookahead)).strftime("%Y-%m-%d")

    result = {
        "symbol": symbol,
        "signal": {"sentiment": news_sentiment, "confidence": news_confidence, "date": news_date},
        "verification": {},
    }

    # 价格检查
    try:
        price = get_price_daily(symbol, start, end)
        if news_date in price.index:
            r = price.loc[news_date, "next_return"]
            result["verification"]["price"] = {
                "next_day_return_pct": round(float(r) * 100, 2),
                "matches_signal": (
                    (news_sentiment == "bullish" and r > 0)
                    or (news_sentiment == "bearish" and r < 0)
                ),
            }
    except Exception as e:
        result["verification"]["price"] = {"error": str(e)}

    # 融资
    try:
        mg = get_margin(symbol, start, end)
        result["verification"]["margin"] = _margin_direction(mg)
    except Exception as e:
        result["verification"]["margin"] = {"error": str(e)}

    # 内部人
    try:
        fe = get_financial_events(symbol, start, end)
        result["verification"]["insider"] = {k: f"{len(v) if isinstance(v, (list, pd.DataFrame)) else 'OK'}" for k, v in fe.items()}
    except Exception as e:
        result["verification"]["insider"] = {"error": str(e)}

    # 龙虎榜
    try:
        lhb = get_lhb(news_date)
        result["verification"]["lhb"] = {"on_list": symbol in lhb.get("symbol", pd.Series()).values if not lhb.empty else False}
    except Exception as e:
        result["verification"]["lhb"] = {"error": str(e)}

    return result


def _margin_direction(df: pd.DataFrame) -> Dict:
    if df.empty:
        return {"status": "no_data"}
    try:
        if "margin_balance" in df.columns and len(df) >= 2:
            a, b = df["margin_balance"].iloc[0], df["margin_balance"].iloc[-1]
            return {"change_pct": round(float(b - a) / float(a) * 100, 2), "direction": "up" if b > a else "down"}
    except Exception:
        pass
    return {"status": "data_incomplete"}


# ═══════════════════════════════════════════════════════════════
# 批量回测 — 解决"LLM confidence 到底有没有用"的核心问题
# ═══════════════════════════════════════════════════════════════

def _format_symbol(code: str) -> str:
    """将 6 位代码转为 PandaAI 格式: 000001 → 000001.SZ, 600001 → 600001.SH"""
    if len(code) == 6:
        return f"{code}.SZ" if code.startswith(("0", "3")) else f"{code}.SH"
    return code


def _iter_stocks_from_row(row) -> list:
    """从 Parquet 行中提取所有股票代码（而非仅 target_id）"""
    stocks = []
    try:
        rj = json.loads(row["result_json"])
        for sc in rj.get("stock_codes", []):
            code = sc.get("code", "")
            name = sc.get("name", "")
            if code and code.isdigit() and len(code) == 6:
                stocks.append((code, name))
    except Exception:
        pass
    # 回退: 用 target_id
    if not stocks:
        tid = str(row.get("target_id", ""))
        code = tid.split("_")[0]
        if code.isdigit() and len(code) == 6:
            stocks.append((code, ""))
    return stocks


def backtest(parquet_path: str, lookahead: int = 1) -> pd.DataFrame:
    """
    从打分后的 Parquet 逐条对照实际股价，输出:

    - 每条信号的 confidence vs 实际涨跌幅
    - 按 confidence 分桶的胜率
    - 按 direction 分桶的胜率
    """
    require_panda()

    df = pd.read_parquet(parquet_path)
    rows = []

    for _, row in df[df["result_type"] == "news_analysis"].iterrows():
        if row["result_value"] != "data_ready":
            continue
        rj = json.loads(row["result_json"])
        score = rj.get("llm_score", {})
        if not score:
            continue

        stocks = _iter_stocks_from_row(row)
        if not stocks:
            continue

        for code, name in stocks:
            symbol = _format_symbol(code)
            try:
                price = get_price_daily(
                    symbol,
                    row["trade_date"],
                    (datetime.strptime(str(row["trade_date"]), "%Y-%m-%d") + timedelta(days=lookahead + 1)).strftime("%Y-%m-%d"),
                )
                tdate = str(row["trade_date"])
                if tdate in price.index:
                    r = float(price.loc[tdate, "next_return"])
                    direction = str(score.get("trading_direction", "hold"))
                    rows.append({
                        "symbol": symbol,
                        "name": name,
                        "date": tdate,
                        "direction": direction,
                        "confidence": float(score.get("confidence", 0)),
                        "sentiment": str(score.get("sentiment", "neutral")),
                        "actual_return_pct": round(r * 100, 2),
                        "correct": (direction == "bullish" and r > 0) or (direction == "bearish" and r < 0),
                    })
            except Exception as e:
                logger.warning(f"回测异常 {symbol} {row['trade_date']}: {e}")

    result = pd.DataFrame(rows)

    if result.empty:
        logger.warning("无有效回测数据")
        return result

    # 打印汇总
    print("\n" + "=" * 64)
    print("  回 测 结 果")
    print("=" * 64)
    print(f"  信号总数: {len(result)}")
    print(f"  整体胜率: {result['correct'].mean():.1%}")
    print()

    for d in ["bullish", "bearish"]:
        sub = result[result["direction"] == d]
        if len(sub):
            print(f"  {d:>8}: {len(sub):>4} 条  胜率 {sub['correct'].mean():.1%}")

    print()
    print("  confidence 分桶:")
    for lo, hi in [(0.8, 1.01), (0.5, 0.8), (0.2, 0.5), (0.0, 0.2)]:
        sub = result[(result["confidence"] >= lo) & (result["confidence"] < hi)]
        if len(sub):
            bar = "█" * int(sub["correct"].mean() * 20)
            print(f"  [{lo:.1f}-{hi:.1f}): {len(sub):>4} 条  胜率 {sub['correct'].mean():.1%}  {bar}")

    print("=" * 64)

    return result


# ═══════════════════════════════════════════════════════════════
# 信号增强 — 嵌入主流程，每条信号自动拉 PandaAI 验证
# ═══════════════════════════════════════════════════════════════

def enrich_signals(signals: list, trade_date: str) -> list:
    """
    对 generate_signal_list() 的输出逐条拉 PandaAI 数据验证。

    每条信号新增字段:
      verify_price   — 最近5日涨跌幅
      verify_margin  — 融资余额变化方向
      verify_lhb     — 当日是否上榜龙虎榜
    """
    if not signals:
        return signals

    try:
        from auth import init_pandaai, is_panda_available
        if not is_panda_available() and not init_pandaai(verbose=False):
            return signals
    except Exception:
        return signals

    import panda_data

    # 收集所有股票代码，去重
    codes = list({s["code"] for s in signals if s.get("code")})

    # 批量查价格（最近5天）
    price_cache = {}
    for code in codes:
        try:
            end = trade_date
            start = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
            sym = _format_symbol(code)
            px = panda_data.get_stock_daily(
                symbol=sym, start_date=start, end_date=end,
                fields=["close"], adjust="pre",
            )
            if px:
                closes = [x.get("close", 0) for x in px if x.get("close")]
                if len(closes) >= 2:
                    chg = round((closes[-1] - closes[-2]) / closes[-2] * 100, 2)
                    chg5 = round((closes[-1] - closes[0]) / closes[0] * 100, 2) if len(closes) >= 5 else None
                    price_cache[code] = {"latest_change_pct": chg, "5d_change_pct": chg5}
        except Exception:
            pass

    # 批量查融资
    margin_cache = {}
    for code in codes:
        try:
            end = trade_date
            start = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")
            sym = _format_symbol(code)
            mg = panda_data.get_margin(symbol=sym, start_date=start, end_date=end)
            if mg and len(mg) >= 2:
                a = mg[0].get("margin_balance", 0) or 0
                b = mg[-1].get("margin_balance", 0) or 0
                margin_cache[code] = "up" if b > a else "down"
        except Exception:
            pass

    # 龙虎榜
    lhb_codes = set()
    try:
        lhb = panda_data.get_lhb_list(trade_date=trade_date)
        if lhb:
            for item in lhb:
                sym = str(item.get("symbol", ""))
                if len(sym) >= 6:
                    lhb_codes.add(sym[-6:])
    except Exception:
        pass

    # 写入每条信号
    for s in signals:
        code = s.get("code", "")
        s["verify"] = {
            "price": price_cache.get(code, {}),
            "margin": margin_cache.get(code),
            "lhb": code in lhb_codes,
        }

    return signals


# ═══════════════════════════════════════════════════════════════
# 市场扫描
# ═══════════════════════════════════════════════════════════════

def market_scan(trade_date: str) -> Dict:
    """当日市场全景：指数 + 北向 + 龙虎榜"""
    require_panda()

    result = {"date": trade_date}

    # 指数
    try:
        ix = get_price_daily("000001.SH", trade_date, trade_date)
        result["sh_index"] = float(ix.iloc[-1]["close"]) if not ix.empty else None
    except Exception:
        result["sh_index"] = None

    # 北向
    try:
        nb = get_northbound(
            (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"),
            trade_date,
        )
        result["northbound_rows"] = len(nb)
    except Exception:
        result["northbound_rows"] = 0

    # 龙虎榜 top5
    try:
        lhb = get_lhb(trade_date)
        result["lhb_count"] = len(lhb)
    except Exception:
        result["lhb_count"] = 0

    return result


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="PandaAI 交叉验证 — 验证新闻信号的实际预测力",
        epilog="认证: cp .env.example .env 并填入手机号密码。详见 https://www.pandaai.online/data-service",
    )
    parser.add_argument("--verify", action="store_true", help="单股交叉验证")
    parser.add_argument("--symbol", default="000001.SZ", help="股票代码")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--market-scan", action="store_true", help="市场全景扫描")
    parser.add_argument("--backtest", type=str, help="Parquet 路径: 批量回测")
    args = parser.parse_args()

    # 初始化 PandaAI
    panda_ok = init_pandaai()
    if not panda_ok:
        if args.backtest or args.market_scan or args.verify:
            logger.error("回测/验证功能需要 PandaAI 凭证。")
            logger.info("cp .env.example .env 并填入手机号和密码即可。")
            sys.exit(1)
        else:
            logger.info("PandaAI 未配置。运行 '--help' 查看认证方式。")
            return

    if args.backtest:
        backtest(args.backtest)
    elif args.market_scan:
        scan = market_scan(args.date)
        print(json.dumps(scan, indent=2, ensure_ascii=False, default=str))
    elif args.verify:
        result = verify_signal(
            symbol=args.symbol,
            news_sentiment="bullish",
            news_confidence=0.85,
            news_date=args.date,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print("未指定操作。可用: --verify / --market-scan / --backtest")
        print(f"\n认证: cp .env.example .env 并填入手机号和密码。详见 https://www.pandaai.online/data-service")


if __name__ == "__main__":
    main()
