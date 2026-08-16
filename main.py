import os
import time
import requests

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Trading AI Market Data API",
    version="7.0"
)


# ============================================================
# CONFIG
# ============================================================

TWELVE_DATA_API_KEY = os.getenv(
    "TWELVE_DATA_API_KEY"
)

TWELVE_DATA_URL = (
    "https://api.twelvedata.com"
)

TZ = ZoneInfo(
    "Europe/Berlin"
)

CACHE_TTL_SECONDS = int(
    os.getenv(
        "CACHE_TTL_SECONDS",
        "300"
    )
)


# ============================================================
# WATCHLIST
# ============================================================

WATCHLIST = [

    ("EURUSD", "EUR/USD"),
    ("GBPUSD", "GBP/USD"),
    ("USDJPY", "USD/JPY"),
    ("USDCHF", "USD/CHF"),
    ("AUDUSD", "AUD/USD"),
    ("NZDUSD", "NZD/USD"),
    ("USDCAD", "USD/CAD"),
    ("EURGBP", "EUR/GBP"),
    ("GBPJPY", "GBP/JPY"),
    ("AUDCHF", "AUD/CHF"),
    ("XAUUSD", "XAU/USD"),

]


# ============================================================
# CACHE
# ============================================================

CACHE = {}


# ============================================================
# SYMBOL NORMALIZATION
# ============================================================

def normalize_symbol(symbol):

    s = (
        symbol
        .upper()
        .strip()
        .replace("-", "/")
        .replace("_", "/")
    )

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

    }

    return aliases.get(
        s,
        s
    )


# ============================================================
# TWELVE DATA REQUEST
# ============================================================

def twelve_data(
    endpoint,
    params
):

    if not TWELVE_DATA_API_KEY:

        raise HTTPException(

            status_code=500,

            detail={
                "provider":
                    "Twelve Data",

                "error":
                    "TWELVE_DATA_API_KEY is missing"
            }
        )


    request_params = dict(
        params
    )

    request_params["apikey"] = (
        TWELVE_DATA_API_KEY
    )


    try:

        response = requests.get(

            f"{TWELVE_DATA_URL}/{endpoint}",

            params=request_params,

            timeout=30

        )

    except requests.RequestException as e:

        raise HTTPException(

            status_code=502,

            detail={
                "provider":
                    "Twelve Data",

                "endpoint":
                    endpoint,

                "error":
                    str(e)
            }
        )


    try:

        data = response.json()

    except Exception:

        data = {
            "raw":
                response.text
        }


    if response.status_code != 200:

        raise HTTPException(

            status_code=response.status_code,

            detail={
                "provider":
                    "Twelve Data",

                "endpoint":
                    endpoint,

                "http_status":
                    response.status_code,

                "response":
                    data
            }
        )


    if data.get(
        "status"
    ) == "error":

        raise HTTPException(

            status_code=400,

            detail={
                "provider":
                    "Twelve Data",

                "endpoint":
                    endpoint,

                "response":
                    data
            }
        )


    return data


# ============================================================
# QUOTE
# ============================================================

def get_quote(
    symbol
):

    return twelve_data(

        "quote",

        {
            "symbol":
                normalize_symbol(
                    symbol
                )
        }

    )


# ============================================================
# HISTORICAL CANDLES
# ============================================================

def get_candles(
    symbol,
    interval,
    outputsize
):

    normalized = normalize_symbol(
        symbol
    )


    data = twelve_data(

        "time_series",

        {

            "symbol":
                normalized,

            "interval":
                interval,

            "outputsize":
                outputsize,

            "timezone":
                "Europe/Berlin"

        }

    )


    values = data.get(
        "values",
        []
    )


    if not values:

        raise HTTPException(

            status_code=404,

            detail={

                "provider":
                    "Twelve Data",

                "endpoint":
                    "time_series",

                "symbol":
                    normalized,

                "interval":
                    interval,

                "error":
                    "No historical candles returned",

                "response":
                    data
            }

        )


    candles = []


    for item in values:

        try:

            volume = None

            if item.get(
                "volume"
            ) not in (
                None,
                "",
                "0",
                0
            ):

                volume = float(
                    item["volume"]
                )


            candles.append({

                "datetime":
                    item["datetime"],

                "open":
                    float(
                        item["open"]
                    ),

                "high":
                    float(
                        item["high"]
                    ),

                "low":
                    float(
                        item["low"]
                    ),

                "close":
                    float(
                        item["close"]
                    ),

                "volume":
                    volume

            })


        except Exception:

            continue


    candles.reverse()


    if not candles:

        raise HTTPException(

            status_code=404,

            detail={

                "provider":
                    "Twelve Data",

                "symbol":
                    normalized,

                "interval":
                    interval,

                "error":
                    "Candles could not be parsed"
            }

        )


    return candles


# ============================================================
# MATH
# ============================================================

def average(
    values
):

    values = [

        x
        for x in values
        if x is not None

    ]

    if not values:

        return None


    return (
        sum(values)
        / len(values)
    )


# ============================================================
# EMA
# ============================================================

def ema(
    values,
    period
):

    if len(values) < period:

        return None


    result = (
        sum(
            values[:period]
        )
        / period
    )


    multiplier = (
        2
        / (period + 1)
    )


    for value in values[period:]:

        result = (

            value
            * multiplier

            +

            result
            * (1 - multiplier)

        )


    return result


# ============================================================
# RSI
# ============================================================

def rsi(
    values,
    period=14
):

    if len(values) <= period:

        return None


    gains = []
    losses = []


    for i in range(
        1,
        len(values)
    ):

        change = (
            values[i]
            - values[i - 1]
        )


        gains.append(
            max(change, 0)
        )


        losses.append(
            max(-change, 0)
        )


    avg_gain = (
        sum(
            gains[:period]
        )
        / period
    )


    avg_loss = (
        sum(
            losses[:period]
        )
        / period
    )


    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (

            (
                avg_gain
                * (period - 1)
            )

            + gains[i]

        ) / period


        avg_loss = (

            (
                avg_loss
                * (period - 1)
            )

            + losses[i]

        ) / period


    if avg_loss == 0:

        return 100.0


    rs = (
        avg_gain
        / avg_loss
    )


    return (
        100
        - (
            100
            / (1 + rs)
        )
    )


# ============================================================
# ATR
# ============================================================

def atr(
    candles,
    period=14
):

    if len(candles) <= period:

        return None


    ranges = []


    for i in range(
        1,
        len(candles)
    ):

        current = candles[i]

        previous = candles[
            i - 1
        ]


        true_range = max(

            current["high"]
            - current["low"],

            abs(
                current["high"]
                - previous["close"]
            ),

            abs(
                current["low"]
                - previous["close"]
            )

        )


        ranges.append(
            true_range
        )


    return average(
        ranges[-period:]
    )


# ============================================================
# VWAP
# ============================================================

def vwap(
    candles
):

    usable = [

        candle

        for candle in candles

        if candle["volume"]
        is not None

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


        total_volume += (
            candle["volume"]
        )


    if total_volume == 0:

        return None


    return (
        total_pv
        / total_volume
    )


# ============================================================
# DATETIME
# ============================================================

def parse_dt(
    value
):

    return datetime.strptime(

        value,

        "%Y-%m-%d %H:%M:%S"

    ).replace(
        tzinfo=TZ
    )


# ============================================================
# SWINGS
# ============================================================

def find_swings(
    candles,
    strength=2
):

    highs = []
    lows = []


    if len(candles) < (
        strength * 2 + 1
    ):

        return highs, lows


    for i in range(

        strength,

        len(candles)
        - strength

    ):

        current = candles[i]


        left = candles[

            i - strength:
            i

        ]


        right = candles[

            i + 1:
            i + strength + 1

        ]


        if (

            current["high"]
            >= max(
                x["high"]
                for x in left
            )

            and

            current["high"]
            >= max(
                x["high"]
                for x in right
            )

        ):

            highs.append({

                "price":
                    current["high"],

                "datetime":
                    current["datetime"]

            })


        if (

            current["low"]
            <= min(
                x["low"]
                for x in left
            )

            and

            current["low"]
            <= min(
                x["low"]
                for x in right
            )

        ):

            lows.append({

                "price":
                    current["low"],

                "datetime":
                    current["datetime"]

            })


    return highs, lows


# ============================================================
# MARKET STRUCTURE
# ============================================================

def market_structure(
    candles
):

    highs, lows = find_swings(
        candles
    )


    highs = highs[-8:]
    lows = lows[-8:]


    if (

        len(highs) < 2

        or

        len(lows) < 2

    ):

        return {

            "bias":
                "unknown",

            "HH":
                False,

            "HL":
                False,

            "LH":
                False,

            "LL":
                False,

            "BOS":
                None,

            "CHoCH":
                None,

            "recent_high":
                None,

            "recent_low":
                None

        }


    previous_high = highs[-2][
        "price"
    ]


    latest_high = highs[-1][
        "price"
    ]


    previous_low = lows[-2][
        "price"
    ]


    latest_low = lows[-1][
        "price"
    ]


    HH = (
        latest_high
        > previous_high
    )


    LH = (
        latest_high
        < previous_high
    )


    HL = (
        latest_low
        > previous_low
    )


    LL = (
        latest_low
        < previous_low
    )


    if HH and HL:

        bias = "bullish"

    elif LH and LL:

        bias = "bearish"

    else:

        bias = "range"


    price = candles[-1][
        "close"
    ]


    BOS = None


    if price > latest_high:

        BOS = "bullish"

    elif price < latest_low:

        BOS = "bearish"


    CHoCH = None


    if (

        bias == "bearish"

        and

        price > previous_high

    ):

        CHoCH = "bullish"


    elif (

        bias == "bullish"

        and

        price < previous_low

    ):

        CHoCH = "bearish"


    return {

        "bias":
            bias,

        "HH":
            HH,

        "HL":
            HL,

        "LH":
            LH,

        "LL":
            LL,

        "BOS":
            BOS,

        "CHoCH":
            CHoCH,

        "recent_high":
            latest_high,

        "recent_low":
            latest_low

    }


# ============================================================
# EQUAL LEVELS
# ============================================================

def equal_levels(
    points,
    tolerance=0.0005
):

    result = []


    for i in range(
        len(points)
    ):

        for j in range(
            i + 1,
            len(points)
        ):

            a = points[i][
                "price"
            ]

            b = points[j][
                "price"
            ]


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

                    "level":
                        (
                            a + b
                        ) / 2,

                    "first":
                        points[i][
                            "datetime"
                        ],

                    "second":
                        points[j][
                            "datetime"
                        ]

                })


    return result[-10:]


# ============================================================
# LIQUIDITY
# ============================================================

def liquidity(
    candles
):

    highs, lows = find_swings(
        candles
    )


    return {

        "equal_highs":
            equal_levels(
                highs
            ),

        "equal_lows":
            equal_levels(
                lows
            ),

        "buy_side_liquidity":

            (
                max(
                    x["price"]
                    for x in highs[-10:]
                )

                if highs

                else None
            ),

        "sell_side_liquidity":

            (
                min(
                    x["price"]
                    for x in lows[-10:]
                )

                if lows

                else None
            )

    }


# ============================================================
# FVG
# ============================================================

def fvg(
    candles
):

    bullish = []
    bearish = []


    for i in range(
        2,
        len(candles)
    ):

        first = candles[
            i - 2
        ]

        middle = candles[
            i - 1
        ]

        third = candles[i]


        if (

            first["high"]
            < third["low"]

        ):

            bullish.append({

                "low":
                    first["high"],

                "high":
                    third["low"],

                "size":
                    (
                        third["low"]
                        - first["high"]
                    ),

                "datetime":
                    middle["datetime"]

            })


        if (

            first["low"]
            > third["high"]

        ):

            bearish.append({

                "low":
                    third["high"],

                "high":
                    first["low"],

                "size":
                    (
                        first["low"]
                        - third["high"]
                    ),

                "datetime":
                    middle["datetime"]

            })


    return {

        "bullish":
            bullish[-10:],

        "bearish":
            bearish[-10:]

    }


# ============================================================
# DISPLACEMENT
# ============================================================

def displacement(
    candles
):

    current = candles[-1]


    current_atr = atr(
        candles,
        14
    )


    if not current_atr:

        return {

            "detected":
                False,

            "direction":
                None,

            "atr_multiple":
                None

        }


    body = abs(

        current["close"]
        - current["open"]

    )


    multiple = (
        body
        / current_atr
    )


    return {

        "detected":
            multiple >= 1.5,

        "direction":

            (
                "bullish"

                if current["close"]
                > current["open"]

                else "bearish"
            ),

        "atr_multiple":
            multiple

    }


# ============================================================
# TIMEFRAME ANALYSIS
# ============================================================

def timeframe_analysis(
    candles
):

    closes = [

        candle["close"]

        for candle in candles

    ]


    return {

        "price":
            closes[-1],

        "EMA21":
            ema(
                closes,
                21
            ),

        "EMA50":
            ema(
                closes,
                50
            ),

        "EMA200":
            ema(
                closes,
                200
            ),

        "RSI14":
            rsi(
                closes,
                14
            ),

        "ATR14":
            atr(
                candles,
                14
            ),

        "VWAP":
            vwap(
                candles
            ),

        "structure":
            market_structure(
                candles
            ),

        "liquidity":
            liquidity(
                candles
            ),

        "FVG":
            fvg(
                candles
            ),

        "displacement":
            displacement(
                candles
            )

    }


# ============================================================
# DAILY STATS
# ============================================================

def daily_stats(
    candles
):

    groups = {}


    for candle in candles:

        date = parse_dt(
            candle["datetime"]
        ).date()


        groups.setdefault(
            date,
            []
        ).append(
            candle
        )


    result = []


    for date in sorted(
        groups
    ):

        day = groups[
            date
        ]


        result.append({

            "date":
                str(date),

            "open":
                day[0]["open"],

            "high":
                max(
                    x["high"]
                    for x in day
                ),

            "low":
                min(
                    x["low"]
                    for x in day
                ),

            "close":
                day[-1]["close"]

        })


    return result


# ============================================================
# ADR
# ============================================================

def calculate_adr(
    days,
    period
):

    if len(days) < period:

        return None


    ranges = [

        x["high"]
        - x["low"]

        for x in days[-period:]

    ]


    return average(
        ranges
    )


# ============================================================
# SESSION RANGE
# ============================================================

def session_range(
    candles,
    date,
    start_hour,
    end_hour
):

    selected = []


    for candle in candles:

        dt = parse_dt(
            candle["datetime"]
        )


        if dt.date() != date:

            continue


        if (

            dt.hour
            >= start_hour

            and

            dt.hour
            < end_hour

        ):

            selected.append(
                candle
            )


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

        "high":
            high,

        "low":
            low,

        "range":
            high - low,

        "start":
            selected[0][
                "datetime"
            ],

        "end":
            selected[-1][
                "datetime"
            ]

    }


# ============================================================
# PIVOTS
# ============================================================

def calculate_pivots(
    previous_day
):

    if not previous_day:

        return None


    high = previous_day[
        "high"
    ]

    low = previous_day[
        "low"
    ]

    close = previous_day[
        "close"
    ]


    pivot = (

        high
        + low
        + close

    ) / 3


    return {

        "pivot":
            pivot,

        "R1":
            2 * pivot - low,

        "R2":
            pivot + high - low,

        "R3":
            high
            + 2 * (
                pivot - low
            ),

        "S1":
            2 * pivot - high,

        "S2":
            pivot - high + low,

        "S3":
            low
            - 2 * (
                high - pivot
            )

    }


# ============================================================
# BUILD MARKET DATA
#
# HISTORICAL CANDLES FIRST.
# LIVE QUOTE IS OPTIONAL.
#
# IMPORTANT:
# If the market is closed and the live quote is unavailable,
# historical data is still used.
# ============================================================

def build_market_data(
    display_symbol,
    api_symbol
):

    # --------------------------------------------------------
    # HISTORICAL DATA
    # --------------------------------------------------------

    intervals = {

    "5m":
        (
            "5min",
            1000
        ),

    "1H":
        (
            "1h",
            500
        ),

    "4H":
        (
            "4h",
            300
        ),

    "1D":
        (
            "1day",
            100
        )
}


    candles = {}


    for tf, (
        interval,
        outputsize
    ) in intervals.items():

        candles[tf] = get_candles(

            api_symbol,

            interval,

            outputsize

        )


    # --------------------------------------------------------
    # LAST HISTORICAL CANDLE
    # --------------------------------------------------------

    last_candle = candles[
        "5m"
    ][-5]


    historical_price = (
        last_candle["close"]
    )


    last_candle_time = (
        last_candle["datetime"]
    )


    # --------------------------------------------------------
    # OPTIONAL LIVE QUOTE
    # --------------------------------------------------------

    live_price = None

    quote_error = None


    try:

        quote = get_quote(
            api_symbol
        )


        if quote.get(
            "close"
        ) is not None:

            live_price = float(
                quote["close"]
            )


    except Exception as e:

        quote_error = str(e)


    # --------------------------------------------------------
    # PRICE SOURCE
    # --------------------------------------------------------

    if live_price is not None:

        price = live_price

        market_status = "OPEN"

        price_source = (
            "LIVE_QUOTE"
        )

    else:

        price = historical_price

        market_status = (
            "CLOSED_OR_"
            "LIVE_QUOTE_UNAVAILABLE"
        )

        price_source = (
            "LAST_COMPLETED_CANDLE"
        )


    # --------------------------------------------------------
    # DAILY DATA
    # --------------------------------------------------------

    daily = daily_stats(
        candles["5m"]
    )


    if not daily:

        raise HTTPException(

            status_code=404,

            detail={

                "provider":
                    "Twelve Data",

                "symbol":
                    api_symbol,

                "error":
                    "Historical daily data unavailable"

            }

        )


    current_day = daily[-1]


    previous_day = (

        daily[-2]

        if len(daily) >= 2

        else None

    )


    current_range = (

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


    # --------------------------------------------------------
    # SESSIONS
    # --------------------------------------------------------

    berlin_date = datetime.now(
        TZ
    ).date()


    asia = session_range(

        candles["5m"],

        berlin_date,

        0,

        9

    )


    london = session_range(

        candles["5m"],

        berlin_date,

        9,

        12

    )


    # --------------------------------------------------------
    # PIVOTS
    # --------------------------------------------------------

    pivots = calculate_pivots(
        previous_day
    )


    # --------------------------------------------------------
    # TIMEFRAMES
    # --------------------------------------------------------

    timeframes = {}


    for tf in candles:

        timeframes[tf] = (

            timeframe_analysis(
                candles[tf]
            )

        )


    # --------------------------------------------------------
    # MTF BIAS
    # --------------------------------------------------------

    biases = {

        tf:
            timeframes[tf]
            ["structure"]
            ["bias"]

        for tf in timeframes

    }


    bullish = list(
        biases.values()
    ).count(
        "bullish"
    )


    bearish = list(
        biases.values()
    ).count(
        "bearish"
    )


    if bullish > bearish:

        overall_bias = "bullish"

    elif bearish > bullish:

        overall_bias = "bearish"

    else:

        overall_bias = "neutral"


    # --------------------------------------------------------
    # RANGE LOCATION
    # --------------------------------------------------------

    range_position = None


    if (

        current_day["high"]
        != current_day["low"]

    ):

        range_position = (

            (

                price
                - current_day["low"]

            )

            /

            (

                current_day["high"]
                - current_day["low"]

            )

        ) * 100


    if range_position is None:

        range_zone = "unknown"

    elif range_position <= 30:

        range_zone = "discount"

    elif range_position >= 70:

        range_zone = "premium"

    else:

        range_zone = "equilibrium"


    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    return {

        "symbol":
            display_symbol,

        "api_symbol":
            api_symbol,

        "timestamp":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "market_status":
            market_status,

        "price_source":
            price_source,

        "price":
            price,

        "last_completed_candle":
            last_candle_time,

        "live_quote_available":
            live_price is not None,

        "quote_error":
            quote_error,

        "bias": {

            "overall":
                overall_bias,

            "bullish_count":
                bullish,

            "bearish_count":
                bearish,

            "timeframes":
                biases

        },

        "daily": {

            "current":
                current_day,

            "previous":
                previous_day,

            "range":
                current_range,

            "ADR5":
                ADR5,

            "ADR10":
                ADR10,

            "ADR14":
                ADR14,

            "ADR20":
                ADR20,

            "ADR_consumed":
                (

                    current_range
                    / ADR14
                    * 100

                    if ADR14

                    else None

                ),

            "range_position":
                range_position,

            "range_zone":
                range_zone

        },

        "sessions": {

            "Asia":
                asia,

            "London":
                london

        },

        "pivots":
            pivots,

        "timeframes":
            timeframes

    }


# ============================================================
# ANALYZE ONE SYMBOL
# ============================================================

def analyze_symbol(
    display_symbol,
    api_symbol
):

    cache_key = display_symbol

    now = time.time()


    cached = CACHE.get(
        cache_key
    )


    if cached:

        age = (

            now
            - cached["timestamp"]

        )


        if age < CACHE_TTL_SECONDS:

            return cached["data"]


    try:

        market_data = build_market_data(

            display_symbol,

            api_symbol

        )


        result = {

            "symbol":
                display_symbol,

            "price":
                market_data[
                    "price"
                ],

            "market_status":
                market_data[
                    "market_status"
                ],

            "price_source":
                market_data[
                    "price_source"
                ],

            "last_completed_candle":
                market_data[
                    "last_completed_candle"
                ],

            "live_quote_available":
                market_data[
                    "live_quote_available"
                ],

            "quote_error":
                market_data[
                    "quote_error"
                ],

            "market":
                market_data[
                    "bias"
                ],

            "daily":
                market_data[
                    "daily"
                ],

            "sessions":
                market_data[
                    "sessions"
                ],

            "pivots":
                market_data[
                    "pivots"
                ],

            "timeframes":
                market_data[
                    "timeframes"
                ],

            "timestamp":
                market_data[
                    "timestamp"
                ]

        }


        CACHE[cache_key] = {

            "timestamp":
                now,

            "data":
                result

        }


        return result


    except HTTPException as e:

        return {

            "symbol":
                display_symbol,

            "price":
                None,

            "market_status":
                "DATA_ERROR",

            "price_source":
                "NONE",

            "live_quote_available":
                False,

            "error":
                e.detail,

            "timestamp":
                datetime.now(
                    timezone.utc
                ).isoformat()

        }


    except Exception as e:

        return {

            "symbol":
                display_symbol,

            "price":
                None,

            "market_status":
                "SYSTEM_ERROR",

            "price_source":
                "NONE",

            "live_quote_available":
                False,

            "error": {

                "type":
                    type(e).__name__,

                "message":
                    str(e)

            },

            "timestamp":
                datetime.now(
                    timezone.utc
                ).isoformat()

        }


# ============================================================
# ALL MARKETS
# ============================================================

def analyze_all():

    results = []


    for (
        display_symbol,
        api_symbol

    ) in WATCHLIST:

        results.append(

            analyze_symbol(

                display_symbol,

                api_symbol

            )

        )


    return {

        "timestamp":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "symbols":
            results

    }


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():

    return {

        "status":
            "online",

        "service":
            "Trading AI Market Data API",

        "dashboard":
            "/dashboard",

        "dashboard_data":
            "/dashboard-data",

        "analysis_data":
            "/analysis-data",

        "single_symbol":
            "/api?symbol=EURUSD",

        "health":
            "/health"

    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    return {

        "status":
            "ok",

        "twelve_data_key":
            bool(
                TWELVE_DATA_API_KEY
            ),

        "cache_ttl":
            CACHE_TTL_SECONDS

    }


# ============================================================
# SINGLE SYMBOL API
# ============================================================

@app.get("/api")
def single_symbol(
    symbol: str
):

    normalized = normalize_symbol(
        symbol
    )


    return build_market_data(

        symbol.upper(),

        normalized

    )


# ============================================================
# DASHBOARD DATA
# ============================================================

@app.get("/dashboard-data")
def dashboard_data():

    return analyze_all()


# ============================================================
# GPT ACTION ENDPOINT
#
# IMPORTANT:
# This endpoint DOES NOT require ?symbol=
#
# It returns all instruments in one request.
# ============================================================

@app.get("/analysis-data")
def analysis_data():

    return analyze_all()


# ============================================================
# FORMAT HELPERS
# ============================================================

def fmt_price(
    value
):

    if value is None:

        return "—"


    try:

        value = float(value)

    except Exception:

        return "—"


    if abs(value) >= 100:

        return f"{value:.2f}"


    if abs(value) >= 10:

        return f"{value:.3f}"


    return f"{value:.5f}"


# ============================================================
# DASHBOARD
# ============================================================

@app.get(
    "/dashboard",
    response_class=HTMLResponse
)
def dashboard():

    data = analyze_all()

    rows = []


    for item in data[
        "symbols"
    ]:

        symbol = item.get(
            "symbol",
            "UNKNOWN"
        )


        price = item.get(
            "price"
        )


        market_status = item.get(
            "market_status",
            "UNKNOWN"
        )


        price_source = item.get(
            "price_source",
            "UNKNOWN"
        )


        last_candle = item.get(
            "last_completed_candle",
            "—"
        )


        error = item.get(
            "error"
        )


        if error:

            error_text = str(
                error
            )

        else:

            error_text = ""


        bias_data = item.get(
            "market",
            {}
        )


        overall_bias = bias_data.get(
            "overall",
            "unknown"
        )


        bias_class = (

            "bullish"

            if overall_bias
            == "bullish"

            else

            "bearish"

            if overall_bias
            == "bearish"

            else

            "neutral"

        )


        rows.append(f"""

<tr>

<td class="symbol">
{symbol}
</td>


<td class="price">
{fmt_price(price)}
</td>


<td>

<span class="status {market_status.lower()}">

{market_status}

</span>

<div class="small">

{price_source}

</div>

</td>


<td>

<span class="bias {bias_class}">

{overall_bias.upper()}

</span>

</td>


<td>

{bias_data.get(
    "bullish_count",
    "—"
)}
bullish /

{bias_data.get(
    "bearish_count",
    "—"
)}
bearish

</td>


<td>

{last_candle}

</td>


<td class="error">

{error_text}

</td>


</tr>

""")


    generated = datetime.now(
        TZ
    ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


    page = f"""

<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<meta
name="viewport"
content="width=device-width,initial-scale=1"
>

<title>
Trading AI Market Data
</title>


<style>

* {{
    box-sizing:border-box;
}}


body {{

    margin:0;

    background:#0b0f14;

    color:#e8edf3;

    font-family:
        Arial,
        Helvetica,
        sans-serif;

}}


.container {{

    padding:24px;

    overflow-x:auto;

}}


.header {{

    display:flex;

    justify-content:
        space-between;

    margin-bottom:20px;

    gap:20px;

}}


h1 {{

    margin:0;

    font-size:28px;

}}


.subtitle {{

    color:#8996a5;

    margin-top:6px;

    font-size:13px;

}}


.refresh {{

    display:inline-block;

    padding:10px 14px;

    background:#151d27;

    border:1px solid #344150;

    border-radius:6px;

    color:#fff;

    text-decoration:none;

}}


table {{

    width:100%;

    min-width:1200px;

    border-collapse:
        collapse;

    background:#111720;

}}


th {{

    background:#18212c;

    color:#9eabb9;

    text-align:left;

    padding:13px;

    font-size:11px;

    text-transform:
        uppercase;

}}


td {{

    padding:13px;

    border-top:
        1px solid #202a35;

    font-size:13px;

    vertical-align:top;

}}


.symbol {{

    font-weight:700;

    font-size:15px;

}}


.price {{

    font-weight:700;

}}


.status,
.bias {{

    display:inline-block;

    padding:5px 9px;

    border-radius:5px;

    font-size:10px;

    font-weight:700;

}}


.status.open,
.bias.bullish {{

    background:#173b2b;

    color:#61e6a4;

}}


.status.closed_or_live_quote_unavailable,
.bias.neutral {{

    background:#3a3420;

    color:#f0ce69;

}}


.status.data_error,
.status.system_error,
.bias.bearish {{

    background:#452023;

    color:#ff7d87;

}}


.small {{

    color:#8996a5;

    margin-top:5px;

    font-size:11px;

}}


.error {{

    color:#ff7d87;

    max-width:500px;

    word-break:break-word;

}}

</style>

</head>


<body>


<div class="container">


<div class="header">

<div>

<h1>
Trading AI Market Data
</h1>

<div class="subtitle">

11 Forex / XAUUSD instruments ·
Twelve Data ·
multi-timeframe data

</div>

</div>


<div>

<div class="subtitle">

Updated:
{generated}

</div>

<br>

<a
class="refresh"
href="/dashboard"
>
Refresh
</a>

</div>

</div>


<table>

<thead>

<tr>

<th>
Symbol
</th>

<th>
Price
</th>

<th>
Market
</th>

<th>
MTF Bias
</th>

<th>
Structure
</th>

<th>
Last Candle
</th>

<th>
Error
</th>

</tr>

</thead>


<tbody>

{"".join(rows)}

</tbody>

</table>


<div class="subtitle">

GPT Action endpoint:

/analysis-data

</div>


</div>

</body>

</html>

"""


    return HTMLResponse(
        content=page
    )
