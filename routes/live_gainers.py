from flask import Blueprint, jsonify
from stock_utility import StockUtility
from mongo_client import non_flask_db as db
import os

live_gainers_api = Blueprint("live_gainers_api", __name__)
su = StockUtility()

def load_stocks_from_file(file_path="/shared/stocks_list.txt"):
    if not os.path.exists(file_path):
        print(f"[❌] File not found: {file_path}")
        return []
    stocks = []
    with open(file_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.lower().startswith("id,ticker"):
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                stock_id = parts[0].strip()
                ticker = parts[1].strip()
                if not ticker.endswith(".NS"):
                    ticker += ".NS"
                stocks.append((stock_id, ticker))
    return stocks

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

        stock_ids, tickers = zip(*stocks)
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
