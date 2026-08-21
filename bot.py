from flask import Flask, request, jsonify
from datetime import datetime, timezone
from collections import defaultdict, deque
import os
import math

app = Flask(__name__)

VERSION = "FINAL-4.0"
MAX_CANDLES = 500
history = defaultdict(lambda: deque(maxlen=MAX_CANDLES))


# ============================================================
# HELPERS
# ============================================================

def f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))


def bull(c): return f(c["close"]) > f(c["open"])
def bear(c): return f(c["close"]) < f(c["open"])


def body(c):
    return abs(f(c["close"]) - f(c["open"]))


def low_wick(c):
    return max(0, min(f(c["open"]), f(c["close"])) - f(c["low"]))


def high_wick(c):
    return max(0, f(c["high"]) - max(f(c["open"]), f(c["close"])))


def atr(cs, period=14):
    if len(cs) < 2:
        return 0
    trs = []
    start = max(1, len(cs) - period)
    for i in range(start, len(cs)):
        h, l = f(cs[i]["high"]), f(cs[i]["low"])
        pc = f(cs[i-1]["close"])
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return sum(trs) / len(trs) if trs else 0


def ema(values, period):
    if not values:
        return 0
    k = 2 / (period + 1)
    e = values[0]
    for x in values[1:]:
        e = x*k + e*(1-k)
    return e


def normalize(c):
    return {
        "time": c.get("time", ""),
        "open": f(c.get("open")),
        "high": f(c.get("high")),
        "low": f(c.get("low")),
        "close": f(c.get("close")),
        "volume": f(c.get("volume"), 0),
    }


# ============================================================
# MARKET STRUCTURE
# ============================================================

def pivot_high(cs, i, s=2):
    if i < s or i+s >= len(cs):
        return False
    h = f(cs[i]["high"])
    return all(j == i or f(cs[j]["high"]) < h
               for j in range(i-s, i+s+1))


def pivot_low(cs, i, s=2):
    if i < s or i+s >= len(cs):
        return False
    l = f(cs[i]["low"])
    return all(j == i or f(cs[j]["low"]) > l
               for j in range(i-s, i+s+1))


def swings(cs):
    highs, lows = [], []
    for i in range(len(cs)):
        if pivot_high(cs, i):
            highs.append((i, f(cs[i]["high"])))
        if pivot_low(cs, i):
            lows.append((i, f(cs[i]["low"])))
    return highs, lows


def structure_engine(cs):
    ph, pl = swings(cs)

    if len(ph) < 2 or len(pl) < 2:
        return {
            "trend": "neutral",
            "structure": "insufficient",
            "bos": None,
            "choch": None,
            "swing_high": None,
            "swing_low": None,
        }

    h1, h2 = ph[-2][1], ph[-1][1]
    l1, l2 = pl[-2][1], pl[-1][1]
    close = f(cs[-1]["close"])

    if h2 > h1 and l2 > l1:
        trend, structure = "bullish", "HH_HL"
    elif h2 < h1 and l2 < l1:
        trend, structure = "bearish", "LH_LL"
    else:
        trend, structure = "range", "mixed"

    bos = None
    choch = None

    if close > h2:
        bos = "bullish_BOS"
    elif close < l2:
        bos = "bearish_BOS"

    if trend == "bearish" and close > h2:
        choch = "bullish_CHoCH"
    elif trend == "bullish" and close < l2:
        choch = "bearish_CHoCH"

    return {
        "trend": trend,
        "structure": structure,
        "bos": bos,
        "choch": choch,
        "swing_high": h2,
        "swing_low": l2,
    }


# ============================================================
# SUPPORT / RESISTANCE + PULLBACK / RETEST
# ============================================================

def sr_engine(cs, lookback=100):
    data = cs[-lookback:]
    ph, pl = swings(data)

    price = f(cs[-1]["close"])

    support = max(
        [v for _, v in pl if v <= price],
        default=min(f(x["low"]) for x in data)
    )

    resistance = min(
        [v for _, v in ph if v >= price],
        default=max(f(x["high"]) for x in data)
    )

    av = max(atr(data), price * 0.0003, 1e-9)

    # Break/retest detection:
    # Bullish: resistance was broken, then current price retested
    # that old resistance from above and rejected upward.
    bull_pullback = False
    bear_pullback = False

    if len(data) >= 8:
        for i in range(max(3, len(data)-12), len(data)-1):
            old_res = f(data[i]["high"])
            later = data[i+1:]

            if any(f(x["close"]) > old_res for x in later[:-1]):
                c = data[-1]
                if f(c["low"]) <= old_res + av*0.35 and f(c["close"]) > old_res:
                    bull_pullback = True
                    resistance = old_res
                    break

            old_sup = f(data[i]["low"])
            if any(f(x["close"]) < old_sup for x in later[:-1]):
                c = data[-1]
                if f(c["high"]) >= old_sup - av*0.35 and f(c["close"]) < old_sup:
                    bear_pullback = True
                    support = old_sup
                    break

    near_support = abs(price-support) <= av*0.45
    near_resistance = abs(price-resistance) <= av*0.45

    bullish_rejection = bull(cs[-1]) and low_wick(cs[-1]) >= body(cs[-1]) * 0.8
    bearish_rejection = bear(cs[-1]) and high_wick(cs[-1]) >= body(cs[-1]) * 0.8

    return {
        "support": support,
        "resistance": resistance,
        "near_support": near_support,
        "near_resistance": near_resistance,
        "bullish_pullback_retest": bull_pullback and bullish_rejection,
        "bearish_pullback_retest": bear_pullback and bearish_rejection,
        "pullback_zone": (
            "bullish_retest" if bull_pullback and bullish_rejection
            else "bearish_retest" if bear_pullback and bearish_rejection
            else "none"
        ),
    }


# ============================================================
# LIQUIDITY SWEEP
# ============================================================

def liquidity_engine(cs, lookback=20):
    if len(cs) < lookback + 2:
        return {"type": "none", "level": None, "strength": 0}

    old = cs[-lookback-1:-1]
    c = cs[-1]

    old_high = max(f(x["high"]) for x in old)
    old_low = min(f(x["low"]) for x in old)

    if f(c["low"]) < old_low and f(c["close"]) > old_low:
        return {
            "type": "sell_side_sweep",
            "level": old_low,
            "strength": int(clamp(65 + low_wick(c)/max(atr(cs),1e-9)*20))
        }

    if f(c["high"]) > old_high and f(c["close"]) < old_high:
        return {
            "type": "buy_side_sweep",
            "level": old_high,
            "strength": int(clamp(65 + high_wick(c)/max(atr(cs),1e-9)*20))
        }

    return {"type": "none", "level": None, "strength": 0}


# ============================================================
# ICT / SMC
# ============================================================

def fvg_engine(cs):
    if len(cs) < 3:
        return {"type": "none"}

    a, c = cs[-3], cs[-1]

    if f(c["low"]) > f(a["high"]):
        return {
            "type": "bullish_FVG",
            "low": f(a["high"]),
            "high": f(c["low"])
        }

    if f(c["high"]) < f(a["low"]):
        return {
            "type": "bearish_FVG",
            "low": f(c["high"]),
            "high": f(a["low"])
        }

    return {"type": "none"}


def order_block_engine(cs):
    if len(cs) < 5:
        return {"type": "none"}

    for i in range(len(cs)-2, max(-1, len(cs)-10), -1):
        c, n = cs[i], cs[i+1]

        if bear(c) and bull(n) and f(n["close"]) > f(c["high"]):
            return {
                "type": "bullish_OB",
                "low": f(c["low"]),
                "high": f(c["high"])
            }

        if bull(c) and bear(n) and f(n["close"]) < f(c["low"]):
            return {
                "type": "bearish_OB",
                "low": f(c["low"]),
                "high": f(c["high"])
            }

    return {"type": "none"}


def premium_discount(cs):
    data = cs[-50:]
    hi = max(f(x["high"]) for x in data)
    lo = min(f(x["low"]) for x in data)
    eq = (hi + lo) / 2
    price = f(cs[-1]["close"])

    return {
        "high": hi,
        "low": lo,
        "equilibrium": eq,
        "zone": "premium" if price > eq else "discount" if price < eq else "equilibrium"
    }


# ============================================================
# PRICE ACTION + TREND
# ============================================================

def price_action(cs):
    c, p = cs[-1], cs[-2]

    if bull(c) and low_wick(c) > body(c) * 1.2:
        return {"bias": "bullish", "pattern": "bullish_rejection"}
    if bear(c) and high_wick(c) > body(c) * 1.2:
        return {"bias": "bearish", "pattern": "bearish_rejection"}
    if bull(c) and f(c["close"]) > f(p["high"]):
        return {"bias": "bullish", "pattern": "bullish_displacement"}
    if bear(c) and f(c["close"]) < f(p["low"]):
        return {"bias": "bearish", "pattern": "bearish_displacement"}

    return {"bias": "bullish" if bull(c) else "bearish" if bear(c) else "neutral",
            "pattern": "normal"}


def trend_engine(cs):
    values = [f(x["close"]) for x in cs[-60:]]
    if len(values) < 25:
        return {"trend": "neutral", "ema9": None, "ema21": None}

    e9 = ema(values, 9)
    e21 = ema(values, 21)

    return {
        "trend": "bullish" if e9 > e21 else "bearish" if e9 < e21 else "neutral",
        "ema9": e9,
        "ema21": e21
    }


# ============================================================
# NEWS FILTER
#
# TradingView should send:
# {
#   "news": {
#       "status": "SAFE" | "CAUTION" | "BLOCKED",
#       "minutes_to_event": 45,
#       "impact": "high",
#       "currency": "USD",
#       "event": "CPI"
#   }
# }
#
# The bot never invents live news. If no news object is supplied,
# status is UNKNOWN and the signal is not automatically blocked.
# ============================================================

def news_engine(data):
    news = data.get("news")

    if not isinstance(news, dict):
        return {
            "status": "UNKNOWN",
            "trade_allowed": True,
            "reason": "No news calendar data supplied"
        }

    status = str(news.get("status", "UNKNOWN")).upper()
    impact = str(news.get("impact", "")).lower()
    minutes = f(news.get("minutes_to_event"), 999999)

    # Hard block around high-impact USD news.
    if status == "BLOCKED":
        return {
            "status": "BLOCKED",
            "trade_allowed": False,
            "reason": news.get("event", "High-impact news")
        }

    if impact == "high" and minutes <= 30:
        return {
            "status": "BLOCKED",
            "trade_allowed": False,
            "reason": news.get("event", "High-impact USD news within 30 minutes")
        }

    if status == "CAUTION" or (impact == "high" and minutes <= 60):
        return {
            "status": "CAUTION",
            "trade_allowed": True,
            "reason": news.get("event", "High-impact news approaching")
        }

    return {
        "status": "SAFE",
        "trade_allowed": True,
        "reason": news.get("event", "No immediate high-impact news")
    }


# ============================================================
# FINAL CONFLUENCE ENGINE
# ============================================================

def analyse(symbol, timeframe, cs, payload):
    if len(cs) < 20:
        return {
            "signal": "WAIT",
            "confidence": 0,
            "status": "collecting_data",
            "reason": f"Need at least 20 candles ({len(cs)}/20)"
        }

    ms = structure_engine(cs)
    sr = sr_engine(cs)
    liq = liquidity_engine(cs)
    pa = price_action(cs)
    tr = trend_engine(cs)
    fvg = fvg_engine(cs)
    ob = order_block_engine(cs)
    pd = premium_discount(cs)
    news = news_engine(payload)

    buy = 0
    sell = 0
    buy_reasons = []
    sell_reasons = []

    # Market structure
    if ms["trend"] == "bullish":
        buy += 20
        buy_reasons.append("bullish structure")
    elif ms["trend"] == "bearish":
        sell += 20
        sell_reasons.append("bearish structure")

    # Liquidity
    if liq["type"] == "sell_side_sweep":
        buy += 30
        buy_reasons.append("sell-side liquidity sweep")
    elif liq["type"] == "buy_side_sweep":
        sell += 30
        sell_reasons.append("buy-side liquidity sweep")

    # S/R pullback / retest
    if sr["bullish_pullback_retest"]:
        buy += 25
        buy_reasons.append("S/R bullish pullback + rejection")

    if sr["bearish_pullback_retest"]:
        sell += 25
        sell_reasons.append("S/R bearish pullback + rejection")

    # Price action
    if pa["bias"] == "bullish":
        buy += 10
        buy_reasons.append(pa["pattern"])
    elif pa["bias"] == "bearish":
        sell += 10
        sell_reasons.append(pa["pattern"])

    # BOS / CHoCH
    if ms["bos"] == "bullish_BOS":
        buy += 15
        buy_reasons.append("bullish BOS")
    elif ms["bos"] == "bearish_BOS":
        sell += 15
        sell_reasons.append("bearish BOS")

    if ms["choch"] == "bullish_CHoCH":
        buy += 15
        buy_reasons.append("bullish CHoCH")
    elif ms["choch"] == "bearish_CHoCH":
        sell += 15
        sell_reasons.append("bearish CHoCH")

    # Trend
    if tr["trend"] == "bullish":
        buy += 8
        buy_reasons.append("EMA trend bullish")
    elif tr["trend"] == "bearish":
        sell += 8
        sell_reasons.append("EMA trend bearish")

    # ICT context
    if pd["zone"] == "discount":
        buy += 5
        buy_reasons.append("discount")
    elif pd["zone"] == "premium":
        sell += 5
        sell_reasons.append("premium")

    if fvg["type"] == "bullish_FVG":
        buy += 4
        buy_reasons.append("bullish FVG")
    elif fvg["type"] == "bearish_FVG":
        sell += 4
        sell_reasons.append("bearish FVG")

    if ob["type"] == "bullish_OB":
        buy += 4
        buy_reasons.append("bullish OB")
    elif ob["type"] == "bearish_OB":
        sell += 4
        sell_reasons.append("bearish OB")

    signal = "WAIT"
    score = max(buy, sell)
    reasons = buy_reasons if buy >= sell else sell_reasons

    # A+ minimum:
    # liquidity + price action + directional confluence.
    if buy >= 75 and buy > sell + 10:
        signal = "BUY"
        reasons = buy_reasons
    elif sell >= 75 and sell > buy + 10:
        signal = "SELL"
        reasons = sell_reasons

    # News block overrides technical signal.
    if not news["trade_allowed"]:
        signal = "WAIT"
        score = min(score, 69)
        reasons = [f"NEWS BLOCK: {news['reason']}"]

    # Unknown news is allowed but clearly reported.
    confidence = int(clamp(score))

    plan = trade_plan(cs, signal, liq, sr)

    return {
        "signal": signal,
        "confidence": confidence,
        "reason": " + ".join(reasons) if reasons else "No A+ confluence",
        "symbol": symbol,
        "timeframe": timeframe,
        "price": f(cs[-1]["close"]),
        "market_structure": ms,
        "support_resistance": sr,
        "liquidity": liq,
        "price_action": pa,
        "trend": tr,
        "premium_discount": pd,
        "fvg": fvg,
        "order_block": ob,
        "news_filter": news,
        "trade_plan": plan,
        "candle_count": len(cs),
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


def trade_plan(cs, signal, liq, sr):
    price = f(cs[-1]["close"])
    av = max(atr(cs), price * 0.0005, 1e-9)

    if signal == "BUY":
        ref = liq.get("level") or sr.get("support") or f(cs[-1]["low"])
        sl = min(f(cs[-1]["low"]), f(ref)) - av * 0.15
        risk = max(price - sl, av * 0.60)
        return {
            "entry": price,
            "sl": price - risk,
            "tp1": price + risk * 1.5,
            "tp2": price + risk * 2,
            "tp3": price + risk * 3,
            "rr": [1.5, 2, 3]
        }

    if signal == "SELL":
        ref = liq.get("level") or sr.get("resistance") or f(cs[-1]["high"])
        sl = max(f(cs[-1]["high"]), f(ref)) + av * 0.15
        risk = max(sl - price, av * 0.60)
        return {
            "entry": price,
            "sl": price + risk,
            "tp1": price - risk * 1.5,
            "tp2": price - risk * 2,
            "tp3": price - risk * 3,
            "rr": [1.5, 2, 3]
        }

    return {
        "entry": price,
        "sl": None,
        "tp1": None,
        "tp2": None,
        "tp3": None,
        "rr": []
    }


# ============================================================
# WEBHOOK DATA
# ============================================================

def add_candle(symbol, timeframe, candle):
    key = f"{symbol.upper()}::{timeframe.lower()}"
    c = normalize(candle)

    if history[key] and history[key][-1]["time"] == c["time"]:
        history[key][-1] = c
    else:
        history[key].append(c)

    return key


def ingest(payload):
    symbol = str(payload.get("symbol", "XAUUSD")).upper()
    timeframe = str(payload.get("timeframe", "3m")).lower()

    # One candle
    if all(k in payload for k in ("open", "high", "low", "close")):
        add_candle(symbol, timeframe, payload)

    # Candle array
    candles = payload.get("candles", [])
    if isinstance(candles, list):
        for c in candles:
            if isinstance(c, dict) and all(
                k in c for k in ("open", "high", "low", "close")
            ):
                add_candle(symbol, timeframe, c)

    key = f"{symbol}::{timeframe}"
    return symbol, timeframe, list(history[key])


# ============================================================
# ROUTES
# ============================================================

@app.get("/")
def home():
    return jsonify({
        "status": "online",
        "name": "XAU AI Trading Copilot",
        "version": VERSION,
        "modules": [
            "SMC", "ICT", "MSNR", "Support/Resistance",
            "S/R Pullback Retest", "Liquidity Sweep",
            "BOS", "CHoCH", "Price Action",
            "Premium/Discount", "FVG", "Order Block",
            "News Filter", "Risk/TP"
        ]
    })


@app.get("/health")
def health():
    return jsonify({
        "status": "healthy",
        "version": VERSION,
        "time": datetime.now(timezone.utc).isoformat()
    })


@app.get("/status")
def status():
    return jsonify({
        "status": "online",
        "version": VERSION,
        "stored_candles": {
            key: len(value) for key, value in history.items()
        }
    })


@app.post("/reset")
def reset():
    history.clear()
    return jsonify({"status": "success", "message": "History cleared"})


@app.post("/webhook")
def webhook():
    try:
        payload = request.get_json(silent=True) or {}

        if not payload:
            return jsonify({
                "status": "error",
                "message": "JSON payload required"
            }), 400

        symbol, timeframe, cs = ingest(payload)

        result = analyse(
            symbol,
            timeframe,
            cs,
            payload
        )

        return jsonify({
            "status": "success",
            "analysis": result
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.post("/analyse")
def analyse_route():
    return webhook()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
