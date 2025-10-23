import os
import pandas as pd
import numpy as np
from io import BytesIO
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify, send_file
from pymongo import ASCENDING
from concurrent.futures import ThreadPoolExecutor, as_completed
from mongo_client import non_flask_db as db

mongo_export = Blueprint("mongo_export", __name__)

ALLOWED_COLLECTIONS = [
    "periodic_summary",
    "intraday",
    "historical",
    "open_positions",
    "login"
]

# Fields and defaults for periodic_summary auto-repair
FIELDS = [
    "Adj_Close", "Close", "High", "Low", "Open", "Volume",
    "RSI", "MACD_hist", "SMA_3", "SMA_20", "OBV",
    "BB_lower", "BB_upper", "Stoch_K", "Stoch_D", "ADX"
]

DEFAULTS = {
    "Adj_Close": 0.0,
    "Close": 0.0,
    "High": 0.0,
    "Low": 0.0,
    "Open": 0.0,
    "Volume": 0,
    "RSI": 50.0,
    "MACD_hist": 0.0,
    "SMA_3": 0.0,
    "SMA_20": 0.0,
    "OBV": 0.0,
    "BB_lower": 0.0,
    "BB_upper": 0.0,
    "Stoch_K": 0.0,
    "Stoch_D": 0.0,
    "ADX": 0.0,
    "signal": "HOLD",
    "score": 0.0,
    "reasons": ["AUTO-FIX: Filled missing values with previous row or defaults"]
}

def is_invalid(val):
    return val is None or (isinstance(val, str) and val.strip() == "") or (isinstance(val, float) and np.isnan(val))

def repair_stock(stock_id, start_obj, end_obj_exclusive):
    cursor = db["periodic_summary"].find({
        "stock_id": stock_id,
        "Datetime": {"$gte": start_obj, "$lt": end_obj_exclusive}
    }).sort("Datetime", ASCENDING)
    docs = list(cursor)
    last_valid = DEFAULTS.copy()
    for doc in docs:
        update_needed = False
        new_doc = {}
        for field in FIELDS:
            if field not in doc or is_invalid(doc[field]):
                new_doc[field] = last_valid.get(field, DEFAULTS[field])
                update_needed = True
            else:
                new_doc[field] = doc[field]
        if update_needed:
            new_doc["signal"] = "HOLD"
            new_doc["score"] = 0.0
            new_doc["reasons"] = ["AUTO-FIX: Filled missing values"]
            db["periodic_summary"].update_one({"_id": doc["_id"]}, {"$set": new_doc})
        last_valid.update(new_doc)

def repair_periodic_summary_range(start_obj, end_obj_exclusive, max_workers=8):
    stock_ids = db["periodic_summary"].distinct("stock_id", {"Datetime": {"$gte": start_obj, "$lt": end_obj_exclusive}})
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(repair_stock, sid, start_obj, end_obj_exclusive) for sid in stock_ids]
        for future in as_completed(futures):
            try:
                future.result()  # Ensures any errors are raised here
            except Exception as exc:
                print(f"Error repairing {exc}")

def parse_iso_date(dt_str):
    try:
        if len(dt_str) == 10:
            return datetime.strptime(dt_str, "%Y-%m-%d")
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None

def export_collection_range(collection_name, start_date_str, end_date_str):
    if collection_name not in ALLOWED_COLLECTIONS:
        raise ValueError(f"Invalid collection: {collection_name}")
    start_obj = parse_iso_date(start_date_str)
    end_obj = parse_iso_date(end_date_str)
    if not start_obj or not end_obj:
        raise ValueError("Invalid date range format. Use YYYY-MM-DD.")
    end_obj_exclusive = end_obj + timedelta(days=1)

    # Run repairs for periodic_summary before export
    if collection_name == "periodic_summary":
        repair_periodic_summary_range(start_obj, end_obj_exclusive)

    date_field = "login_time" if collection_name == "login" else "Datetime"
    query = {date_field: {"$gte": start_obj, "$lt": end_obj_exclusive}}
    cursor = db[collection_name].find(query).sort(date_field, 1)

    docs = []
    for d in cursor:
        d = dict(d)
        d["_id"] = str(d["_id"]) # Ensure _id is serializable
        docs.append(d)

    if not docs:
        raise ValueError(f"No data found in {collection_name} for selected range.")

    df = pd.DataFrame(docs)
    output = BytesIO()
    df.to_csv(output, index=False)
    output.seek(0)
    filename = f"{collection_name}_{start_date_str}_to_{end_date_str}.csv"
    return output, filename

@mongo_export.route("/api/db/export", methods=["GET"])
def export_and_download():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    collection = request.args.get("collection", "periodic_summary")
    if not start_date or not end_date:
        return jsonify({"error": "Missing 'start_date' or 'end_date' parameter. Format: YYYY-MM-DD"}), 400
    try:
        file_content, filename = export_collection_range(collection, start_date, end_date)
        file_content.seek(0)
        return send_file(
            file_content,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
@mongo_export.route("/api/db/delete", methods=["DELETE"])
def delete_collection_range():
    data = request.get_json()
    collection_name = data.get("collection")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    if collection_name not in ALLOWED_COLLECTIONS:
        return jsonify({"status": "error", "message": "Invalid collection."}), 400

    start_obj = parse_iso_date(start_date)
    end_obj = parse_iso_date(end_date)
    if not start_obj or not end_obj:
        return jsonify({"status": "error", "message": "Invalid date format."}), 400

    end_obj_exclusive = end_obj + timedelta(days=1)
    date_field = "login_time" if collection_name == "login" else "Datetime"
    query = {date_field: {"$gte": start_obj, "$lt": end_obj_exclusive}}

    result = db[collection_name].delete_many(query)
    return jsonify({"status": "success", "deleted_count": result.deleted_count})
