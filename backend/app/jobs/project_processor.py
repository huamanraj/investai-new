"""
Background job for processing projects
Handles: Scraping → Downloading → Cloudinary Upload → Database Storage
"""
import asyncio
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_maker, Project, Document, ProjectStatus
from app.services import (
    scraper, 
    cloudinary_service, 
    extract_company_name
)
from app.core.logging import job_logger, console_logger


# Store for tracking running jobs
_running_jobs: dict[str, dict] = {}


async def process_project(project_id: str, source_url: str):
    """
    Background job to process a project:
    1. Scrape BSE India page for PDF links
    2. Download the latest annual report PDF
    3. Upload to Cloudinary
    4. Save document info to database
    
    Args:
        project_id: UUID of the project
        source_url: BSE India annual reports URL
    """
    job_id = str(uuid.uuid4())[:8]
    
    job_logger.info(
        f"Starting project processing job",
        project_id=project_id,
        job_id=job_id,
        data={"source_url": source_url}
    )
    console_logger.info(f"🚀 [Job {job_id}] Starting project processing for {project_id}")
    
    # Track job
    _running_jobs[project_id] = {
        "job_id": job_id,
        "status": "running",
        "started_at": datetime.utcnow().isoformat(),
        "progress": []
    }
    
    async with async_session_maker() as session:
        try:
            # Update status to scraping
            await _update_project_status(session, project_id, ProjectStatus.SCRAPING)
            _running_jobs[project_id]["status"] = "scraping"
            
            # Progress callback
            def on_progress(progress: dict):
                _running_jobs[project_id]["progress"].append(progress)
                job_logger.info(
                    progress.get("message", "Progress update"),
                    project_id=project_id,
                    job_id=job_id,
                    data=progress
                )
            
            # Step 1: Scrape BSE India page
            console_logger.info(f"📋 [Job {job_id}] Scraping BSE India page...")
            scrape_result = await scraper.scrape_latest_annual_report(
                url=source_url,
                project_id=project_id,
                on_progress=on_progress
            )
            
            if not scrape_result.success:
                await _fail_project(
                    session, project_id, job_id,
                    f"Scraping failed: {scrape_result.error}"
                )
                return
            
            if not scrape_result.pdfs:
                await _fail_project(
                    session, project_id, job_id,
                    "No PDFs found on the page"
                )
                return
            
            # Update status to downloading
            await _update_project_status(session, project_id, ProjectStatus.DOWNLOADING)
            _running_jobs[project_id]["status"] = "downloading"
            
            # Step 2: Upload PDFs to Cloudinary and save to database
            console_logger.info(f"☁️ [Job {job_id}] Uploading {len(scrape_result.pdfs)} PDF(s) to Cloudinary...")
            
            # Get company name from URL
            company_name = extract_company_name(source_url)
            
            documents_created = 0
            
            for pdf_info in scrape_result.pdfs:
                if not pdf_info.pdf_buffer:
                    job_logger.warning(
                        f"PDF buffer is empty for {pdf_info.label}",
                        project_id=project_id,
                        job_id=job_id
                    )
                    continue
                
                # Upload to Cloudinary
                success, file_url, error = await cloudinary_service.upload_pdf(
                    pdf_buffer=pdf_info.pdf_buffer,
                    company_name=company_name,
                    fiscal_year=pdf_info.label,
                    project_id=project_id
                )
                
                if not success:
                    job_logger.error(
                        f"Cloudinary upload failed for {pdf_info.label}: {error}",
                        project_id=project_id,
                        job_id=job_id
                    )
                    # Continue with other PDFs even if one fails
                    continue
                
                # Create document record
                document = Document(
                    project_id=uuid.UUID(project_id),
                    document_type="annual_report",
                    fiscal_year=str(pdf_info.year) if pdf_info.year else None,
                    label=pdf_info.label,
                    file_url=file_url,
                    original_url=pdf_info.url
                )
                
                session.add(document)
                documents_created += 1
                
                job_logger.info(
                    f"Document created: {pdf_info.label}",
                    project_id=project_id,
                    job_id=job_id,
                    data={
                        "label": pdf_info.label,
                        "file_url": file_url,
                        "year": pdf_info.year
                    }
                )
            
            await session.commit()
            
            if documents_created == 0:
                await _fail_project(
                    session, project_id, job_id,
                    "Failed to upload any documents to Cloudinary"
                )
                return
            
            # Step 3: Mark project as completed
            await _update_project_status(session, project_id, ProjectStatus.COMPLETED)
            _running_jobs[project_id]["status"] = "completed"
            _running_jobs[project_id]["completed_at"] = datetime.utcnow().isoformat()
            _running_jobs[project_id]["documents_created"] = documents_created
            
            console_logger.info(
                f"✅ [Job {job_id}] Project processing completed! "
                f"Created {documents_created} document(s)"
            )
            job_logger.info(
                f"Project processing completed",
                project_id=project_id,
                job_id=job_id,
                data={"documents_created": documents_created}
            )
        
        except Exception as e:
            await _fail_project(session, project_id, job_id, str(e))
            raise


async def _update_project_status(
    session: AsyncSession, 
    project_id: str, 
    status: ProjectStatus
):
    """Update project status in database"""
    await session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(project_id))
        .values(status=status.value)
    )
    await session.commit()


async def _fail_project(
    session: AsyncSession,
    project_id: str,
    job_id: str,
    error_message: str
):
    """Mark project as failed with error message"""
    await session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(project_id))
        .values(
            status=ProjectStatus.FAILED.value,
            error_message=error_message
        )
    )
    await session.commit()
    
    _running_jobs[project_id]["status"] = "failed"
    _running_jobs[project_id]["error"] = error_message
    
    console_logger.error(f"❌ [Job {job_id}] Project failed: {error_message}")
    job_logger.error(
        f"Project processing failed",
        project_id=project_id,
        job_id=job_id,
        data={"error": error_message}
    )


def get_job_status(project_id: str) -> Optional[dict]:
    """Get the status of a running or completed job"""
    return _running_jobs.get(project_id)


def get_all_jobs() -> dict:
    """Get all job statuses"""
    return _running_jobs.copy()
