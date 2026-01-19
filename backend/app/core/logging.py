"""
Logging configuration for the application
Logs are saved to local logs folder (not in DB)
"""
import logging
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


# Create logs directory
LOGS_DIR = Path(__file__).parent.parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)


class JSONFileLogger:
    """Logger that writes JSON logs to files in the logs folder"""
    
    def __init__(self, log_name: str):
        self.log_name = log_name
        self.log_file = LOGS_DIR / f"{log_name}.jsonl"
    
    def log(
        self, 
        level: str, 
        message: str, 
        data: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
        job_id: Optional[str] = None
    ):
        """Write a log entry to the file"""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "message": message,
            "log_name": self.log_name,
        }
        
        if project_id:
            log_entry["project_id"] = project_id
        if job_id:
            log_entry["job_id"] = job_id
        if data:
            log_entry["data"] = data
        
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    
    def info(self, message: str, **kwargs):
        self.log("INFO", message, **kwargs)
    
    def error(self, message: str, **kwargs):
        self.log("ERROR", message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        self.log("WARNING", message, **kwargs)
    
    def debug(self, message: str, **kwargs):
        self.log("DEBUG", message, **kwargs)


# Pre-configured loggers for different components
scraper_logger = JSONFileLogger("scraper")
api_logger = JSONFileLogger("api")
job_logger = JSONFileLogger("jobs")
cloudinary_logger = JSONFileLogger("cloudinary")


def setup_console_logging(level: str = "INFO"):
    """Setup console logging for the application"""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    return logging.getLogger("investai")


# Console logger
console_logger = setup_console_logging()
