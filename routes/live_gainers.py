from flask import Blueprint, jsonify
from stock_utility import StockUtility
from mongo_client import non_flask_db as db
from pymongo import DESCENDING
import os
from datetime import datetime, timedelta, timezone
import pytz

live_gainers_api = Blueprint("live_gainers_api", __name__)
su = StockUtility()

def convert_to_ist(dt):
    if dt is None:
        return None
    # Assuming dt is naive or in UTC
    utc = pytz.utc
    ist = pytz.timezone('Asia/Kolkata')
    if dt.tzinfo is None:
        dt = utc.localize(dt)
    return dt.astimezone(ist)

def load_stocks_from_file(file_path="/shared/stocks_list.txt"):
    if not os.path.exists(file_path):
        return {}

    stock_dict = {}
    with open(file_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.lower().startswith("id"):
                continue
            
            parts = line.split(",")
            if len(parts) >= 3:
                try:
                    stock_id = int(parts[0].strip())
                    ticker = parts[2].strip()
                    stock_dict[stock_id] = ticker
                except ValueError:
                    continue
    return stock_dict
def fetch_latest_periodic_summaries(stock_ids, tickers):
    # Aggregation pipeline for latest entry per (stock_id, ticker)
    pipeline = [
        {"$match": {
            "stock_id": {"$in": [int(sid) for sid in stock_ids]},
            "ticker": {"$in": tickers}
        }},
        {"$sort": {"Datetime": -1}},
        {"$group": {
            "_id": {"stock_id": "$stock_id", "ticker": "$ticker"},
            "doc": {"$first": "$$ROOT"}
        }}
    ]
    return list(db["periodic_summary"].aggregate(pipeline, allowDiskUse=True))

@live_gainers_api.route("/api/live_intraday_gainers", methods=['GET'])
def get_live_intraday_gainers():
    try:
        stocks = load_stocks_from_file()
        if not stocks:
            return jsonify({"stocks": []})

        # Use .items() to get (stock_id, ticker) pairs
        stock_ids, tickers = zip(*stocks.items())
        latest_docs = fetch_latest_periodic_summaries(stock_ids, tickers)

        results = []
        for entry in latest_docs:
            doc = entry["doc"]
            ticker = doc.get("ticker", "")
            results.append({
                "symbol": ticker.replace(".NS", ""),
                "price": doc.get("Close"),
                "volume": doc.get("Volume"),
                "change": doc.get("profit_percent"),
                "profit": doc.get("profit_amount"),
                "profit_percent": doc.get("profit_percent"),
                "signal": doc.get("signal", "HOLD")
            })

        sorted_results = sorted(
            results, key=lambda x: (x["change"] if x["change"] is not None else -999), reverse=True
        )
        return jsonify({"stocks": sorted_results})
    except Exception as e:
        print(f"[❌] Exception in /api/live_intraday_gainers: {e}")
        return jsonify({"error": str(e)}), 500

@live_gainers_api.route("/api/live_intra_gainers", methods=['GET'])
def get_live_intra_gainers():
    try:
        # Connect to open_positions collection
        collection = db["open_positions"]

        # Get current date range in UTC (since MongoDB stores datetime in UTC)
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        #today = datetime(2025, 10, 17, 0, 0, 0, 0, tzinfo=timezone.utc)
        tomorrow = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=0)
        #tomorrow = datetime(2025, 10, 17, 23, 0, 0, 0, tzinfo=timezone.utc)

        # Fetch documents for current day only
        cursor = collection.find({
            "Datetime": {"$gte": today, "$lt": tomorrow}
        }).sort("buy_time", DESCENDING)

        open_positions = list(cursor)

        if not open_positions:
            return jsonify({"stocks": []})

        # Prepare variables for categorized signals
        buys = []
        sells = []

        for doc in open_positions:
            signal = doc.get("signal", "").upper()
            ticker = doc.get("ticker", "")
            base_entry = {
                "ticker": ticker,
                "symbol": ticker.replace(".NS", ""),
                "stock_id": doc.get("stock_id"),
                "reason": doc.get("reason", ""),
            }

            # Parse safe date/time fields
            def safe_dt(value):
                if isinstance(value, dict) and "$date" in value:
                    return value["$date"]
                return value

            if signal == "BUY":
                buys.append({
                    **base_entry,
                    "buy_time": convert_to_ist(doc.get("buy_time")),
                    "buy_price": doc.get("buy_price"),
                    "sell_time": None,
                    "sell_price": None,
                    "profit_pct": None,
                    "signal": signal,
                })
                
            
            elif signal == "CLOSED":
                sells.append({
                    **base_entry,
                    "buy_time": convert_to_ist(safe_dt(doc.get("buy_time"))),
                    "buy_price": doc.get("buy_price"),
                    "sell_time": convert_to_ist(doc.get("sell_time")),
                    "sell_price": doc.get("sell_price"),
                    "profit_pct": doc.get("profit_pct"),
                    "signal": "SELL",
                })
            
        return jsonify({
                    "stocks": buys + sells # unified array for frontend
        })
        

    except Exception as e:
        print(f"[❌] Exception in /api/live_intra_gainers: {e}")
        return jsonify({"error": str(e)}), 500