import os
import math
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException

app = FastAPI(title="Trading AI Market API", version="3.0")

API_KEY = os.getenv("TWELVE_DATA_API_KEY")
TD_URL = "https://api.twelvedata.com"
TZ = ZoneInfo("Europe/Berlin")


# ============================================================
# TWELVE DATA
# ============================================================

def td(endpoint, params):
    if not API_KEY:
        raise HTTPException(500, "TWELVE_DATA_API_KEY is not configured")

    p = dict(params)
    p["apikey"] = API_KEY

    r = requests.get(
        f"{TD_URL}/{endpoint}",
        params=p,
        timeout=30
    )

    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)

    data = r.json()

    if data.get("status") == "error":
        raise HTTPException(
            400,
            str(data)
        )

    return data


def get_candles(symbol, interval, outputsize):
    data = td(
        "time_series",
        {
            "symbol": symbol,
            "interval": interval,
            "outputsize": outputsize,
            "timezone": "Europe/Berlin",
        }
    )

    values = data.get("values", [])

    result = []

    for x in values:
        result.append({
            "datetime": x["datetime"],
            "open": float(x["open"]),
            "high": float(x["high"]),
            "low": float(x["low"]),
            "close": float(x["close"]),
            "volume": (
                float(x["volume"])
                if x.get("volume") not in (None, "", "0")
                else None
            )
        })

    result.reverse()
    return result


def get_quote(symbol):
    return td(
        "quote",
        {
            "symbol": symbol
        }
    )


# ============================================================
# HELPERS
# ============================================================

def dt(c):
    return datetime.strptime(
        c["datetime"],
        "%Y-%m-%d %H:%M:%S"
    ).replace(tzinfo=TZ)


def avg(values):
    values = [x for x in values if x is not None]
    return sum(values) / len(values) if values else None


def pct(a, b):
    if b == 0:
        return None
    return (a / b) * 100


def distance(price, level):
    if level is None:
        return None
    return price - level


def nearest_above(price, levels):
    valid = [x for x in levels if x is not None and x > price]
    return min(valid) if valid else None


def nearest_below(price, levels):
    valid = [x for x in levels if x is not None and x < price]
    return max(valid) if valid else None


# ============================================================
# INDICATORS
# ============================================================

def ema(values, period):
    if len(values) < period:
        return None

    value = sum(values[:period]) / period
    k = 2 / (period + 1)

    for x in values[period:]:
        value = x * k + value * (1 - k)

    return value


def rsi(values, period=14):
    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    gain = sum(gains[:period]) / period
    loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        gain = ((gain * (period - 1)) + gains[i]) / period
        loss = ((loss * (period - 1)) + losses[i]) / period

    if loss == 0:
        return 100

    rs = gain / loss
    return 100 - (100 / (1 + rs))


def atr(candles, period=14):
    if len(candles) <= period:
        return None

    tr = []

    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i - 1]["close"]

        tr.append(
            max(
                h - l,
                abs(h - pc),
                abs(l - pc)
            )
        )

    return avg(tr[-period:])


def vwap(candles):
    usable = [
        x for x in candles
        if x["volume"] is not None
    ]

    if not usable:
        return None

    pv = 0
    vol = 0

    for x in usable:
        typical = (
            x["high"] +
            x["low"] +
            x["close"]
        ) / 3

        pv += typical * x["volume"]
        vol += x["volume"]

    return pv / vol if vol else None


# ============================================================
# SWINGS / STRUCTURE
# ============================================================

def swings(candles, strength=2):
    highs = []
    lows = []

    for i in range(strength, len(candles) - strength):

        h = candles[i]["high"]
        l = candles[i]["low"]

        left_h = max(
            candles[j]["high"]
            for j in range(i - strength, i)
        )

        right_h = max(
            candles[j]["high"]
            for j in range(i + 1, i + strength + 1)
        )

        left_l = min(
            candles[j]["low"]
            for j in range(i - strength, i)
        )

        right_l = min(
            candles[j]["low"]
            for j in range(i + 1, i + strength + 1)
        )

        if h >= left_h and h >= right_h:
            highs.append({
                "price": h,
                "index": i,
                "datetime": candles[i]["datetime"]
            })

        if l <= left_l and l <= right_l:
            lows.append({
                "price": l,
                "index": i,
                "datetime": candles[i]["datetime"
                ]
            })

    return highs, lows


def structure(candles):
    highs, lows = swings(candles)

    rh = highs[-8:]
    rl = lows[-8:]

    if len(rh) < 2 or len(rl) < 2:
        return {
            "bias": "unknown",
            "HH": False,
            "HL": False,
            "LH": False,
            "LL": False,
            "BOS": None,
            "CHoCH": None,
            "recent_high": None,
            "recent_low": None
        }

    prev_h = rh[-2]["price"]
    last_h = rh[-1]["price"]

    prev_l = rl[-2]["price"]
    last_l = rl[-1]["price"]

    HH = last_h > prev_h
    LH = last_h < prev_h
    HL = last_l > prev_l
    LL = last_l < prev_l

    if HH and HL:
        bias = "bullish"
    elif LH and LL:
        bias = "bearish"
    else:
        bias = "range"

    price = candles[-1]["close"]

    BOS = None

    if price > last_h:
        BOS = "bullish"

    elif price < last_l:
        BOS = "bearish"

    # CHoCH: current structure breaks opposite side
    CHoCH = None

    if bias == "bearish" and price > prev_h:
        CHoCH = "bullish"

    elif bias == "bullish" and price < prev_l:
        CHoCH = "bearish"

    return {
        "bias": bias,
        "HH": HH,
        "HL": HL,
        "LH": LH,
        "LL": LL,
        "BOS": BOS,
        "CHoCH": CHoCH,
        "recent_high": last_h,
        "recent_low": last_l,
        "swing_highs": rh[-5:],
        "swing_lows": rl[-5:]
    }


# ============================================================
# LIQUIDITY
# ============================================================

def equal_levels(points, tolerance=0.0005):
    result = []

    for i in range(len(points)):
        for j in range(i + 1, len(points)):

            a = points[i]["price"]
            b = points[j]["price"]

            if abs(a - b) / max(abs(a), abs(b), 1e-12) <= tolerance:
                result.append({
                    "level": (a + b) / 2,
                    "first": points[i]["datetime"],
                    "second": points[j]["datetime"]
                })

    return result[-10:]


def liquidity(candles):
    highs, lows = swings(candles)

    eq_highs = equal_levels(highs)
    eq_lows = equal_levels(lows)

    recent_highs = [x["price"] for x in highs[-10:]]
    recent_lows = [x["price"] for x in lows[-10:]]

    return {
        "equal_highs": eq_highs,
        "equal_lows": eq_lows,
        "buy_side_liquidity": max(recent_highs) if recent_highs else None,
        "sell_side_liquidity": min(recent_lows) if recent_lows else None
    }


# ============================================================
# FVG
# ============================================================

def fvg(candles):
    bullish = []
    bearish = []

    for i in range(2, len(candles)):

        a = candles[i - 2]
        b = candles[i - 1]
        c = candles[i]

        if a["high"] < c["low"]:
            bullish.append({
                "low": a["high"],
                "high": c["low"],
                "datetime": b["datetime"],
                "size": c["low"] - a["high"]
            })

        if a["low"] > c["high"]:
            bearish.append({
                "low": c["high"],
                "high": a["low"],
                "datetime": b["datetime"],
                "size": a["low"] - c["high"]
            })

    return {
        "bullish": bullish[-10:],
        "bearish": bearish[-10:]
    }


# ============================================================
# DISPLACEMENT
# ============================================================

def displacement(candles):
    a = atr(candles, 14)

    if not a:
        return {
            "detected": False,
            "direction": None,
            "body": None,
            "atr_multiple": None
        }

    c = candles[-1]

    body = abs(c["close"] - c["open"])
    multiple = body / a

    return {
        "detected": multiple >= 1.5,
        "direction": (
            "bullish"
            if c["close"] > c["open"]
            else "bearish"
        ),
        "body": body,
        "atr_multiple": multiple
    }


# ============================================================
# SESSION / DAILY DATA
# ============================================================

def candles_for_day(candles, day):
    return [
        c for c in candles
        if dt(c).date() == day
    ]


def session(candles, start_hour, end_hour, day):
    selected = []

    for c in candles_for_day(candles, day):
        h = dt(c).hour

        if start_hour <= h < end_hour:
            selected.append(c)

    if not selected:
        return None

    high = max(x["high"] for x in selected)
    low = min(x["low"] for x in selected)

    return {
        "high": high,
        "low": low,
        "range": high - low,
        "start": selected[0]["datetime"],
        "end": selected[-1]["datetime"]
    }


def daily_stats(candles):
    days = {}

    for c in candles:
        d = dt(c).date()

        if d not in days:
            days[d] = []

        days[d].append(c)

    result = []

    for day in sorted(days):

        x = days[day]

        result.append({
            "date": str(day),
            "open": x[0]["open"],
            "high": max(c["high"] for c in x),
            "low": min(c["low"] for c in x),
            "close": x[-1]["close"]
        })

    return result


def adr(days, period):
    if len(days) < period:
        return None

    ranges = [
        x["high"] - x["low"]
        for x in days[-period:]
    ]

    return avg(ranges)


# ============================================================
# PIVOTS
# ============================================================

def pivots(previous):
    if not previous:
        return None

    h = previous["high"]
    l = previous["low"]
    c = previous["close"]

    p = (h + l + c) / 3

    return {
        "pivot": p,
        "R1": 2 * p - l,
        "R2": p + (h - l),
        "R3": h + 2 * (p - l),
        "S1": 2 * p - h,
        "S2": p - (h - l),
        "S3": l - 2 * (h - p)
    }


# ============================================================
# RANGE / PREMIUM DISCOUNT
# ============================================================

def range_context(price, high, low):
    if high is None or low is None or high == low:
        return {
            "position_percent": None,
            "zone": "unknown",
            "premium_discount": "unknown"
        }

    position = ((price - low) / (high - low)) * 100

    if position <= 30:
        zone = "lower_range"
    elif position >= 70:
        zone = "upper_range"
    else:
        zone = "middle_range"

    return {
        "position_percent": position,
        "zone": zone,
        "premium_discount": (
            "discount"
            if position < 50
            else "premium"
            if position > 50
            else "equilibrium"
        )
    }


# ============================================================
# TIMEFRAME PACKAGE
# ============================================================

def timeframe_package(candles):

    closes = [x["close"] for x in candles]

    return {
        "price": closes[-1],
        "high_100": max(x["high"] for x in candles[-100:]),
        "low_100": min(x["low"] for x in candles[-100:]),
        "EMA21": ema(closes, 21),
        "EMA50": ema(closes, 50),
        "EMA200": ema(closes, 200),
        "RSI14": rsi(closes, 14),
        "ATR14": atr(candles, 14),
        "VWAP": vwap(candles),
        "structure": structure(candles),
        "liquidity": liquidity(candles),
        "FVG": fvg(candles),
        "displacement": displacement(candles)
    }


# ============================================================
# SETUP ENGINE
# ============================================================

def setup_engine(price, bias, levels, tf, adr14):

    candidates = []

    pivot = levels.get("pivot")
    pdh = levels.get("previous_day_high")
    pdl = levels.get("previous_day_low")
    asia_high = levels.get("asia_high")
    asia_low = levels.get("asia_low")
    london_high = levels.get("london_high")
    london_low = levels.get("london_low")

    resistance = nearest_above(
        price,
        [
            pdh,
            asia_high,
            london_high,
            levels.get("R1"),
            levels.get("R2"),
            levels.get("R3")
        ]
    )

    support = nearest_below(
        price,
        [
            pdl,
            asia_low,
            london_low,
            levels.get("S1"),
            levels.get("S2"),
            levels.get("S3")
        ]
    )

    # LONG
    if bias in ("bullish", "neutral") and support:

        risk = max(
            price - support,
            adr14 * 0.05 if adr14 else 0
        )

        if risk > 0:

            entry = support
            sl = support - risk * 0.5
            tp1 = resistance if resistance and resistance > price else price + risk
            tp2 = price + risk * 2
            tp3 = price + risk * 3

            rr = (tp1 - entry) / (entry - sl)

            candidates.append({
                "type": "LONG_PULLBACK",
                "entry": entry,
                "SL": sl,
                "TP1": tp1,
                "TP2": tp2,
                "TP3": tp3,
                "RR_to_TP1": rr,
                "condition": "bullish confirmation at support/liquidity",
                "invalidation": sl
            })

    # SHORT
    if bias in ("bearish", "neutral") and resistance:

        risk = max(
            resistance - price,
            adr14 * 0.05 if adr14 else 0
        )

        if risk > 0:

            entry = resistance
            sl = resistance + risk * 0.5
            tp1 = support if support and support < price else price - risk
            tp2 = price - risk * 2
            tp3 = price - risk * 3

            rr = (entry - tp1) / (sl - entry)

            candidates.append({
                "type": "SHORT_PULLBACK",
                "entry": entry,
                "SL": sl,
                "TP1": tp1,
                "TP2": tp2,
                "TP3": tp3,
                "RR_to_TP1": rr,
                "condition": "bearish confirmation at resistance/liquidity",
                "invalidation": sl
            })

    return candidates


# ============================================================
# CONFIDENCE
# ============================================================

def confidence(bias, tf, context):

    score = 50

    if bias == "bullish":
        score += 10

    elif bias == "bearish":
        score += 10

    structures = [
        tf["4H"]["structure"]["bias"],
        tf["1H"]["structure"]["bias"],
        tf["15m"]["structure"]["bias"],
        tf["5m"]["structure"]["bias"]
    ]

    if structures.count(bias) >= 3:
        score += 15

    if context["zone"] == "middle_range":
        score -= 15

    if context["zone"] in ("upper_range", "lower_range"):
        score += 5

    return max(0, min(100, score))


# ============================================================
# COMPLETE ENDPOINT
# ============================================================

@app.get("/")
def root():
    return {
        "status": "online",
        "service": "Trading AI Market API",
        "version": "3.0"
    }


@app.get("/analysis-data")
def analysis_data(symbol: str):

    # ------------------------------------------
    # DATA
    # ------------------------------------------

    quote = get_quote(symbol)

    price = float(quote["close"])

    m1 = get_candles(symbol, "1min", 1500)
    m5 = get_candles(symbol, "5min", 5000)
    m15 = get_candles(symbol, "15min", 2500)
    h1 = get_candles(symbol, "1h", 1200)
    h4 = get_candles(symbol, "4h", 600)
    d1 = get_candles(symbol, "1day", 100)

    # ------------------------------------------
    # DAILY
    # ------------------------------------------

    days = daily_stats(m5)

    if not days:
        raise HTTPException(400, "No daily data available")

    current_day = days[-1]
    previous_day = days[-2] if len(days) >= 2 else None

    current_range = (
        current_day["high"] -
        current_day["low"]
    )

    adr5 = adr(days[:-1], 5)
    adr10 = adr(days[:-1], 10)
    adr14 = adr(days[:-1], 14)
    adr20 = adr(days[:-1], 20)

    range_ctx = range_context(
        price,
        current_day["high"],
        current_day["low"]
    )

    # ------------------------------------------
    # SESSIONS
    # ------------------------------------------

    day = datetime.now(TZ).date()

    asia = session(m5, 0, 9, day)
    london = session(m5, 9, 12, day)
    london_full = session(m5, 9, 18, day)

    # ------------------------------------------
    # PIVOTS
    # ------------------------------------------

    pv = pivots(previous_day)

    # ------------------------------------------
    # TIMEFRAMES
    # ------------------------------------------

    tf = {
        "1m": timeframe_package(m1),
        "5m": timeframe_package(m5),
        "15m": timeframe_package(m15),
        "1H": timeframe_package(h1),
        "4H": timeframe_package(h4),
        "1D": timeframe_package(d1)
    }

    # ------------------------------------------
    # HTF BIAS
    # ------------------------------------------

    biases = {
        "1D": tf["1D"]["structure"]["bias"],
        "4H": tf["4H"]["structure"]["bias"],
        "1H": tf["1H"]["structure"]["bias"],
        "15m": tf["15m"]["structure"]["bias"],
        "5m": tf["5m"]["structure"]["bias"]
    }

    bullish = list(biases.values()).count("bullish")
    bearish = list(biases.values()).count("bearish")

    if bullish > bearish:
        overall_bias = "bullish"
    elif bearish > bullish:
        overall_bias = "bearish"
    else:
        overall_bias = "neutral"

    # ------------------------------------------
    # LEVELS
    # ------------------------------------------

    levels = {
        "previous_day_high": (
            previous_day["high"]
            if previous_day else None
        ),
        "previous_day_low": (
            previous_day["low"]
            if previous_day else None
        ),
        "daily_open": current_day["open"],
        "daily_high": current_day["high"],
        "daily_low": current_day["low"],

        "pivot": pv["pivot"] if pv else None,
        "R1": pv["R1"] if pv else None,
        "R2": pv["R2"] if pv else None,
        "R3": pv["R3"] if pv else None,
        "S1": pv["S1"] if pv else None,
        "S2": pv["S2"] if pv else None,
        "S3": pv["S3"] if pv else None,

        "asia_high": asia["high"] if asia else None,
        "asia_low": asia["low"] if asia else None,

        "london_high": london["high"] if london else None,
        "london_low": london["low"] if london else None
    }

    # ------------------------------------------
    # LIQUIDITY
    # ------------------------------------------

    liq = {
        "5m": tf["5m"]["liquidity"],
        "15m": tf["15m"]["liquidity"],
        "1H": tf["1H"]["liquidity"],
        "4H": tf["4H"]["liquidity"]
    }

    # ------------------------------------------
    # SETUPS
    # ------------------------------------------

    candidates = setup_engine(
        price,
        overall_bias,
        levels,
        tf,
        adr14
    )

    # ------------------------------------------
    # CONFIDENCE
    # ------------------------------------------

    conf = confidence(
        overall_bias,
        tf,
        range_ctx
    )

    # ------------------------------------------
    # DISTANCES
    # ------------------------------------------

    distances = {
        key: distance(price, value)
        for key, value in levels.items()
    }

    # ------------------------------------------
    # FINAL RESPONSE
    # ------------------------------------------

    return {

        "symbol": symbol,

        "timestamp_utc":
            datetime.now(timezone.utc).isoformat(),

        "analysis_timezone":
            "Europe/Berlin",

        "current_price": price,

        "market": {
            "overall_bias": overall_bias,
            "confidence": conf,
            "bullish_timeframes": bullish,
            "bearish_timeframes": bearish,
            "timeframe_biases": biases
        },

        "daily": {
            "current": current_day,
            "previous": previous_day,
            "range": current_range,
            "range_context": range_ctx,
            "ADR5": adr5,
            "ADR10": adr10,
            "ADR14": adr14,
            "ADR20": adr20,
            "ADR_consumed_percent": (
                current_range / adr14 * 100
                if adr14 else None
            )
        },

        "sessions": {
            "Asia_00_09": asia,
            "London_09_12": london,
            "London_09_18": london_full
        },

        "pivots": pv,

        "levels": levels,

        "distance_from_levels": distances,

        "timeframes": tf,

        "liquidity": liq,

        "setups": candidates,

        "market_context": {

            "trend_or_range": (
                "trend"
                if overall_bias in ("bullish", "bearish")
                else "range"
            ),

            "price_location":
                range_ctx["zone"],

            "premium_discount":
                range_ctx["premium_discount"],

            "middle_of_range":
                range_ctx["zone"] == "middle_range",

            "ADR_80_percent_reached":
                (
                    adr14 is not None
                    and current_range >= adr14 * 0.8
                ),

            "daily_high_near_price":
                abs(price - current_day["high"])
                <= (adr14 or 1) * 0.05,

            "daily_low_near_price":
                abs(price - current_day["low"])
                <= (adr14 or 1) * 0.05
        },

        "ai_rules": {

            "must_use_HTF":
                True,

            "must_use_session_ranges":
                True,

            "must_use_pivots":
                True,

            "must_use_liquidity":
                True,

            "must_use_structure":
                True,

            "must_use_FVG":
                True,

            "must_use_ADR":
                True,

            "must_separate_bias_and_entry":
                True,

            "must_allow_no_trade":
                True,

            "never_force_trade":
                True
        }
    }
