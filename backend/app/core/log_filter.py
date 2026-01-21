"""
Custom logging filter to exclude polling/status check requests
"""
import logging


class ExcludePollingFilter(logging.Filter):
    """Filter out polling/status check requests from access logs"""
    
    def filter(self, record: logging.LogRecord) -> bool:
        # Exclude status polling requests
        if hasattr(record, 'args') and record.args:
            # Check if this is an access log with request path
            if len(record.args) >= 3:
                request_path = str(record.args[2]) if len(record.args) > 2 else ""
                
                # Filter out these endpoints
                excluded_patterns = [
                    "/api/projects/",
                    "/status",
                    "/api/chats"
                ]
                
                # Only exclude GET requests to status endpoints
                if any(pattern in request_path for pattern in excluded_patterns):
                    if "GET" in str(record.args):
                        return False
        
        return True
