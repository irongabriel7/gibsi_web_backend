from flask import Flask, jsonify, request
from flask_cors import CORS
import yfinance as yf
from datetime import datetime, timedelta
import pandas as pd
import pytz
from mongo_client import mongo
from routes.top_gainers import top_gainers_api
from routes.live_gainers import live_gainers_api
from routes.display_chart import display_chart_api
from routes.data_handler import data_handler_api
from routes.mongo_export import mongo_export
from routes.system_check import health_api
from routes.stock_analyzer import analyzer_api
from routes.auth import init_auth
from routes.notifier import notifier,init_notifier_jwt
from stock_utility import StockUtility
import yaml
import os

stock_util = StockUtility()


with open("/shared/mongo.yaml", "r") as f:
    config = yaml.safe_load(f)
    
MONGODB = config["MONGODB"]

# Allow environment override (for Docker / K8s)
MONGO_URI = os.getenv("MONGO_URI", MONGODB['mongo_uri'])
DB_NAME = os.getenv("DB_NAME", MONGODB['db_name'])


app = Flask(__name__)
app.config["MONGO_URI"] = MONGO_URI + DB_NAME
mongo.init_app(app)
init_auth(app)
app.register_blueprint(top_gainers_api)
app.register_blueprint(live_gainers_api)
app.register_blueprint(display_chart_api)
app.register_blueprint(data_handler_api)
app.register_blueprint(mongo_export)
app.register_blueprint(health_api)
app.register_blueprint(analyzer_api)
init_notifier_jwt(app)
app.register_blueprint(notifier)
CORS(app)

def format_datetime(dt, fmt):
    if isinstance(dt, str):
        return dt
    return dt.strftime(fmt)

@app.route('/api/stocks_list', methods=['GET'])
def get_stocks_list():
    """
    Refactored Flask route that uses the utility function
    """
    return stock_util.get_stock_symbols_json()

@app.route('/api/market_update', methods=['GET'])
def get_market_update():
    ist = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(ist)
    is_open = stock_util.is_market_live(now_ist)
    last_trading_day = stock_util.get_last_trading_day(now_ist)
    next_open_time = stock_util.get_next_trading_day(now_ist)
    return jsonify({
        "is_market_open": is_open,
        "server_time_ist": now_ist.strftime("%Y-%m-%d %H:%M:%S"),
        "next_market_open": format_datetime(next_open_time, "%Y-%m-%d %H:%M:%S") if next_open_time else None,
        "last_trading_day": format_datetime(last_trading_day, "%Y-%m-%d") if last_trading_day else None
    })

@app.route('/api/stock', methods=['GET'])
def get_stock_data():
    symbol = request.args.get('symbol')
    interval = request.args.get('interval', '1d')
    start = request.args.get('start')
    end = request.args.get('end')
    period = request.args.get('period')

    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400

    try:
        stock = yf.Ticker(symbol)

        if start and end:
            # Handle same-day case by adding 1 day
            if start == end:
                end_dt = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
                end = end_dt.strftime("%Y-%m-%d")

            data = stock.history(
                start=start,
                end=end,
                interval=interval,
                auto_adjust=False
            )
        elif period:
            data = stock.history(
                period=period,
                interval=interval,
                auto_adjust=False
            )
        else:
            return jsonify({'error': 'Either start/end or period must be provided'}), 400

        if data.empty:
            return jsonify({'error': 'No data found for given parameters'}), 404

        if not isinstance(data.index, pd.DatetimeIndex):
            data.index = pd.to_datetime(data.index, errors='coerce')

        data.reset_index(inplace=True)

        if "Date" not in data.columns:
            return jsonify({'error': 'No date information in stock data'}), 500

        result = [
            {
                "Date": row["Date"].strftime("%Y-%m-%d"),
                "Open": round(row["Open"], 2),
                "High": round(row["High"], 2),
                "Low": round(row["Low"], 2),
                "Close": round(row["Close"], 2),
                "Volume": int(row["Volume"])
            }
            for _, row in data.iterrows()
        ]

        return jsonify(result)

    except Exception as e:
        print("Error fetching stock data:", str(e))
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/test_alive', methods=['GET'])
def test_alive():
    """
    Simple API to check if server is alive.
    """
    return jsonify({'status': 'gibsi_alive'}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
