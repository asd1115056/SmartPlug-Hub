"""Logging configuration — rich output for app.*, silence for third-party libs."""

import copy

from uvicorn.config import LOGGING_CONFIG


def build_log_config(debug: bool = False) -> dict:
    cfg = copy.deepcopy(LOGGING_CONFIG)

    cfg["handlers"]["rich"] = {
        "()": "rich.logging.RichHandler",
        "rich_tracebacks": True,
        "show_path": False,
        "markup": False,
    }

    cfg["loggers"]["app"] = {
        "handlers": ["rich"],
        "level": "DEBUG" if debug else "INFO",
        "propagate": False,
    }

    for lib in ("kasa", "miio", "sqlalchemy", "httpx", "httpcore"):
        cfg["loggers"][lib] = {"level": "WARNING", "propagate": False}

    cfg["loggers"]["uvicorn.access"] = {"handlers": ["access"], "level": "INFO", "propagate": False}

    return cfg
