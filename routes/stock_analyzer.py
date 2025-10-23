from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from mongo_client import non_flask_db as db


analyzer_api = Blueprint("analyzer_api", __name__)


@analyzer_api.route("/api/purchases_by_date", methods=["GET"])
def get_purchases_by_date():
    """
    Returns all stock purchase (open_positions) details for a given date.
    Example: /api/purchases_by_date?date=2025-10-17
    """
    try:
        # --- 1️⃣ Parse and validate input date ---
        date_str = request.args.get("date")
        if not date_str:
            return jsonify({"error": "Missing 'date' parameter (format: YYYY-MM-DD)"}), 400
        
        try:
            input_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400
        
        # Define date range for that day (UTC)
        start_of_day = datetime(input_date.year, input_date.month, input_date.day)
        end_of_day = start_of_day + timedelta(days=1)

        # --- 2️⃣ Query MongoDB ---
        query = {
            "Datetime": {
                "$gte": start_of_day,
                "$lt": end_of_day
            }
        }

        records = list(db["open_positions"].find(query))

        # --- 3️⃣ Transform documents for JSON response ---
        def safe_isoformat(dt):
            if isinstance(dt, datetime):
                return dt.isoformat()
            return dt  # return as is if not datetime
        
        result = []
        for doc in records:
            result.append({
                "ticker": doc.get("ticker"),
                "buy_price": doc.get("buy_price"),
                "buy_time": safe_isoformat(doc.get("buy_time")),
                "expected_sell_close": doc.get("expected_sell_close"),
                "expected_sell_time": safe_isoformat(doc.get("expected_sell_time")),
                "max_profit_pct": doc.get("max_profit_pct"),
                "reason": doc.get("reason"),
                "signal": doc.get("signal"),
                "stock_id": doc.get("stock_id"),
                "profit_pct": doc.get("profit_pct"),
                "sell_price": doc.get("sell_price"),
                "sell_time": safe_isoformat(doc.get("sell_time")),
                "trade_signal": doc.get("trade_signal"),
            })

        # --- 4️⃣ Return JSON response ---
        return jsonify({
            "date": date_str,
            "count": len(result),
            "purchases": result
        })

    except Exception as e:
        print(f"[❌] Exception in /api/purchases_by_date: {e}")
        return jsonify({"error": str(e)}), 500
