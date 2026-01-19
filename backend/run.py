"""
Custom startup script for InvestAI backend
Fixes Windows asyncio + Playwright compatibility
"""
import sys
import asyncio

# CRITICAL: Set event loop policy BEFORE importing anything else
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
