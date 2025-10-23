# app/logger_config.py
import logging
import sys
from pythonjsonlogger import jsonlogger

def setup_gibsi_logging():
    """Set up JSON logging for GIBSI trading system (K8s & ELK compatible)."""

    # JSON formatter for ELK ingestion
    json_formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s %(filename)s %(lineno)d",
        json_ensure_ascii=False
    )

    # Define all module-level loggers
    loggers = {
        "GIBSI_Auth": "auth",
    }

    configured_loggers = {}

    for logger_name in loggers.keys():
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.INFO)
        logger.propagate = False  # prevent double logs

        # --- Console handler (stdout) only ---
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(json_formatter)
        logger.addHandler(console_handler)

        configured_loggers[logger_name] = logger

    return (
        configured_loggers["GIBSI_Auth"]
    )
