import os
import subprocess
from flask import Blueprint, jsonify, request
from concurrent.futures import ThreadPoolExecutor, as_completed
import psutil
from mongo_client import non_flask_db as db
import shutil

health_api = Blueprint("health_api", __name__)

TEMP_FOLDER = "/shared/temp/"

# Collections
control_collection = db.control

# ===============================
# --- Utility Functions ---
# ===============================
def ensure_notifier_flag():
    """
    Ensure that the 'notifier' flag exists in the control collection.
    If not found, create one with default 'stop' status.
    """
    existing = control_collection.find_one({"flagname": "notifier"})
    if not existing:
        control_collection.insert_one({
            "flagname": "notifier",
            "status": "stop",
            "description": "Controls whether notification system is active"
        })
        return {"flagname": "notifier", "status": "stop", "created": True}
    return existing


def is_notifier_active() -> bool:
    """
    Returns True if notifier flag status == 'start', otherwise False.
    Automatically creates flag if missing.
    """
    flag = ensure_notifier_flag()
    return flag.get("status", "stop") == "start"


def get_cpu_info():
    try:
        return {"cpu_percent": psutil.cpu_percent(interval=1)}
    except Exception as e:
        return {"cpu_percent": None, "error": str(e)}


def get_memory_info():
    try:
        vm = psutil.virtual_memory()
        return {
            "memory_percent": vm.percent,
            "memory_used_gb": round(vm.used / (1024 ** 3), 2),
            "memory_total_gb": round(vm.total / (1024 ** 3), 2)
        }
    except Exception as e:
        return {"memory_percent": None, "error": str(e)}


def get_disk_info():
    try:
        du = psutil.disk_usage("/")
        return {
            "disk_percent": du.percent,
            "disk_used_gb": round(du.used / (1024 ** 3), 2),
            "disk_total_gb": round(du.total / (1024 ** 3), 2)
        }
    except Exception as e:
        return {"disk_percent": None, "error": str(e)}


def get_network_info():
    try:
        net_io = psutil.net_io_counters()
        return {
            "bytes_sent_mb": round(net_io.bytes_sent / (1024 ** 2), 2),
            "bytes_recv_mb": round(net_io.bytes_recv / (1024 ** 2), 2)
        }
    except Exception as e:
        return {"network_error": str(e)}


def get_gpu_info():
    try:
        output = subprocess.check_output(['vcgencmd', 'measure_temp']).decode()
        temp = output.strip().split('=')[-1]
        return {"gpu_temp": temp}
    except Exception:
        return {"gpu_temp": "N/A"}


def get_process_statuses():
    """
    Fetch statuses for all known flagnames from control collection.
    Returns a dict of flagname -> status, including notifier flag.
    """
    status_map = {}
    try:
        flagnames = ["stocks_fetcher", "trade_engine", "model_trainer", "notifier"]
        all_docs = control_collection.find({"flagname": {"$in": flagnames}})

        found_flags = set()
        for doc in all_docs:
            flag = doc.get("flagname")
            found_flags.add(flag)
            if flag == "model_trainer":
                status_map[flag] = {
                    "stocks_fetcher_status": doc.get("stocks_fetcher_status"),
                    "trade_engine_status": doc.get("trade_engine_status"),
                    "model_training_status": doc.get("model_training_status"),
                    "status": doc.get("status"),
                    "percent": doc.get("percent", 0)
                }
            else:
                status_map[flag] = {"status": doc.get("status")}

        # Ensure notifier flag always exists
        if "notifier" not in found_flags:
            ensure_notifier_flag()
            status_map["notifier"] = {"status": "stop"}

    except Exception as e:
        status_map["error"] = str(e)
    return status_map


# ===============================
# --- API Routes ---
# ===============================
@health_api.route("/api/health", methods=['GET'])
def get_health():
    """
    Return system health info + control flag statuses.
    """
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(get_cpu_info): "cpu",
            executor.submit(get_memory_info): "memory",
            executor.submit(get_disk_info): "disk",
            executor.submit(get_network_info): "network",
            executor.submit(get_gpu_info): "gpu"
        }
        results = {}
        for future in as_completed(futures):
            key = futures[future]
            results[key] = future.result()

    # Add process statuses
    results["process_statuses"] = get_process_statuses()

    # Include notifier state directly for convenience
    results["notifier_active"] = is_notifier_active()

    return jsonify(results)


@health_api.route("/api/control/<flagname>/status", methods=['POST'])
def change_process_status(flagname):
    """
    Change the status of a process by flagname.
    Expects JSON body: { "status": "<start|pause|stop|restart>" }
    If flag doesn't exist, creates it automatically.
    Returns updated status message and current percent if applicable.
    """
    valid_flagnames = ["stocks_fetcher", "trade_engine", "model_trainer", "notifier"]
    valid_statuses = ["start", "pause", "stop", "restart"]

    if flagname not in valid_flagnames:
        return jsonify({"error": f"Invalid flagname '{flagname}'. Must be one of {valid_flagnames}"}), 400

    data = request.json
    if not data or "status" not in data:
        return jsonify({"error": "Missing 'status' in request body"}), 400

    status = data["status"]
    if status not in valid_statuses:
        return jsonify({"error": f"Invalid status '{status}'. Must be one of {valid_statuses}"}), 400

    try:
        # Update document status field, upsert if needed
        control_collection.update_one(
            {"flagname": flagname},
            {"$set": {"status": status}},
            upsert=True
        )
        # After update, retrieve document including "percent" field if available
        doc = control_collection.find_one({"flagname": flagname}, {"percent": 1, "_id": 0})
        percent_value = doc.get("percent") if doc else None

        message = f"Status for '{flagname}' updated to '{status}'"

        response = {"message": message}
        if percent_value is not None and flagname == "model_trainer":
            response["percent"] = percent_value

        return jsonify(response)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@health_api.route("/api/control/new_trainer", methods=["GET"])
def get_new_trainer_flag():
    flag = control_collection.find_one({"flagname": "new_trainer"})
    if not flag:
        # Create default flag document
        flag = {
            "flagname": "new_trainer",
            "status": "stop",
            "flagvalue": False,
            "percent": 0,
            "description": "Controls weekend training status and progress"
        }
        control_collection.insert_one(flag)
    # Serialize _id for JSON response
    flag["_id"] = str(flag["_id"])
    return jsonify(flag)


@health_api.route("/api/control/new_trainer", methods=["POST"])
def update_new_trainer_flag():
    data = request.get_json()
    status = data.get("status")
    flagvalue = data.get("flagvalue")
    percent = data.get("percent")

    if status not in ["start", "stop"]:
        return jsonify({"error": "Invalid status value"}), 400
    if not isinstance(flagvalue, bool):
        return jsonify({"error": "flagvalue must be boolean"}), 400
    if percent is not None and (not isinstance(percent, int) or not 0 <= percent <= 100):
        return jsonify({"error": "percent must be int in [0,100]"}), 400

    update_doc = {
        "status": status,
        "flagvalue": flagvalue,
    }
    if percent is not None:
        update_doc["percent"] = percent

    control_collection.update_one(
        {"flagname": "new_trainer"},
        {"$set": update_doc},
        upsert=True
    )
    return jsonify({"success": True, "message": "new_trainer flag updated"})

@health_api.route("/api/temp/check", methods=["GET"])
def check_temp_folder():
    try:
        files = os.listdir(TEMP_FOLDER)
        has_files = len(files) > 0
        return jsonify({"success": True, "has_files": has_files})
    except Exception as e:
        print(f"Error checking temp folder: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500

@health_api.route("/api/temp/clear", methods=["POST"])
def clear_temp_folder():
    try:
        if os.path.exists(TEMP_FOLDER):
            for filename in os.listdir(TEMP_FOLDER):
                file_path = os.path.join(TEMP_FOLDER, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
        return jsonify({"success": True, "message": "Temp folder cleared."})
    except Exception as e:
        print(f"Error clearing temp folder: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500