"""
Custom startup script for InvestAI backend
"""
import uvicorn
import logging

if __name__ == "__main__":
    # Configure logging to exclude polling requests
    from app.core.log_filter import ExcludePollingFilter
    
    # Add filter to uvicorn access logger
    logging.getLogger("uvicorn.access").addFilter(ExcludePollingFilter())
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False, 
        log_level="info"
    )
