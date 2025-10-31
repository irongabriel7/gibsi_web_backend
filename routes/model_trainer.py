from flask import Blueprint, jsonify, current_app, request
import yfinance as yf
import os
from mongo_client import non_flask_db as db

model_trainer_api = Blueprint("model_trainer_api", __name__)

@model_trainer_api.route("/api/stock-check/<string:ticker>", methods=["GET"])
def check_stock_name(ticker):
    """
    Validate if a ticker exists by fetching minimal info from yfinance.
    """
    try:
        ticker_obj = yf.Ticker(ticker)
        info = ticker_obj.info
        # If info is empty dict or missing key, consider invalid
        if not info or 'regularMarketPrice' not in info:
            return jsonify({"success": False, "message": "Invalid stock ticker"}), 404
        return jsonify({"success": True, "message": "Valid stock ticker"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@model_trainer_api.route("/api/stock-data/<string:ticker>", methods=["GET"])
def download_stock_data(ticker):
    """
    Download last 7 days 1-minute interval stock data using yfinance,
    delete old CSV if exists, save new CSV, and return success message.
    """
    try:
        data = yf.download(ticker, period="7d", interval="1m", progress=False, auto_adjust=True)
        if data.empty:
            return jsonify({"success": False, "message": "No data found for ticker"}), 404

        save_folder = os.path.expanduser("/shared/temp/")
        os.makedirs(save_folder, exist_ok=True)

        filename = f"{ticker}_7d_1m.csv"
        save_path = os.path.join(save_folder, filename)

        # Delete existing file if any
        if os.path.exists(save_path):
            os.remove(save_path)
            current_app.logger.info(f"Deleted old CSV for {ticker} at {save_path}")

        data.to_csv(save_path)
        current_app.logger.info(f"Saved stock data CSV for {ticker} at {save_path}")

        return jsonify({"success": True, "message": f"Data downloaded and saved to {save_path}"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    
    
@model_trainer_api.route("/api/control/set_flag", methods=["POST"])
def set_control_flag():
    """
    Set or create control flag document in MongoDB collection.
    Expected JSON payload: { "flagname": str, "flagvalue": value }
    For new_trainer flag, sets status=start, percent=0, with description.
    """
    try:
        data = request.get_json()
        if not data or "flagname" not in data:
            return jsonify({"success": False, "message": "Missing flagname in request"}), 400

        flagname = data["flagname"]
        flagvalue = data.get("flagvalue", None)

        control_col = db["control"]

        # Find existing document by flagname
        doc = control_col.find_one({"flagname": flagname})

        if doc:
            # Update existing document fields
            update_fields = {
                "status": "start",
            }
            if flagname == "new_trainer":
                update_fields["percent"] = 0
                update_fields["description"] = (
                    "Controls new trainer status. Possible statuses: start, stop."
                )
            # Update with flagvalue if provided, else leave as is
            if flagvalue is not None:
                update_fields["flagvalue"] = flagvalue
            control_col.update_one({"flagname": flagname}, {"$set": update_fields})
        else:
            # Create new document
            doc = {
                "flagname": flagname,
                "status": "start",
                "description": "",
                "percent": 0
            }
            if flagname == "new_trainer":
                doc["description"] = (
                    "Controls new trainer status. Possible statuses: start, stop."
                )
            if flagvalue is not None:
                doc["flagvalue"] = flagvalue
            control_col.insert_one(doc)

        return jsonify({"success": True, "message": f"Flag '{flagname}' set successfully."})

    except Exception as e:
        current_app.logger.error(f"Error setting control flag: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500