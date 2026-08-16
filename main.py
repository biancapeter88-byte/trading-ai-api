import os
import requests
from fastapi import FastAPI, HTTPException

app = FastAPI(title="Trading AI Market API")

TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
TWELVE_DATA_URL = "https://api.twelvedata.com"


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "Trading AI Market API"
    }


@app.get("/quote")
def quote(symbol: str):

    if not TWELVE_DATA_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="TWELVE_DATA_API_KEY is not configured"
        )

    response = requests.get(
        f"{TWELVE_DATA_URL}/quote",
        params={
            "symbol": symbol,
            "apikey": TWELVE_DATA_API_KEY,
        },
        timeout=10,
    )

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text,
        )

    data = response.json()

    if "code" in data:
        raise HTTPException(
            status_code=400,
            detail=data,
        )

    return data


@app.get("/candles")
def candles(
    symbol: str,
    interval: str = "5min",
    outputsize: int = 200,
):

    if not TWELVE_DATA_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="TWELVE_DATA_API_KEY is not configured"
        )

    response = requests.get(
        f"{TWELVE_DATA_URL}/time_series",
        params={
            "symbol": symbol,
            "interval": interval,
            "outputsize": outputsize,
            "apikey": TWELVE_DATA_API_KEY,
        },
        timeout=15,
    )

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text,
        )

    data = response.json()

    if "code" in data:
        raise HTTPException(
            status_code=400,
            detail=data,
        )

    return data
