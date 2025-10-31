import pandas as pd
from flask import jsonify
import os
import time
import datetime
import pytz
import socket
from mongo_client import non_flask_db as db

IST = pytz.timezone("Asia/Kolkata")
UTC = pytz.utc
os_holiday_file = os.getenv("HOLIDAY_FILE", "/shared/holiday.txt")
os_stocks_file = os.getenv("STOCKS_LIST_FILE", "/shared/stocks_list.txt")

class StockUtility:
    def __init__(self, stock_list_file=None):
        self.ist = pytz.timezone("Asia/Kolkata")
        self.stock_list_file = stock_list_file or os_stocks_file
        self.stock_df = self.load_stock_list()

    def get_market_start_utc(self, dt):
        # Convert any datetime to start of the trading day in UTC
        return datetime.datetime.combine(dt.date(), datetime.time(3, 45))
    
    def is_market_closed(self, date, holiday_file=os_holiday_file):
        # 1. Check weekend (Saturday=5, Sunday=6)
        if date.weekday() >= 5:
            return True

        # 2. Check holidays
        try:
            with open(holiday_file, "r") as f:
                holidays = {line.strip() for line in f if line.strip()}
                if date.strftime("%Y-%m-%d") in holidays:
                    return True
        except FileNotFoundError:
            print(f"[⚠️] Holiday file not found: {holiday_file}")

        # Market is open
        return False

    def get_last_trading_day(self, reference_date):
        
        #if reference_date:
        #    reference_date -= datetime.timedelta(days=1)

        while self.is_market_closed(reference_date):
            reference_date -= datetime.timedelta(days=1)
        return reference_date

    def is_market_day(self, date, holiday_file=os_holiday_file):
        # Check if weekend
        if date.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
            return False

        # Check against holiday list
        try:
            with open(holiday_file, "r") as f:
                holidays = {line.strip() for line in f if line.strip()}
                if date.strftime("%Y-%m-%d") in holidays:
                    return False
        except FileNotFoundError:
            print(f"[⚠️] Holiday file not found: {holiday_file}")
        
        return True
    
    def is_market_live(self, date, holiday_file=os_holiday_file):
        """
        Checks if the market is live:
        - Not a weekend
        - Not a holiday (from file)
        - Between 9:15 AM and 3:30 PM IST (inclusive)
        """
        ist = pytz.timezone("Asia/Kolkata")
        if date is None:
            now_ist = datetime.datetime.now(ist)
            
        else:
            if date.tzinfo is None:
                date = ist.localize(date)
            now_ist = date.astimezone(ist)

        today = now_ist.date()

        # Weekend
        if today.weekday() >= 5:
            return False

        # Holiday
        try:
            with open(holiday_file, "r") as f:
                holidays = {line.strip() for line in f if line.strip()}
                if today.strftime("%Y-%m-%d") in holidays:
                    return False
        except FileNotFoundError:
            print(f"[⚠️] Holiday file not found: {holiday_file}")

        # Time check
        market_start = datetime.time(9, 15)
        market_end = datetime.time(15, 30)

        if market_start <= now_ist.time() <= market_end:
            return True

        return False

    
        
    def get_next_trading_day(self, current_date):
        ist = pytz.timezone("Asia/Kolkata")
        now = datetime.datetime.now(ist)
        market_open_time = datetime.time(9, 15)
        market_close_time = datetime.time(15, 30)
        # If today is a trading day,
        if self.is_market_day(now.date()):
            # If now is BEFORE market open today
            if now.time() < market_open_time:
                # next open is today at 9:15
                return ist.localize(datetime.datetime.combine(now.date(), market_open_time))
            # If now is DURING trading hours
            elif now.time() < market_close_time:
                # (if you want: still return today 9:15, or optionally None because market is open)
                return ist.localize(datetime.datetime.combine(now.date(), market_open_time))
            # If now is after market close
            # Will fall through to next day logic

        # Otherwise, find next valid trading day
        next_day = now.date() + datetime.timedelta(days=1)
        while not self.is_market_day(next_day):
            next_day += datetime.timedelta(days=1)
        return ist.localize(datetime.datetime.combine(next_day, market_open_time))

    def get_live_profit_status(self, stock_id, ticker):
        try:
            stock_id = int(stock_id)

            # Get latest record
            last_row = db["intraday"].find_one(
                {"stock_id": stock_id, "ticker": ticker},
                sort=[("Datetime", -1)]
            )
            if not last_row:
                return None

            # Ensure datetime is a datetime object
            dt_utc = last_row["Datetime"]
            if isinstance(dt_utc, str):
                dt_utc = datetime.datetime.fromisoformat(dt_utc)

            # Query first record of the same trading day (IST day boundaries)
            dt_ist = dt_utc.astimezone(IST).date()
            day_start_utc = IST.localize(datetime.datetime.combine(dt_ist, datetime.time.min)).astimezone(UTC)
            day_end_utc = IST.localize(datetime.datetime.combine(dt_ist, datetime.time.max)).astimezone(UTC)

            first_row = db["intraday"].find_one(
                {"stock_id": stock_id, "ticker": ticker,
                "Datetime": {"$gte": day_start_utc, "$lte": day_end_utc}},
                sort=[("Datetime", 1)]
            )
            if not first_row:
                return None

            open_price = first_row.get("Close") or first_row.get("Open")
            last_price, last_volume = last_row.get("Close"), last_row.get("Volume")
            if not open_price or not last_price:
                return None

            profit_amount = round(last_price - open_price, 2)
            profit_percent = round((profit_amount / open_price) * 100, 2)

            return {
                "price": round(last_price, 2),
                "volume": int(last_volume or 0),
                "change": profit_percent,
                "profit": profit_amount
            }

        except Exception as e:
            print(f"[❌] Error in get_live_profit_status: {e}")
            return None
        
    def get_intraday_profit(self, stock_id, ticker, target_datetime):
        """
        Calculate intraday profit % and value for a given stock and date.
        
        Parameters:
            stock_id (int): Stock's ID.
            ticker (str): Stock ticker symbol.
            target_datetime (str): Date in format 'YYYY-MM-DD' (IST timezone).
        
        Returns:
            dict: {
                "price": float,
                "volume": int,
                "intraday_profit_percent": float,
                "intraday_profit_value": float
            }
        """
        try:
            stock_id_int = int(stock_id)

            # Convert target date to UTC range for Mongo query
            date_obj = datetime.datetime.strptime(target_datetime, "%Y-%m-%d")
            start_ist = IST.localize(datetime.datetime.combine(date_obj, datetime.time.min))
            end_ist = IST.localize(datetime.datetime.combine(date_obj, datetime.time.max))
            start_utc = start_ist.astimezone(UTC)
            end_utc = end_ist.astimezone(UTC)

            # Fetch intraday data for the date
            intraday_data = list(db["intraday"].find(
                {
                    "stock_id": stock_id_int,
                    "ticker": ticker,
                    "Datetime": {"$gte": start_utc, "$lte": end_utc}
                }
            ).sort("Datetime", 1))

            if not intraday_data:
                return {
                    "price": None,
                    "volume": None,
                    "intraday_profit_percent": None,
                    "intraday_profit_value": None
                }

            # First and last record of the day
            first_row = intraday_data[0]
            last_row = intraday_data[-1]

            first_price = first_row.get("Close") or first_row.get("close")
            last_price = last_row.get("Close") or last_row.get("close")
            last_volume = last_row.get("Volume") or last_row.get("volume")

            if first_price is None or last_price is None:
                return {
                    "price": None,
                    "volume": None,
                    "intraday_profit_percent": None,
                    "intraday_profit_value": None
                }

            # Profit % and value
            profit_percent = round(((last_price - first_price) / first_price) * 100, 2)
            profit_amount = round(last_price - first_price, 2)

            return {
                "price": round(last_price, 2),
                "volume": int(last_volume) if last_volume is not None else None,
                "intraday_profit_percent": profit_percent,
                "intraday_profit_value": profit_amount
            }

        except Exception as e:
            return {
                "error": str(e)
            }

    def get_weekly_profit_status(self, stock_id, ticker):
        return self.get_periodic_profit(stock_id, ticker, days=7)

    def get_monthly_profit_status(self, stock_id, ticker):
        return self.get_periodic_profit(stock_id, ticker, days=30)

    def get_periodic_profit(self, stock_id, ticker, days=30):
        try:
            stock_id_int = int(stock_id)

            # Get all historical data sorted by date descending
            cursor = db["historical"].find(
                {"stock_id": stock_id_int, "ticker": ticker}
            ).sort("Datetime", -1).limit(days)

            df = pd.DataFrame(list(cursor))

            if df.empty or 'Open' not in df.columns or 'Close' not in df.columns:
                print(f"[❌] Not enough historical data for {ticker}")
                return None

            df['Datetime'] = pd.to_datetime(df['Datetime'])
            df.dropna(subset=['Open', 'Close'], inplace=True)

            # Ensure we have enough data
            if len(df) < 2:
                return None

            # Sort back to ascending order (oldest to newest)
            df = df.sort_values("Datetime")

            open_price = df.iloc[0]['Open']
            close_price = df.iloc[-1]['Close']

            if open_price is None or close_price is None or open_price == 0:
                return None

            profit_amount = round(close_price - open_price, 2)
            profit_percent = round(((close_price - open_price) / open_price) * 100, 2)

            return f"{profit_percent:.2f}% ({'+' if profit_amount >= 0 else ''}{profit_amount:.2f})"

        except Exception as e:
            print(f"[❌] Error computing periodic profit: {e}")
            return None

    def get_intraday_summary(self, stock_id, ticker, date=None):
        try:
            if date is None:
                now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
                current_date = now.date()
                current_time = now.time()
                check_date = current_date if current_time >= datetime.time(15, 30) else current_date - datetime.timedelta(days=1)
                date = self.get_last_trading_day(check_date)

            start_dt = datetime.datetime.combine(date, datetime.time(0, 0))
            end_dt = datetime.datetime.combine(date, datetime.time(23, 59))

            query = {
                "stock_id": stock_id,
                "ticker": ticker,
                "Datetime": {"$gte": start_dt, "$lte": end_dt}
            }
            df = pd.DataFrame(list(db["intraday"].find(query)))

            if df.empty:
                print(f"[⚠️] No intraday data for {ticker} on {date}")
                return None

            required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            for col in required_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df.dropna(subset=required_cols, inplace=True)

            if df.empty:
                return None

            summary = {
                "Open": round(df.iloc[0]['Open'], 2),
                "High": round(df['High'].max(), 2),
                "Low": round(df['Low'].min(), 2),
                "Close": round(df.iloc[-1]['Close'], 2),
                "Adj Close": round(df.iloc[-1]['Close'], 2),
                "Volume": int(df['Volume'].sum())
            }
            return summary
        except Exception as e:
            print(f"[❌] Error computing intraday summary: {e}")
            return None

    def load_stock_list_as_symbols(self, file_path="/shared/stocks_list.txt"):
        """
        Load stock symbols (ticker) from stocks_list.txt and return as a list of symbols.
        Assumes ticker is in the 3rd column (index 2), based on previous info,
        skipping header lines and ignoring empty lines.
        """
        try:
            with open(file_path, "r") as f:
                # Skip lines starting with 'id' (case insensitive) and empty lines
                lines = [line.strip() for line in f if line.strip() and not line.lower().startswith("id")]
                # Extract 3rd column (ticker) if line contains at least 3 columns
                symbols = [line.split(",")[2].strip() for line in lines if len(line.split(",")) >= 3]
            return symbols
        except FileNotFoundError:
            raise FileNotFoundError("stocks_list.txt not found")
        except Exception as e:
            raise Exception(f"Error loading stock list: {str(e)}")

    def load_stock_list_as_dataframe(self):
        """
        Load stock list from stocks_list.txt and return as a pandas DataFrame.
        Properly reads all columns based on CSV header.
        """
        
        try:
            # Use pandas CSV reader with proper NA handling for 'None' string
            df = pd.read_csv(os_stocks_file, na_values=['None', 'NULL', 'null', ''])
            
            # Optionally convert 'ID' column to integer
            if 'ID' in df.columns:
                df['ID'] = pd.to_numeric(df['ID'], errors='coerce').fillna(0).astype(int)
            
            # Parse datetime columns if present
            datetime_cols = ['End Datetime', 'Trained Datetime']
            for col in datetime_cols:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors='coerce')
            
            return df
        except FileNotFoundError:
            raise FileNotFoundError("stocks_list.txt not found")
        except Exception as e:
            raise Exception(f"Error loading stock list: {str(e)}")

    def get_stock_symbols_json(self):
        """
        Get stock symbols in JSON format (for Flask routes)
        """
        try:
            symbols = self.load_stock_list_as_symbols()
            return jsonify(symbols)
        except FileNotFoundError:
            return jsonify({'error': 'stocks_list.txt not found'}), 404
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # Alternative function names for different use cases
    def load_stock_list(self):
        """Alias for load_stock_list_as_dataframe for backward compatibility"""
        return self.load_stock_list_as_dataframe()

    def get_stock_symbols(self):
        """Alias for load_stock_list_as_symbols for simple symbol list"""
        return self.load_stock_list_as_symbols()
    
    def is_internet_connected(self, host="8.8.8.8", port=53, timeout=3):
        """
        Checks internet connectivity by attempting to connect to Google DNS.
        Returns True if online, False if offline.
        """
        try:
            socket.setdefaulttimeout(timeout)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
            return True
        except Exception:
            return False
    def mongo_retry_operation(self, operation_fn, description="", retries=999999, delay=10):
        """
        A robust wrapper to retry MongoDB operations on connection failures.
        Keeps retrying until success or until retries run out.
        """
        attempt = 0
        while attempt < retries:
            try:
                return operation_fn()  # Call the actual DB operation
            except Exception as e:
                if "Connection" in str(e) or "network" in str(e) or "timeout" in str(e):
                    print(f"MongoDB Connection Issue during '{description}'. Retrying in {delay}s... Error: {e}")
                    #stk_fetcher_logger.warning(f"MongoDB Connection Issue during '{description}'. Retrying in {delay}s... Error: {e}")
                else:
                    #stk_fetcher_logger.error(f"MongoDB Operation Error during '{description}': {e}")
                    return None  # Non-retryable error
            attempt += 1
            time.sleep(delay)
        #stk_fetcher_logger.error(f"Failed '{description}' after {retries} attempts.")
        return None

if __name__ == "__main__":
    util = StockUtility(os_stocks_file)
    for _, row in util.stock_df.iterrows():
        stock_id = row['ID']
        ticker = row['Ticker']
        print(ticker)
        print("Live Profit:", util.get_live_profit_status(stock_id, ticker))
        print("Last 7 Days Profit:", util.get_weekly_profit_status(stock_id, ticker))
        print("Last 30 Days Profit:", util.get_periodic_profit(stock_id, ticker))
