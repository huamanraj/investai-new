"""
Background job for processing projects (LEGACY - redirects to resumable_processor)

This file is kept for backwards compatibility.
All processing now uses resumable_processor with GPT-based extraction.
"""
import asyncio
from datetime import datetime
from typing import Optional

from app.core.logging import job_logger, console_logger


# Store for tracking running jobs (legacy in-memory tracking)
_running_jobs: dict[str, dict] = {}


async def process_project(project_id: str, source_url: str):
    """
    Legacy function - redirects to resumable processor.
    
    Use process_project_resumable instead for new implementations.
    """
    from .resumable_processor import process_project_resumable
    
    console_logger.warning(
        f"⚠️ Using legacy process_project - consider using process_project_resumable instead"
    )
    
    # Track job in legacy format
    _running_jobs[project_id] = {
        "job_id": project_id[:8],
        "status": "running",
        "started_at": datetime.utcnow().isoformat(),
        "progress": []
    }
    
    try:
        await process_project_resumable(project_id, source_url, resume=False)
        _running_jobs[project_id]["status"] = "completed"
        _running_jobs[project_id]["completed_at"] = datetime.utcnow().isoformat()
    except Exception as e:
        _running_jobs[project_id]["status"] = "failed"
        _running_jobs[project_id]["error"] = str(e)
        raise


def get_job_status(project_id: str) -> Optional[dict]:
    """Get the status of a running or completed job"""
    return _running_jobs.get(project_id)


def get_all_jobs() -> dict:
    """Get all job statuses"""
    return _running_jobs.copy()
