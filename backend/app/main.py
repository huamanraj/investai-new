"""
InvestAI Backend - FastAPI Application
PDF Scraping and Processing for BSE India Annual Reports
"""
# CRITICAL: Fix Windows asyncio + Playwright compatibility BEFORE any other imports
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import console_logger, api_logger
from app.api import projects_router
from app.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    console_logger.info(f"🚀 Starting {settings.APP_NAME} in {settings.ENV} mode")
    api_logger.info(f"Application started", data={"env": settings.ENV})
    
    # Initialize database
    try:
        await init_db()
        console_logger.info("✅ Database initialized (tables created/verified)")
    except Exception as e:
        console_logger.error(f"❌ Database initialization failed: {e}")
        
    yield
    console_logger.info(f"👋 Shutting down {settings.APP_NAME}")
    api_logger.info("Application shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    description="AI-powered financial document analysis system",
    version="0.1.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(projects_router, prefix="/api")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": settings.APP_NAME,
        "version": "0.1.0",
        "status": "running",
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}
