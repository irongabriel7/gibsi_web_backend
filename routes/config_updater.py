from flask import Blueprint, request, jsonify
import yaml
from yaml.representer import SafeRepresenter
from yaml.dumper import SafeDumper
import os
import re
import csv

config_update_api = Blueprint("config_update_api", __name__)

class QuotedString(str):
    pass

def quoted_str_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')

def float_representer(dumper, data):
    text = f"{data:.6f}".rstrip('0').rstrip('.')
    if '.' not in text:
        text += '.0'
    return dumper.represent_scalar('tag:yaml.org,2002:float', text)

time_pattern = re.compile(r"^\d{2}:\d{2}$")  # Matches HH:MM format

def quote_strings(obj):
    """Recursively traverse dict/list and wrap HH:MM or textual values in QuotedString."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            obj[k] = quote_strings(v)
        return obj
    elif isinstance(obj, list):
        return [quote_strings(i) for i in obj]
    elif isinstance(obj, str):
        # Detect HH:MM format or string that contains colon but not a full datetime
        if time_pattern.match(obj) or (":" in obj and not re.search(r"\d{2}:\d{2}:\d{2}", obj)):
            return QuotedString(obj)
        # Also quote strings containing letters (non-numeric identifiers)
        try:
            float(obj)
            is_number = True
        except ValueError:
            is_number = False
        if not is_number and any(c.isalpha() for c in obj):
            return QuotedString(obj)
        return obj
    else:
        return obj

class ConfigUpdater:
    def __init__(self, stocks_file_path="/shared/stocks_list.txt", trade_config_path="/shared/trade_config.yaml"):
        self.stocks_file_path = stocks_file_path
        self.trade_config_path = trade_config_path

    def load_stocks_list(self):
        if not os.path.exists(self.stocks_file_path):
            return False, [], f"Stocks file not found: {self.stocks_file_path}"
        with open(self.stocks_file_path, newline='') as f:
            reader = csv.DictReader(f)
            result = [dict(row) for row in reader]
        return True, result, "Stocks list loaded successfully"

    def load_trade_config(self):
        if not os.path.exists(self.trade_config_path):
            return False, {}, f"Trade config file not found: {self.trade_config_path}"
        with open(self.trade_config_path, "r") as f:
            config = yaml.safe_load(f)
        return True, config, "Trade config loaded successfully"

    def update_stocks_list(self, updates):
        if not os.path.exists(self.stocks_file_path):
            return False, f"Stocks file not found: {self.stocks_file_path}"

        with open(self.stocks_file_path, newline='') as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames

        updated_entries = {}
        for update in updates:
            uid = str(update.get("ID"))
            if uid:
                normalized_entry = {key: str(update.get(key, "")) for key in header}
                updated_entries[uid] = normalized_entry

        final_entries = [updated_entries[uid] for uid in updated_entries]

        with open(self.stocks_file_path, "w", newline='') as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            for entry in final_entries:
                writer.writerow(entry)

        return True, "Stocks list updated successfully"

    def update_trade_config(self, updates):
        if not os.path.exists(self.trade_config_path):
            return False, f"Trade config file not found: {self.trade_config_path}"

        with open(self.trade_config_path, "r") as f:
            config = yaml.safe_load(f)

        def recursive_update(d, u):
            for k, v in u.items():
                if isinstance(v, dict) and k in d:
                    recursive_update(d[k], v)
                else:
                    d[k] = v

        recursive_update(config, updates)

        # Apply quoting logic recursively
        config = quote_strings(config)

        yaml.add_representer(QuotedString, quoted_str_representer, Dumper=SafeDumper)
        yaml.add_representer(float, float_representer, Dumper=SafeDumper)

        with open(self.trade_config_path, "w") as f:
            yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False, indent=2)

        return True, "Trade config updated successfully"

updater = ConfigUpdater()

@config_update_api.route("/get_stocks", methods=["GET"])
def get_stocks():
    success, stocks_list, message = updater.load_stocks_list()
    status_code = 200 if success else 404
    return jsonify({"success": success, "data": stocks_list, "message": message}), status_code

@config_update_api.route("/get_trade_config", methods=["GET"])
def get_trade_config():
    success, config, message = updater.load_trade_config()
    status_code = 200 if success else 404
    return jsonify({"success": success, "data": config, "message": message}), status_code

@config_update_api.route("/update_stocks", methods=["POST"])
def update_stocks():
    data = request.get_json()
    updates = data.get("updates", [])
    success, message = updater.update_stocks_list(updates)
    status_code = 200 if success else 400
    return jsonify({"success": success, "message": message}), status_code

@config_update_api.route("/update_trade_config", methods=["POST"])
def update_trade_cfg():
    data = request.get_json()
    updates = data.get("updates", {})
    success, message = updater.update_trade_config(updates)
    status_code = 200 if success else 400
    return jsonify({"success": success, "message": message}), status_code
