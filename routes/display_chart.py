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
    with open(file_path, "r") as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
        stock_dict = {}
        for line in lines:
            if line.lower().startswith("id"):
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                stock_dict[parts[1].strip()] = int(parts[0].strip())
        return stock_dict
    
def historical_position(stock_id, ticker, dt):
    """
    After 9:59 data is stored, calculate profit if BUY and SELL both occurred today.
    Uses open_positions/trade_history collection for BUY/SELL prices.
    This also stores historical for that day
    """
    if dt.tzinfo is None:
        dt_ist = IST.localize(dt)
    else:
        dt_ist = dt.astimezone(IST)
    ist_midnight = dt_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    dt = ist_midnight.astimezone(UTC)
    print(dt)
    start_dt = dt.replace(hour=3, minute=45, second=0, microsecond=0)
    print(start_dt)
    end_dt = dt.replace(hour=9, minute=59, second=0, microsecond=0)
    print(end_dt)
    hist_dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    print(hist_dt)

    # Get BUY and SELL entries for the day from open_positions or trade_history
    buy_entry = db["open_positions"].find_one({
        "stock_id": int(stock_id),
        "ticker": ticker,
        "signal": "BUY",
        "Datetime": {"$gt": start_dt, "$lt": end_dt}
    })

    sell_entry = db["open_positions"].find_one({
        "stock_id": int(stock_id),
        "ticker": ticker,
        "signal": "SELL",
        "Datetime": {"$gt": start_dt, "$lt": end_dt}
    })

    # Fetch intraday documents for ticker on the given date
    docs = list(db["intraday"].find({
        "ticker": ticker,
        "Datetime": {"$gte": start_dt, "$lt": end_dt}
    }).sort("Datetime", 1))

    if not docs:
        return None  # No data, skip

    open_price = docs[0]["Open"]
    close_price = docs[-1]["Close"]
    high_price = max(d["High"] for d in docs)
    low_price = min(d["Low"] for d in docs)
    volume = sum(d["Volume"] for d in docs)
    adj_close = docs[-1].get("Adj Close", close_price)


    if buy_entry and sell_entry:
        buy_price = float(buy_entry["price"])
        sell_price = float(sell_entry["price"])
        profit_value = round(sell_price - buy_price, 2)
        profit_percent = round((profit_value / buy_price) * 100, 2) if buy_price else 0.0
        status = "GAIN" if profit_value > 0 else "LOSS" if profit_value < 0 else "NEUTRAL"

        doc = {
            "Datetime": hist_dt,
            "stock_id": int(stock_id),
            "ticker": ticker,
            "Open": round(open_price, 2),
            "High": round(high_price, 2),
            "Low": round(low_price, 2),
            "Close": round(close_price, 2),
            "Adj Close": round(adj_close, 2) if adj_close else round(close_price, 2),
            "Volume": int(volume),
            "profit_percent": profit_percent,
            "profit_value": profit_value,
            "status": status
        }

        db["historical"].update_one(
            {
                "Datetime": doc["Datetime"],
                "stock_id": doc["stock_id"],
                "ticker": doc["ticker"]
            },
            {"$set": doc},
            upsert=True
        )

        print(
            f"✅ Profit logged: {ticker} - {status} {profit_percent}% (₹{profit_value}) on {doc['Datetime']}"
        )

    elif buy_entry is None or sell_entry is None:
        profit_value = 0.0
        profit_percent = 0.0
        status = "NEUTRAL"
        doc = {
            "Datetime": hist_dt,
            "stock_id": int(stock_id),
            "ticker": ticker,
            "Open": round(open_price, 2),
            "High": round(high_price, 2),
            "Low": round(low_price, 2),
            "Close": round(close_price, 2),
            "Adj Close": round(adj_close, 2) if adj_close else round(close_price, 2),
            "Volume": int(volume),
            "profit_percent": profit_percent,
            "profit_value": profit_value,
            "status": status
        }
        db["historical"].update_one(
            {
                "Datetime": doc["Datetime"],
                "stock_id": doc["stock_id"],
                "ticker": doc["ticker"]
            },
            {"$set": doc},
            upsert=True
        )

        print(
            f"Neutral logged: {ticker} - {status} {profit_percent}% (₹{profit_value}) on {doc['Datetime']}"
        )


    else:
        print(f"⚠️ No complete BUY/SELL found yet for {ticker} on {dt.date()} to calculate profit.")

STOCK_MAP = load_stocks()
# reverse map: id -> ticker
ID_TO_TICKER = {v: k for k, v in STOCK_MAP.items()}

# timezone helpers
IST = pytz.timezone("Asia/Kolkata")
UTC = pytz.utc

def to_ist_iso(dt):
    """Convert a datetime (naive or tz-aware) to IST and return ISO string with offset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # assume stored as UTC if naive
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(IST).isoformat()

def ensure_db_query_range(start_date_str, end_date_str=None):
    """
    Given date strings 'YYYY-MM-DD', return (start_utc, end_utc) datetimes suitable for querying
    a DB that stores times in UTC. Inputs are interpreted in IST (user's local).
    """
    start_dt_naive = datetime.strptime(start_date_str, "%Y-%m-%d")
    start_ist = IST.localize(datetime.combine(start_dt_naive, time.min))
    if end_date_str:
        end_dt_naive = datetime.strptime(end_date_str, "%Y-%m-%d")
        end_ist = IST.localize(datetime.combine(end_dt_naive, time.max))
    else:
        end_ist = IST.localize(datetime.combine(start_dt_naive, time.max))

    # convert to UTC for DB queries
    start_utc = start_ist.astimezone(UTC)
    end_utc = end_ist.astimezone(UTC)
    return start_utc, end_utc

@display_chart_api.route("/api/display_chart", methods=["GET"])
def display_chart():
    try:
        # Accept either (ticker + start_date) OR (stock_id + target_datetime)
        ticker = request.args.get("ticker")
        start_date = request.args.get("start_date")  # YYYY-MM-DD (optional if target_datetime provided)
        end_date = request.args.get("end_date")      # optional
        stock_id_param = request.args.get("stock_id")
        target_datetime = request.args.get("target_datetime")  # optional

        # Resolve stock_id and ticker in a flexible way
        stock_id = None
        # If stock_id param present, convert to int
        if stock_id_param:
            try:
                stock_id = int(stock_id_param)
            except ValueError:
                return jsonify({"error": "stock_id must be an integer"}), 400

            # If ticker not provided, try to resolve from reverse mapping
            if not ticker:
                ticker = ID_TO_TICKER.get(stock_id)
                if not ticker:
                    return jsonify({"error": f"ticker not found for stock_id={stock_id}"}), 404

        # If ticker provided but no stock_id, resolve using STOCK_MAP
        if ticker and not stock_id:
            # exact match expected; normalize spaces
            if ticker not in STOCK_MAP:
                return jsonify({"error": f"{ticker} not found in stocks list"}), 404
            stock_id = STOCK_MAP[ticker]

        # If neither a (ticker+start_date) nor (stock_id+target_datetime) situation, try to fill gaps:
        # If user provided target_datetime but not start_date, use target_datetime as start_date.
        if not start_date and target_datetime:
            start_date = target_datetime
            end_date = None

        # Now we must have stock_id and start_date to perform DB range queries.
        if not stock_id or not start_date:
            return jsonify({"error": "Missing required parameters. Provide either (ticker & start_date) or (stock_id & target_datetime)."}), 400

        # Validate date format
        try:
            start_utc, end_utc = ensure_db_query_range(start_date, end_date)
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400

        # If target_datetime provided, compute intraday profit for that date
        intraday_profit_percent = None
        intraday_profit_value = None
        if target_datetime:
            try:
                profit_data = stock_util.get_intraday_profit(stock_id, ticker, target_datetime)
                # profit_data may be None or contain 'error'
                if isinstance(profit_data, dict) and profit_data.get("error"):
                    # don't fail entire endpoint — just keep profit fields None but include error in response
                    intraday_profit_percent = None
                    intraday_profit_value = None
                    profit_error = profit_data.get("error")
                else:
                    intraday_profit_percent = profit_data.get("intraday_profit_percent")
                    intraday_profit_value = profit_data.get("intraday_profit_value")
                    profit_error = None
            except Exception as e:
                intraday_profit_percent = None
                intraday_profit_value = None
                profit_error = str(e)
        else:
            profit_error = None

        # Query historical (assume DB stores Datetime in UTC or tz-aware)
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

        # Fetch intraday
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

        # Fetch periodic_summary (signal, score)
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
                # DB might use 'signal' or 'type' or other names; prefer 'signal'
                "signal": doc.get("signal") or doc.get("type") or doc.get("position_type"),
                "score": doc.get("score")
            })

        # Fetch open_positions and normalize to the frontend shape:
        start_day_utc = start_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        open_pos_docs = list(db["open_positions"].find({
            "stock_id": int(stock_id),
            "ticker": ticker,
            "Datetime": {"$gte": start_day_utc, "$lte": end_utc}
        }).sort("Datetime", 1))

        positions_data = []
        for doc in open_pos_docs:
            # Get main fields
            signal = doc.get("signal") or doc.get("type") or doc.get("position_type")
            trade_signal = doc.get("trade_signal")
            reason = doc.get("reason")

            # --- Extract price and timestamp properly ---
            price = None
            timestamp = None

            if signal in ("BUY", "OPEN"):
                price = doc.get("buy_price") or doc.get("price")
                timestamp = doc.get("buy_time") or doc.get("Datetime")
            elif signal in ("SELL", "CLOSED", "EXIT"):
                price = doc.get("sell_price") or doc.get("expected_sell_close") or doc.get("price")
                timestamp = doc.get("sell_time") or doc.get("expected_sell_time") or doc.get("Datetime")
            else:
                price = doc.get("price") or doc.get("close")
                timestamp = doc.get("Datetime")

            # --- Normalize timestamp type (datetime or str) ---
            if isinstance(timestamp, dict) and "$date" in timestamp:
                timestamp = timestamp["$date"]
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except Exception:
                    timestamp = None

            # --- Convert to IST for display ---
            if timestamp:
                timestamp = to_ist_iso(timestamp)
            else:
                dt = doc.get("Datetime")
                if isinstance(dt, str):
                    try:
                        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
                    except Exception:
                        dt = None
                timestamp = to_ist_iso(dt) if dt else None

            # --- Append final normalized entry ---
            positions_data.append({
                "datetime": timestamp,
                "signal": signal,
                "price": price,
                "profit_pct": doc.get("profit_pct"),
                "max_profit_pct": doc.get("max_profit_pct"),
                "trade_signal": trade_signal,
                "reason": reason
            })

        start_ist_iso = start_utc.astimezone(IST).isoformat()
        end_ist_iso = end_utc.astimezone(IST).isoformat()

        response = {
            "ticker": ticker,
            "stock_id": int(stock_id),
            "date_range": {"from": start_ist_iso, "to": end_ist_iso},
            "intraday_profit_percent": intraday_profit_percent,
            "intraday_profit_value": intraday_profit_value,
            "historical": historical_data,
            "intraday": intraday_data,
            "periodic_summary": periodic_data,
            "open_positions": positions_data
        }

        # attach a profit_error if there was an issue computing profit
        if profit_error:
            response["intraday_profit_error"] = profit_error

        return jsonify(response)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

@display_chart_api.route("/api/update_open_positions", methods=["POST"])
def update_open_positions():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400

        stock_id = data.get("stock_id")
        ticker = data.get("ticker")
        positions = data.get("open_positions", [])

        if not stock_id or not ticker or not positions:
            return jsonify({"error": "Missing stock_id, ticker, or open_positions"}), 400

        updates = []
        for pos in positions:
            dt_str = pos.get("datetime")
            old_dt_str = pos.get("old_datetime", dt_str)
            signal = pos.get("signal")
            price = pos.get("price")

            if price is None:
                return jsonify({"error": "No price available for selected time"}), 400

            if not dt_str or signal is None or price is None:
                continue

            # Convert IST datetime string to UTC datetime
            dt_obj_ist = datetime.fromisoformat(dt_str)
            if dt_obj_ist.tzinfo is None:
                dt_obj_ist = IST.localize(dt_obj_ist)
            dt_obj_utc = dt_obj_ist.astimezone(UTC)

            old_dt_obj_ist = datetime.fromisoformat(old_dt_str)
            if old_dt_obj_ist.tzinfo is None:
                old_dt_obj_ist = IST.localize(old_dt_obj_ist)
            old_dt_obj_utc = old_dt_obj_ist.astimezone(UTC)

            # DELETE old record (only if datetime actually changed)
            if old_dt_str != dt_str:
                result_del = db["open_positions"].delete_one({
                    "stock_id": int(stock_id),
                    "ticker": ticker,
                    "Datetime": old_dt_obj_utc
                })
            else:
                result_del = None  # Only need insert if not changed

            # INSERT new record
            result_insert = db["open_positions"].insert_one({
                "stock_id": int(stock_id),
                "ticker": ticker,
                "price": price,
                "Datetime": dt_obj_utc,
                "signal": signal
                
            })

            # Update periodic_summary for old and new times
            db["periodic_summary"].update_one(
                {
                    "ticker": ticker,
                    "stock_id": int(stock_id),
                    "Datetime": old_dt_obj_utc,
                    "signal": {"$in": ["BUY", "SELL"]}
                },
                {"$set": {"signal": "HOLD"}}
            )
            db["periodic_summary"].update_one(
                {
                    "ticker": ticker,
                    "stock_id": int(stock_id),
                    "Datetime": dt_obj_utc,
                },
                {"$set": {"signal": signal}},
                upsert=True
            )
            # dt_obj_ist is a timezone-aware IST datetime for the trade (or get it from UTC)
            dt_for_historical = dt_obj_ist if dt_obj_ist else dt_obj_utc
            try:
                historical_position(stock_id, ticker, dt_for_historical)
            except Exception as e:
                print(f"Profit calculation update failed for {ticker}: {e}")

        return jsonify({
            "status": "success",
            "updates": updates
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
