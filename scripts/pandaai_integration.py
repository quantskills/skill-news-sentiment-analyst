"""
PandaAI 数据服务 — 市场数据 + 信号验证 + 回测引擎

认证: cp .env.example .env 并填入手机号和密码

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
from typing import Dict, List

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import init_pandaai, require_panda

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pandaai")


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _get_client():
    require_panda()
    import panda_data
    return panda_data


def _format_symbol(code: str) -> str:
    """6 位代码 → PandaAI 格式: 000001 → 000001.SZ, 600001 → 600001.SH"""
    if len(code) == 6:
        return f"{code}.SZ" if code.startswith(("0", "3")) else f"{code}.SH"
    return code


def _ensure_connected() -> bool:
    try:
        from auth import is_panda_available
        if not is_panda_available():
            return init_pandaai(verbose=False)
        return True
    except Exception:
        return False


def _is_empty(df) -> bool:
    """判断 DataFrame 或 list 是否为空"""
    if df is None:
        return True
    if isinstance(df, pd.DataFrame):
        return df.empty
    if isinstance(df, list):
        return len(df) == 0
    return False


# ═══════════════════════════════════════════════════════════════
# 市场快照 — build.py 的主数据源
# ═══════════════════════════════════════════════════════════════

def get_market_snapshot(trade_date: str) -> Dict:
    """
    PandaAI 市场全景。返回:
        {"available": True, "indices": {...}, "northbound": ..., "lhb_count": ...}
    """
    if not _ensure_connected():
        return {"available": False}

    pd_mod = _get_client()
    result = {"available": True, "indices": {}, "northbound": None, "lhb_count": 0}

    date_fmt = trade_date.replace("-", "")

    try:
        sh = pd_mod.get_index_daily(symbol="000001.SH", start_date=date_fmt, end_date=date_fmt)
        if not _is_empty(sh):
            result["indices"]["sh"] = {
                "close": sh.iloc[-1].get("close"),
                "pct_change": sh.iloc[-1].get("pct_change"),
            }
    except Exception:
        pass

    try:
        cy = pd_mod.get_index_daily(symbol="399006.SZ", start_date=date_fmt, end_date=date_fmt)
        if not _is_empty(cy):
            result["indices"]["cy"] = {
                "close": cy.iloc[-1].get("close"),
                "pct_change": cy.iloc[-1].get("pct_change"),
            }
    except Exception:
        pass

    try:
        nb = pd_mod.get_hsgt_hold(start_date=date_fmt, end_date=date_fmt)
        result["northbound"] = len(nb) if not _is_empty(nb) else 0
    except Exception:
        pass

    try:
        lhb = pd_mod.get_lhb_list(start_date=date_fmt, end_date=date_fmt)
        result["lhb_count"] = len(lhb) if not _is_empty(lhb) else 0
    except Exception:
        pass

    return result


# ═══════════════════════════════════════════════════════════════
# 股票上下文 — 注入 LLM prompt
# ═══════════════════════════════════════════════════════════════

def get_stock_context_batch(codes: List[str], trade_date: str) -> Dict:
    """
    批量获取股票多维上下文，供 sentiment.py 注入 LLM prompt。

    返回: { code: { price, margin, industry, pledge_ratio, holder_trend, fina } }
    """
    if not codes or not _ensure_connected():
        return {}

    pd_mod = _get_client()
    result = {}
    date_fmt = trade_date.replace("-", "")
    start_7d = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y%m%d")
    start_5d = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y%m%d")

    for code in codes:
        ctx = {}
        sym = _format_symbol(code)

        # 近5日价格 (DataFrame)
        try:
            px = pd_mod.get_stock_daily(symbol=sym, start_date=start_7d, end_date=date_fmt, fields=["close"])
            if not _is_empty(px):
                closes = px["close"].tolist()
                if len(closes) >= 2:
                    ctx["price"] = {
                        "latest": closes[-1],
                        "change_1d": round((closes[-1] - closes[-2]) / closes[-2] * 100, 2),
                        "change_5d": round((closes[-1] - closes[0]) / closes[0] * 100, 2) if len(closes) >= 5 else None,
                    }
        except Exception:
            pass

        # 融资方向 (DataFrame)
        try:
            mg = pd_mod.get_margin(symbol=sym, start_date=start_5d, end_date=date_fmt)
            if not _is_empty(mg) and "margin_balance" in mg.columns and len(mg) >= 2:
                a = mg["margin_balance"].iloc[0]
                b = mg["margin_balance"].iloc[-1]
                ctx["margin"] = "up" if b > a else "down"
        except Exception:
            pass

        # 行业分类
        try:
            ind = pd_mod.get_stock_industry(stock_symbol=sym)
            if not _is_empty(ind):
                row = ind.iloc[0].to_dict() if isinstance(ind, pd.DataFrame) else ind
                ctx["industry"] = row.get("industry_name", str(row))
        except Exception:
            pass

        # 质押 (DataFrame)
        try:
            pledge = pd_mod.get_stock_pledge(symbol=sym, start_date=start_7d, end_date=date_fmt)
            if not _is_empty(pledge):
                ratio = None
                for col in ["pledge_ratio", "质押比例", "pledge_rate"]:
                    if col in pledge.columns:
                        ratio = float(pledge[col].iloc[-1])
                        break
                if ratio is not None:
                    ctx["pledge_ratio"] = round(ratio, 1)
        except Exception:
            pass

        # 股东人数趋势 (DataFrame)
        try:
            holders = pd_mod.get_holder_count(symbol=sym, start_date=start_7d, end_date=date_fmt)
            if not _is_empty(holders) and len(holders) >= 2:
                hcol = "holder_count" if "holder_count" in holders.columns else holders.columns[0]
                a = holders[hcol].iloc[0]
                b = holders[hcol].iloc[-1]
                if a and b:
                    ctx["holder_trend"] = "集中" if b < a else "分散"
        except Exception:
            pass

        # 财务快报
        try:
            fina = pd_mod.get_fina_performance(symbol=sym, end_quarter=date_fmt)
            if _is_empty(fina):
                fina = pd_mod.get_fina_performance(symbol=sym, info_date=date_fmt)
            if not _is_empty(fina):
                rev = profit = None
                for col in ["revenue", "营业总收入", "total_revenue"]:
                    if col in fina.columns:
                        rev = fina[col].iloc[-1]
                        break
                for col in ["net_profit", "净利润", "net_income"]:
                    if col in fina.columns:
                        profit = fina[col].iloc[-1]
                        break
                if rev or profit:
                    ctx["fina"] = {"revenue": rev, "net_profit": profit}
        except Exception:
            pass

        if ctx:
            result[code] = ctx

    return result


def get_stock_price_snapshot(codes: List[str], trade_date: str) -> Dict:
    """轻量版 — 只拉价格，用于 enrich_signals()"""
    if not codes or not _ensure_connected():
        return {}

    pd_mod = _get_client()
    result = {}
    date_fmt = trade_date.replace("-", "")
    start_7d = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y%m%d")

    for code in codes:
        sym = _format_symbol(code)
        try:
            px = pd_mod.get_stock_daily(symbol=sym, start_date=start_7d, end_date=date_fmt, fields=["close"])
            if not _is_empty(px):
                closes = px["close"].tolist()
                if len(closes) >= 2:
                    chg = round((closes[-1] - closes[-2]) / closes[-2] * 100, 2)
                    chg5 = round((closes[-1] - closes[0]) / closes[0] * 100, 2) if len(closes) >= 5 else None
                    result[code] = {"latest_change_pct": chg, "5d_change_pct": chg5}
        except Exception:
            pass

    return result


# ═══════════════════════════════════════════════════════════════
# 数据获取（独立使用）
# ═══════════════════════════════════════════════════════════════

def get_price_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """A股日线"""
    pd_mod = _get_client()
    data = pd_mod.get_stock_daily(
        symbol=symbol,
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
        fields=["open", "high", "low", "close", "volume", "amount"],
    )
    df = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
    df.sort_index(inplace=True)
    df["next_return"] = df["close"].pct_change().shift(-1)
    logger.info(f"日线: {symbol} {len(df)} 条, {start_date} ~ {end_date}")
    return df


def get_price_minutes(symbol: str, trade_date: str) -> pd.DataFrame:
    """A股分钟线"""
    pd_mod = _get_client()
    data = pd_mod.get_stock_min(symbol=symbol, trade_date=trade_date.replace("-", ""), freq="1min")
    df = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    logger.info(f"分钟线: {symbol} {trade_date} {len(df)} 条")
    return df


def get_margin(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """融资融券"""
    pd_mod = _get_client()
    data = pd_mod.get_margin(
        symbol=symbol,
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
    )
    df = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    logger.info(f"融资融券: {symbol} {len(df)} 条")
    return df


def get_northbound(start_date: str, end_date: str) -> pd.DataFrame:
    """北向资金"""
    pd_mod = _get_client()
    data = pd_mod.get_hsgt_hold(
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
    )
    df = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    logger.info(f"北向资金: {len(df)} 条, {start_date} ~ {end_date}")
    return df


def get_lhb(trade_date: str) -> pd.DataFrame:
    """龙虎榜"""
    pd_mod = _get_client()
    data = pd_mod.get_lhb_list(
        start_date=trade_date.replace("-", ""),
        end_date=trade_date.replace("-", ""),
    )
    df = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    logger.info(f"龙虎榜: {trade_date} {len(df)} 条")
    return df


def get_financial_events(symbol: str, start_date: str, end_date: str) -> Dict:
    """内部人信号"""
    pd_mod = _get_client()
    s = start_date.replace("-", "")
    e = end_date.replace("-", "")
    events = {}
    fetchers = {
        "fina_forecast": lambda: pd_mod.get_fina_forecast(symbol=symbol, start_date=s, end_date=e),
        "repurchase": lambda: pd_mod.get_repurchase(symbol=symbol, start_date=s, end_date=e),
        "shareholder_change": lambda: pd_mod.get_stock_shareholder_change(symbol=symbol, start_date=s, end_date=e),
        "block_trade": lambda: pd_mod.get_block_trade(symbol=symbol, start_date=s, end_date=e),
        "restricted": lambda: pd_mod.get_restricted_list(symbol=symbol, start_date=s, end_date=e),
    }
    for name, fetcher in fetchers.items():
        try:
            events[name] = fetcher()
        except Exception as e:
            logger.debug(f"{name}: {e}")
    return events


# ═══════════════════════════════════════════════════════════════
# 交叉验证
# ═══════════════════════════════════════════════════════════════

def verify_signal(symbol: str, news_sentiment: str, news_confidence: float,
                  news_date: str, lookback: int = 20, lookahead: int = 3) -> Dict:
    """4 维度交叉验证一条新闻信号"""
    start = (datetime.strptime(news_date, "%Y-%m-%d") - timedelta(days=lookback)).strftime("%Y-%m-%d")
    end = (datetime.strptime(news_date, "%Y-%m-%d") + timedelta(days=lookahead)).strftime("%Y-%m-%d")

    result = {
        "symbol": symbol,
        "signal": {"sentiment": news_sentiment, "confidence": news_confidence, "date": news_date},
        "verification": {},
    }

    try:
        price = get_price_daily(symbol, start, end)
        if news_date in price.index:
            r = float(price.loc[news_date, "next_return"])
            result["verification"]["price"] = {
                "next_day_return_pct": round(r * 100, 2),
                "matches_signal": (news_sentiment == "bullish" and r > 0) or (news_sentiment == "bearish" and r < 0),
            }
    except Exception as e:
        result["verification"]["price"] = {"error": str(e)}

    try:
        mg = get_margin(symbol, start, end)
        result["verification"]["margin"] = _margin_direction(mg)
    except Exception as e:
        result["verification"]["margin"] = {"error": str(e)}

    try:
        fe = get_financial_events(symbol, start, end)
        result["verification"]["insider"] = {
            k: f"{len(v) if not _is_empty(v) else 0}" for k, v in fe.items()
        }
    except Exception as e:
        result["verification"]["insider"] = {"error": str(e)}

    try:
        lhb = get_lhb(news_date)
        result["verification"]["lhb"] = {
            "on_list": symbol in lhb.get("symbol", pd.Series()).values if not lhb.empty else False
        }
    except Exception as e:
        result["verification"]["lhb"] = {"error": str(e)}

    return result


def _margin_direction(df: pd.DataFrame) -> Dict:
    if _is_empty(df):
        return {"status": "no_data"}
    try:
        if "margin_balance" in df.columns and len(df) >= 2:
            a, b = df["margin_balance"].iloc[0], df["margin_balance"].iloc[-1]
            return {"change_pct": round(float(b - a) / float(a) * 100, 2), "direction": "up" if b > a else "down"}
    except Exception:
        pass
    return {"status": "data_incomplete"}


# ═══════════════════════════════════════════════════════════════
# 批量回测
# ═══════════════════════════════════════════════════════════════

def _iter_stocks_from_row(row) -> list:
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
    if not stocks:
        tid = str(row.get("target_id", ""))
        code = tid.split("_")[0]
        if code.isdigit() and len(code) == 6:
            stocks.append((code, ""))
    return stocks


def backtest(parquet_path: str, lookahead: int = 1) -> pd.DataFrame:
    """从打分后的 Parquet 逐条对照实际股价"""
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
                tdate = str(row["trade_date"])
                end_date = (datetime.strptime(tdate, "%Y-%m-%d") + timedelta(days=lookahead + 1)).strftime("%Y-%m-%d")
                price = get_price_daily(symbol, tdate, end_date)
                if tdate in price.index:
                    r = float(price.loc[tdate, "next_return"])
                    direction = str(score.get("trading_direction", "hold"))
                    rows.append({
                        "symbol": symbol, "name": name, "date": tdate,
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
# 信号增强 — 嵌入 SKILL.md 第四步
# ═══════════════════════════════════════════════════════════════

def enrich_signals(signals: list, trade_date: str) -> list:
    """
    主动验证每条信号 — PandaAI 数据改结论 + 补全上下文。

    每条信号新增:
      - confidence_original: LLM 原始置信度
      - confidence: 经 PandaAI 调整后的置信度
      - verify: {price{latest_change_pct,5d_change_pct}, margin, lhb, pledge_ratio, industry}
      - alerts: [数据矛盾/确认描述]
      - analysis: 一句话分析总结
    """
    if not signals:
        return signals

    for s in signals:
        s["confidence_original"] = s.get("confidence", 0)

    if not _ensure_connected():
        for s in signals:
            s["verify"] = {}
            s["alerts"] = ["PandaAI 未配置"]
            s["analysis"] = ""
        return signals

    pd_mod = _get_client()
    codes = list({s["code"] for s in signals if s.get("code")})
    date_fmt = trade_date.replace("-", "")
    start_7d = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y%m%d")
    start_5d = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y%m%d")

    # 批量拉全量数据
    price_cache = get_stock_price_snapshot(codes, trade_date)

    margin_cache = {}
    for code in codes:
        try:
            mg = pd_mod.get_margin(symbol=_format_symbol(code), start_date=start_5d, end_date=date_fmt)
            if not _is_empty(mg) and "margin_balance" in mg.columns and len(mg) >= 2:
                a = mg["margin_balance"].iloc[0]
                b = mg["margin_balance"].iloc[-1]
                margin_cache[code] = "up" if b > a else "down"
        except Exception:
            pass

    pledge_cache = {}
    for code in codes:
        try:
            pledge = pd_mod.get_stock_pledge(symbol=_format_symbol(code), start_date=start_7d, end_date=date_fmt)
            if not _is_empty(pledge):
                for col in ["pledge_ratio", "质押比例", "pledge_rate"]:
                    if col in pledge.columns:
                        ratio = float(pledge[col].iloc[-1])
                        pledge_cache[code] = round(ratio, 1)
                        break
        except Exception:
            pass

    industry_cache = {}
    for code in codes:
        try:
            ind = pd_mod.get_stock_industry(stock_symbol=_format_symbol(code))
            if not _is_empty(ind):
                row = ind.iloc[0].to_dict() if isinstance(ind, pd.DataFrame) else ind
                industry_cache[code] = row.get("industry_name", "")
        except Exception:
            pass

    lhb_cache = {}
    try:
        lhb_list = pd_mod.get_lhb_list(start_date=date_fmt, end_date=date_fmt)
        if not _is_empty(lhb_list):
            for _, item in lhb_list.iterrows():
                sym = str(item.get("symbol", ""))
                code = sym[-6:] if len(sym) >= 6 else sym
                if code.isdigit() and len(code) == 6:
                    lhb_cache[code] = True
    except Exception:
        pass

    # ── 主动调整每条信号的置信度 ──
    for s in signals:
        code = s.get("code", "")
        direction = s.get("direction", "hold")
        conf = s.get("confidence", 0)
        px = price_cache.get(code, {})
        margin = margin_cache.get(code)
        pledge = pledge_cache.get(code)
        on_lhb = lhb_cache.get(code, False)
        alerts = []
        adjustment = 0.0

        chg = px.get("latest_change_pct")

        # 价格方向检查
        if chg is not None:
            if direction == "bullish" and chg < -2:
                alerts.append(f"价格矛盾: 看多但今日{chg}%")
                adjustment -= 0.15
            elif direction == "bearish" and chg > 2:
                alerts.append(f"价格矛盾: 看空但今日+{chg}%")
                adjustment -= 0.15
            elif direction == "bullish" and chg > 0:
                alerts.append(f"价格确认: +{chg}%")
                adjustment += 0.05
            elif direction == "bearish" and chg < 0:
                alerts.append(f"价格确认: {chg}%")
                adjustment += 0.05

        # 融资方向检查
        if margin:
            if direction == "bullish" and margin == "down":
                alerts.append("融资矛盾: 看多但杠杆减")
                adjustment -= 0.10
            elif direction == "bearish" and margin == "up":
                alerts.append("融资矛盾: 看空但杠杆增")
                adjustment -= 0.10
            elif direction == "bullish" and margin == "up":
                alerts.append("融资确认: 杠杆同向增")
                adjustment += 0.10
            elif direction == "bearish" and margin == "down":
                alerts.append("融资确认: 杠杆同向减")
                adjustment += 0.10

        # 质押风险
        if pledge is not None and pledge > 50:
            alerts.append(f"质押高危: {pledge}%")
            adjustment -= 0.15
        elif pledge is not None and pledge > 30:
            alerts.append(f"质押偏高: {pledge}%")

        # 龙虎榜
        if on_lhb:
            alerts.append("龙虎榜上榜")

        # 应用调整
        new_conf = round(max(0.0, min(1.0, conf + adjustment)), 2)
        s["confidence"] = new_conf
        s["confidence_original"] = conf

        # 丰富验证数据
        chg_5d = px.get("5d_change_pct")
        industry = industry_cache.get(code, "")
        pledge_ratio = pledge_cache.get(code)

        s["verify"] = {
            "price_1d": chg,
            "price_5d": chg_5d,
            "margin": margin,
            "lhb": on_lhb,
            "pledge_ratio": pledge_ratio,
            "pledge_risk": "high" if (pledge_ratio and pledge_ratio > 50) else ("medium" if (pledge_ratio and pledge_ratio > 30) else ("low" if pledge_ratio is not None else None)),
            "industry": industry,
        }
        s["alerts"] = alerts

        # 生成一句话分析
        parts = []
        name = s.get("name", code)
        dir_cn = "看多" if direction == "bullish" else "看空"
        parts.append(f"{name} {dir_cn}")

        if chg is not None:
            parts.append(f"今日{chg:+.1f}%")
        if chg_5d is not None:
            parts.append(f"5日{chg_5d:+.1f}%")
        if margin:
            parts.append(f"融资{'增' if margin == 'up' else '减'}")
        if industry:
            parts.append(f"行业:{industry}")
        if pledge_ratio is not None and pledge_ratio > 30:
            parts.append(f"质押{pledge_ratio}%{'⚠' if pledge_ratio > 50 else ''}")
        if on_lhb:
            parts.append("龙虎榜上榜")
        if adjustment > 0:
            parts.append(f"→ 置信度上调{adjustment:+.2f}")
        elif adjustment < 0:
            parts.append(f"→ 置信度下调{adjustment:.2f}")

        s["analysis"] = " | ".join(parts)

    signals.sort(key=lambda x: x["confidence"], reverse=True)
    return signals


# ═══════════════════════════════════════════════════════════════
# 市场扫描
# ═══════════════════════════════════════════════════════════════

def market_scan(trade_date: str) -> Dict:
    """当日市场全景"""
    require_panda()
    result = {"date": trade_date}
    try:
        ix = get_price_daily("000001.SH", trade_date, trade_date)
        result["sh_index"] = float(ix.iloc[-1]["close"]) if not ix.empty else None
    except Exception:
        result["sh_index"] = None
    try:
        nb = get_northbound(
            (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"), trade_date)
        result["northbound_rows"] = len(nb)
    except Exception:
        result["northbound_rows"] = 0
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
    parser.add_argument("--symbol", default="000001.SZ")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--market-scan", action="store_true", help="市场全景扫描")
    parser.add_argument("--backtest", type=str, help="Parquet 路径: 批量回测")
    args = parser.parse_args()

    panda_ok = init_pandaai()
    if not panda_ok:
        if args.backtest or args.market_scan or args.verify:
            logger.error("PandaAI 未连接，请检查 .env 配置")
            sys.exit(1)
        else:
            logger.info("PandaAI 未配置")
            return

    if args.backtest:
        backtest(args.backtest)
    elif args.market_scan:
        scan = market_scan(args.date)
        print(json.dumps(scan, indent=2, ensure_ascii=False, default=str))
    elif args.verify:
        result = verify_signal(symbol=args.symbol, news_sentiment="bullish", news_confidence=0.85, news_date=args.date)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print("未指定操作。可用: --verify / --market-scan / --backtest")


if __name__ == "__main__":
    main()
