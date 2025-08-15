# backend/core/mstock_api.py
import requests
import pandas as pd
import datetime
import io
import yfinance as yf
from backend.core.config import API_KEY, ACCESS_TOKEN

# Base URLs
BASE_URL = "https://api.mstock.trade/openapi/typea"
CHART_BASE_URL = BASE_URL

# Common headers
COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "*/*",
    "Cache-Control": "no-cache",
    "X-Mirae-Version": "1"
}

# ------------ HEADER HELPERS ------------
def get_headers_quote(api_key, access_token):
    return {
        **COMMON_HEADERS,
        "Authorization": f"token {api_key}:{access_token}"
    }

def get_headers_chart(api_key, access_token):
    return {
        **COMMON_HEADERS,
        "Authorization": f"token {api_key}:{access_token}"
    }

# ------------ Dynamic Token Fetch from MStock ------------
def get_token_from_mstock(symbol, api_key, access_token):
    """
    Fetch scriptmaster CSV and find instrument token for the given symbol (NSE).
    Raises exception on failure so callers can fallback to Yahoo.
    """
    url = f"{BASE_URL}/instruments/scriptmaster"
    headers = get_headers_quote(api_key, access_token)

    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    df = pd.read_csv(io.StringIO(response.text))
    df.columns = df.columns.str.strip().str.lower()

    match = df[
        (df['tradingsymbol'].str.upper() == symbol.upper()) &
        (df['exchange'].str.upper() == 'NSE')
    ]
    if match.empty:
        raise ValueError(f"Token not found for symbol: {symbol}")

    # instrument_token may be int-like string; ensure int
    return int(match.iloc[0]['instrument_token'])


# ------------ Yahoo Finance Helpers (Fallback) ------------
def fetch_yf_historical(symbol, timeframe="30m"):
    """
    Fetch historical intraday/daily data from Yahoo as fallback.
    Returns a pandas.DataFrame indexed by datetime with columns:
      open, high, low, close, volume, EMA7, EMA21, VWAP
    """
    try:
        yf_symbol = symbol.upper() + ".NS"
        # map incoming timeframe to yfinance interval
        interval_map = {
            "1m": "1m", "3m": "1m", "5m": "5m", "10m": "5m",
            "15m": "15m", "30m": "30m", "1h": "60m", "1d": "1d"
        }
        interval = interval_map.get(timeframe, "5m")
        # period: for intraday use last 7 days, for daily use 1mo
        period = "7d" if interval != "1d" else "1mo"

        print(f"[INFO] Yahoo: fetching {yf_symbol} interval={interval} period={period}")
        ticker = yf.Ticker(yf_symbol)

        hist = ticker.history(interval=interval, period=period, auto_adjust=False, prepost=False)

        if hist is None or hist.empty:
            raise ValueError("Yahoo Finance returned no data")

        # Remove tz info to keep index naive
        try:
            if getattr(hist.index, "tz", None) is not None:
                hist.index = hist.index.tz_convert(None)
        except Exception:
            try:
                hist.index = hist.index.tz_localize(None)
            except Exception:
                pass

        # Normalize columns to lowercase names
        df = hist.rename(columns={
            "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume",
            "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"
        })

        # Keep only required columns (if available)
        for col in ["open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                df[col] = pd.NA

        df = df[["open", "high", "low", "close", "volume"]].copy()

        # Indicators: uppercase keys to match MStock style if needed
        df["EMA7"] = df["close"].ewm(span=7, adjust=False).mean()
        df["EMA21"] = df["close"].ewm(span=21, adjust=False).mean()
        vwap = (df["close"] * df["volume"]).cumsum() / (df["volume"].cumsum().replace(0, pd.NA))
        df["VWAP"] = vwap

        df.dropna(subset=["close"], inplace=True)
        df.index.name = "time"

        return df

    except Exception as e:
        print(f"[ERROR] Yahoo Finance historical fallback failed for {symbol}: {e}")
        return pd.DataFrame()


def fetch_yf_spot(symbol):
    """
    Return {"last_price": float} or {"last_price": None}
    """
    try:
        yf_symbol = symbol.upper() + ".NS"
        ticker = yf.Ticker(yf_symbol)
        hist = ticker.history(period="1d", interval="1d")
        if hist is None or hist.empty:
            raise ValueError("Yahoo Finance returned no spot data")
        last_price = float(hist["Close"].iloc[-1])
        return {"last_price": last_price}
    except Exception as e:
        print(f"[ERROR] Yahoo Finance spot fallback failed for {symbol}: {e}")
        return {"last_price": None}


def fetch_yf_ohlc(symbol):
    """
    Return dict with open/high/low/close from Yahoo or dict with None values.
    """
    try:
        yf_symbol = symbol.upper() + ".NS"
        ticker = yf.Ticker(yf_symbol)
        hist = ticker.history(period="1d", interval="1d")
        if hist is None or hist.empty:
            raise ValueError("Yahoo Finance returned no OHLC")
        latest = hist.iloc[-1]
        return {
            "open": float(latest["Open"]),
            "high": float(latest["High"]),
            "low": float(latest["Low"]),
            "close": float(latest["Close"])
        }
    except Exception as e:
        print(f"[ERROR] Yahoo Finance OHLC fallback failed for {symbol}: {e}")
        return {"open": None, "high": None, "low": None, "close": None}


# ------------ Fetch Historical Chart Data ------------
def fetch_historical_data(symbol, api_key, access_token, timeframe="30m"):
    """
    Try MStock first; on any failure fallback to Yahoo.
    Returns pandas.DataFrame indexed by datetime with columns:
    open, high, low, close, volume, EMA7, EMA21, VWAP
    """
    interval_map = {
        "1m": "1minute", "3m": "3minute", "5m": "5minute", "10m": "10minute",
        "15m": "15minute", "30m": "30minute", "1h": "60minute", "1d": "1day"
    }

    if timeframe not in interval_map:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    resolution = interval_map[timeframe]

    try:
        # ---- Attempt MStock ----
        token = get_token_from_mstock(symbol, api_key, access_token)
        now = datetime.datetime.now()
        from_time = now - datetime.timedelta(days=7)

        from_str = from_time.strftime("%Y-%m-%d+%H:%M:%S")
        to_str = now.strftime("%Y-%m-%d+%H:%M:%S")

        url = f"{BASE_URL}/instruments/historical/{token}/{resolution}?from={from_str}&to={to_str}"
        headers = get_headers_chart(api_key, access_token)

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        candles = response.json().get("data", {}).get("candles", [])
        if not candles:
            raise ValueError("No candle data received from MStock")

        df = pd.DataFrame(candles, columns=["time", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df["time"])
        df.set_index("time", inplace=True)

        # Add indicators
        df["EMA7"] = df["close"].ewm(span=7, adjust=False).mean()
        df["EMA21"] = df["close"].ewm(span=21, adjust=False).mean()
        df["VWAP"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()

        print(f"[INFO] MStock historical data fetched successfully for {symbol}")
        return df

    except Exception as e:
        # FALLBACK TO YAHOO
        print(f"[ERROR] MStock historical fetch failed for {symbol}: {e}")
        print(f"[INFO] Falling back to Yahoo Finance for {symbol}")
        return fetch_yf_historical(symbol, timeframe)


# ------------ LTP ------------
def get_spot_price(symbol, api_key, access_token):
    """
    Return standardized dict: {"last_price": float or None}
    """
    try:
        print(f"[INFO] Fetching MStock LTP for {symbol}")
        url = f"{BASE_URL}/instruments/quote/ltp/?i=NSE:{symbol}"
        headers = get_headers_quote(api_key, access_token)
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()

        raw = response.json().get("data", {}).get(f"NSE:{symbol}")

        # Different MStock payload shapes: handle dict or primitive
        if isinstance(raw, dict):
            last = raw.get("last_price") or raw.get("ltp") or raw.get("lastPrice")
            return {"last_price": float(last) if last is not None else None}
        elif isinstance(raw, (int, float, str)):
            try:
                return {"last_price": float(raw)}
            except Exception:
                pass

        # If we reach here, MStock did not produce usable LTP -> fallback
        raise ValueError("Invalid LTP data from MStock")

    except Exception as e:
        print(f"[ERROR] MStock LTP fetch failed for {symbol}: {e}")
        print(f"[INFO] Falling back to Yahoo Finance for LTP {symbol}")
        return fetch_yf_spot(symbol)


# ------------ OHLC ------------
def get_ohlc_data(symbol, api_key, access_token):
    """
    Return standardized dict: {"open":..., "high":..., "low":..., "close":...}
    """
    try:
        print(f"[INFO] Fetching MStock OHLC for {symbol}")
        url = f"{BASE_URL}/instruments/quote/ohlc/?i=NSE:{symbol}"
        headers = get_headers_quote(api_key, access_token)
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()

        data = response.json().get("data", {}).get(f"NSE:{symbol}", {}).get("ohlc")
        if not data:
            raise ValueError("No OHLC data from MStock")

        return {
            "open": float(data.get("open")) if data.get("open") is not None else None,
            "high": float(data.get("high")) if data.get("high") is not None else None,
            "low": float(data.get("low")) if data.get("low") is not None else None,
            "close": float(data.get("close")) if data.get("close") is not None else None
        }

    except Exception as e:
        print(f"[ERROR] MStock OHLC fetch failed for {symbol}: {e}")
        print(f"[INFO] Falling back to Yahoo Finance for OHLC {symbol}")
        return fetch_yf_ohlc(symbol)
