import requests
from rest_framework.response import Response
from rest_framework.decorators import api_view
from django.http import JsonResponse
from django.conf import settings
import upstox_client
from upstox_client.rest import ApiException
from upstox_client import InstrumentData
from datetime import datetime, timedelta
import pytz
import json

API_KEY = settings.API_KEY
@api_view(["GET"])
def get_historical_stock_data(request, symbol):

    try:
        url = "https://www.alphavantage.co/query"
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol, 
            "apikey": API_KEY
        }

        response = requests.get(url, params=params)
        data = response.json()

        time_series = data.get("Time Series (Daily)")
        if not time_series:
            return Response({"error": "No historical data found"}, status=400)

        history = [
            {
                "time": date,
                "open": float(info["1. open"]),
                "high": float(info["2. high"]),
                "low": float(info["3. low"]),
                "close": float(info["4. close"]),
            }
            for date, info in sorted(time_series.items(), reverse=True)
        ]

        return Response({"symbol": symbol.upper(), "history": history}, status=200)

    except Exception as e:
        print(f"Error: {e}")
        return Response({"error": str(e)}, status=500)

@api_view(["GET"])
def get_stock_data(request, symbol):
    try:
        url="https://www.alphavantage.co/query"
        params = {
            "function": "TIME_SERIES_INTRADAY",
            "symbol": symbol,
            "interval": "5min",
            "apikey": API_KEY
        }

        response = requests.get(url, params=params)
        data = response.json()

        time_series = data.get("Time Series (5min)")
        if not time_series:
            return Response({"error": "Stock data not available"}, status=400)

        latest_timestamp = sorted(time_series.keys())[-1]
        latest_data = time_series[latest_timestamp]

        stock_data = {
            "symbol": symbol.upper(),
            "last_price": float(latest_data["4. close"]),
            "open": float(latest_data["1. open"]),
            "high": float(latest_data["2. high"]),
            "low": float(latest_data["3. low"]),
            "volume": int(latest_data["5. volume"])
        }

        return Response(stock_data, status=200)
    except Exception as e:
        print(f"Error: {e}")


        return Response({"error": str(e)}, status=500)
    



@api_view(["GET"])
def search_stock(request):
    symbol = request.GET.get("symbol")
    if not symbol:
        return Response({"error": "Query parameter 'symbol' is required"}, status=400)

    try:
        url = "https://www.alphavantage.co/query"
        params = {
            "function": "SYMBOL_SEARCH",
            "keywords": symbol,
            "apikey": API_KEY
        }

        response = requests.get(url, params=params)
        data = response.json()

        matches = data.get("bestMatches")
        if not matches:
            return Response({"error": "No matches found"}, status=404)

        match = matches[0]
        return Response({
            "symbol": match["1. symbol"],
            "name": match["2. name"],
            "exchange": match["4. region"],
        })

    except Exception as e:
        print(f"Error: {e}")
        return Response({"error": str(e)}, status=500)
    