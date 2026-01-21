"""
Projects API Router
"""
import asyncio
import json
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db, Project, CompanySnapshot, ProcessingJob
from app.schemas import (
    ProjectCreate, ProjectResponse, ProjectListResponse,
    ProjectStatusResponse, DocumentResponse, ProjectDetailResponse
)
from app.services import extract_company_name
from app.services.progress_tracker import progress_tracker
from app.jobs import process_project_resumable, cancel_job
from app.core.logging import api_logger, console_logger

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_data: ProjectCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """Create a new project from a BSE India URL with resumable processing"""
    try:
        company_name = extract_company_name(project_data.source_url)
        console_logger.info(f"📝 Creating project for: {company_name}")
        
        # Check if exists
        try:
            existing = await db.execute(
                select(Project).where(Project.source_url == project_data.source_url)
            )
            if existing.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Project with this URL already exists")
        except HTTPException:
            raise  # Re-raise HTTP exceptions
        except Exception as db_error:
            console_logger.error(f"❌ Database error checking existing project: {db_error}")
            raise HTTPException(
                status_code=503,
                detail="Database connection error. Please try again in a moment."
            )
        
        # Create project
        try:
            project = Project(
                company_name=company_name,
                source_url=project_data.source_url,
                exchange="BSE",
                status="pending"
            )
            db.add(project)
            await db.commit()
            await db.refresh(project)
        except Exception as db_error:
            console_logger.error(f"❌ Database error creating project: {db_error}")
            await db.rollback()
            raise HTTPException(
                status_code=503,
                detail="Failed to create project due to database error. Please try again."
            )
        
        # Use resumable processor
        background_tasks.add_task(
            process_project_resumable, 
            str(project.id), 
            project_data.source_url,
            False  # Not a resume
        )
        console_logger.info(f"✅ Project created: {project.id}")
        return project
    
    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        console_logger.error(f"❌ Unexpected error creating project: {e}")
        api_logger.error("Project creation failed", data={"error": str(e)})
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create project: {str(e)}"
        )


@router.get("", response_model=ProjectListResponse)
async def list_projects(skip: int = 0, limit: int = 20, db: AsyncSession = Depends(get_db)):
    """List all projects"""
    count = await db.execute(select(func.count(Project.id)))
    result = await db.execute(
        select(Project).order_by(Project.created_at.desc()).offset(skip).limit(limit)
    )
    return ProjectListResponse(projects=result.scalars().all(), total=count.scalar())


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(project_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get project details with documents"""
    result = await db.execute(
        select(Project).options(selectinload(Project.documents)).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    job_result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.project_id == project_id)
        .order_by(ProcessingJob.updated_at.desc())
    )
    latest_job = job_result.scalar_one_or_none()
    job_status = None
    if latest_job:
        job_status = {
            "job_id": latest_job.job_id,
            "status": latest_job.status,
            "current_step": latest_job.current_step,
            "current_step_index": latest_job.current_step_index,
            "total_steps": latest_job.total_steps,
            "failed_step": latest_job.failed_step,
            "error_message": latest_job.error_message,
            "can_resume": bool(latest_job.can_resume),
            "updated_at": latest_job.updated_at.isoformat() if latest_job.updated_at else None,
        }
    
    return ProjectDetailResponse(
        project=ProjectResponse.model_validate(project),
        documents=[DocumentResponse.model_validate(d) for d in project.documents],
        job_status=job_status
    )


@router.get("/{project_id}/status", response_model=ProjectStatusResponse)
async def get_project_status(project_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get project status"""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Prefer DB-backed job status (resumable processor) over in-memory legacy status.
    job_result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.project_id == project_id)
        .order_by(ProcessingJob.updated_at.desc())
    )
    latest_job = job_result.scalar_one_or_none()

    job_status = None
    if latest_job:
        job_status = {
            "job_id": latest_job.job_id,
            "status": latest_job.status,
            "current_step": latest_job.current_step,
            "current_step_index": latest_job.current_step_index,
            "total_steps": latest_job.total_steps,
            "failed_step": latest_job.failed_step,
            "error_message": latest_job.error_message,
            "can_resume": bool(latest_job.can_resume),
            "updated_at": latest_job.updated_at.isoformat() if latest_job.updated_at else None,
        }

    # If job has a terminal state but project.status is stale (e.g. still "scraping"),
    # reflect the terminal state in the response (and best-effort persist it).
    effective_project = ProjectResponse.model_validate(project)
    if latest_job and latest_job.status in {"failed", "cancelled", "completed"}:
        desired_status = (
            "failed" if latest_job.status in {"failed", "cancelled"} else "completed"
        )
        desired_error = (
            latest_job.error_message
            if latest_job.status in {"failed", "cancelled"}
            else None
        )

        if effective_project.status != desired_status or effective_project.error_message != desired_error:
            effective_project = effective_project.model_copy(
                update={"status": desired_status, "error_message": desired_error}
            )
            try:
                project.status = desired_status
                project.error_message = desired_error
                await db.commit()
            except Exception:
                await db.rollback()

    return ProjectStatusResponse(project=effective_project, job_status=job_status)


@router.get("/{project_id}/snapshot")
async def get_project_snapshot(project_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Get company snapshot for a project.
    Returns comprehensive company overview with financials, charts, and analysis.
    """
    # Verify project exists
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Get snapshot
    result = await db.execute(
        select(CompanySnapshot).where(CompanySnapshot.project_id == project_id)
    )
    snapshot = result.scalar_one_or_none()
    
    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail="Snapshot not yet generated. Please wait for project processing to complete."
        )
    
    return {
        "project_id": str(project_id),
        "company_name": project.company_name,
        "snapshot": snapshot.snapshot_data,
        "generated_at": snapshot.generated_at.isoformat() if snapshot.generated_at else None,
        "updated_at": snapshot.updated_at.isoformat(),
        "version": snapshot.version
    }


@router.post("/{project_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_project_job(project_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Cancel a running job for a project.
    The job can be resumed later from the last successful step.
    """
    # Verify project exists
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Cancel the job
    cancelled = await cancel_job(str(project_id))
    
    if not cancelled:
        raise HTTPException(
            status_code=404, 
            detail="No active job found for this project"
        )
    
    console_logger.info(f"🛑 Job cancelled for project: {project_id}")
    api_logger.info("Job cancelled", data={"project_id": str(project_id)})
    
    return {
        "message": "Job cancelled successfully",
        "project_id": str(project_id),
        "can_resume": True
    }


@router.post("/{project_id}/resume", status_code=status.HTTP_200_OK)
async def resume_project_job(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Resume a failed or cancelled job from the last successful step.
    If no job exists (e.g., background task crashed before creating job), starts a fresh job.
    Also handles stale "running" jobs that were stopped unexpectedly.
    """
    from datetime import datetime, timedelta
    
    # Verify project exists
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Validate source_url exists
    if not project.source_url:
        raise HTTPException(
            status_code=400,
            detail="Project source URL is missing. Cannot resume job."
        )
    
    # If project is already completed, don't allow resume
    if project.status == "completed":
        raise HTTPException(
            status_code=400,
            detail="Project is already completed. No resume needed."
        )
    
    # Check if there's any job at all for this project
    result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.project_id == project_id)
        .order_by(ProcessingJob.updated_at.desc())
    )
    any_job = result.scalar_one_or_none()
    
    # If no job exists, start a fresh job (background task may have crashed before creating job)
    if not any_job:
        console_logger.info(f"🆕 No job found for project {project_id}, starting fresh job")
        api_logger.info("Starting fresh job (no previous job found)", data={
            "project_id": str(project_id),
            "source_url": project.source_url
        })
        
        # Reset project status to pending
        project.status = "pending"
        project.error_message = None
        await db.commit()
        
        background_tasks.add_task(
            process_project_resumable,
            str(project_id),
            project.source_url,
            False  # Fresh start, not resume
        )
        
        return {
            "message": "Started fresh processing job (no previous job found)",
            "project_id": str(project_id),
            "resuming_from_step": None,
            "failed_step": None
        }
    
    # Check if job is marked as "running" but is actually stale
    if any_job.status == "running":
        # Calculate staleness threshold (5 minutes)
        stale_threshold = datetime.utcnow() - timedelta(minutes=5)
        
        if any_job.updated_at and any_job.updated_at < stale_threshold:
            # Job is stale - it was stuck/crashed unexpectedly
            # Reset it to "failed" status so it can be resumed
            console_logger.warning(
                f"⚠️ Job {any_job.job_id} appears stale (last update: {any_job.updated_at}). "
                f"Resetting to failed status for resume."
            )
            api_logger.warning("Stale running job detected, resetting to failed", data={
                "project_id": str(project_id),
                "job_id": any_job.job_id,
                "last_updated": any_job.updated_at.isoformat() if any_job.updated_at else None,
                "current_step": any_job.current_step
            })
            
            # Update job to failed status
            any_job.status = "failed"
            any_job.failed_step = any_job.current_step
            any_job.error_message = f"Job was stuck/crashed at step: {any_job.current_step}"
            any_job.can_resume = 1
            any_job.updated_at = datetime.utcnow()
            
            # Update project status too
            project.status = "failed"
            project.error_message = f"Job crashed at {any_job.current_step}"
            
            await db.commit()
            await db.refresh(any_job)
        else:
            # Job is still actively running (updated recently)
            raise HTTPException(
                status_code=400,
                detail=f"Job is currently running (last updated: {any_job.updated_at.isoformat() if any_job.updated_at else 'unknown'}). Cancel it first if you want to restart."
            )
    
    # Check if there's a resumable job (failed or cancelled)
    if any_job.status in ["failed", "cancelled"] and any_job.can_resume:
        console_logger.info(f"▶️ Resuming job for project: {project_id} from step: {any_job.last_successful_step}")
        api_logger.info("Job resumed", data={
            "project_id": str(project_id),
            "last_step": any_job.last_successful_step,
            "failed_step": any_job.failed_step,
            "source_url": project.source_url
        })
        
        # Reset project status for resume
        project.status = "pending"
        project.error_message = None
        
        # Reset job status to running before starting
        any_job.status = "running"
        any_job.error_message = None
        any_job.failed_step = None
        any_job.updated_at = datetime.utcnow()
        await db.commit()
        
        # Start resume in background
        background_tasks.add_task(
            process_project_resumable,
            str(project_id),
            project.source_url,
            True  # Resume mode
        )
        
        return {
            "message": "Job resumed successfully",
            "project_id": str(project_id),
            "resuming_from_step": any_job.last_successful_step,
            "failed_step": any_job.failed_step
        }
    
    # Job exists but can't be resumed (maybe completed or can_resume=0)
    raise HTTPException(
        status_code=400,
        detail=f"Job exists with status '{any_job.status}' but cannot be resumed. Status: {any_job.status}, can_resume: {any_job.can_resume}"
    )


@router.get("/{project_id}/progress-stream")
async def stream_project_progress(project_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Stream real-time progress updates for a project's processing job via SSE.
    
    Updates include:
    - Validating link
    - Scraping page
    - Found PDFs
    - Downloading PDFs
    - Uploading to cloud
    - Extracting data
    - Creating embeddings
    - Generating snapshot
    - Completion status
    
    The stream automatically closes when job completes, fails, or is cancelled.
    """
    # Verify project exists
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Get latest job
    result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.project_id == project_id)
        .order_by(ProcessingJob.updated_at.desc())
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail="No processing job found for this project"
        )
    
    job_id = job.job_id
    
    async def generate_progress_stream():
        """Generate SSE stream of progress events"""
        # Subscribe to progress updates
        queue = await progress_tracker.subscribe(job_id)
        
        try:
            console_logger.info(f"📡 Client subscribed to job {job_id} progress stream")
            
            # Check if job is already finished
            finished_status = progress_tracker.is_job_finished(job_id)
            
            # Send initial connection event with job status
            yield f"data: {json.dumps({'type': 'connected', 'job_id': job_id, 'message': 'Progress stream connected', 'already_finished': finished_status is not None})}\n\n"
            
            # Stream events as they come
            while True:
                try:
                    # Wait for next event with timeout
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    
                    # Format as SSE
                    event_json = json.dumps(event)
                    yield f"data: {event_json}\n\n"
                    
                    # Check if job is done
                    if event.get("type") in ["completed", "error", "cancelled"]:
                        console_logger.info(f"📡 Job {job_id} stream ending: {event.get('type')}")
                        # Send final event and close
                        yield f"data: {json.dumps({'type': 'stream_end', 'reason': event.get('type')})}\n\n"
                        break
                
                except asyncio.TimeoutError:
                    # Check if job finished during timeout (backup check)
                    finished_status = progress_tracker.is_job_finished(job_id)
                    if finished_status:
                        console_logger.info(f"📡 Job {job_id} finished during timeout: {finished_status}")
                        yield f"data: {json.dumps({'type': finished_status, 'message': f'Job {finished_status}'})}\n\n"
                        yield f"data: {json.dumps({'type': 'stream_end', 'reason': finished_status})}\n\n"
                        break
                    
                    # Send keep-alive ping every 30 seconds
                    yield f": keep-alive\n\n"
                
                except asyncio.CancelledError:
                    console_logger.info(f"📡 Client disconnected from job {job_id}")
                    break
        
        finally:
            # Unsubscribe when client disconnects or stream ends
            progress_tracker.unsubscribe(job_id, queue)
            console_logger.info(f"📡 Client unsubscribed from job {job_id}")
    
    return StreamingResponse(
        generate_progress_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


@router.get("/{project_id}/job", status_code=status.HTTP_200_OK)
async def get_project_job_details(project_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Get detailed job information for a project.
    Shows current step, progress, and whether job can be resumed.
    """
    # Verify project exists
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Get latest job
    result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.project_id == project_id)
        .order_by(ProcessingJob.updated_at.desc())
    )
    job = result.scalar_one_or_none()
    
    if not job:
        return {
            "project_id": str(project_id),
            "has_job": False,
            "message": "No processing job found for this project"
        }
    
    return {
        "project_id": str(project_id),
        "has_job": True,
        "job_id": job.job_id,
        "status": job.status,
        "current_step": job.current_step,
        "current_step_index": job.current_step_index,
        "total_steps": job.total_steps,
        "progress_percentage": round((job.current_step_index / job.total_steps) * 100, 1),
        "last_successful_step": job.last_successful_step,
        "failed_step": job.failed_step,
        "error_message": job.error_message,
        "can_resume": bool(job.can_resume),
        "documents_processed": job.documents_processed,
        "embeddings_created": job.embeddings_created,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "cancelled_at": job.cancelled_at.isoformat() if job.cancelled_at else None
    }


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete a project and all associated data"""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Cancel any running jobs first
    await cancel_job(str(project_id))
    
    await db.delete(project)
    await db.commit()
