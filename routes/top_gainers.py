import os
from flask import Blueprint, jsonify
from stock_utility import StockUtility
from concurrent.futures import ThreadPoolExecutor, as_completed
from stock_utility import StockUtility

top_gainers_api = Blueprint("top_gainers_api", __name__)
stock_util = StockUtility("/shared/stocks_list.txt")


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



def extract_percent_amount(profit_str):
    if not profit_str:
        return (None, None)
    try:
        percent_str = profit_str.split('%')[0]
        amount_str = profit_str.split('(')[-1].replace(')', '')
        return (float(percent_str), amount_str)
    except:
        return (None, None)


def fetch_stock_profit(stock_id, ticker):
    try:
        profit_7d = stock_util.get_periodic_profit(stock_id, ticker, days=7)
        profit_30d = stock_util.get_periodic_profit(stock_id, ticker, days=30)

        if not profit_7d and not profit_30d:
            return None

        percent_7d, amount_7d = extract_percent_amount(profit_7d)
        percent_30d, amount_30d = extract_percent_amount(profit_30d)

        return {
            "stock": ticker.replace(".NS", ""),
            "7d_percent": percent_7d,
            "7d_profit": amount_7d,
            "30d_percent": percent_30d,
            "30d_profit": amount_30d
        }
    except Exception as e:
        print(f"[❌] Error fetching {ticker}: {e}")
        return None


@top_gainers_api.route("/api/top_gainers", methods=['GET'])
def get_top_gainers():
    stocks = load_stocks_from_file()
    results = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_stock = {
            executor.submit(fetch_stock_profit, stock_id, ticker): (stock_id, ticker)
            for stock_id, ticker in stocks.items()
        }

        for future in as_completed(future_to_stock):
            data = future.result()
            if data:
                results.append(data)

    sorted_data = sorted(
        results,
        key=lambda x: (x['7d_percent'] if x['7d_percent'] is not None else -999),
        reverse=True
    )
    return jsonify(sorted_data)
