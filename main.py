import os
import requests
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException

app = FastAPI(title="Trading AI Market API")

API_KEY = os.getenv("TWELVE_DATA_API_KEY")
BASE_URL = "https://api.twelvedata.com"


def get_candles(symbol, interval, outputsize=300):
    response = requests.get(
        f"{BASE_URL}/time_series",
        params={
            "symbol": symbol,
            "interval": interval,
            "outputsize": outputsize,
            "apikey": API_KEY,
        },
        timeout=20,
    )

    if response.status_code != 200:
        raise HTTPException(response.status_code, response.text)

    data = response.json()

    if data.get("status") == "error":
        raise HTTPException(400, str(data))

    return list(reversed(data.get("values", [])))


def num(x):
    return float(x)


def ema(values, period):
    if len(values) < period:
        return None

    k = 2 / (period + 1)
    result = sum(values[:period]) / period

    for price in values[period:]:
        result = price * k + result * (1 - k)

    return result


def rsi(values, period=14):
    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(candles, period=14):
    if len(candles) <= period:
        return None

    trs = []

    for i in range(1, len(candles)):
        high = num(candles[i]["high"])
        low = num(candles[i]["low"])
        previous_close = num(candles[i - 1]["close"])

        tr = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )

        trs.append(tr)

    return sum(trs[-period:]) / period


def structure(candles, lookback=20):
    if len(candles) < lookback:
        return "unknown"

    recent = candles[-lookback:]
    highs = [num(x["high"]) for x in recent]
    lows = [num(x["low"]) for x in recent]

    midpoint = len(recent) // 2

    first_high = max(highs[:midpoint])
    second_high = max(highs[midpoint:])

    first_low = min(lows[:midpoint])
    second_low = min(lows[midpoint:])

    if second_high > first_high and second_low > first_low:
        return "bullish"

    if second_high < first_high and second_low < first_low:
        return "bearish"

    return "range"


def analyze_timeframe(symbol, interval, outputsize=300):
    candles = get_candles(symbol, interval, outputsize)

    if not candles:
        raise HTTPException(400, f"No data for {symbol} {interval}")

    closes = [num(x["close"]) for x in candles]
    highs = [num(x["high"]) for x in candles]
    lows = [num(x["low"]) for x in candles]

    price = closes[-1]

    return {
        "interval": interval,
        "price": price,
        "high": max(highs[-50:]),
        "low": min(lows[-50:]),
        "ema21": ema(closes, 21),
        "ema50": ema(closes, 50),
        "ema200": ema(closes, 200),
        "rsi14": rsi(closes, 14),
        "atr14": atr(candles, 14),
        "structure": structure(candles),
    }


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "Trading AI Market API"
    }


@app.get("/quote")
def quote(symbol: str):

    if not API_KEY:
        raise HTTPException(
            500,
            "TWELVE_DATA_API_KEY is not configured"
        )

    response = requests.get(
        f"{BASE_URL}/quote",
        params={
            "symbol": symbol,
            "apikey": API_KEY,
        },
        timeout=10,
    )

    if response.status_code != 200:
        raise HTTPException(
            response.status_code,
            response.text
        )

    data = response.json()

    if data.get("status") == "error":
        raise HTTPException(400, str(data))

    return data


@app.get("/analysis-data")
def analysis_data(symbol: str):

    if not API_KEY:
        raise HTTPException(
            500,
            "TWELVE_DATA_API_KEY is not configured"
        )

    quote_data = quote(symbol)

    timeframes = {
        "5m": analyze_timeframe(symbol, "5min", 300),
        "15m": analyze_timeframe(symbol, "15min", 300),
        "1h": analyze_timeframe(symbol, "1h", 300),
        "4h": analyze_timeframe(symbol, "4h", 300),
        "1d": analyze_timeframe(symbol, "1day", 300),
    }

    current_price = float(quote_data["close"])

    daily = timeframes["1d"]

    daily_high = daily["high"]
    daily_low = daily["low"]

    daily_range = daily_high - daily_low

    if daily_range > 0:
        range_position = (
            (current_price - daily_low) / daily_range
        ) * 100
    else:
        range_position = 50

    structures = [
        timeframes["1d"]["structure"],
        timeframes["4h"]["structure"],
        timeframes["1h"]["structure"],
        timeframes["15m"]["structure"],
        timeframes["5m"]["structure"],
    ]

    bullish = structures.count("bullish")
    bearish = structures.count("bearish")

    if bullish > bearish:
        bias = "bullish"
    elif bearish > bullish:
        bias = "bearish"
    else:
        bias = "neutral"

    bias_score = int(
        ((bullish - bearish) / 5) * 100
    )

    return {
        "symbol": symbol,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "current_price": current_price,

        "daily_range": {
            "high": daily_high,
            "low": daily_low,
            "size": daily_range,
            "position_percent": round(range_position, 2),
        },

        "bias": {
            "direction": bias,
            "score": bias_score,
        },

        "timeframes": timeframes,

        "important_levels": {
            "daily_high": daily_high,
            "daily_low": daily_low,
            "recent_5m_high": timeframes["5m"]["high"],
            "recent_5m_low": timeframes["5m"]["low"],
            "recent_15m_high": timeframes["15m"]["high"],
            "recent_15m_low": timeframes["15m"]["low"],
            "recent_1h_high": timeframes["1h"]["high"],
            "recent_1h_low": timeframes["1h"]["low"],
            "recent_4h_high": timeframes["4h"]["high"],
            "recent_4h_low": timeframes["4h"]["low"],
        },

        "instructions_for_ai": {
            "use_multi_timeframe_analysis": True,
            "separate_bias_from_entry": True,
            "look_for_breakout_retest": True,
            "look_for_liquidity_sweep": True,
            "avoid_middle_of_range": True,
            "allow_no_trade": True,
        },
    }
