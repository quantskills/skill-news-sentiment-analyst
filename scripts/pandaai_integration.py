"""
PandaAI 数据服务集成 — 与新闻情感分析的交叉验证

用法:
    python pandaai_integration.py --symbol 000001.SZ --date 2026-06-25
    python pandaai_integration.py --compare --date 2026-06-25  # 全量对比
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── PandaAI SDK ──────────────────────────────────────────────
try:
    import panda_data
except ImportError:
    logger.warning("panda_data 未安装。运行: pip install panda_data")
    panda_data = None


# ═══════════════════════════════════════════════════════════════
# 第 1 层：核心行情 — 回测新闻信号的"真值"
# ═══════════════════════════════════════════════════════════════

def get_price_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    获取日线 + 分钟线，用于对照新闻信号计算实际胜率。

    PandaAI: get_stock_daily(symbol, start_date, end_date, fields, adjust)
    """
    if not panda_data:
        raise RuntimeError("panda_data 未安装")

    # 日线
    daily = panda_data.get_stock_daily(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        fields=["open", "high", "low", "close", "volume", "amount"],
        adjust="pre",
    )
    df = pd.DataFrame(daily)
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    df.sort_index(inplace=True)

    # 计算次日涨跌幅
    df["next_return"] = df["close"].pct_change().shift(-1)
    df["next_day_up"] = df["next_return"] > 0

    logger.info(f"获取 {symbol} 日线: {len(df)} 条, {start_date} ~ {end_date}")
    return df


def get_intraday_price(symbol: str, trade_date: str) -> pd.DataFrame:
    """
    获取当日分钟线 — 判断新闻发布后几分钟内的价格反应。

    PandaAI: get_stock_min(symbol, trade_date, freq="1min")
    """
    if not panda_data:
        raise RuntimeError("panda_data 未安装")

    minutes = panda_data.get_stock_min(
        symbol=symbol,
        trade_date=trade_date,
        freq="1min",
    )
    df = pd.DataFrame(minutes)
    logger.info(f"获取 {symbol} {trade_date} 分钟线: {len(df)} 条")
    return df


# ═══════════════════════════════════════════════════════════════
# 第 2 层：资金流 — 验证"聪明的钱"是否同向
# ═══════════════════════════════════════════════════════════════

def get_margin_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    融资融券数据 — 融资买入增加 + bullish 新闻 = 共振信号。

    PandaAI: get_margin(symbol, start_date, end_date)
    """
    if not panda_data:
        raise RuntimeError("panda_data 未安装")

    margin = panda_data.get_margin(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
    )
    df = pd.DataFrame(margin)
    logger.info(f"获取 {symbol} 融资融券: {len(df)} 条")
    return df


def get_northbound_flow(start_date: str, end_date: str) -> pd.DataFrame:
    """
    沪深股通（北向资金）持仓 — 外资是最敏感的"聪明钱"。

    PandaAI: get_hsgt_hold(start_date, end_date)
    """
    if not panda_data:
        raise RuntimeError("panda_data 未安装")

    hsgt = panda_data.get_hsgt_hold(
        start_date=start_date,
        end_date=end_date,
    )
    df = pd.DataFrame(hsgt)
    logger.info(f"获取北向资金: {len(df)} 条, {start_date} ~ {end_date}")
    return df


def get_lhb_data(trade_date: str) -> pd.DataFrame:
    """
    龙虎榜 — 游资当天在买什么。

    PandaAI: get_lhb_list(trade_date)
    """
    if not panda_data:
        raise RuntimeError("panda_data 未安装")

    lhb = panda_data.get_lhb_list(trade_date=trade_date)
    df = pd.DataFrame(lhb)
    logger.info(f"获取 {trade_date} 龙虎榜: {len(df)} 条")
    return df


# ═══════════════════════════════════════════════════════════════
# 第 3 层：公司行为 — 基本面催化剂
# ═══════════════════════════════════════════════════════════════

def get_financial_events(symbol: str, start_date: str, end_date: str) -> Dict:
    """
    整合财务事件：业绩预告 + 回购 + 增减持 + 大宗交易。

    这些是"内部人信号"——公司内部人/大股东用真金白银投票。
    """
    if not panda_data:
        raise RuntimeError("panda_data 未安装")

    events = {}

    # 业绩预告（最重要）
    try:
        forecast = panda_data.get_fina_forecast(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )
        events["fina_forecast"] = forecast
    except Exception as e:
        logger.warning(f"业绩预告获取失败: {e}")

    # 回购
    try:
        repurchase = panda_data.get_repurchase(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )
        events["repurchase"] = repurchase
    except Exception as e:
        logger.warning(f"回购数据获取失败: {e}")

    # 股东增减持
    try:
        shareholder = panda_data.get_stock_shareholder_change(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )
        events["shareholder_change"] = shareholder
    except Exception as e:
        logger.warning(f"股东增减持获取失败: {e}")

    # 大宗交易
    try:
        block_trade = panda_data.get_block_trade(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )
        events["block_trade"] = block_trade
    except Exception as e:
        logger.warning(f"大宗交易获取失败: {e}")

    # 限售解禁
    try:
        restricted = panda_data.get_restricted_list(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )
        events["restricted"] = restricted
    except Exception as e:
        logger.warning(f"解禁数据获取失败: {e}")

    return events


# ═══════════════════════════════════════════════════════════════
# 第 4 层：行业/概念 — 替代硬编码关键词
# ═══════════════════════════════════════════════════════════════

def get_stock_classification(symbol: str) -> Dict:
    """
    获取股票的行业和概念分类，替代 build.py 里的硬编码板块关键词。

    PandaAI: get_stock_industry(symbol) + get_concept_constituents(concept)
    """
    if not panda_data:
        raise RuntimeError("panda_data 未安装")

    result = {}

    try:
        industry = panda_data.get_stock_industry(symbol=symbol)
        result["industry"] = industry
    except Exception as e:
        logger.warning(f"行业分类获取失败: {e}")

    try:
        concepts = panda_data.get_concept_list()
        result["concept_list"] = concepts  # 所有概念列表
    except Exception as e:
        logger.warning(f"概念列表获取失败: {e}")

    return result


# ═══════════════════════════════════════════════════════════════
# 交叉验证引擎
# ═══════════════════════════════════════════════════════════════

def cross_validate_signal(
    symbol: str,
    news_sentiment: str,   # bullish / bearish / hold
    news_confidence: float,
    news_date: str,
    lookback_days: int = 20,
    lookahead_days: int = 3,
) -> Dict:
    """
    对一条新闻信号进行多维度交叉验证：

    ┌──────────────────────┐
    │  新闻 LLM 打分       │  → bullish, confidence 0.85
    └──────┬───────────────┘
           │
           ├── 维度1: 价格验证 (get_stock_daily)
           │   新闻前20日涨跌幅 vs 新闻后3日涨跌幅
           │
           ├── 维度2: 资金验证 (get_margin + get_hsgt_hold)
           │   融资余额/北向持仓 → 聪明的钱是否同向？
           │
           ├── 维度3: 内部人验证 (get_fina_forecast + repurchase + shareholder)
           │   业绩预告/回购/增减持 → 是否有内部信号支撑？
           │
           └── 维度4: 龙虎榜验证 (get_lhb_list)
               当日龙虎榜是否有该股票？游资方向？
    """
    start_date = (datetime.strptime(news_date, "%Y-%m-%d") - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_date = (datetime.strptime(news_date, "%Y-%m-%d") + timedelta(days=lookahead_days)).strftime("%Y-%m-%d")

    result = {
        "symbol": symbol,
        "news_sentiment": news_sentiment,
        "news_confidence": news_confidence,
        "news_date": news_date,
        "checks": {},
    }

    # 维度1: 价格
    try:
        price_df = get_price_data(symbol, start_date, end_date)
        if news_date in price_df.index:
            row = price_df.loc[news_date]
            actual_return = row.get("next_return", 0)
            sentiment_correct = (
                (news_sentiment == "bullish" and actual_return > 0)
                or (news_sentiment == "bearish" and actual_return < 0)
            )
            result["checks"]["price"] = {
                "next_day_return": round(actual_return * 100, 2),
                "sentiment_correct": sentiment_correct,
            }
    except Exception as e:
        result["checks"]["price"] = {"error": str(e)}

    # 维度2: 融资融券
    try:
        margin_df = get_margin_data(symbol, start_date, end_date)
        if not margin_df.empty:
            margin_change = _calc_margin_change(margin_df, news_date)
            result["checks"]["margin"] = margin_change
    except Exception as e:
        result["checks"]["margin"] = {"error": str(e)}

    # 维度3: 内部人信号
    try:
        fin_events = get_financial_events(symbol, start_date, end_date)
        result["checks"]["insider"] = _summarize_fin_events(fin_events, news_date)
    except Exception as e:
        result["checks"]["insider"] = {"error": str(e)}

    # 维度4: 龙虎榜
    try:
        lhb_df = get_lhb_data(news_date)
        result["checks"]["lhb"] = _check_lhb(lhb_df, symbol)
    except Exception as e:
        result["checks"]["lhb"] = {"error": str(e)}

    return result


def _calc_margin_change(df: pd.DataFrame, target_date: str) -> Dict:
    """计算融资余额变化方向和幅度"""
    try:
        df_sorted = df.sort_values("date")
        target_idx = df_sorted[df_sorted["date"] == target_date].index
        if len(target_idx) == 0:
            return {"change": 0, "direction": "unknown"}

        idx = target_idx[0]
        recent = df_sorted.iloc[max(0, idx - 5) : idx + 1]

        if "margin_balance" in df_sorted.columns and len(recent) >= 2:
            change = recent["margin_balance"].iloc[-1] - recent["margin_balance"].iloc[0]
            return {
                "change_pct": round(change / recent["margin_balance"].iloc[0] * 100, 2),
                "direction": "increasing" if change > 0 else "decreasing",
            }
    except Exception:
        pass
    return {"status": "data_not_available"}


def _summarize_fin_events(events: Dict, target_date: str) -> Dict:
    """汇总近期内部人事件"""
    summary = {}
    for event_type, data in events.items():
        if data is None:
            continue
        if isinstance(data, list):
            summary[event_type] = f"{len(data)} events"
        elif isinstance(data, pd.DataFrame):
            summary[event_type] = f"{len(data)} rows"
        else:
            summary[event_type] = "available"
    return summary


def _check_lhb(df: pd.DataFrame, symbol: str) -> Dict:
    """检查股票是否出现在龙虎榜"""
    if df.empty:
        return {"on_list": False}
    matches = df[df["symbol"] == symbol] if "symbol" in df.columns else pd.DataFrame()
    return {
        "on_list": len(matches) > 0,
        "detail": matches.to_dict("records") if len(matches) > 0 else None,
    }


# ═══════════════════════════════════════════════════════════════
# 批量回测（解决核心问题）
# ═══════════════════════════════════════════════════════════════

def backtest_signals(
    parquet_path: str,
    lookahead_days: int = 1,
) -> pd.DataFrame:
    """
    从打分后的 Parquet 读取所有信号，
    用 PandaAI 价格数据计算每条信号的实际胜率。
    """
    df = pd.read_parquet(parquet_path)
    results = []

    for _, row in df[df["result_type"] == "news_analysis"].iterrows():
        if row["result_value"] != "data_ready":
            continue
        rj = json.loads(row["result_json"])
        score = rj.get("llm_score", {})
        if not score:
            continue

        symbol = row.get("target_id", "").split("_")[0]
        if not symbol or not symbol[0].isdigit():
            continue

        try:
            price = get_price_data(
                symbol,
                row["trade_date"],
                (datetime.strptime(row["trade_date"], "%Y-%m-%d") + timedelta(days=lookahead_days + 1)).strftime("%Y-%m-%d"),
            )
            if row["trade_date"] in price.index:
                actual_return = price.loc[row["trade_date"], "next_return"]
                results.append({
                    "symbol": symbol,
                    "trade_date": row["trade_date"],
                    "sentiment": score.get("sentiment"),
                    "direction": score.get("trading_direction"),
                    "confidence": score.get("confidence"),
                    "actual_return": actual_return,
                    "correct": (
                        (score.get("trading_direction") == "bullish" and actual_return > 0)
                        or (score.get("trading_direction") == "bearish" and actual_return < 0)
                    ),
                })
        except Exception as e:
            logger.warning(f"回测 {symbol} {row['trade_date']} 失败: {e}")

    result_df = pd.DataFrame(results)

    if not result_df.empty:
        logger.info("=" * 60)
        logger.info("回测结果")
        logger.info("=" * 60)
        logger.info(f"总信号数: {len(result_df)}")
        logger.info(f"整体胜率: {result_df['correct'].mean():.1%}")

        for direction in ["bullish", "bearish"]:
            sub = result_df[result_df["direction"] == direction]
            if len(sub) > 0:
                logger.info(f"  {direction}: {len(sub)} 条, 胜率 {sub['correct'].mean():.1%}")

        for conf_bucket in [(0.8, 1.0), (0.5, 0.8), (0.2, 0.5), (0.0, 0.2)]:
            sub = result_df[(result_df["confidence"] >= conf_bucket[0]) & (result_df["confidence"] < conf_bucket[1])]
            if len(sub) > 0:
                logger.info(f"  confidence [{conf_bucket[0]}-{conf_bucket[1]}): {len(sub)} 条, 胜率 {sub['correct'].mean():.1%}")

    return result_df


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="PandaAI 数据集成 — 新闻信号交叉验证")
    parser.add_argument("--symbol", default="000001.SZ", help="股票代码")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="交易日期")
    parser.add_argument("--compare", action="store_true", help="全量对比模式")
    parser.add_argument("--backtest", type=str, help="Parquet 路径，运行批量回测")
    args = parser.parse_args()

    if not panda_data:
        logger.error("panda_data 未安装。请确认已安装 PandaAI SDK")
        sys.exit(1)

    if args.backtest:
        result_df = backtest_signals(args.backtest)
        print(result_df.to_string())
        return

    if args.compare:
        # 全量对比：同一天的新闻信号 vs 实际行情 vs 资金流向
        print(f"\n{'='*60}")
        print(f"全量交叉验证 — {args.date}")
        print(f"{'='*60}")

        # 1. 市场全景
        print("\n[1] 市场全景")
        try:
            index_df = panda_data.get_index_daily(
                symbol="000001.SH",
                start_date=(datetime.strptime(args.date, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d"),
                end_date=args.date,
            )
            if not index_df.empty:
                last = index_df.iloc[-1]
                print(f"  上证指数: {last.get('close')}, 涨跌幅: {last.get('pct_change', 'N/A')}%")
        except Exception as e:
            print(f"  指数获取失败: {e}")

        # 2. 北向资金
        print("\n[2] 北向资金")
        try:
            hsgt_df = get_northbound_flow(
                (datetime.strptime(args.date, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d"),
                args.date,
            )
            if not hsgt_df.empty:
                print(f"  近5日北向净流入: {hsgt_df.get('net_flow', pd.Series()).tail(5).to_list()}")
        except Exception as e:
            print(f"  北向获取失败: {e}")

        # 3. 龙虎榜
        print("\n[3] 龙虎榜 Top5")
        try:
            lhb_df = get_lhb_data(args.date)
            if not lhb_df.empty:
                for _, row in lhb_df.head(5).iterrows():
                    print(f"  {row.get('symbol')} {row.get('name')} — {row.get('reason')}")
        except Exception as e:
            print(f"  龙虎榜获取失败: {e}")

        return

    # 单股验证
    print(f"\n{'='*60}")
    print(f"单股交叉验证 — {args.symbol} @ {args.date}")
    print(f"{'='*60}")

    # 模拟一条 bullish 信号
    result = cross_validate_signal(
        symbol=args.symbol,
        news_sentiment="bullish",
        news_confidence=0.85,
        news_date=args.date,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
