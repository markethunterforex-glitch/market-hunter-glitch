from flask import Flask, request, jsonify
from datetime import datetime
import os
import math

app = Flask(__name__)

# ============================================================
# XAU AI TRADING COPILOT
# SMC + ICT + MSNR + S/R + LIQUIDITY SWEEP
# MARKET STRUCTURE + PRICE ACTION ENGINE
# Version 2.0
# ============================================================


# ============================================================
# BASIC HELPERS
# ============================================================

def safe_float(value, default=0.0):
    try:
        return float(value)
    except:
        return default


def clamp(value, low, high):
    return max(low, min(high, value))


def avg(values):
    values = [v for v in values if isinstance(v, (int, float))]
    if not values:
        return 0.0
    return sum(values) / len(values)


def candle_range(c):
    return max(0.0, c["high"] - c["low"])


def body_size(c):
    return abs(c["close"] - c["open"])


def is_bullish(c):
    return c["close"] > c["open"]


def is_bearish(c):
    return c["close"] < c["open"]


# ============================================================
# NORMALIZE CANDLE DATA
# ============================================================

def normalize_candles(raw):
    candles = []

    if not isinstance(raw, list):
        return candles

    for item in raw:
        if not isinstance(item, dict):
            continue

        try:
            c = {
                "time": item.get("time", ""),
                "open": safe_float(item.get("open")),
                "high": safe_float(item.get("high")),
                "low": safe_float(item.get("low")),
                "close": safe_float(item.get("close")),
                "volume": safe_float(item.get("volume", 0))
            }

            if c["high"] <= 0 or c["low"] <= 0:
                continue

            if c["high"] < c["low"]:
                continue

            candles.append(c)

        except:
            continue

    return candles


# ============================================================
# PRICE ACTION
# ============================================================

def price_action(candles):
    if len(candles) < 3:
        return {
            "bullish": False,
            "bearish": False,
            "pattern": "insufficient_data"
        }

    c = candles[-1]
    p = candles[-2]

    rng = candle_range(c)

    if rng <= 0:
        return {
            "bullish": False,
            "bearish": False,
            "pattern": "neutral"
        }

    body = body_size(c)

    upper_wick = c["high"] - max(c["open"], c["close"])
    lower_wick = min(c["open"], c["close"]) - c["low"]

    bullish = False
    bearish = False
    pattern = "normal"

    # Bullish engulfing
    if (
        is_bullish(c)
        and is_bearish(p)
        and c["close"] > p["open"]
        and c["open"] < p["close"]
    ):
        bullish = True
        pattern = "bullish_engulfing"

    # Bearish engulfing
    elif (
        is_bearish(c)
        and is_bullish(p)
        and c["open"] > p["close"]
        and c["close"] < p["open"]
    ):
        bearish = True
        pattern = "bearish_engulfing"

    # Bullish rejection
    elif lower_wick > body * 1.5 and c["close"] > c["open"]:
        bullish = True
        pattern = "bullish_rejection"

    # Bearish rejection
    elif upper_wick > body * 1.5 and c["close"] < c["open"]:
        bearish = True
        pattern = "bearish_rejection"

    return {
        "bullish": bullish,
        "bearish": bearish,
        "pattern": pattern
    }


# ============================================================
# MARKET STRUCTURE
# ============================================================

def market_structure(candles, lookback=20):
    if len(candles) < 8:
        return {
            "trend": "neutral",
            "bos": "none",
            "choch": "none",
            "structure": "insufficient_data"
        }

    data = candles[-lookback:] if len(candles) > lookback else candles

    highs = [c["high"] for c in data]
    lows = [c["low"] for c in data]

    recent_high = max(highs[:-2])
    recent_low = min(lows[:-2])

    last = data[-1]
    previous = data[-2]

    trend = "neutral"
    bos = "none"
    choch = "none"

    # Basic directional structure
    if data[-1]["close"] > data[0]["close"]:
        trend = "bullish"
    elif data[-1]["close"] < data[0]["close"]:
        trend = "bearish"

    # Break of structure
    if last["close"] > recent_high:
        bos = "bullish"

    elif last["close"] < recent_low:
        bos = "bearish"

    # Reversal / CHoCH approximation
    if trend == "bearish" and last["close"] > previous["high"]:
        choch = "bullish"

    elif trend == "bullish" and last["close"] < previous["low"]:
        choch = "bearish"

    return {
        "trend": trend,
        "bos": bos,
        "choch": choch,
        "structure": "valid"
    }


# ============================================================
# SUPPORT / RESISTANCE
# ============================================================

def support_resistance(candles, lookback=50):
    if len(candles) < 5:
        return {
            "support": 0,
            "resistance": 0
        }

    data = candles[-lookback:] if len(candles) > lookback else candles

    support = min(c["low"] for c in data)
    resistance = max(c["high"] for c in data)

    return {
        "support": support,
        "resistance": resistance
    }


# ============================================================
# LIQUIDITY SWEEP
# ============================================================

def liquidity_sweep(candles, lookback=10):
    if len(candles) < lookback + 2:
        return {
            "sweep": "none",
            "level": 0
        }

    previous = candles[-lookback-1:-1]
    current = candles[-1]

    previous_high = max(c["high"] for c in previous)
    previous_low = min(c["low"] for c in previous)

    # Sell-side liquidity sweep
    # Price takes previous low and closes back above it
    if (
        current["low"] < previous_low
        and current["close"] > previous_low
    ):
        return {
            "sweep": "sell_side_sweep",
            "level": previous_low
        }

    # Buy-side liquidity sweep
    # Price takes previous high and closes back below it
    if (
        current["high"] > previous_high
        and current["close"] < previous_high
    ):
        return {
            "sweep": "buy_side_sweep",
            "level": previous_high
        }

    return {
        "sweep": "none",
        "level": 0
    }


# ============================================================
# FAIR VALUE GAP
# ============================================================

def detect_fvg(candles):
    if len(candles) < 3:
        return {
            "bullish": False,
            "bearish": False,
            "type": "none"
        }

    a = candles[-3]
    b = candles[-2]
    c = candles[-1]

    # Bullish FVG
    if c["low"] > a["high"]:
        return {
            "bullish": True,
            "bearish": False,
            "type": "bullish_fvg",
            "low": a["high"],
            "high": c["low"]
        }

    # Bearish FVG
    if c["high"] < a["low"]:
        return {
            "bullish": False,
            "bearish": True,
            "type": "bearish_fvg",
            "low": c["high"],
            "high": a["low"]
        }

    return {
        "bullish": False,
        "bearish": False,
        "type": "none"
    }


# ============================================================
# ORDER BLOCK
# ============================================================

def detect_order_block(candles):
    if len(candles) < 5:
        return {
            "type": "none"
        }

    last = candles[-1]
    previous = candles[-2]

    # Bullish OB approximation:
    # Previous bearish candle followed by strong bullish move
    if is_bearish(previous) and is_bullish(last):
        if last["close"] > previous["high"]:
            return {
                "type": "bullish_ob",
                "high": previous["high"],
                "low": previous["low"]
            }

    # Bearish OB approximation:
    # Previous bullish candle followed by strong bearish move
    if is_bullish(previous) and is_bearish(last):
        if last["close"] < previous["low"]:
            return {
                "type": "bearish_ob",
                "high": previous["high"],
                "low": previous["low"]
            }

    return {
        "type": "none"
    }


# ============================================================
# PREMIUM / DISCOUNT
# ============================================================

def premium_discount(candles, lookback=50):
    if not candles:
        return {
            "zone": "unknown",
            "equilibrium": 0,
            "high": 0,
            "low": 0
        }

    data = candles[-lookback:] if len(candles) > lookback else candles

    high = max(c["high"] for c in data)
    low = min(c["low"] for c in data)

    equilibrium = (high + low) / 2
    price = candles[-1]["close"]

    if price < equilibrium:
        zone = "discount"
    elif price > equilibrium:
        zone = "premium"
    else:
        zone = "equilibrium"

    return {
        "zone": zone,
        "equilibrium": equilibrium,
        "high": high,
        "low": low
    }


# ============================================================
# ATR
# ============================================================

def calculate_atr(candles, period=14):
    if len(candles) < 2:
        return 0

    trs = []

    start = max(1, len(candles) - period)

    for i in range(start, len(candles)):
        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"])
        )

        trs.append(tr)

    return avg(trs)


# ============================================================
# TREND STRENGTH
# ============================================================

def trend_strength(candles):
    if len(candles) < 10:
        return {
            "trend": "neutral",
            "strength": 0
        }

    closes = [c["close"] for c in candles[-10:]]

    first = closes[0]
    last = closes[-1]

    if first == 0:
        return {
            "trend": "neutral",
            "strength": 0
        }

    move = ((last - first) / first) * 100

    if move > 0.10:
        trend = "bullish"
    elif move < -0.10:
        trend = "bearish"
    else:
        trend = "neutral"

    strength = clamp(abs(move) * 100, 0, 100)

    return {
        "trend": trend,
        "strength": round(strength, 2)
    }


# ============================================================
# MAIN ANALYSIS ENGINE
# ============================================================

def analyse_market(symbol, price, timeframe, data):
    candles = normalize_candles(data.get("candles", []))

    # --------------------------------------------------------
    # BACKWARD COMPATIBILITY
    # --------------------------------------------------------

    if len(candles) < 5:
        return {
            "signal": "WAIT",
            "confidence": 0,
            "reason": "Waiting for sufficient OHLC candle data",
            "required": "Send at least 20 candles from TradingView",
            "symbol": symbol,
            "timeframe": timeframe
        }

    price = price if price > 0 else candles[-1]["close"]

    # --------------------------------------------------------
    # ANALYSE COMPONENTS
    # --------------------------------------------------------

    structure = market_structure(candles)
    sr = support_resistance(candles)
    sweep = liquidity_sweep(candles)
    fvg = detect_fvg(candles)
    ob = detect_order_block(candles)
    pd = premium_discount(candles)
    pa = price_action(candles)
    atr = calculate_atr(candles)
    trend = trend_strength(candles)

    # --------------------------------------------------------
    # SCORING
    # --------------------------------------------------------

    buy_score = 0
    sell_score = 0

    buy_reasons = []
    sell_reasons = []

    # ============================
    # TREND
    # ============================

    if structure["trend"] == "bullish":
        buy_score += 15
        buy_reasons.append("bullish market structure")

    elif structure["trend"] == "bearish":
        sell_score += 15
        sell_reasons.append("bearish market structure")

    # ============================
    # BOS
    # ============================

    if structure["bos"] == "bullish":
        buy_score += 15
        buy_reasons.append("bullish BOS")

    elif structure["bos"] == "bearish":
        sell_score += 15
        sell_reasons.append("bearish BOS")

    # ============================
    # CHOCH
    # ============================

    if structure["choch"] == "bullish":
        buy_score += 15
        buy_reasons.append("bullish CHoCH")

    elif structure["choch"] == "bearish":
        sell_score += 15
        sell_reasons.append("bearish CHoCH")

    # ============================
    # LIQUIDITY
    # ============================

    if sweep["sweep"] == "sell_side_sweep":
        buy_score += 25
        buy_reasons.append("sell-side liquidity sweep")

    elif sweep["sweep"] == "buy_side_sweep":
        sell_score += 25
        sell_reasons.append("buy-side liquidity sweep")

    # ============================
    # PRICE ACTION
    # ============================

    if pa["bullish"]:
        buy_score += 10
        buy_reasons.append(pa["pattern"])

    elif pa["bearish"]:
        sell_score += 10
        sell_reasons.append(pa["pattern"])

    # ============================
    # FVG
    # ============================

    if fvg.get("bullish"):
        buy_score += 8
        buy_reasons.append("bullish FVG")

    elif fvg.get("bearish"):
        sell_score += 8
        sell_reasons.append("bearish FVG")

    # ============================
    # ORDER BLOCK
    # ============================

    if ob.get("type") == "bullish_ob":
        buy_score += 8
        buy_reasons.append("bullish order block")

    elif ob.get("type") == "bearish_ob":
        sell_score += 8
        sell_reasons.append("bearish order block")

    # ============================
    # PREMIUM / DISCOUNT
    # ============================

    if pd["zone"] == "discount":
        buy_score += 7
        buy_reasons.append("discount zone")

    elif pd["zone"] == "premium":
        sell_score += 7
        sell_reasons.append("premium zone")

    # ============================
    # SUPPORT / RESISTANCE
    # ============================

    support = sr["support"]
    resistance = sr["resistance"]

    if support > 0 and price <= support + atr * 0.25:
        buy_score += 7
        buy_reasons.append("near support")

    if resistance > 0 and price >= resistance - atr * 0.25:
        sell_score += 7
        sell_reasons.append("near resistance")

    # ========================================================
    # FINAL DECISION
    # ========================================================

    signal = "WAIT"
    confidence = 0
    reason = "No valid A+ confluence setup"

    # Strong BUY
    if (
        buy_score >= 60
        and buy_score > sell_score + 10
        and (
            sweep["sweep"] == "sell_side_sweep"
            or structure["bos"] == "bullish"
            or structure["choch"] == "bullish"
        )
    ):
        signal = "BUY"
        confidence = clamp(buy_score, 0, 100)

        reason = (
            "A+ BUY: "
            + " + ".join(buy_reasons)
        )

    # Strong SELL
    elif (
        sell_score >= 60
        and sell_score > buy_score + 10
        and (
            sweep["sweep"] == "buy_side_sweep"
            or structure["bos"] == "bearish"
            or structure["choch"] == "bearish"
        )
    ):
        signal = "SELL"
        confidence = clamp(sell_score, 0, 100)

        reason = (
            "A+ SELL: "
            + " + ".join(sell_reasons)
        )

    # ========================================================
    # RISK LEVELS
    # ========================================================

    entry = price

    if atr <= 0:
        atr = candle_range(candles[-1])

    if signal == "BUY":

        sl = entry - (atr * 1.2)
        risk = entry - sl

        tp1 = entry + risk * 1.5
        tp2 = entry + risk * 2.0
        tp3 = entry + risk * 3.0

    elif signal == "SELL":

        sl = entry + (atr * 1.2)
        risk = sl - entry

        tp1 = entry - risk * 1.5
        tp2 = entry - risk * 2.0
        tp3 = entry - risk * 3.0

    else:

        sl = 0
        tp1 = 0
        tp2 = 0
        tp3 = 0

    # ========================================================
    # RESULT
    # ========================================================

    return {
        "signal": signal,
        "confidence": round(confidence, 2),
        "reason": reason,

        "symbol": symbol,
        "timeframe": timeframe,
        "price": price,

        "entry": round(entry, 5),
        "stop_loss": round(sl, 5),
        "tp1": round(tp1, 5),
        "tp2": round(tp2, 5),
        "tp3": round(tp3, 5),

        "buy_score": buy_score,
        "sell_score": sell_score,

        "market_structure": structure,
        "trend": trend,

        "liquidity": sweep,
        "support_resistance": sr,

        "fvg": fvg,
        "order_block": ob,

        "premium_discount": pd,
        "price_action": pa,

        "atr": round(atr, 5),

        "timestamp": datetime.utcnow().isoformat()
    }


# ============================================================
# HOME
# ============================================================

@app.route("/", methods=["GET"])
def home():

    return jsonify({
        "status": "online",
        "name": "XAU AI Trading Copilot",
        "version": "2.0",
        "message": "SMC + ICT market analysis engine is running"
    })


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health", methods=["GET"])
def health():

    return jsonify({
        "status": "healthy",
        "time": datetime.utcnow().isoformat()
    })


# ============================================================
# TRADINGVIEW WEBHOOK
# ============================================================

@app.route("/webhook", methods=["POST"])
def webhook():

    try:

        data = request.get_json(silent=True)

        if not data:
            return jsonify({
                "status": "error",
                "message": "No JSON data received"
            }), 400

        symbol = data.get("symbol", "XAUUSD")

        price = safe_float(
            data.get("price", 0)
        )

        timeframe = data.get(
            "timeframe",
            "3m"
        )

        signal = analyse_market(
            symbol=symbol,
            price=price,
            timeframe=timeframe,
            data=data
        )

        return jsonify({
            "status": "success",
            "analysis": signal
        })

    except Exception as e:

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# ============================================================
# TEST ENDPOINT
# ============================================================

@app.route("/test", methods=["GET"])
def test():

    sample = []

    price = 3400.0

    for i in range(30):

        open_price = price

        if i % 3 == 0:
            close_price = price + 1.5
        else:
            close_price = price + 0.5

        high = max(open_price, close_price) + 1.0
        low = min(open_price, close_price) - 1.0

        sample.append({
            "time": i,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close_price,
            "volume": 1000
        })

        price = close_price

    result = analyse_market(
        symbol="XAUUSD",
        price=price,
        timeframe="3m",
        data={
            "candles": sample
        }
    )

    return jsonify(result)


# ============================================================
# RUN SERVER
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 5000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
