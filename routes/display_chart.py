from flask import Blueprint, request, jsonify
from datetime import datetime, time
from mongo_client import non_flask_db as db
from stock_utility import StockUtility
import os
import pytz

stock_util = StockUtility()
display_chart_api = Blueprint("display_chart_api", __name__)

def load_stocks(file_path="/shared/stocks_list.txt"):
    if not os.path.exists(file_path):
        return {}
    
    stock_dict = {}
    with open(file_path, "r") as f:
        lines = [line.strip() for line in f if line.strip()]
        for line in lines:
            if line.lower().startswith("id"):
                continue
            parts = line.split(",")
            if len(parts) >= 3:
                try:
                    stock_id = int(parts[0].strip())
                    ticker = parts[2].strip()
                    stock_dict[ticker] = stock_id
                except ValueError:
                    continue
    return stock_dict

STOCK_MAP = load_stocks()
ID_TO_TICKER = {v: k for k, v in STOCK_MAP.items()}

IST = pytz.timezone("Asia/Kolkata")
UTC = pytz.utc

def to_ist_iso(dt):
    """Convert a datetime (naive or tz-aware) to IST and return ISO string with offset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)  # Assume naive datetime as UTC
    return dt.astimezone(IST).isoformat()

def to_utc_datetime(dt):
    """Ensure datetime is timezone-aware in UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)

@display_chart_api.route("/api/display_chart", methods=["GET"])
def display_chart():
    try:
        ticker = request.args.get("ticker")
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        stock_id_param = request.args.get("stock_id")
        target_datetime = request.args.get("target_datetime")

        stock_id = None
        if stock_id_param:
            try:
                stock_id = int(stock_id_param)
            except ValueError:
                return jsonify({"error": "stock_id must be an integer"}), 400
            if not ticker:
                ticker = ID_TO_TICKER.get(stock_id)
                if not ticker:
                    return jsonify({"error": f"ticker not found for stock_id={stock_id}"}), 404

        if ticker and not stock_id:
            if ticker not in STOCK_MAP:
                return jsonify({"error": f"{ticker} not found in stocks list"}), 404
            stock_id = STOCK_MAP[ticker]

        if not start_date and target_datetime:
            start_date = target_datetime
            end_date = None

        if not stock_id or not start_date:
            return jsonify({"error": "Missing required parameters. Provide either (ticker & start_date) or (stock_id & target_datetime)."}), 400

        try:
            # Interpret input dates as IST, convert to UTC for queries
            start_ist = IST.localize(datetime.strptime(start_date, "%Y-%m-%d"))
            if end_date:
                end_ist = IST.localize(datetime.strptime(end_date, "%Y-%m-%d"))
            else:
                end_ist = start_ist
            start_utc = start_ist.astimezone(UTC)
            # Set end to end of day IST converted to UTC
            end_utc = end_ist.replace(hour=23, minute=59, second=59, microsecond=999999).astimezone(UTC)
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400

        # Fetch historical data
        historical_docs = list(db["historical"].find({
            "stock_id": int(stock_id),
            "ticker": ticker,
            "Datetime": {"$gte": start_utc, "$lte": end_utc}
        }).sort("Datetime", 1))
        historical_data = []
        for doc in historical_docs:
            dt = doc.get("Datetime")
            historical_data.append({
                "datetime": to_ist_iso(dt),
                "open": doc.get("Open"),
                "high": doc.get("High"),
                "low": doc.get("Low"),
                "close": doc.get("Close"),
                "volume": doc.get("Volume"),
                "profit_percent": doc.get("profit_percent"),
                "profit_value": doc.get("profit_value"),
                "status": doc.get("status")
            })

        # Fetch intraday data
        intraday_docs = list(db["intraday"].find({
            "stock_id": int(stock_id),
            "ticker": ticker,
            "Datetime": {"$gte": start_utc, "$lte": end_utc}
        }).sort("Datetime", 1))
        intraday_data = []
        for doc in intraday_docs:
            dt = doc.get("Datetime")
            intraday_data.append({
                "datetime": to_ist_iso(dt),
                "open": doc.get("Open"),
                "high": doc.get("High"),
                "low": doc.get("Low"),
                "close": doc.get("Close"),
                "volume": doc.get("Volume")
            })

        # Fetch periodic summary
        periodic_docs = list(db["periodic_summary"].find({
            "stock_id": int(stock_id),
            "ticker": ticker,
            "Datetime": {"$gte": start_utc, "$lte": end_utc}
        }).sort("Datetime", 1))
        periodic_data = []
        for doc in periodic_docs:
            dt = doc.get("Datetime")
            periodic_data.append({
                "datetime": to_ist_iso(dt),
                "signal": doc.get("signal") or doc.get("type") or doc.get("position_type"),
                "score": doc.get("score")
            })

        # Fetch open positions and normalize
        start_day_utc = start_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        open_pos_docs = list(db["open_positions"].find({
            "stock_id": stock_id,
            "ticker": ticker,
            "Datetime": {"$gte": start_day_utc, "$lte": end_utc}
        }).sort("Datetime", 1))

        positions_data = []
        # Get intraday profit data if requested
        intraday_profit_percent = None
        intraday_profit_value = None
        profit_error = None

        def normalize_dt_field(dt_field):
            if not dt_field:
                return None
            if isinstance(dt_field, dict) and "$date" in dt_field:
                dt_obj = datetime.fromisoformat(dt_field["$date"].replace("Z", "+00:00"))
            elif isinstance(dt_field, str):
                dt_obj = datetime.fromisoformat(dt_field.replace("Z", "+00:00"))
            else:
                dt_obj = dt_field
            return to_utc_datetime(dt_obj) if dt_obj else None

        for doc in open_pos_docs:
            position_entry = {k: v for k, v in doc.items() if k != "_id"}

            # Normalize buy_time
            buy_time = normalize_dt_field(doc.get("buy_time") or doc.get("Datetime"))
            position_entry["buy_time"] = buy_time.isoformat() if buy_time else None

            # Normalize sell_time (if exists)
            sell_time = normalize_dt_field(doc.get("sell_time")) if doc.get("sell_time") else None
            position_entry["sell_time"] = sell_time.isoformat() if sell_time else None

            intraday_profit_percent = position_entry["profit_pct"]
            intraday_profit_value = position_entry["sell_price"] - position_entry["buy_price"]

            # Decide signal type
            if sell_time and "sell_price" in doc:
                position_entry["signal"] = "CLOSED"
            else:
                position_entry["signal"] = "BUY"

                # Ensure no stray sell fields
                for field in ["sell_price", "sell_time", "expected_sell_close", "expected_sell_time"]:
                    position_entry.pop(field, None)

            # Normalize Datetime to IST
            dt_field = doc.get("Datetime")
            if dt_field:
                if isinstance(dt_field, dict) and "$date" in dt_field:
                    dt_obj = datetime.fromisoformat(dt_field["$date"].replace("Z", "+00:00"))
                elif isinstance(dt_field, str):
                    dt_obj = datetime.fromisoformat(dt_field.replace("Z", "+00:00"))
                else:
                    dt_obj = dt_field
                position_entry["Datetime"] = to_ist_iso(dt_obj)

            positions_data.append(position_entry)

        # Add response fields
        start_ist_iso = start_utc.astimezone(IST).isoformat()
        end_ist_iso = end_utc.astimezone(IST).isoformat()

        response = {
            "ticker": ticker,
            "stock_id": stock_id,
            "date_range": {"from": start_ist_iso, "to": end_ist_iso},
            "intraday_profit_percent": intraday_profit_percent,
            "intraday_profit_value": intraday_profit_value,
            "historical": historical_data,
            "intraday": intraday_data,
            "periodic_summary": periodic_data,
            "open_positions": positions_data
        }
        if profit_error:
            response["intraday_profit_error"] = profit_error

        return jsonify(response)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
