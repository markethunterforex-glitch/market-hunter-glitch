from flask import Flask, request, jsonify
from datetime import datetime
import os

app = Flask(__name__)


# ==========================================
# XAU AI TRADING COPILOT
# Version 1.0
# ==========================================

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "name": "XAU AI Trading Copilot",
        "version": "1.0",
        "message": "Copilot is running"
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "time": datetime.utcnow().isoformat()
    })


# ==========================================
# TRADINGVIEW WEBHOOK
# ==========================================

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
        price = float(data.get("price", 0))
        timeframe = data.get("timeframe", "3m")

        signal = analyse_market(
            symbol=symbol,
            price=price,
            timeframe=timeframe,
            data=data
        )

        return jsonify({
            "status": "success",
            "symbol": symbol,
            "price": price,
            "timeframe": timeframe,
            "analysis": signal
        })

    except Exception as e:

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# ==========================================
# MARKET ANALYSIS ENGINE
# ==========================================

def analyse_market(symbol, price, timeframe, data):

    signal = "WAIT"
    confidence = 0
    reason = "Waiting for confirmation"

    # --------------------------------------
    # Basic input
    # --------------------------------------

    trend = str(data.get("trend", "")).lower()
    liquidity = str(data.get("liquidity", "")).lower()
    confirmation = str(data.get("confirmation", "")).lower()

    # --------------------------------------
    # BUY LOGIC
    # --------------------------------------

    if (
        trend == "bullish"
        and liquidity == "sell_side_sweep"
        and confirmation == "bullish"
    ):
        signal = "BUY"
        confidence = 85
        reason = (
            "Bullish trend + sell-side liquidity sweep "
            "+ bullish confirmation"
        )

    # --------------------------------------
    # SELL LOGIC
    # --------------------------------------

    elif (
        trend == "bearish"
        and liquidity == "buy_side_sweep"
        and confirmation == "bearish"
    ):
        signal = "SELL"
        confidence = 85
        reason = (
            "Bearish trend + buy-side liquidity sweep "
            "+ bearish confirmation"
        )

    # --------------------------------------
    # Otherwise WAIT
    # --------------------------------------

    else:
        signal = "WAIT"
        confidence = 0
        reason = "No valid A+ setup confirmed"

    return {
        "signal": signal,
        "confidence": confidence,
        "reason": reason
    }


# ==========================================
# RUN SERVER
# ==========================================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port
    )
