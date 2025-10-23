# data_handler.py
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta, timezone
from bson.objectid import ObjectId
from pymongo import ASCENDING, DESCENDING
from mongo_client import non_flask_db as db


COLLECTIONS = [
    "historical",
    "intraday",
    "open_positions",
    "periodic_summary",
    "login",
    "user",
    "counters",
]

data_handler_api = Blueprint("data_handler_api", __name__)

def parse_iso_date(dt_str):
    try:
        if len(dt_str) == 10:  # just date
            return datetime.strptime(dt_str, "%Y-%m-%d")
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None

def utc_to_ist(dt):
    if not dt:
        return ""
    try:
        if hasattr(dt, "tzinfo") and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except Exception:
        return str(dt)


def serialize_doc(doc, db_name="intraday"):
    """
    Convert BSON doc -> JSON-serializable dict for frontend:
    - convert datetime fields to IST strings
    - convert _id to hex string under key '_id'
    - remove internal keys (stock_id/type) if present
    """
    doc = dict(doc)  # copy
    # Keep original _id as string for frontend (but don't keep BSON object)
    oid = doc.get("_id")
    if oid is not None:
        try:
            doc["_id"] = str(oid)
        except Exception:
            doc["_id"] = str(oid)

    # Remove helper keys not intended for frontend
    doc.pop("stock_id", None)
    doc.pop("type", None)

    # For user/login collections: convert created_at/last_login/login_time
    if db_name in ("login", "user"):
        for dt_field in ("created_at", "last_login", "login_time", "logout_time"):
            dt = doc.get(dt_field)
            if dt:
                try:
                    if hasattr(dt, "isoformat"):
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        doc[dt_field] = dt.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d %H:%M:%S")
                    elif isinstance(dt, dict) and "$date" in dt:
                        utc_dt = datetime.fromisoformat(dt["$date"].replace("Z", "+00:00"))
                        doc[dt_field] = utc_dt.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        doc[dt_field] = str(dt)
                except Exception:
                    doc[dt_field] = str(dt)
        # Remove Datetime if present (these collections use created_at / login_time)
        doc.pop("Datetime", None)

    else:
        # For other collections, convert Datetime if present
        dt = doc.get("Datetime")
        if dt:
            try:
                # If it's a proper datetime
                if hasattr(dt, "isoformat"):
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    dt_ist = dt.astimezone(timezone(timedelta(hours=5, minutes=30)))
                    if db_name in ("intraday", "periodic_summary"):
                        # intraday / periodic: show time only for readability
                        doc["Datetime"] = dt_ist.strftime("%H:%M:%S")
                    else:
                        doc["Datetime"] = dt_ist.strftime("%Y-%m-%d %H:%M:%S")
                # If mongo-style {'$date': '...Z'}
                elif isinstance(dt, dict) and "$date" in dt:
                    utc_dt = datetime.fromisoformat(dt["$date"].replace("Z", "+00:00"))
                    dt_ist = utc_dt.astimezone(timezone(timedelta(hours=5, minutes=30)))
                    if db_name in ("intraday", "periodic_summary"):
                        doc["Datetime"] = dt_ist.strftime("%H:%M:%S")
                    else:
                        doc["Datetime"] = dt_ist.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    doc["Datetime"] = str(dt)
            except Exception:
                doc["Datetime"] = str(dt)

    # Preferred ordering for frontend columns
    default_orders = {
        "intraday": ["Datetime", "ticker", "Open", "High", "Low", "Close", "Volume"],
        "periodic_summary": ["Datetime", "ticker", "signal", "score", "reasons"],
    }
    preferred_keys = default_orders.get(db_name, [])

    ordered_doc = {k: doc[k] for k in preferred_keys if k in doc}
    for key in doc:
        if key not in ordered_doc:
            ordered_doc[key] = doc[key]

    return ordered_doc


@data_handler_api.route("/api/data_query", methods=["GET"])
def data_query():
    """
    Backwards-compatible query for intraday / periodic_summary that uses offset-based pagination.
    Kept for older code paths (not the cursor-based collection_data).
    """
    db_name = request.args.get("db")  # intraday or periodic_summary
    ticker = request.args.get("ticker")
    stock_id = request.args.get("stock_id")
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 20))
    skip = (page - 1) * limit

    if db_name not in ("intraday", "periodic_summary"):
        return jsonify({"error": "db must be 'intraday' or 'periodic_summary'."}), 400
    if not ticker or stock_id is None:
        return jsonify({"error": "ticker and stock_id are required."}), 400

    query = {"ticker": ticker, "stock_id": int(stock_id)}

    if db_name == "intraday":
        date_str = request.args.get("date")
        if not date_str:
            return jsonify({"error": "date (YYYY-MM-DD) required for intraday."}), 400
        date_obj = parse_iso_date(date_str)
        if not date_obj:
            return jsonify({"error": "Invalid date format."}), 400
        next_day = date_obj + timedelta(days=1)
        query["Datetime"] = {"$gte": date_obj, "$lt": next_day}
        collection = db["intraday"]
        sort_key = "Datetime"
    else:
        datetime_str = request.args.get("datetime")
        if datetime_str:
            if len(datetime_str) == 10:
                day_obj = parse_iso_date(datetime_str)
                if not day_obj:
                    return jsonify({"error": "Invalid datetime format."}), 400
                next_day = day_obj + timedelta(days=1)
                query["Datetime"] = {"$gte": day_obj, "$lt": next_day}
            else:
                dt_obj = parse_iso_date(datetime_str)
                if not dt_obj:
                    return jsonify({"error": "Invalid datetime format."}), 400
                query["Datetime"] = dt_obj
        collection = db["periodic_summary"]
        sort_key = "Datetime"

    total = collection.count_documents(query)
    cursor = (
        collection.find(query)
        .sort(sort_key, 1)
        .skip(skip)
        .limit(limit)
    )
    data = [serialize_doc(x, db_name=db_name) for x in cursor]

    return jsonify(
        {
            "success": True,
            "db": db_name,
            "ticker": ticker,
            "stock_id": int(stock_id),
            "total": total,
            "limit": limit,
            "page": page,
            "pages": (total + limit - 1) // limit,
            "data": data,
        }
    )


@data_handler_api.route("/api/db/collections_overview", methods=["GET"])
def get_collections_overview():
    overview = []
    for cname in COLLECTIONS:
        col = db[cname]
        count = col.count_documents({})
        try:
            stats = db.command("collstats", cname)
            size = round(stats.get("size", 0) / (1024 * 1024), 2)
        except Exception:
            size = "N/A"

        # Get first and last by Datetime field only (skip BSON/ObjectId logic)
        first_doc = col.find({"Datetime": {"$exists": True}}).sort("Datetime", ASCENDING).limit(1)
        last_doc = col.find({"Datetime": {"$exists": True}}).sort("Datetime", DESCENDING).limit(1)
        first_dt = None
        last_dt = None

        for d in first_doc:
            first_dt = d.get("Datetime")
        for d in last_doc:
            last_dt = d.get("Datetime")

        overview.append(
            {
                "collection": cname,
                "count": count,
                "size_mb": size,
                "first_datetime_ist": utc_to_ist(first_dt),
                "last_datetime_ist": utc_to_ist(last_dt),
            }
        )
    return jsonify(overview)


@data_handler_api.route("/api/db/collection_data", methods=["GET"])
def get_collection_data():
    """
    Cursor-based collection listing across various collections.
    Query params:
      - collection: collection name (required)
      - limit: page size (optional)
      - cursor: cursor token (optional) -> format "ISOdatetime|objectid" when Datetime exists, else ObjectId hex
      - direction: 'next' (default) or 'prev'
      - date: YYYY-MM-DD (applies to collections that have Datetime, e.g. historical/intraday)
      - other filters (exact match) are supported (e.g. ticker=XXX)
    Response:
      {
        "collection": cname,
        "data": [ ... serialized docs ... ],
        "cursor": "<cursor for next page or null>",
        "limit": limit,
        "has_more": bool,
        "total": total_count_base_filters
      }
    """
    cname = request.args.get("collection")
    limit = min(int(request.args.get("limit", 50)), 100)  # safety cap
    cursor_value = request.args.get("cursor")  # expecting 'datetime|objectid' or just objectid
    direction = request.args.get("direction", "next")  # "next" or "prev"

    if cname not in COLLECTIONS:
        return jsonify({"error": "Invalid collection"}), 400

    col = db[cname]

    # Determine if this collection uses Datetime for sorting
    has_datetime = col.find_one({"Datetime": {"$exists": True}}) is not None
    sort_order = 1 if direction == "next" else -1

    if has_datetime:
        sort_fields = [("Datetime", sort_order), ("_id", sort_order)]
    else:
        sort_fields = [("_id", sort_order)]

    # --- Build base (non-pagination) filters ---
    # Date filter (only for collections that have Datetime and not user/login)
    date_str = request.args.get("date", "").strip()
    base_filter = {}
    if date_str and cname not in ("login", "user"):
        date_obj = parse_iso_date(date_str)
        if date_obj is None:
            return jsonify({"error": "Invalid date format"}), 400
        next_day = date_obj + timedelta(days=1)
        base_filter["Datetime"] = {"$gte": date_obj, "$lt": next_day}

    # Add other non-pagination filters from query args (exact matches)
    exclude_keys = {"collection", "limit", "cursor", "direction", "date"}
    for k, v in request.args.items():
        if k in exclude_keys:
            continue
        if v.strip() == "":
            continue
        # these go into base_filter (they are independent of page cursor)
        base_filter[k] = v

    # Compute total count using base_filter only (so total stays stable across pages)
    try:
        total_count = col.count_documents(base_filter)
    except Exception:
        # fallback: 0
        total_count = 0

    # --- Build pagination filter separately and combine with base_filter for query ---
    pagination_filter = {}
    if cursor_value and has_datetime:
        try:
            dt_str, oid_str = cursor_value.split("|")
            dt_cursor = parse_iso_date(dt_str)
            oid_cursor = ObjectId(oid_str)
            if not dt_cursor:
                return jsonify({"error": "Invalid cursor datetime format"}), 400

            if direction == "next":
                # Datetime > dt_cursor OR (Datetime == dt_cursor AND _id > oid_cursor)
                pagination_filter["$or"] = [
                    {"Datetime": {"$gt": dt_cursor}},
                    {"Datetime": dt_cursor, "_id": {"$gt": oid_cursor}},
                ]
            else:
                # Datetime < dt_cursor OR (Datetime == dt_cursor AND _id < oid_cursor)
                pagination_filter["$or"] = [
                    {"Datetime": {"$lt": dt_cursor}},
                    {"Datetime": dt_cursor, "_id": {"$lt": oid_cursor}},
                ]
        except Exception:
            return jsonify({"error": "Invalid cursor format, expected 'datetime|objectid'"}), 400
    elif cursor_value and not has_datetime:
        try:
            oid_cursor = ObjectId(cursor_value)
            op = "$gt" if direction == "next" else "$lt"
            pagination_filter["_id"] = {op: oid_cursor}
        except Exception:
            return jsonify({"error": "Invalid cursor ObjectId"}), 400

    # Combine base_filter + pagination_filter correctly
    if base_filter and pagination_filter:
        # both present -> need $and
        combined_filter = {"$and": [base_filter, pagination_filter]}
    elif base_filter:
        combined_filter = base_filter
    elif pagination_filter:
        combined_filter = pagination_filter
    else:
        combined_filter = {}

    # Build aggregation pipeline
    pipeline = [
        {"$match": combined_filter},
        {"$sort": dict(sort_fields)},
        {"$limit": limit + 1},  # fetch one extra to detect more pages
    ]

    try:
        cursor = col.aggregate(pipeline, allowDiskUse=True)
    except Exception as e:
        return jsonify({"error": f"Query failed: {str(e)}"}), 500

    docs = list(cursor)
    has_more = len(docs) > limit
    if has_more:
        docs = docs[:limit]

    # Serialize docs for frontend and ensure _id is present as string
    result_docs = [serialize_doc(d, db_name=cname) for d in docs]

    # Prepare next-cursor only if there's more
    next_cursor = None
    if has_more:
        last_doc = docs[-1]
        # last_doc still contains original BSON types (Datetime object, _id)
        last_oid = last_doc.get("_id")
        if has_datetime:
            last_dt = last_doc.get("Datetime")
            # use ISO format (UTC) for cursor token — keep timezone info if present
            try:
                dt_iso = last_dt.isoformat() if hasattr(last_dt, "isoformat") else str(last_dt)
            except Exception:
                dt_iso = str(last_dt)
            next_cursor = f"{dt_iso}|{str(last_oid)}"
        else:
            next_cursor = str(last_oid)

    # If user requested prev direction we returned results reversed by sort order — API keeps direction semantics:
    if direction == "prev":
        # For previous page requests we reversed the sort order; to keep chronological display, reverse the result docs
        result_docs.reverse()

    return jsonify(
        {
            "collection": cname,
            "data": result_docs,
            "cursor": next_cursor,
            "limit": limit,
            "has_more": has_more,
            "total": total_count,
        }
    )
