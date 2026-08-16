import os
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException

app = FastAPI(
    title="Trading AI Market API",
    version="3.1"
)

API_KEY = os.getenv("TWELVE_DATA_API_KEY")
TD_URL = "https://api.twelvedata.com"
TZ = ZoneInfo("Europe/Berlin")


# ============================================================
# SYMBOL NORMALIZATION
# ============================================================

def normalize_symbol(symbol: str) -> str:
    s = symbol.upper().strip()

    aliases = {
        "EURUSD": "EUR/USD",
        "GBPUSD": "GBP/USD",
        "USDJPY": "USD/JPY",
        "USDCHF": "USD/CHF",
        "AUDUSD": "AUD/USD",
        "NZDUSD": "NZD/USD",
        "USDCAD": "USD/CAD",
        "EURGBP": "EUR/GBP",
        "GBPJPY": "GBP/JPY",
        "AUDCHF": "AUD/CHF",
        "XAUUSD": "XAU/USD",
        "XAGUSD": "XAG/USD",
    }

    return aliases.get(s, s)


# ============================================================
# TWELVE DATA
# ============================================================

def td(endpoint, params):
    if not API_KEY:
        raise HTTPException(
            status_code=500,
            detail="TWELVE_DATA_API_KEY is not configured"
        )

    request_params = dict(params)
    request_params["apikey"] = API_KEY

    try:
        response = requests.get(
            f"{TD_URL}/{endpoint}",
            params=request_params,
            timeout=30
        )
    except requests.RequestException as e:
        raise HTTPException(
            status_code=502,
            detail=f"Twelve Data connection error: {str(e)}"
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text
        )

    try:
        data = response.json()
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Invalid JSON response from Twelve Data"
        )

    if data.get("status") == "error":
        raise HTTPException(
            status_code=400,
            detail=str(data)
        )

    if data.get("code") and data.get("code") != 200:
        raise HTTPException(
            status_code=400,
            detail=str(data)
        )

    return data


def get_quote(symbol):
    symbol = normalize_symbol(symbol)

    return td(
        "quote",
        {
            "symbol": symbol
        }
    )


def get_candles(symbol, interval, outputsize):
    symbol = normalize_symbol(symbol)

    data = td(
        "time_series",
        {
            "symbol": symbol,
            "interval": interval,
            "outputsize": outputsize,
            "timezone": "Europe/Berlin"
        }
    )

    values = data.get("values", [])

    if not values:
        raise HTTPException(
            status_code=404,
            detail=f"No candle data returned for {symbol} {interval}"
        )

    candles = []

    for x in values:
        try:
            volume = None

            if x.get("volume") not in (
                None,
                "",
                "0",
                0
            ):
                volume = float(x["volume"])

            candles.append({
                "datetime": x["datetime"],
                "open": float(x["open"]),
                "high": float(x["high"]),
                "low": float(x["low"]),
                "close": float(x["close"]),
                "volume": volume
            })

        except (ValueError, TypeError, KeyError):
            continue

    candles.reverse()

    if not candles:
        raise HTTPException(
            status_code=404,
            detail=f"Unable to parse candles for {symbol} {interval}"
        )

    return candles


# ============================================================
# HELPERS
# ============================================================

def parse_dt(value):
    return datetime.strptime(
        value,
        "%Y-%m-%d %H:%M:%S"
    ).replace(tzinfo=TZ)


def average(values):
    values = [
        x for x in values
        if x is not None
    ]

    if not values:
        return None

    return sum(values) / len(values)


def safe_distance(price, level):
    if level is None:
        return None

    return price - level


def nearest_above(price, levels):
    valid = [
        x for x in levels
        if x is not None and x > price
    ]

    return min(valid) if valid else None


def nearest_below(price, levels):
    valid = [
        x for x in levels
        if x is not None and x < price
    ]

    return max(valid) if valid else None


# ============================================================
# EMA
# ============================================================

def ema(values, period):
    if len(values) < period:
        return None

    result = sum(values[:period]) / period
    multiplier = 2 / (period + 1)

    for value in values[period:]:
        result = (
            value * multiplier
            + result * (1 - multiplier)
        )

    return result


# ============================================================
# RSI
# ============================================================

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
        avg_gain = (
            avg_gain * (period - 1)
            + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1)
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# ============================================================
# ATR
# ============================================================

def atr(candles, period=14):
    if len(candles) <= period:
        return None

    true_ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"] - current["low"],
            abs(
                current["high"]
                - previous["close"]
            ),
            abs(
                current["low"]
                - previous["close"]
            )
        )

        true_ranges.append(tr)

    return average(
        true_ranges[-period:]
    )


# ============================================================
# VWAP
# ============================================================

def vwap(candles):
    usable = [
        x for x in candles
        if x["volume"] is not None
    ]

    if not usable:
        return None

    total_pv = 0
    total_volume = 0

    for candle in usable:

        typical_price = (
            candle["high"]
            + candle["low"]
            + candle["close"]
        ) / 3

        total_pv += (
            typical_price
            * candle["volume"]
        )

        total_volume += candle["volume"]

    if total_volume == 0:
        return None

    return total_pv / total_volume


# ============================================================
# SWINGS
# ============================================================

def find_swings(candles, strength=2):

    highs = []
    lows = []

    if len(candles) < strength * 2 + 1:
        return highs, lows

    for i in range(
        strength,
        len(candles) - strength
    ):

        current = candles[i]

        left = candles[
            i - strength:i
        ]

        right = candles[
            i + 1:i + strength + 1
        ]

        left_high = max(
            x["high"] for x in left
        )

        right_high = max(
            x["high"] for x in right
        )

        left_low = min(
            x["low"] for x in left
        )

        right_low = min(
            x["low"] for x in right
        )

        if (
            current["high"] >= left_high
            and current["high"] >= right_high
        ):
            highs.append({
                "price": current["high"],
                "datetime": current["datetime"],
                "index": i
            })

        if (
            current["low"] <= left_low
            and current["low"] <= right_low
        ):
            lows.append({
                "price": current["low"],
                "datetime": current["datetime"],
                "index": i
            })

    return highs, lows


# ============================================================
# MARKET STRUCTURE
# ============================================================

def market_structure(candles):

    highs, lows = find_swings(candles)

    recent_highs = highs[-8:]
    recent_lows = lows[-8:]

    if (
        len(recent_highs) < 2
        or len(recent_lows) < 2
    ):
        return {
            "bias": "unknown",
            "HH": False,
            "HL": False,
            "LH": False,
            "LL": False,
            "BOS": None,
            "CHoCH": None,
            "recent_high": None,
            "recent_low": None,
            "swing_highs": [],
            "swing_lows": []
        }

    previous_high = recent_highs[-2]["price"]
    latest_high = recent_highs[-1]["price"]

    previous_low = recent_lows[-2]["price"]
    latest_low = recent_lows[-1]["price"]

    HH = latest_high > previous_high
    LH = latest_high < previous_high

    HL = latest_low > previous_low
    LL = latest_low < previous_low

    if HH and HL:
        bias = "bullish"
    elif LH and LL:
        bias = "bearish"
    else:
        bias = "range"

    current_price = candles[-1]["close"]

    BOS = None

    if current_price > latest_high:
        BOS = "bullish"

    elif current_price < latest_low:
        BOS = "bearish"

    CHoCH = None

    if bias == "bearish" and current_price > previous_high:
        CHoCH = "bullish"

    elif bias == "bullish" and current_price < previous_low:
        CHoCH = "bearish"

    return {
        "bias": bias,
        "HH": HH,
        "HL": HL,
        "LH": LH,
        "LL": LL,
        "BOS": BOS,
        "CHoCH": CHoCH,
        "recent_high": latest_high,
        "recent_low": latest_low,
        "swing_highs": recent_highs[-5:],
        "swing_lows": recent_lows[-5:]
    }


# ============================================================
# EQUAL HIGHS / LOWS
# ============================================================

def equal_levels(points, tolerance=0.0005):

    result = []

    for i in range(len(points)):

        for j in range(i + 1, len(points)):

            a = points[i]["price"]
            b = points[j]["price"]

            denominator = max(
                abs(a),
                abs(b),
                1e-12
            )

            if (
                abs(a - b)
                / denominator
                <= tolerance
            ):
                result.append({
                    "level": (a + b) / 2,
                    "first": points[i]["datetime"],
                    "second": points[j]["datetime"]
                })

    return result[-10:]


# ============================================================
# LIQUIDITY
# ============================================================

def liquidity(candles):

    highs, lows = find_swings(candles)

    equal_highs = equal_levels(highs)
    equal_lows = equal_levels(lows)

    recent_highs = [
        x["price"]
        for x in highs[-10:]
    ]

    recent_lows = [
        x["price"]
        for x in lows[-10:]
    ]

    return {
        "equal_highs": equal_highs,
        "equal_lows": equal_lows,
        "buy_side_liquidity": (
            max(recent_highs)
            if recent_highs
            else None
        ),
        "sell_side_liquidity": (
            min(recent_lows)
            if recent_lows
            else None
        )
    }


# ============================================================
# FVG
# ============================================================

def find_fvg(candles):

    bullish = []
    bearish = []

    for i in range(
        2,
        len(candles)
    ):

        first = candles[i - 2]
        middle = candles[i - 1]
        third = candles[i]

        # Bullish FVG
        if first["high"] < third["low"]:

            bullish.append({
                "low": first["high"],
                "high": third["low"],
                "size": (
                    third["low"]
                    - first["high"]
                ),
                "datetime": middle["datetime"]
            })

        # Bearish FVG
        if first["low"] > third["high"]:

            bearish.append({
                "low": third["high"],
                "high": first["low"],
                "size": (
                    first["low"]
                    - third["high"]
                ),
                "datetime": middle["datetime"]
            })

    return {
        "bullish": bullish[-10:],
        "bearish": bearish[-10:]
    }


# ============================================================
# DISPLACEMENT
# ============================================================

def displacement(candles):

    current = candles[-1]

    current_atr = atr(
        candles,
        14
    )

    if not current_atr:
        return {
            "detected": False,
            "direction": None,
            "body": None,
            "atr_multiple": None
        }

    body = abs(
        current["close"]
        - current["open"]
    )

    multiple = body / current_atr

    direction = (
        "bullish"
        if current["close"]
        > current["open"]
        else "bearish"
    )

    return {
        "detected": multiple >= 1.5,
        "direction": direction,
        "body": body,
        "atr_multiple": multiple
    }


# ============================================================
# DAILY DATA
# ============================================================

def build_daily_stats(candles):

    grouped = {}

    for candle in candles:

        date = parse_dt(
            candle["datetime"]
        ).date()

        grouped.setdefault(
            date,
            []
        ).append(candle)

    result = []

    for date in sorted(grouped):

        day = grouped[date]

        result.append({
            "date": str(date),
            "open": day[0]["open"],
            "high": max(
                x["high"] for x in day
            ),
            "low": min(
                x["low"] for x in day
            ),
            "close": day[-1]["close"]
        })

    return result


def calculate_adr(
    daily_data,
    period
):

    if len(daily_data) < period:
        return None

    ranges = [
        x["high"] - x["low"]
        for x in daily_data[-period:]
    ]

    return average(ranges)


# ============================================================
# SESSION RANGE
# ============================================================

def session_range(
    candles,
    day,
    start_hour,
    end_hour
):

    selected = []

    for candle in candles:

        candle_dt = parse_dt(
            candle["datetime"]
        )

        if candle_dt.date() != day:
            continue

        hour = candle_dt.hour

        if (
            hour >= start_hour
            and hour < end_hour
        ):
            selected.append(candle)

    if not selected:
        return None

    high = max(
        x["high"]
        for x in selected
    )

    low = min(
        x["low"]
        for x in selected
    )

    return {
        "high": high,
        "low": low,
        "range": high - low,
        "start": selected[0]["datetime"],
        "end": selected[-1]["datetime"]
    }


# ============================================================
# PIVOTS
# ============================================================

def calculate_pivots(previous_day):

    if not previous_day:
        return None

    high = previous_day["high"]
    low = previous_day["low"]
    close = previous_day["close"]

    pivot = (
        high
        + low
        + close
    ) / 3

    return {
        "pivot": pivot,

        "R1": (
            2 * pivot
            - low
        ),

        "R2": (
            pivot
            + high
            - low
        ),

        "R3": (
            high
            + 2 * (
                pivot
                - low
            )
        ),

        "S1": (
            2 * pivot
            - high
        ),

        "S2": (
            pivot
            - high
            + low
        ),

        "S3": (
            low
            - 2 * (
                high
                - pivot
            )
        )
    }


# ============================================================
# RANGE CONTEXT
# ============================================================

def range_context(
    price,
    high,
    low
):

    if (
        high is None
        or low is None
        or high == low
    ):
        return {
            "position_percent": None,
            "zone": "unknown",
            "premium_discount": "unknown"
        }

    position = (
        (price - low)
        / (high - low)
    ) * 100

    if position <= 30:
        zone = "lower_range"

    elif position >= 70:
        zone = "upper_range"

    else:
        zone = "middle_range"

    if position < 50:
        pd = "discount"

    elif position > 50:
        pd = "premium"

    else:
        pd = "equilibrium"

    return {
        "position_percent": position,
        "zone": zone,
        "premium_discount": pd
    }


# ============================================================
# TIMEFRAME PACKAGE
# ============================================================

def timeframe_package(candles):

    closes = [
        x["close"]
        for x in candles
    ]

    return {
        "price": closes[-1],

        "high_100": max(
            x["high"]
            for x in candles[-100:]
        ),

        "low_100": min(
            x["low"]
            for x in candles[-100:]
        ),

        "EMA21": ema(
            closes,
            21
        ),

        "EMA50": ema(
            closes,
            50
        ),

        "EMA200": ema(
            closes,
            200
        ),

        "RSI14": rsi(
            closes,
            14
        ),

        "ATR14": atr(
            candles,
            14
        ),

        "VWAP": vwap(
            candles
        ),

        "structure": market_structure(
            candles
        ),

        "liquidity": liquidity(
            candles
        ),

        "FVG": find_fvg(
            candles
        ),

        "displacement": displacement(
            candles
        )
    }


# ============================================================
# SETUP ENGINE
# ============================================================

def setup_engine(
    price,
    bias,
    levels,
    adr14
):

    setups = []

    resistance = nearest_above(
        price,
        [
            levels.get("previous_day_high"),
            levels.get("asia_high"),
            levels.get("london_high"),
            levels.get("R1"),
            levels.get("R2"),
            levels.get("R3")
        ]
    )

    support = nearest_below(
        price,
        [
            levels.get("previous_day_low"),
            levels.get("asia_low"),
            levels.get("london_low"),
            levels.get("S1"),
            levels.get("S2"),
            levels.get("S3")
        ]
    )

    # ---------------- LONG ----------------

    if (
        bias in (
            "bullish",
            "neutral"
        )
        and support is not None
        and support < price
    ):

        base_risk = (
            price - support
        )

        if adr14:
            base_risk = max(
                base_risk,
                adr14 * 0.05
            )

        sl = support - (
            base_risk * 0.5
        )

        tp1 = (
            resistance
            if (
                resistance is not None
                and resistance > price
            )
            else price + base_risk
        )

        tp2 = price + (
            base_risk * 2
        )

        tp3 = price + (
            base_risk * 3
        )

        rr = (
            (tp1 - price)
            / (price - sl)
            if price != sl
            else None
        )

        setups.append({
            "type": "LONG_PULLBACK",
            "entry": price,
            "entry_zone": support,
            "SL": sl,
            "TP1": tp1,
            "TP2": tp2,
            "TP3": tp3,
            "RR_to_TP1": rr,
            "condition": (
                "Bullish confirmation "
                "at support/liquidity"
            ),
            "invalidation": sl
        })

    # ---------------- SHORT ----------------

    if (
        bias in (
            "bearish",
            "neutral"
        )
        and resistance is not None
        and resistance > price
    ):

        base_risk = (
            resistance - price
        )

        if adr14:
            base_risk = max(
                base_risk,
                adr14 * 0.05
            )

        sl = resistance + (
            base_risk * 0.5
        )

        tp1 = (
            support
            if (
                support is not None
                and support < price
            )
            else price - base_risk
        )

        tp2 = price - (
            base_risk * 2
        )

        tp3 = price - (
            base_risk * 3
        )

        rr = (
            (price - tp1)
            / (sl - price)
            if sl != price
            else None
        )

        setups.append({
            "type": "SHORT_PULLBACK",
            "entry": price,
            "entry_zone": resistance,
            "SL": sl,
            "TP1": tp1,
            "TP2": tp2,
            "TP3": tp3,
            "RR_to_TP1": rr,
            "condition": (
                "Bearish confirmation "
                "at resistance/liquidity"
            ),
            "invalidation": sl
        })

    return setups


# ============================================================
# CONFIDENCE
# ============================================================

def calculate_confidence(
    overall_bias,
    timeframe_biases,
    range_zone
):

    score = 50

    if overall_bias in (
        "bullish",
        "bearish"
    ):
        score += 10

    aligned = sum(
        1
        for x in timeframe_biases.values()
        if x == overall_bias
    )

    if aligned >= 4:
        score += 20

    elif aligned >= 3:
        score += 10

    if range_zone == "middle_range":
        score -= 20

    elif range_zone in (
        "upper_range",
        "lower_range"
    ):
        score += 5

    return max(
        0,
        min(100, score)
    )


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():

    return {
        "status": "online",
        "service": "Trading AI Market API",
        "version": "3.1"
    }


# ============================================================
# COMPLETE ANALYSIS ENDPOINT
# ============================================================

@app.get("/analysis-data")
@app.get("/getAnalysisData")
def analysis_data(symbol: str):

    original_symbol = symbol

    symbol = normalize_symbol(symbol)

    # --------------------------------------------------------
    # CURRENT QUOTE
    # --------------------------------------------------------

    quote = get_quote(symbol)

    try:
        current_price = float(
            quote["close"]
        )
    except (
        KeyError,
        TypeError,
        ValueError
    ):
        raise HTTPException(
            status_code=502,
            detail={
                "error": "Invalid quote",
                "symbol": symbol,
                "response": quote
            }
        )

    # --------------------------------------------------------
    # MULTI-TIMEFRAME DATA
    # --------------------------------------------------------

    candles_1m = get_candles(
        symbol,
        "1min",
        1500
    )

    candles_5m = get_candles(
        symbol,
        "5min",
        5000
    )

    candles_15m = get_candles(
        symbol,
        "15min",
        2500
    )

    candles_1h = get_candles(
        symbol,
        "1h",
        1200
    )

    candles_4h = get_candles(
        symbol,
        "4h",
        600
    )

    candles_1d = get_candles(
        symbol,
        "1day",
        100
    )

    # --------------------------------------------------------
    # DAILY DATA
    # --------------------------------------------------------

    daily = build_daily_stats(
        candles_5m
    )

    if not daily:
        raise HTTPException(
            status_code=404,
            detail="No daily data available"
        )

    current_day = daily[-1]

    previous_day = (
        daily[-2]
        if len(daily) >= 2
        else None
    )

    current_daily_range = (
        current_day["high"]
        - current_day["low"]
    )

    ADR5 = calculate_adr(
        daily[:-1],
        5
    )

    ADR10 = calculate_adr(
        daily[:-1],
        10
    )

    ADR14 = calculate_adr(
        daily[:-1],
        14
    )

    ADR20 = calculate_adr(
        daily[:-1],
        20
    )

    daily_range_context = range_context(
        current_price,
        current_day["high"],
        current_day["low"]
    )

    # --------------------------------------------------------
    # SESSION DATA
    # --------------------------------------------------------

    berlin_now = datetime.now(TZ)

    session_day = berlin_now.date()

    asia = session_range(
        candles_5m,
        session_day,
        0,
        9
    )

    london = session_range(
        candles_5m,
        session_day,
        9,
        12
    )

    london_extended = session_range(
        candles_5m,
        session_day,
        9,
        18
    )

    # --------------------------------------------------------
    # PIVOTS
    # --------------------------------------------------------

    pivot_data = calculate_pivots(
        previous_day
    )

    # --------------------------------------------------------
    # TIMEFRAME ANALYSIS
    # --------------------------------------------------------

    timeframes = {

        "1m": timeframe_package(
            candles_1m
        ),

        "5m": timeframe_package(
            candles_5m
        ),

        "15m": timeframe_package(
            candles_15m
        ),

        "1H": timeframe_package(
            candles_1h
        ),

        "4H": timeframe_package(
            candles_4h
        ),

        "1D": timeframe_package(
            candles_1d
        )
    }

    timeframe_biases = {

        "1D":
            timeframes["1D"]
            ["structure"]
            ["bias"],

        "4H":
            timeframes["4H"]
            ["structure"]
            ["bias"],

        "1H":
            timeframes["1H"]
            ["structure"]
            ["bias"],

        "15m":
            timeframes["15m"]
            ["structure"]
            ["bias"],

        "5m":
            timeframes["5m"]
            ["structure"]
            ["bias"],

        "1m":
            timeframes["1m"]
            ["structure"]
            ["bias"]
    }

    bias_values = list(
        timeframe_biases.values()
    )

    bullish_count = bias_values.count(
        "bullish"
    )

    bearish_count = bias_values.count(
        "bearish"
    )

    if bullish_count > bearish_count:
        overall_bias = "bullish"

    elif bearish_count > bullish_count:
        overall_bias = "bearish"

    else:
        overall_bias = "neutral"

    bias_score = int(
        (
            (
                bullish_count
                - bearish_count
            )
            / 6
        )
        * 100
    )

    # --------------------------------------------------------
    # LEVELS
    # --------------------------------------------------------

    levels = {

        "previous_day_high":
            (
                previous_day["high"]
                if previous_day
                else None
            ),

        "previous_day_low":
            (
                previous_day["low"]
                if previous_day
                else None
            ),

        "daily_open":
            current_day["open"],

        "daily_high":
            current_day["high"],

        "daily_low":
            current_day["low"],

        "pivot":
            (
                pivot_data["pivot"]
                if pivot_data
                else None
            ),

        "R1":
            (
                pivot_data["R1"]
                if pivot_data
                else None
            ),

        "R2":
            (
                pivot_data["R2"]
                if pivot_data
                else None
            ),

        "R3":
            (
                pivot_data["R3"]
                if pivot_data
                else None
            ),

        "S1":
            (
                pivot_data["S1"]
                if pivot_data
                else None
            ),

        "S2":
            (
                pivot_data["S2"]
                if pivot_data
                else None
            ),

        "S3":
            (
                pivot_data["S3"]
                if pivot_data
                else None
            ),

        "asia_high":
            (
                asia["high"]
                if asia
                else None
            ),

        "asia_low":
            (
                asia["low"]
                if asia
                else None
            ),

        "london_high":
            (
                london["high"]
                if london
                else None
            ),

        "london_low":
            (
                london["low"]
                if london
                else None
            )
    }

    # --------------------------------------------------------
    # DISTANCES
    # --------------------------------------------------------

    distances = {
        key: safe_distance(
            current_price,
            value
        )
        for key, value in levels.items()
    }

    # --------------------------------------------------------
    # LIQUIDITY
    # --------------------------------------------------------

    liquidity_data = {

        "5m":
            timeframes["5m"]
            ["liquidity"],

        "15m":
            timeframes["15m"]
            ["liquidity"],

        "1H":
            timeframes["1H"]
            ["liquidity"],

        "4H":
            timeframes["4H"]
            ["liquidity"]
    }

    # --------------------------------------------------------
    # SETUPS
    # --------------------------------------------------------

    setups = setup_engine(
        current_price,
        overall_bias,
        levels,
        ADR14
    )

    confidence = calculate_confidence(
        overall_bias,
        timeframe_biases,
        daily_range_context["zone"]
    )

    # --------------------------------------------------------
    # MARKET CONTEXT
    # --------------------------------------------------------

    ADR_consumed = (
        (
            current_daily_range
            / ADR14
        ) * 100
        if ADR14
        else None
    )

    market_context = {

        "regime": (
            "trend"
            if overall_bias
            in (
                "bullish",
                "bearish"
            )
            else "range"
        ),

        "price_location":
            daily_range_context["zone"],

        "premium_discount":
            daily_range_context[
                "premium_discount"
            ],

        "middle_of_range":
            (
                daily_range_context[
                    "zone"
                ]
                == "middle_range"
            ),

        "ADR_consumed_percent":
            ADR_consumed,

        "ADR_80_percent_reached":
            (
                ADR14 is not None
                and current_daily_range
                >= ADR14 * 0.8
            ),

        "near_daily_high":
            (
                abs(
                    current_price
                    - current_day["high"]
                )
                <= (
                    ADR14 * 0.05
                    if ADR14
                    else 0
                )
            ),

        "near_daily_low":
            (
                abs(
                    current_price
                    - current_day["low"]
                )
                <= (
                    ADR14 * 0.05
                    if ADR14
                    else 0
                )
            )
    }

    # --------------------------------------------------------
    # RESPONSE
    # --------------------------------------------------------

    return {

        "request": {
            "original_symbol":
                original_symbol,

            "normalized_symbol":
                symbol,

            "timestamp_utc":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "timezone":
                "Europe/Berlin"
        },

        "current_price":
            current_price,

        "market": {

            "overall_bias":
                overall_bias,

            "bias_score":
                bias_score,

            "confidence":
                confidence,

            "bullish_timeframes":
                bullish_count,

            "bearish_timeframes":
                bearish_count,

            "timeframe_biases":
                timeframe_biases
        },

        "daily": {

            "current":
                current_day,

            "previous":
                previous_day,

            "current_range":
                current_daily_range,

            "ADR5":
                ADR5,

            "ADR10":
                ADR10,

            "ADR14":
                ADR14,

            "ADR20":
                ADR20,

            "ADR_consumed_percent":
                ADR_consumed,

            "range_context":
                daily_range_context
        },

        "sessions": {

            "Asia_00_09":
                asia,

            "London_09_12":
                london,

            "London_09_18":
                london_extended
        },

        "pivots":
            pivot_data,

        "levels":
            levels,

        "distance_from_levels":
            distances,

        "timeframes":
            timeframes,

        "liquidity":
            liquidity_data,

        "setups":
            setups,

        "market_context":
            market_context,

        "analysis_rules": {

            "use_1D_context":
                True,

            "use_4H_context":
                True,

            "use_1H_context":
                True,

            "use_15m_context":
                True,

            "use_5m_execution":
                True,

            "use_1m_execution":
                True,

            "use_daily_range":
                True,

            "use_sessions":
                True,

            "use_pivots":
                True,

            "use_liquidity":
                True,

            "use_FVG":
                True,

            "use_BOS":
                True,

            "use_CHoCH":
                True,

            "use_ADR":
                True,

            "separate_bias_from_entry":
                True,

            "allow_no_trade":
                True,

            "never_force_trade":
                True
        }
    }

@app.get("/api")
def api_analysis(symbol: str):
    return analysis_data(symbol)


@app.get("/data")
def data_analysis(symbol: str):
    return analysis_data(symbol)

@app.get("/dashboard-data")
def dashboard_data():
    return analyze_all()

@app.get("/analysis-data")
def analysis_data():
    return analyze_all()
