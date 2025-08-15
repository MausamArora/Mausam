import sys
import os
import traceback
from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup
import requests
import pandas as pd
import numpy as np
import yfinance as yf

# --- Project imports ---
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))
from backend.core.config import API_KEY, ACCESS_TOKEN
from backend.core.chart_generator import generate_signal_chart
from backend.core.mstock_api import get_spot_price, get_ohlc_data, fetch_historical_data
from backend.core.order_executor import place_order
from backend.core.chart import generate_chart_base64
from backend.utils.symbol_mapper import get_symbol_from_name
from backend.core.indicators import fetch_mstock_ohlc_data, calculate_atr_sl_crossover_signals

def check_mstock(api_key, access_token):
    try:
        # Try fetching a known large-cap stock
        test = get_spot_price("TCS", api_key, access_token)
        if not test or test.get("last_price") is None:
            raise Exception("No valid LTP from MStock")
        print("[INFO] MStock API is available.")
        return True
    except Exception as e:
        print(f"[ERROR] MStock API check failed: {e}")
        print("[INFO] Starting Yahoo Finance fallback...")
        return False
# Optional Yahoo helpers if you created them; routes below will use them if present
try:
    from yahoo_fallback import get_yahoo_ltp, get_yahoo_ohlc, get_yahoo_chart
except Exception:
    get_yahoo_ltp = get_yahoo_ohlc = get_yahoo_chart = None

app = Flask(__name__)

# =======================
# Home
# =======================
@app.route("/")
def home():
    return render_template("index.html")

# =======================
# Start Bot (MStock → Yahoo fallback for LTP/OHLC snapshot)
# =======================
@app.route("/start-bot", methods=["POST"])
def start_bot():
    try:
        data = request.get_json()
        symbol = data.get("symbol", "").strip().upper()
        if not symbol:
            return jsonify({"error": "Symbol is required"}), 400

        spot_data, ohlc_data = None, None

        # --- Try MStock first ---
        try:
            spot_data = get_spot_price(symbol, API_KEY, ACCESS_TOKEN)  # dict with 'last_price'
            ohlc_data = get_ohlc_data(symbol, API_KEY, ACCESS_TOKEN)   # dict with open/high/low/close
        except Exception as e:
            print(f"[MSTOCK] snapshot failed for {symbol}: {e}")

        # --- Fallback to Yahoo if needed ---
        if not spot_data or not ohlc_data:
            try:
                t = yf.Ticker(symbol + ".NS")
                hist = t.history(period="1d", interval="1d")
                if hist.empty:
                    return jsonify({"error": f"Yahoo snapshot empty for {symbol}"}), 500
                last_close = float(hist["Close"].iloc[-1])
                spot_data = {"last_price": last_close}
                ohlc_data = {
                    "open": float(hist["Open"].iloc[-1]),
                    "high": float(hist["High"].iloc[-1]),
                    "low":  float(hist["Low"].iloc[-1]),
                    "close": last_close
                }
            except Exception as e:
                traceback.print_exc()
                return jsonify({"error": f"Both MStock and Yahoo snapshot failed for {symbol}"}), 500

        resp = {
            "symbol": symbol,
            "ltp": spot_data["last_price"],
            "open": ohlc_data["open"],
            "high": ohlc_data["high"],
            "low":  ohlc_data["low"],
            "close": ohlc_data["close"],
            "buy_price": round(spot_data["last_price"] * 0.995, 2),
            "sell_price": round(spot_data["last_price"] * 1.005, 2),
            "prediction": "N/A"
        }
        return jsonify(resp)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Internal error: {str(e)}"}), 500

# =======================
# Place Order (unchanged)
# =======================
@app.route("/place-order", methods=["POST"])
def handle_place_order():
    try:
        data = request.get_json()
        symbol = data.get("symbol", "").strip().upper()
        transaction_type = data.get("transaction_type", "").strip().upper()
        order_type = data.get("order_type", "MARKET").strip().upper()
        product = data.get("product", "MIS").strip().upper()

        def safe_float(v, default=0.0):
            try: return float(v)
            except (TypeError, ValueError): return default

        def safe_int(v, default=0):
            try: return int(v)
            except (TypeError, ValueError): return default

        quantity = safe_int(data.get("quantity"))
        price = safe_float(data.get("price"))
        sl_price = safe_float(data.get("sl_price"))
        trigger_price = safe_float(data.get("trigger_price"))

        if not symbol or not transaction_type or quantity <= 0:
            return jsonify({"status": "error", "message": "Missing or invalid input"}), 400

        result = place_order(
            symbol=symbol, transaction_type=transaction_type, quantity=quantity,
            order_type=order_type, price=price, product=product,
            sl_price=sl_price, trigger_price=trigger_price,
            api_key=API_KEY, access_token=ACCESS_TOKEN
        )

        if result.get("status") == "success":
            return jsonify({"status": "success", "order_id": result.get("order_id")})
        return jsonify({"status": "error", "message": result.get("message", "Order failed"),
                        "raw": result.get("raw", {})}), 500

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Internal error: {str(e)}"}), 500

# =======================
# Sentiment (unchanged)
# =======================
@app.route("/sentiment", methods=["GET"])
def get_market_sentiment():
    try:
        url = "https://www.moneycontrol.com/news/business/markets/"
        response = requests.get(url, timeout=5)
        soup = BeautifulSoup(response.text, "html.parser")
        headlines = [h.text.strip() for h in soup.select("li.clearfix a")[:10] if h.text.strip()]

        bullish = ["rally", "up", "gain", "surge", "record high", "bull", "positive"]
        bearish = ["fall", "drop", "down", "loss", "bear", "negative", "panic"]

        score = 0
        for h in headlines:
            l = h.lower()
            score += any(w in l for w in bullish)
            score -= any(w in l for w in bearish)

        sentiment = "😐 Neutral"
        if score > 1: sentiment = "📈 Bullish"
        elif score < -1: sentiment = "📉 Bearish"

        found = []
        for headline in headlines:
            words = headline.split()
            for i in range(len(words)):
                for j in range(i + 1, len(words) + 1):
                    name = " ".join(words[i:j])
                    sym = get_symbol_from_name(name)
                    if sym and sym not in found:
                        found.append(sym)

        return jsonify({"sentiment": sentiment, "headlines": headlines, "watchlist": found[:5]})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Failed to fetch sentiment: {str(e)}"}), 500

# =======================
# Chart (MStock first → Yahoo fallback). Route matches /chart/<symbol>?timeframe=5m
# =======================
@app.route("/watchlist", methods=["GET"])
def get_watchlist():
    try:
        print("[INFO] Loading default watchlist with ACC...")

        api_key, access_token = load_api_credentials()

        # Default watchlist only ACC
        watchlist_data = []
        ltp_data = get_spot_price("ACC", api_key, access_token)
        watchlist_data.append({
            "symbol": "ACC",
            "ltp": ltp_data.get("last_price")
        })

        return jsonify({"status": "success", "data": watchlist_data})

    except Exception as e:
        print(f"[ERROR] Watchlist loading failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# -------------------- CHART DATA --------------------
@app.route("/chart/<symbol>", methods=["GET"])
def get_chart(symbol):
    try:
        if not symbol or symbol.strip() == "":
            symbol = "ACC"  # Default

        print(f"[INFO] Fetching chart data for {symbol}...")

        api_key, access_token = load_api_credentials()

        # Try MStock first
        try:
            chart_data = get_mstock_history(symbol, interval="5m", days=5,
                                            api_key=api_key, access_token=access_token)
            if not chart_data:
                raise ValueError("Empty MStock chart data")
        except Exception as e:
            print(f"[WARN] MStock chart fetch failed for {symbol}: {e}")
            print(f"[INFO] Falling back to Yahoo Finance for {symbol}")
            chart_data = fetch_yf_history(symbol, interval="5m", days=5)

        return jsonify({"status": "success", "symbol": symbol, "data": chart_data})

    except Exception as e:
        print(f"[ERROR] Chart route failed for {symbol}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
# =======================
# ATR-SL Indicator (unchanged)
# =======================
@app.route("/indicator/atr-sl", methods=["POST"])
def atr_sl_indicator():
    try:
        data = request.get_json()
        symbol = data.get("symbol", "").strip().upper()
        interval = data.get("interval", "5m")
        atr_period = int(data.get("atr_period", 10))
        sensitivity = float(data.get("sensitivity", 1.0))

        if not symbol:
            return jsonify({"error": "Symbol is required"}), 400

        df = fetch_mstock_ohlc_data(symbol, interval, API_KEY, ACCESS_TOKEN)
        result_df = calculate_atr_sl_crossover_signals(df, atr_period=atr_period, sensitivity=sensitivity)
        output = result_df.tail(20).reset_index().to_dict(orient='records')
        return jsonify({"symbol": symbol, "interval": interval, "signals": output})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =======================
# Optional Yahoo-only endpoints (use the SAME app; no re-declare)
# =======================
@app.route("/yahoo-ltp/<symbol>", methods=["GET"])
def yahoo_ltp(symbol):
    if get_yahoo_ltp is None:
        return jsonify({"error": "yahoo_fallback.py not available"}), 501
    ltp = get_yahoo_ltp(symbol)
    if ltp is None:
        return jsonify({"error": f"LTP not available for {symbol}"}), 404
    return jsonify({"symbol": symbol.upper(), "ltp": ltp})

@app.route("/yahoo-ohlc/<symbol>", methods=["GET"])
def yahoo_ohlc(symbol):
    if get_yahoo_ohlc is None:
        return jsonify({"error": "yahoo_fallback.py not available"}), 501
    interval = request.args.get("interval") or request.args.get("timeframe") or "5m"
    period = request.args.get("period", "7d")
    data = get_yahoo_ohlc(symbol, interval, period)
    if not data:
        return jsonify({"error": f"OHLC not available for {symbol}"}), 404
    return jsonify({"symbol": symbol.upper(), "ohlc": data})

@app.route("/yahoo-chart/<symbol>", methods=["GET"])
def yahoo_chart(symbol):
    if get_yahoo_chart is None:
        # Provide inline Yahoo fallback if helper not present
        interval = (request.args.get("interval") or request.args.get("timeframe") or "5m").lower()
        t = yf.Ticker(symbol + ".NS")
        period = "7d" if interval in {"1m","3m","5m","10m","15m","30m","60m"} else "1y"
        df = t.history(period=period, interval=interval)
        if df.empty:
            return jsonify({"error": f"Chart data not available for {symbol}"}), 404
        df = df.reset_index()
        out = [{
            "time": pd.to_datetime(r["Datetime"]).strftime("%Y-%m-%d %H:%M:%S"),
            "open": float(r["Open"]), "high": float(r["High"]),
            "low": float(r["Low"]), "close": float(r["Close"])
        } for _, r in df.iterrows()]
        return jsonify({"symbol": symbol.upper(), "chart": out})

    # If helper exists, use it and accept timeframe alias
    interval = request.args.get("interval") or request.args.get("timeframe") or "5m"
    period = request.args.get("period", "7d")
    chart_data = get_yahoo_chart(symbol, interval, period)
    if not chart_data:
        return jsonify({"error": f"Chart data not available for {symbol}"}), 404
    return jsonify({"symbol": symbol.upper(), "chart": chart_data})

if __name__ == "__main__":
    USE_MSTOCK = check_mstock(API_KEY, ACCESS_TOKEN)
    app.run(debug=True)
