"""
Resumable Background Job Processor
Supports cancellation and resuming from the last successful step
Uses LlamaParse for 100% PDF text extraction
"""
import asyncio
import uuid
import aiohttp
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum
from pathlib import Path

from sqlalchemy import update, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from app.db import (
    async_session_maker, Project, Document, ProjectStatus, 
    ExtractionResult, TextChunk, Embedding, DocumentPage, 
    CompanySnapshot, ProcessingJob
)
from app.services import (
    scraper, 
    extract_company_name,
    llama_extract_service,  # LlamaCloud-based extractor
    embeddings_service,
    snapshot_generator
)
from app.core.logging import job_logger, console_logger
from app.services.progress_tracker import progress_tracker


class JobStep(str, Enum):
    """Job processing steps"""
    SCRAPING = "scraping"
    DOWNLOADING = "downloading"
    EXTRACTING = "extracting"
    SAVING_EXTRACTION = "saving_extraction"
    SAVING_PAGES = "saving_pages"
    CREATING_EMBEDDINGS = "creating_embeddings"
    SAVING_EMBEDDINGS = "saving_embeddings"
    GENERATING_SNAPSHOT = "generating_snapshot"
    COMPLETED = "completed"


STEP_ORDER = [
    JobStep.SCRAPING,
    JobStep.DOWNLOADING,
    JobStep.EXTRACTING,
    JobStep.SAVING_EXTRACTION,
    JobStep.SAVING_PAGES,
    JobStep.CREATING_EMBEDDINGS,
    JobStep.SAVING_EMBEDDINGS,
    JobStep.GENERATING_SNAPSHOT,
    JobStep.COMPLETED
]


async def process_project_resumable(project_id: str, source_url: str, resume: bool = False):
    """
    Resumable background job to process a project.
    
    IMPORTANT: This processor properly handles resume scenarios:
    - Each step saves its output to resume_data
    - If a step fails, the previous step's data is preserved
    - On resume, data from previous steps is loaded from DB
    
    Args:
        project_id: UUID of the project
        source_url: BSE India annual reports URL
        resume: Whether this is a resume operation
    """
    # Validate inputs
    if not source_url:
        console_logger.error(f"❌ Cannot process project {project_id}: source_url is empty")
        async with async_session_maker() as session:
            await session.execute(
                update(Project)
                .where(Project.id == uuid.UUID(project_id))
                .values(
                    status=ProjectStatus.FAILED.value,
                    error_message="Source URL is missing. Cannot process project."
                )
            )
            await session.commit()
        return
    
    async with async_session_maker() as session:
        try:
            # Get or create processing job
            if resume:
                job = await _get_job_for_resume(session, project_id)
                if not job:
                    console_logger.error(f"❌ No resumable job found for project {project_id}")
                    return
                
                console_logger.info(f"▶️ Resuming job {job.job_id} from step: {job.last_successful_step}")
                job_id = job.job_id
                
                # CRITICAL: Load resume data from DB to preserve previous step outputs
                resume_data = job.resume_data or {}
                console_logger.info(f"📦 Loaded resume_data with keys: {list(resume_data.keys())}")
            else:
                job_id = str(uuid.uuid4())[:8]
                job = await _create_job(session, project_id, job_id)
                resume_data = {}
                console_logger.info(f"🚀 Starting new job {job_id} for project {project_id}")
            
            job_logger.info(
                "Processing job started",
                project_id=project_id,
                job_id=job_id,
                data={"source_url": source_url, "resume": resume}
            )
            
            # Get company name
            company_name = extract_company_name(source_url)
            
            # Emit started event
            await progress_tracker.emit(
                job_id=job_id,
                event_type="started",
                message=f"{'Resuming' if resume else 'Starting'} project processing",
                data={"company_name": company_name},
                step_index=0,
                total_steps=len(STEP_ORDER)
            )
            
            # Determine starting step
            start_step_index = 0
            if resume and job.last_successful_step:
                try:
                    last_step_index = STEP_ORDER.index(JobStep(job.last_successful_step))
                    start_step_index = last_step_index + 1
                    console_logger.info(f"📍 Resuming from step index {start_step_index} (after {job.last_successful_step})")
                except (ValueError, IndexError):
                    start_step_index = 0
            
            # Execute steps
            for step_index in range(start_step_index, len(STEP_ORDER)):
                step = STEP_ORDER[step_index]
                
                # Check if job was cancelled
                await session.refresh(job)
                if job.status == "cancelled":
                    console_logger.warning(f"⚠️ Job {job_id} was cancelled")
                    await progress_tracker.emit(
                        job_id=job_id,
                        event_type="cancelled",
                        message="Job was cancelled",
                        step=step.value,
                        step_index=step_index,
                        total_steps=len(STEP_ORDER)
                    )
                    return
                
                # Update current step
                await _update_job_step(session, job.id, step, step_index)
                
                console_logger.info(f"📍 [{job_id}] Step {step_index + 1}/{len(STEP_ORDER)}: {step.value}")
                
                # Emit step started event
                await progress_tracker.emit(
                    job_id=job_id,
                    event_type="step_started",
                    message=f"Starting: {step.value.replace('_', ' ').title()}",
                    step=step.value,
                    step_index=step_index,
                    total_steps=len(STEP_ORDER)
                )
                
                try:
                    # Execute step
                    if step == JobStep.SCRAPING:
                        resume_data = await _step_scraping(
                            session, project_id, job_id, source_url, resume_data
                        )
                    
                    elif step == JobStep.DOWNLOADING:
                        resume_data = await _step_saving_documents(
                            session, project_id, job_id, resume_data
                        )
                    
                    elif step == JobStep.EXTRACTING:
                        # CRITICAL: Check if we have documents before extracting
                        if not resume_data.get("uploaded_documents"):
                            raise Exception("No documents available for extraction. Previous step data missing.")
                        resume_data = await _step_extracting_with_llama(
                            session, project_id, job_id, company_name, resume_data
                        )
                    
                    elif step == JobStep.SAVING_EXTRACTION:
                        # CRITICAL: Check if we have extraction data
                        if not resume_data.get("extractions") and not resume_data.get("pages"):
                            console_logger.warning(f"⚠️ [{job_id}] No extraction data found, checking if extraction was skipped...")
                            # Try to recover from DB if extraction exists
                            recovery_result = await _try_recover_extraction_from_db(session, project_id)
                            if recovery_result:
                                resume_data["extractions"] = recovery_result.get("extractions", [])
                                resume_data["pages"] = recovery_result.get("pages", [])
                        resume_data = await _step_saving_extraction(
                            session, project_id, job_id, resume_data
                        )
                    
                    elif step == JobStep.SAVING_PAGES:
                        resume_data = await _step_saving_pages(
                            session, project_id, job_id, resume_data
                        )
                    
                    elif step == JobStep.CREATING_EMBEDDINGS:
                        # CRITICAL: Load extraction data from DB if not in resume_data
                        # This ensures resume works even if extraction step completed but embedding failed
                        if not resume_data.get("extractions") and not resume_data.get("pages"):
                            console_logger.info(f"📦 [{job_id}] Loading extraction data from DB for embeddings...")
                            recovery_result = await _try_recover_extraction_from_db(session, project_id)
                            if recovery_result:
                                resume_data["extractions"] = recovery_result.get("extractions", [])
                                resume_data["pages"] = recovery_result.get("pages", [])
                                console_logger.info(f"✅ [{job_id}] Loaded extraction data from DB")
                        
                        # Also ensure we have pages metadata
                        if not resume_data.get("pages_metadata"):
                            pages_from_db = await _get_pages_from_db(session, project_id)
                            if pages_from_db:
                                resume_data["pages_metadata"] = pages_from_db
                        
                        resume_data = await _step_creating_embeddings(
                            session, project_id, job_id, resume_data
                        )
                    
                    elif step == JobStep.SAVING_EMBEDDINGS:
                        resume_data = await _step_saving_embeddings(
                            session, project_id, job_id, resume_data
                        )
                    
                    elif step == JobStep.GENERATING_SNAPSHOT:
                        # CRITICAL: Load extraction data from DB if not in resume_data
                        # This ensures resume works even if previous steps completed but snapshot failed
                        if not resume_data.get("extractions"):
                            console_logger.info(f"📦 [{job_id}] Loading extraction data from DB for snapshot...")
                            recovery_result = await _try_recover_extraction_from_db(session, project_id)
                            if recovery_result:
                                resume_data["extractions"] = recovery_result.get("extractions", [])
                                console_logger.info(f"✅ [{job_id}] Loaded extraction data from DB for snapshot")
                        
                        resume_data = await _step_generating_snapshot(
                            session, project_id, job_id, company_name, source_url, resume_data
                        )
                    
                    elif step == JobStep.COMPLETED:
                        await _complete_job(session, job.id, project_id)
                        console_logger.info(f"✅ Job {job_id} completed successfully!")
                        
                        # Emit completed event
                        await progress_tracker.emit(
                            job_id=job_id,
                            event_type="completed",
                            message="Project processing completed successfully!",
                            step="completed",
                            step_index=len(STEP_ORDER),
                            total_steps=len(STEP_ORDER),
                            data={
                                "documents_processed": resume_data.get("documents_processed", 0),
                                "embeddings_created": resume_data.get("embeddings_count", 0)
                            }
                        )
                        
                        # Cleanup progress after a delay
                        await asyncio.sleep(5)
                        progress_tracker.cleanup_job(job_id)
                        return
                    
                    # Mark step as successful and SAVE resume_data
                    await _mark_step_successful(session, job.id, step, resume_data)
                    await session.commit()
                    
                    # Emit step completed event
                    await progress_tracker.emit(
                        job_id=job_id,
                        event_type="step_completed",
                        message=f"Completed: {step.value.replace('_', ' ').title()}",
                        step=step.value,
                        step_index=step_index + 1,
                        total_steps=len(STEP_ORDER)
                    )
                
                except Exception as e:
                    # Step failed - save state for resume
                    error_msg = str(e)
                    console_logger.error(f"❌ [{job_id}] Step {step.value} failed: {error_msg}")

                    # Rollback any pending changes
                    try:
                        await session.rollback()
                    except Exception:
                        pass

                    # Save failure state (with previous successful step data preserved)
                    try:
                        await _mark_job_failed(session, job.id, project_id, step, error_msg, resume_data)
                    except Exception as mark_err:
                        console_logger.error(f"❌ [{job_id}] Failed to persist job failure state: {mark_err}")
                        try:
                            async with async_session_maker() as retry_session:
                                await _mark_job_failed(
                                    retry_session, job.id, project_id, step, error_msg, resume_data
                                )
                        except Exception as retry_err:
                            console_logger.error(f"❌ [{job_id}] Failure state retry also failed: {retry_err}")
                    
                    # Emit error event with detailed error message
                    await progress_tracker.emit(
                        job_id=job_id,
                        event_type="error",
                        message=error_msg,
                        step=step.value,
                        step_index=step_index,
                        total_steps=len(STEP_ORDER),
                        data={
                            "error": error_msg, 
                            "can_resume": True, 
                            "failed_step": step.value,
                            "last_successful_step": STEP_ORDER[step_index - 1].value if step_index > 0 else None
                        }
                    )
                    
                    job_logger.error(
                        "Job step failed",
                        project_id=project_id,
                        job_id=job_id,
                        data={"step": step.value, "error": error_msg}
                    )
                    return
        
        except Exception as e:
            console_logger.error(f"❌ Job processing error: {e}")
            raise


async def cancel_job(project_id: str) -> bool:
    """
    Cancel a running job.
    
    Args:
        project_id: Project UUID
        
    Returns:
        True if cancelled, False if no active job found
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProcessingJob).where(
                ProcessingJob.project_id == uuid.UUID(project_id),
                ProcessingJob.status.in_(["pending", "running"])
            )
        )
        job = result.scalar_one_or_none()
        
        if not job:
            return False
        
        # Mark as cancelled
        job.status = "cancelled"
        job.cancelled_at = datetime.utcnow()
        job.can_resume = 1  # Can resume cancelled jobs
        
        await session.commit()
        
        console_logger.info(f"🛑 Job {job.job_id} cancelled for project {project_id}")
        job_logger.info(
            "Job cancelled",
            project_id=project_id,
            job_id=job.job_id
        )
        
        # Update project status
        await session.execute(
            update(Project)
            .where(Project.id == uuid.UUID(project_id))
            .values(status=ProjectStatus.FAILED.value, error_message="Job cancelled by user")
        )
        await session.commit()
        
        # Emit cancelled event
        await progress_tracker.emit(
            job_id=job.job_id,
            event_type="cancelled",
            message="Job cancelled by user",
            data={"can_resume": True}
        )
        
        return True


# Helper functions

async def _create_job(session: AsyncSession, project_id: str, job_id: str) -> ProcessingJob:
    """Create a new processing job"""
    job = ProcessingJob(
        project_id=uuid.UUID(project_id),
        job_id=job_id,
        status="running",
        total_steps=len(STEP_ORDER)
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _get_job_for_resume(session: AsyncSession, project_id: str) -> Optional[ProcessingJob]:
    """Get the last failed, cancelled, or running (for resume) job"""
    result = await session.execute(
        select(ProcessingJob).where(
            ProcessingJob.project_id == uuid.UUID(project_id)
        ).order_by(ProcessingJob.updated_at.desc())
    )
    job = result.scalar_one_or_none()
    
    if job and (job.can_resume == 1 or job.status == "running"):
        return job
    return None


async def _update_job_step(session: AsyncSession, job_id: uuid.UUID, step: JobStep, step_index: int):
    """Update current job step"""
    await session.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job_id)
        .values(
            status="running",
            current_step=step.value,
            current_step_index=step_index,
            updated_at=datetime.utcnow()
        )
    )
    await session.commit()


async def _mark_step_successful(
    session: AsyncSession,
    job_id: uuid.UUID,
    step: JobStep,
    resume_data: Dict[str, Any]
):
    """
    Mark step as successful and save resume data.
    
    CRITICAL: This saves all step outputs so they can be recovered on resume.
    Large data (PDF buffers, full text) is excluded - only metadata is saved.
    Full text can be loaded from DB tables on resume.
    """
    # Remove in-memory buffers and large data before saving (too large for JSONB)
    resume_data_clean = {}
    
    for k, v in resume_data.items():
        if k.startswith("_") or k == "pdf_buffers":
            continue  # Skip internal buffers
        
        # Clean extractions: remove full text, keep only metadata
        if k == "extractions" and isinstance(v, list):
            resume_data_clean[k] = [
                {
                    "document_id": ext.get("document_id"),
                    "metadata": ext.get("metadata", {}),
                    # DO NOT include "data" field - contains full text (900KB+)
                }
                for ext in v
            ]
        # Clean pages: remove text, keep only metadata
        elif k in ("pages", "parsed_pages") and isinstance(v, list):
            cleaned_pages = []
            for page_item in v:
                if isinstance(page_item, dict):
                    if "pages" in page_item:
                        # This is a page set with nested pages array
                        cleaned_pages.append({
                            "document_id": page_item.get("document_id"),
                            "total_pages": page_item.get("total_pages"),
                            # DO NOT include "pages" array with text - too large
                        })
                    elif "document_id" in page_item and "page_number" in page_item:
                        # This is a single page
                        cleaned_pages.append({
                            "document_id": page_item.get("document_id"),
                            "page_number": page_item.get("page_number"),
                            # DO NOT include "text" field - too large
                        })
                    else:
                        # Unknown format, keep minimal data
                        cleaned_pages.append({
                            "document_id": page_item.get("document_id"),
                        })
                else:
                    # Not a dict, skip it
                    pass
            resume_data_clean[k] = cleaned_pages
        else:
            # Keep other fields as-is
            resume_data_clean[k] = v
    
    await session.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job_id)
        .values(
            last_successful_step=step.value,
            resume_data=resume_data_clean,
            updated_at=datetime.utcnow()
        )
    )


async def _mark_job_failed(
    session: AsyncSession,
    job_id: uuid.UUID,
    project_id: str,
    failed_step: JobStep,
    error_message: str,
    resume_data: Dict[str, Any]
):
    """
    Mark job as failed and preserve resume data.
    
    CRITICAL: Previous step data is preserved so resume works correctly.
    """
    # Remove in-memory buffers
    resume_data_clean = {
        k: v for k, v in resume_data.items() 
        if not k.startswith("_") and k != "pdf_buffers"
    }
    
    await session.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job_id)
        .values(
            status="failed",
            failed_step=failed_step.value,
            error_message=error_message,
            can_resume=1,
            resume_data=resume_data_clean,
            updated_at=datetime.utcnow()
        )
    )
    await session.commit()
    
    # Update project status
    await session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(project_id))
        .values(status=ProjectStatus.FAILED.value, error_message=f"Failed at {failed_step.value}: {error_message}")
    )
    await session.commit()


async def _complete_job(session: AsyncSession, job_id: uuid.UUID, project_id: str):
    """Mark job as completed"""
    await session.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job_id)
        .values(
            status="completed",
            current_step="completed",
            completed_at=datetime.utcnow(),
            can_resume=0,
            updated_at=datetime.utcnow()
        )
    )
    await session.commit()
    
    # Update project status
    await session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(project_id))
        .values(status=ProjectStatus.COMPLETED.value)
    )
    await session.commit()


async def _try_recover_extraction_from_db(session: AsyncSession, project_id: str) -> Optional[Dict[str, Any]]:
    """Try to recover extraction data from database if it was saved before failure"""
    try:
        # Get documents for this project
        docs_result = await session.execute(
            select(Document).where(Document.project_id == uuid.UUID(project_id))
        )
        documents = docs_result.scalars().all()
        
        if not documents:
            return None
        
        extractions = []
        pages = []
        
        for doc in documents:
            # Check for existing extraction
            ext_result = await session.execute(
                select(ExtractionResult).where(ExtractionResult.document_id == doc.id)
            )
            extraction = ext_result.scalar_one_or_none()
            if extraction:
                extractions.append({
                    "document_id": str(doc.id),
                    "data": extraction.extracted_data or {},
                    "metadata": extraction.extraction_metadata or {}
                })
            
            # Check for existing pages
            pages_result = await session.execute(
                select(DocumentPage).where(DocumentPage.document_id == doc.id)
            )
            doc_pages = pages_result.scalars().all()
            if doc_pages:
                pages.append({
                    "document_id": str(doc.id),
                    "pages": [{"page_number": p.page_number, "text": p.page_text} for p in doc_pages]
                })
        
        if extractions or pages:
            console_logger.info(f"📦 Recovered {len(extractions)} extractions and {len(pages)} page sets from DB")
            return {"extractions": extractions, "pages": pages}
        
        return None
    except Exception as e:
        console_logger.warning(f"⚠️ Could not recover extraction data from DB: {e}")
        return None


async def _get_pages_from_db(session: AsyncSession, project_id: str) -> List[Dict[str, Any]]:
    """Get pages metadata from database for resume scenario"""
    try:
        docs_result = await session.execute(
            select(Document).where(Document.project_id == uuid.UUID(project_id))
        )
        documents = docs_result.scalars().all()
        
        pages_metadata = []
        for doc in documents:
            pages_result = await session.execute(
                select(DocumentPage).where(DocumentPage.document_id == doc.id)
            )
            doc_pages = pages_result.scalars().all()
            if doc_pages:
                pages_metadata.append({
                    "document_id": str(doc.id),
                    "total_pages": len(doc_pages),
                    "from_db": True
                })
        
        return pages_metadata
    except Exception:
        return []


# Step implementations

async def _step_scraping(
    session: AsyncSession,
    project_id: str,
    job_id: str,
    source_url: str,
    resume_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Step 1: Scrape BSE India page"""
    await session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(project_id))
        .values(status=ProjectStatus.SCRAPING.value)
    )
    await session.commit()
    
    await progress_tracker.emit(
        job_id=job_id,
        event_type="progress",
        message="Validating BSE India URL...",
        step="scraping"
    )
    
    console_logger.info(f"📋 [{job_id}] Scraping BSE India page...")
    
    await progress_tracker.emit(
        job_id=job_id,
        event_type="progress",
        message="Connecting to BSE India website...",
        step="scraping"
    )
    
    scrape_result = await scraper.scrape_latest_annual_report(
        url=source_url,
        project_id=project_id
    )
    
    if not scrape_result.success:
        error_msg = scrape_result.error or "Scraping failed"
        raise Exception(f"Scraping failed: {error_msg}")
    
    await progress_tracker.emit(
        job_id=job_id,
        event_type="progress",
        message="Page loaded, searching for annual reports...",
        step="scraping"
    )
    
    if not scrape_result.pdfs:
        raise Exception("No PDFs found on the page")
    
    await progress_tracker.emit(
        job_id=job_id,
        event_type="progress",
        message=f"Found {len(scrape_result.pdfs)} annual report(s).",
        step="scraping",
        data={"pdf_count": len(scrape_result.pdfs)}
    )
    
    # Save PDF info to resume data (URLs only, not buffers)
    resume_data["pdfs"] = [
        {
            "label": pdf.label,
            "url": pdf.url,
            "year": pdf.year,
        }
        for pdf in scrape_result.pdfs
    ]
    
    # Keep PDF buffers in memory for this run only (not saved to DB)
    resume_data["_pdf_buffers_in_memory"] = [
        pdf.pdf_buffer if pdf.pdf_buffer else None 
        for pdf in scrape_result.pdfs
    ]
    
    return resume_data


async def _step_saving_documents(
    session: AsyncSession,
    project_id: str,
    job_id: str,
    resume_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Step 2: Save documents with direct PDF URLs"""
    await session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(project_id))
        .values(status=ProjectStatus.DOWNLOADING.value)
    )
    await session.commit()
    
    pdfs_info = resume_data.get("pdfs", [])
    
    console_logger.info(f"💾 [{job_id}] Saving {len(pdfs_info)} document(s)...")
    
    await progress_tracker.emit(
        job_id=job_id,
        event_type="progress",
        message=f"Saving {len(pdfs_info)} document(s)...",
        step="downloading",
        data={"total_pdfs": len(pdfs_info)}
    )
    
    saved_documents = []
    
    for idx, pdf_info in enumerate(pdfs_info):
        pdf_url = pdf_info["url"]
        
        # Check if document already exists (resume scenario)
        existing_doc = await session.execute(
            select(Document).where(
                Document.project_id == uuid.UUID(project_id),
                Document.original_url == pdf_url
            )
        )
        existing = existing_doc.scalar_one_or_none()
        
        if existing:
            console_logger.info(f"⏭️ [{job_id}] Document already exists: {pdf_info['label']}")
            saved_documents.append({
                "id": str(existing.id),
                "label": pdf_info["label"],
                "file_url": existing.file_url,
                "url": pdf_url
            })
            continue
        
        # Create document record
        document = Document(
            project_id=uuid.UUID(project_id),
            document_type="annual_report",
            fiscal_year=str(pdf_info["year"]) if pdf_info["year"] else None,
            label=pdf_info["label"],
            file_url=pdf_url,
            original_url=pdf_url
        )
        
        session.add(document)
        await session.flush()
        
        await progress_tracker.emit(
            job_id=job_id,
            event_type="progress",
            message=f"Saved: {pdf_info['label']} ({idx + 1}/{len(pdfs_info)})",
            step="downloading",
            data={"current": idx + 1, "total": len(pdfs_info)}
        )
        
        saved_documents.append({
            "id": str(document.id),
            "label": pdf_info["label"],
            "file_url": pdf_url,
            "url": pdf_url
        })
    
    await session.commit()
    
    if not saved_documents:
        raise Exception("Failed to save any documents")
    
    resume_data["uploaded_documents"] = saved_documents
    return resume_data


async def _step_extracting_with_llama(
    session: AsyncSession,
    project_id: str,
    job_id: str,
    company_name: str,
    resume_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Step 3: Extract COMPLETE text using LlamaParse.
    
    Uses LlamaCloud Parse to get 100% of PDF content including tables, charts, graphs.
    Ensures ALL text is extracted - nothing missing.
    """
    if not llama_extract_service.is_configured():
        raise Exception("LlamaCloud API is not configured. Cannot extract PDF content.")
    
    await session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(project_id))
        .values(status=ProjectStatus.PROCESSING.value)
    )
    await session.commit()
    
    saved_docs = resume_data.get("uploaded_documents", [])
    pdf_buffers_in_memory = resume_data.get("_pdf_buffers_in_memory", [])
    
    await progress_tracker.emit(
        job_id=job_id,
        event_type="progress",
        message=f"Starting AI-powered extraction from {len(saved_docs)} document(s)...",
        step="extracting",
        data={"total_documents": len(saved_docs)}
    )
    
    extractions = []
    all_pages = []
    
    for idx, doc_info in enumerate(saved_docs):
        # Get PDF buffer
        pdf_buffer = None
        
        # Try in-memory buffer first (initial run)
        if idx < len(pdf_buffers_in_memory) and pdf_buffers_in_memory[idx]:
            pdf_buffer = pdf_buffers_in_memory[idx]
            console_logger.info(f"📄 [{job_id}] Using in-memory PDF buffer for {doc_info['label']}")
        else:
            # Download PDF from URL (resume scenario)
            try:
                console_logger.info(f"📥 [{job_id}] Downloading PDF from URL: {doc_info['file_url']}")
                await progress_tracker.emit(
                    job_id=job_id,
                    event_type="progress",
                    message=f"Downloading: {doc_info['label']}...",
                    step="extracting"
                )
                
                async with aiohttp.ClientSession() as http_session:
                    async with http_session.get(
                        doc_info["file_url"],
                        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
                        timeout=aiohttp.ClientTimeout(total=300)
                    ) as response:
                        response.raise_for_status()
                        pdf_buffer = await response.read()
                        console_logger.info(f"✅ [{job_id}] Downloaded {len(pdf_buffer) / 1024 / 1024:.2f} MB")
            except Exception as e:
                console_logger.error(f"❌ [{job_id}] Failed to download PDF: {e}")
                continue
        
        if not pdf_buffer:
            console_logger.warning(f"⚠️ [{job_id}] No PDF buffer available for {doc_info['label']}")
            continue
        
        filename = f"{company_name}_{doc_info['label']}.pdf"
        
        # Extract using LlamaParse for 100% text extraction
        console_logger.info(
            f"📊 [{job_id}] Extracting with LlamaParse: {doc_info['label']}..."
        )
        
        await progress_tracker.emit(
            job_id=job_id,
            event_type="progress",
            message=f"Extracting complete text from: {doc_info['label']} (this may take several minutes)...",
            step="extracting",
            data={"current": idx + 1, "total": len(saved_docs)}
        )
        
        extraction_result = await llama_extract_service.extract_from_pdf_buffer(
            pdf_buffer=pdf_buffer,
            filename=filename,
            project_id=project_id
        )
        
        if extraction_result.get("success"):
            extractions.append({
                "document_id": doc_info["id"],
                "data": extraction_result.get("data", {}),
                "metadata": extraction_result.get("metadata", {})
            })
            
            # Store pages for embedding creation
            pages = extraction_result.get("pages", [])
            if pages:
                all_pages.append({
                    "document_id": doc_info["id"],
                    "pages": pages,
                    "total_pages": extraction_result.get("total_pages", len(pages))
                })
            
            console_logger.info(f"✅ [{job_id}] Extracted {len(pages)} pages from {doc_info['label']}")
        else:
            error_msg = extraction_result.get("error", "Extraction failed")
            console_logger.error(f"❌ [{job_id}] Extraction failed for {doc_info['label']}: {error_msg}")
            # Don't fail the whole job, continue with other documents
    
    # Clear in-memory buffers
    resume_data.pop("_pdf_buffers_in_memory", None)
    
    # Save extraction results to resume_data (full data kept in memory for next steps)
    # NOTE: Full text will be stripped when saving to DB in _mark_step_successful
    resume_data["extractions"] = extractions
    resume_data["pages"] = all_pages  # This is used for page saving and embeddings
    resume_data["parsed_pages"] = all_pages  # Legacy compatibility
    
    if not extractions and not all_pages:
        raise Exception("Failed to extract any content from PDFs")
    
    return resume_data


async def _save_extraction_to_txt_file(
    document_id: str,
    document_label: str,
    extracted_data: Dict[str, Any],
    extraction_metadata: Dict[str, Any],
    pages: List[Dict[str, Any]],
    project_id: str
) -> Optional[Path]:
    """
    Save extraction results to a txt file.
    
    Args:
        document_id: Document UUID
        document_label: Document label/name
        extracted_data: Extracted structured data
        extraction_metadata: Extraction metadata
        pages: List of pages with text
        project_id: Project UUID
        
    Returns:
        Path to saved file or None if failed
    """
    try:
        # Create logs directory structure
        logs_dir = Path(__file__).parent.parent.parent / "logs" / "extractions"
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Create project-specific subdirectory
        project_dir = logs_dir / project_id
        project_dir.mkdir(exist_ok=True)
        
        # Create safe filename from document label
        safe_label = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in document_label)[:100]
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{safe_label}_{document_id[:8]}.txt"
        file_path = project_dir / filename
        
        # Write extraction results to file
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(f"EXTRACTION RESULTS - {document_label}\n")
            f.write("=" * 80 + "\n\n")
            
            f.write(f"Document ID: {document_id}\n")
            f.write(f"Extracted At: {datetime.utcnow().isoformat()}\n")
            f.write(f"Project ID: {project_id}\n\n")
            
            # Write extracted structured data
            f.write("-" * 80 + "\n")
            f.write("STRUCTURED DATA\n")
            f.write("-" * 80 + "\n\n")
            f.write(json.dumps(extracted_data, indent=2, ensure_ascii=False))
            f.write("\n\n")
            
            # Write extraction metadata if available
            if extraction_metadata:
                f.write("-" * 80 + "\n")
                f.write("EXTRACTION METADATA\n")
                f.write("-" * 80 + "\n\n")
                f.write(json.dumps(extraction_metadata, indent=2, ensure_ascii=False))
                f.write("\n\n")
            
            # Write all pages text
            if pages:
                f.write("=" * 80 + "\n")
                f.write(f"COMPLETE TEXT EXTRACTION ({len(pages)} pages)\n")
                f.write("=" * 80 + "\n\n")
                
                for page in sorted(pages, key=lambda x: x.get("page_number", 0)):
                    page_num = page.get("page_number", 0)
                    page_text = page.get("text", "")
                    
                    f.write(f"\n{'=' * 80}\n")
                    f.write(f"PAGE {page_num}\n")
                    f.write(f"{'=' * 80}\n\n")
                    f.write(page_text)
                    f.write("\n\n")
        
        console_logger.info(f"📄 Saved extraction to: {file_path}")
        return file_path
        
    except Exception as e:
        console_logger.error(f"❌ Failed to save extraction to txt file: {e}")
        return None


async def _step_saving_extraction(
    session: AsyncSession,
    project_id: str,
    job_id: str,
    resume_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Step 4: Save extraction results to database AND txt files"""
    extractions = resume_data.get("extractions", [])
    pages_data = resume_data.get("pages", []) or resume_data.get("parsed_pages", [])
    saved_docs = resume_data.get("uploaded_documents", [])
    
    if not extractions:
        console_logger.info(f"⚠️ [{job_id}] No extraction data to save")
        return resume_data
    
    console_logger.info(f"💾 [{job_id}] Saving {len(extractions)} extraction result(s) to database and txt files...")
    
    await progress_tracker.emit(
        job_id=job_id,
        event_type="progress",
        message=f"Saving extraction data to database and files...",
        step="saving_extraction"
    )
    
    for extraction in extractions:
        document_id = uuid.UUID(extraction["document_id"])
        
        # Get document info for filename
        doc_info = next((d for d in saved_docs if d["id"] == str(document_id)), None)
        document_label = doc_info.get("label", "Unknown") if doc_info else "Unknown"
        
        # Get pages for this document
        doc_pages = []
        for page_set in pages_data:
            if page_set.get("document_id") == str(document_id):
                doc_pages = page_set.get("pages", [])
                break
        
        # Check if already exists (resume scenario)
        existing = await session.execute(
            select(ExtractionResult).where(ExtractionResult.document_id == document_id)
        )
        existing_record = existing.scalar_one_or_none()
        
        if existing_record:
            console_logger.info(f"⏭️ [{job_id}] Extraction already saved for document {document_id}")
            # Still save to txt file even if DB record exists (for backup)
            # Build complete text for txt file
            complete_text_for_file = extraction["data"] if isinstance(extraction["data"], str) else ""
            if not complete_text_for_file and doc_pages:
                complete_text_parts = []
                for page in sorted(doc_pages, key=lambda x: x.get("page_number", 0)):
                    page_num = page.get("page_number", 0)
                    page_text = page.get("text", "")
                    if page_text.strip():
                        complete_text_parts.append(f"=== PAGE {page_num} ===\n\n{page_text}\n\n")
                complete_text_for_file = "\n".join(complete_text_parts)
            
            await _save_extraction_to_txt_file(
                document_id=str(document_id),
                document_label=document_label,
                extracted_data={"complete_text": complete_text_for_file},  # Wrap for txt file format
                extraction_metadata=extraction.get("metadata", {}),
                pages=doc_pages,
                project_id=project_id
            )
            continue
        
        # Get complete text - data field now contains just the raw text string
        extracted_data_raw = extraction["data"]
        
        # If data is a dict (old format), extract complete_text
        # If data is already a string (new format), use it directly
        if isinstance(extracted_data_raw, dict):
            complete_text = extracted_data_raw.get("complete_text", "")
            # If complete_text not in dict, build it from pages
            if not complete_text and doc_pages:
                complete_text_parts = []
                for page in sorted(doc_pages, key=lambda x: x.get("page_number", 0)):
                    page_num = page.get("page_number", 0)
                    page_text = page.get("text", "")
                    if page_text.strip():
                        complete_text_parts.append(f"=== PAGE {page_num} ===\n\n{page_text}\n\n")
                complete_text = "\n".join(complete_text_parts)
        else:
            # Data is already the complete text string
            complete_text = extracted_data_raw if isinstance(extracted_data_raw, str) else ""
            # If empty and we have pages, build it
            if not complete_text and doc_pages:
                complete_text_parts = []
                for page in sorted(doc_pages, key=lambda x: x.get("page_number", 0)):
                    page_num = page.get("page_number", 0)
                    page_text = page.get("text", "")
                    if page_text.strip():
                        complete_text_parts.append(f"=== PAGE {page_num} ===\n\n{page_text}\n\n")
                complete_text = "\n".join(complete_text_parts)
        
        # Save to database - extracted_data contains ONLY the complete raw text
        # Store as JSON string (valid JSONB) containing just the text
        extraction_record = ExtractionResult(
            document_id=document_id,
            extracted_data=complete_text,  # Just the complete text string
            extraction_metadata=extraction.get("metadata", {}),
            company_name=None,  # No structured fields
            fiscal_year=None,
            revenue=None,
            net_profit=None
        )
        session.add(extraction_record)
        
        # Save to txt file
        txt_file_path = await _save_extraction_to_txt_file(
            document_id=str(document_id),
            document_label=document_label,
            extracted_data={"complete_text": complete_text},  # Wrap for txt file format
            extraction_metadata=extraction.get("metadata", {}),
            pages=doc_pages,
            project_id=project_id
        )
        
        if txt_file_path:
            console_logger.info(f"✅ [{job_id}] Saved extraction for {document_label} to DB and file: {txt_file_path.name}")
    
    await session.commit()
    console_logger.info(f"✅ [{job_id}] Extraction results saved to database and txt files")
    
    return resume_data


async def _step_saving_pages(
    session: AsyncSession,
    project_id: str,
    job_id: str,
    resume_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Step 5: Save parsed pages to database"""
    pages_data = resume_data.get("pages", []) or resume_data.get("parsed_pages", [])
    saved_docs = resume_data.get("uploaded_documents", [])
    
    if not pages_data and not saved_docs:
        console_logger.info(f"⚠️ [{job_id}] No page data to save")
        return resume_data
    
    console_logger.info(f"💾 [{job_id}] Saving pages for {len(pages_data)} document(s)...")
    
    await progress_tracker.emit(
        job_id=job_id,
        event_type="progress",
        message="Saving extracted pages to database...",
        step="saving_pages"
    )
    
    total_pages_saved = 0
    pages_metadata = []
    
    for doc_pages_info in pages_data:
        document_id = uuid.UUID(doc_pages_info["document_id"])
        pages = doc_pages_info.get("pages", [])
        
        # Check if pages already exist
        existing_check = await session.execute(
            select(DocumentPage).where(DocumentPage.document_id == document_id).limit(1)
        )
        if existing_check.scalar_one_or_none():
            console_logger.info(f"⏭️ [{job_id}] Pages already exist for document {document_id}")
            pages_count_result = await session.execute(
                select(DocumentPage).where(DocumentPage.document_id == document_id)
            )
            existing_pages_count = len(pages_count_result.scalars().all())
            pages_metadata.append({
                "document_id": doc_pages_info["document_id"],
                "total_pages": existing_pages_count,
                "from_db": True
            })
            continue
        
        # Save pages
        for page_data in pages:
            page_number = page_data.get("page_number", 0)
            page_text = page_data.get("text", "")
            
            if not page_text.strip():
                continue
            
            page_record = DocumentPage(
                document_id=document_id,
                page_number=page_number,
                page_text=page_text
            )
            session.add(page_record)
            total_pages_saved += 1
        
        pages_metadata.append({
            "document_id": doc_pages_info["document_id"],
            "total_pages": len(pages),
            "from_db": False
        })
        console_logger.info(f"✅ [{job_id}] Saved {len(pages)} pages for document {document_id}")
    
    await session.commit()
    
    if total_pages_saved > 0:
        console_logger.info(f"✅ [{job_id}] Saved {total_pages_saved} pages total")
    
    resume_data["pages_metadata"] = pages_metadata
    resume_data["pages_saved"] = total_pages_saved
    
    return resume_data


async def _step_creating_embeddings(
    session: AsyncSession,
    project_id: str,
    job_id: str,
    resume_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Step 6: Create embeddings from extracted_data (complete text) and metadata.
    Loads data from DB if not in resume_data (for resume scenarios).
    """
    if not embeddings_service.is_configured():
        console_logger.warning(f"⚠️ Embeddings service not configured, skipping")
        return resume_data
    
    saved_docs = resume_data.get("uploaded_documents", [])
    extractions = resume_data.get("extractions", [])
    
    # If no extractions in resume_data, load from DB
    if not extractions:
        console_logger.info(f"📦 [{job_id}] Loading extraction results from DB...")
        for doc_info in saved_docs:
            document_id = uuid.UUID(doc_info["id"])
            ext_result = await session.execute(
                select(ExtractionResult).where(ExtractionResult.document_id == document_id)
            )
            extraction = ext_result.scalar_one_or_none()
            if extraction:
                # Get complete text from extracted_data
                extracted_data = extraction.extracted_data
                
                # Handle different formats - JSONB can store strings in different ways
                complete_text = ""
                if extracted_data is None:
                    complete_text = ""
                elif isinstance(extracted_data, str):
                    # Check if it's a JSON-encoded string (starts/ends with quotes)
                    if len(extracted_data) > 1 and extracted_data.startswith('"') and extracted_data.endswith('"'):
                        try:
                            # It's a JSON string, decode it
                            complete_text = json.loads(extracted_data)
                        except (json.JSONDecodeError, ValueError):
                            # Not valid JSON, use as-is (remove outer quotes if present)
                            complete_text = extracted_data.strip('"')
                    else:
                        complete_text = extracted_data
                elif isinstance(extracted_data, dict):
                    complete_text = extracted_data.get("complete_text", "")
                else:
                    # Convert to string
                    complete_text = str(extracted_data) if extracted_data else ""
                
                console_logger.info(
                    f"✅ [{job_id}] Loaded extraction from DB for document {doc_info['id']}: "
                    f"text_length={len(complete_text)}, type={type(extracted_data).__name__}"
                )
                
                if not complete_text or not complete_text.strip():
                    console_logger.warning(
                        f"⚠️ [{job_id}] Extraction loaded but text is empty for document {doc_info['id']}. "
                        f"extracted_data type: {type(extracted_data).__name__}, "
                        f"preview: {str(extracted_data)[:200] if extracted_data else 'None'}"
                    )
                
                extractions.append({
                    "document_id": doc_info["id"],
                    "data": complete_text,  # Complete raw text
                    "metadata": extraction.extraction_metadata or {}
                })
    
    if not extractions and not saved_docs:
        console_logger.warning(f"⚠️ [{job_id}] No documents or extractions for embeddings")
        return resume_data
    
    # Determine documents to process
    documents_to_process = []
    if extractions:
        for extraction in extractions:
            doc_id = extraction["document_id"]
            doc_info = next((d for d in saved_docs if d["id"] == doc_id), None)
            documents_to_process.append({
                "document_id": doc_id,
                "label": doc_info.get("label", "Unknown") if doc_info else "Unknown",
                "extraction": extraction
            })
    elif saved_docs:
        for doc_info in saved_docs:
            documents_to_process.append({
                "document_id": doc_info["id"],
                "label": doc_info.get("label", "Unknown"),
                "extraction": None
            })
    
    if not documents_to_process:
        console_logger.warning(f"⚠️ [{job_id}] No documents for embeddings")
        return resume_data
    
    console_logger.info(f"🔢 [{job_id}] Creating embeddings for {len(documents_to_process)} document(s)...")
    
    await progress_tracker.emit(
        job_id=job_id,
        event_type="progress",
        message="Converting extracted text into searchable vectors...",
        step="creating_embeddings"
    )
    
    embeddings_data = []
    
    for doc_info in documents_to_process:
        document_id = uuid.UUID(doc_info["document_id"])
        
        # Check if embeddings from extracted_data already exist (field="complete_text")
        # We want to recreate embeddings from extracted_data, so check for complete_text chunks
        existing_complete_text_check = await session.execute(
            select(TextChunk)
            .join(DocumentPage)
            .where(
                DocumentPage.document_id == document_id,
                TextChunk.field == "complete_text"  # Check for new embeddings from extracted_data
            )
            .limit(1)
        )
        if existing_complete_text_check.scalar_one_or_none():
            console_logger.info(f"⏭️ [{job_id}] Embeddings from extracted_data already exist for document {document_id}")
            continue
        
        # Delete old page-based embeddings if they exist (we're switching to extracted_data embeddings)
        # This ensures we recreate embeddings from the complete extracted text
        old_chunks_result = await session.execute(
            select(TextChunk)
            .join(DocumentPage)
            .where(
                DocumentPage.document_id == document_id,
                TextChunk.field != "complete_text",  # Old embeddings
                TextChunk.field != "extraction_metadata"  # Keep metadata chunks if any
            )
        )
        old_chunks = old_chunks_result.scalars().all()
        if old_chunks:
            console_logger.info(f"🗑️ [{job_id}] Deleting {len(old_chunks)} old page-based embeddings, recreating from extracted_data...")
            # Delete associated embeddings first (cascade might handle this, but be explicit)
            for old_chunk in old_chunks:
                # Delete embedding if exists
                emb_result = await session.execute(
                    select(Embedding).where(Embedding.chunk_id == old_chunk.id)
                )
                old_embedding = emb_result.scalar_one_or_none()
                if old_embedding:
                    await session.delete(old_embedding)
                await session.delete(old_chunk)
            await session.flush()
        
        # Get extraction data (complete text + metadata)
        # Always try to load from DB first to ensure we have the latest data
        extraction = None
        extraction_record = None
        
        # Try to load from DB
        ext_result = await session.execute(
            select(ExtractionResult).where(ExtractionResult.document_id == document_id)
        )
        extraction_record = ext_result.scalar_one_or_none()
        
        if extraction_record:
            extracted_data = extraction_record.extracted_data
            
            # Handle different formats of extracted_data
            # JSONB can store strings in different ways depending on how it was inserted
            complete_text = ""
            if extracted_data is None:
                complete_text = ""
            elif isinstance(extracted_data, str):
                # Check if it's a JSON-encoded string (wrapped in quotes)
                trimmed = extracted_data.strip()
                if len(trimmed) > 1 and trimmed.startswith('"') and trimmed.endswith('"'):
                    try:
                        # It's a JSON string value, decode it
                        complete_text = json.loads(extracted_data)
                    except (json.JSONDecodeError, ValueError):
                        # Not valid JSON, try removing outer quotes manually
                        complete_text = trimmed[1:-1] if len(trimmed) > 1 else extracted_data
                else:
                    complete_text = extracted_data
            elif isinstance(extracted_data, dict):
                complete_text = extracted_data.get("complete_text", "")
            else:
                # Try to convert to string
                complete_text = str(extracted_data) if extracted_data else ""
            
            console_logger.info(
                f"📦 [{job_id}] Loaded extraction from DB for document {document_id}: "
                f"text_length={len(complete_text) if complete_text else 0}, "
                f"type={type(extracted_data).__name__}"
            )
            
            extraction = {
                "data": complete_text,
                "metadata": extraction_record.extraction_metadata or {}
            }
        else:
            # Fallback to resume_data extraction if DB doesn't have it
            extraction = doc_info.get("extraction")
            if extraction:
                console_logger.info(f"📦 [{job_id}] Using extraction from resume_data for document {document_id}")
        
        if not extraction:
            console_logger.warning(f"⚠️ [{job_id}] No extraction data found for document {document_id}")
            continue
        
        # Get complete text and metadata
        complete_text = extraction.get("data", "")
        if isinstance(complete_text, dict):
            complete_text = complete_text.get("complete_text", "")
        
        extraction_metadata = extraction.get("metadata", {})
        
        # Debug logging
        console_logger.info(
            f"📊 [{job_id}] Processing extraction for document {document_id}: "
            f"text_length={len(complete_text) if complete_text else 0}, "
            f"has_metadata={bool(extraction_metadata)}"
        )
        
        if not complete_text or not complete_text.strip():
            # Try to load from txt file as fallback
            console_logger.warning(
                f"⚠️ [{job_id}] Empty extraction text for document {document_id}. "
                f"Trying to load from txt file..."
            )
            
            # Try to find and read the extraction txt file
            logs_dir = Path(__file__).parent.parent.parent / "logs" / "extractions"
            project_dir = logs_dir / project_id if logs_dir.exists() else None
            
            if project_dir and project_dir.exists():
                # Find the most recent txt file for this document
                txt_files = list(project_dir.glob(f"*_{document_id[:8]}.txt"))
                if txt_files:
                    # Sort by modification time, get most recent
                    txt_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                    latest_file = txt_files[0]
                    
                    try:
                        console_logger.info(f"📄 [{job_id}] Reading extraction from txt file: {latest_file.name}")
                        with open(latest_file, "r", encoding="utf-8") as f:
                            file_content = f.read()
                        
                        # Extract complete text section from txt file
                        if "COMPLETE TEXT EXTRACTION" in file_content:
                            # Find the section and extract all page text
                            start_marker = "COMPLETE TEXT EXTRACTION"
                            start_idx = file_content.find(start_marker)
                            if start_idx != -1:
                                # Extract everything after the marker
                                complete_text = file_content[start_idx + len(start_marker):].strip()
                                # Remove any trailing metadata sections
                                if "=" * 80 in complete_text:
                                    complete_text = complete_text.split("=" * 80)[0].strip()
                                
                                console_logger.info(
                                    f"✅ [{job_id}] Loaded {len(complete_text)} characters from txt file"
                                )
                    except Exception as e:
                        console_logger.error(f"❌ [{job_id}] Failed to read txt file: {e}")
            
            # Debug logging
            if extraction_record:
                console_logger.warning(
                    f"⚠️ [{job_id}] Raw extracted_data from DB: "
                    f"type={type(extraction_record.extracted_data).__name__}, "
                    f"preview={str(extraction_record.extracted_data)[:500] if extraction_record.extracted_data else 'None'}"
                )
            
            if not complete_text or not complete_text.strip():
                console_logger.error(
                    f"❌ [{job_id}] Cannot create embeddings: No extraction text found in DB or txt file for document {document_id}"
                )
                continue
        
        # Get first page ID for linking chunks (required by schema)
        # We'll use first page as anchor, but mark chunks with field="complete_text"
        pages_result = await session.execute(
            select(DocumentPage).where(DocumentPage.document_id == document_id).order_by(DocumentPage.page_number).limit(1)
        )
        first_page = pages_result.scalar_one_or_none()
        
        if not first_page:
            console_logger.warning(f"⚠️ [{job_id}] No pages found for document {document_id}, cannot create embeddings")
            continue
        
        anchor_page_id = str(first_page.id)
        
        # Chunk the complete text (respects token limits)
        text_chunks = embeddings_service.chunk_text(complete_text)
        
        # Also create chunks from metadata if available
        metadata_chunks = []
        if extraction_metadata:
            # Convert metadata to text chunks
            metadata_text = json.dumps(extraction_metadata, indent=2, ensure_ascii=False)
            metadata_chunks = embeddings_service.chunk_text(metadata_text)
        
        # Combine all chunks
        all_chunks = []
        
        # Add metadata chunks first (with metadata flag)
        for chunk_idx, chunk_text in enumerate(metadata_chunks):
            all_chunks.append({
                "page_id": anchor_page_id,  # Use anchor page ID (required by schema)
                "page_number": None,
                "chunk_index": chunk_idx,
                "content": f"[METADATA] {chunk_text}",
                "field": "extraction_metadata",
                "is_metadata": True
            })
        
        # Add text chunks (from complete text)
        text_chunk_start_idx = len(all_chunks)
        for chunk_idx, chunk_text in enumerate(text_chunks):
            all_chunks.append({
                "page_id": anchor_page_id,  # Use anchor page ID (required by schema)
                "page_number": None,
                "chunk_index": text_chunk_start_idx + chunk_idx,
                "content": chunk_text,
                "field": "complete_text",  # Mark as complete text chunk
                "is_metadata": False
            })
        
        if not all_chunks:
            console_logger.warning(f"⚠️ [{job_id}] No chunks created for document {document_id}")
            continue
        
        console_logger.info(
            f"📦 [{job_id}] Created {len(all_chunks)} chunks "
            f"({len(metadata_chunks)} metadata + {len(text_chunks)} text) for document {document_id}"
        )
        
        await progress_tracker.emit(
            job_id=job_id,
            event_type="progress",
            message=f"Creating embeddings for {len(all_chunks)} chunks...",
            step="creating_embeddings",
            data={"document": doc_info["label"], "chunk_count": len(all_chunks)}
        )
        
        # Create and save embeddings sequentially (one by one) directly to DB
        # This avoids storing huge embedding vectors in resume_data
        console_logger.info(f"📊 [{job_id}] Creating and saving {len(all_chunks)} embeddings sequentially...")
        
        saved_count = 0
        failed_count = 0
        
        # Commit in batches to avoid connection timeouts
        commit_batch_size = 50
        
        for idx, chunk in enumerate(all_chunks, 1):
            try:
                # Create embedding for this chunk
                embedding_vector = await embeddings_service.create_embedding(chunk["content"])
                
                if embedding_vector:
                    # Save directly to database
                    try:
                        page_id_str = chunk.get("page_id")
                        if not page_id_str:
                            console_logger.warning(
                                f"⚠️ [{job_id}] Chunk {idx}/{len(all_chunks)} missing page_id, skipping"
                            )
                            failed_count += 1
                            continue
                        
                        page_id = uuid.UUID(page_id_str)
                        
                        # Create TextChunk
                        text_chunk = TextChunk(
                            page_id=page_id,
                            chunk_index=chunk.get("chunk_index", idx - 1),
                            content=chunk.get("content", ""),
                            field=chunk.get("field")
                        )
                        session.add(text_chunk)
                        await session.flush()
                        
                        # Create Embedding
                        embedding = Embedding(
                            chunk_id=text_chunk.id,
                            embedding=embedding_vector
                        )
                        session.add(embedding)
                        saved_count += 1
                        
                        # Commit in batches to avoid connection timeouts
                        if saved_count % commit_batch_size == 0:
                            try:
                                await session.commit()
                                console_logger.info(
                                    f"💾 [{job_id}] Committed batch: {saved_count} embeddings saved "
                                    f"({idx}/{len(all_chunks)} processed)"
                                )
                            except Exception as commit_error:
                                console_logger.error(
                                    f"❌ [{job_id}] Error committing batch: {commit_error}"
                                )
                                await session.rollback()
                                # Continue processing - embeddings are already saved in previous commits
                        
                        # Log progress every 50 chunks
                        if idx % 50 == 0 or idx == len(all_chunks):
                            console_logger.info(
                                f"✅ [{job_id}] Created and saved embedding {idx}/{len(all_chunks)} "
                                f"for document {document_id}"
                            )
                    except Exception as save_error:
                        console_logger.error(
                            f"❌ [{job_id}] Error saving embedding {idx}/{len(all_chunks)}: {save_error}"
                        )
                        failed_count += 1
                        await session.rollback()
                        # Continue with next chunk
                        continue
                else:
                    console_logger.warning(
                        f"⚠️ [{job_id}] Failed to create embedding for chunk {idx}/{len(all_chunks)}"
                    )
                    failed_count += 1
                
                # Small delay to avoid rate limits (if needed)
                if idx % 100 == 0:
                    await asyncio.sleep(0.1)
                    
            except Exception as e:
                console_logger.error(
                    f"❌ [{job_id}] Error creating embedding {idx}/{len(all_chunks)}: {e}"
                )
                failed_count += 1
                # Continue with next chunk even if one fails
                continue
        
        # Final commit for any remaining embeddings
        try:
            await session.commit()
            console_logger.info(
                f"💾 [{job_id}] Final commit: {saved_count} embeddings saved for document {document_id}"
            )
        except Exception as commit_error:
            console_logger.error(f"❌ [{job_id}] Error in final commit: {commit_error}")
            await session.rollback()
        
        console_logger.info(
            f"✅ [{job_id}] Completed embeddings for document {document_id}: "
            f"{saved_count} saved, {failed_count} failed out of {len(all_chunks)} total"
        )
        
        # Store only metadata in resume_data, not the actual embeddings
        embeddings_data.append({
            "document_id": doc_info["document_id"],
            "chunks_count": len(all_chunks),
            "saved_count": saved_count,
            "failed_count": failed_count
        })
    
    # Store only metadata, not actual embeddings
    resume_data["embeddings_data"] = embeddings_data
    console_logger.info(f"✅ [{job_id}] Embeddings created and saved for {len(embeddings_data)} documents")
    
    return resume_data


async def _step_saving_embeddings(
    session: AsyncSession,
    project_id: str,
    job_id: str,
    resume_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Step 7: Verify embeddings were saved (they're saved directly during creation now)"""
    embeddings_data = resume_data.get("embeddings_data", [])
    
    if not embeddings_data:
        console_logger.info(f"⚠️ [{job_id}] No embeddings metadata found")
        return resume_data
    
    console_logger.info(f"✅ [{job_id}] Verifying embeddings were saved to database...")
    
    await progress_tracker.emit(
        job_id=job_id,
        event_type="progress",
        message="Verifying embeddings in database...",
        step="saving_embeddings"
    )
    
    total_saved = 0
    docs_processed = 0
    
    for emb_data in embeddings_data:
        document_id = uuid.UUID(emb_data["document_id"])
        
        # Verify embeddings exist in database
        try:
            # Get actual count
            from sqlalchemy import func
            chunks_result = await session.execute(
                select(func.count(TextChunk.id))
                .join(DocumentPage)
                .where(DocumentPage.document_id == document_id)
            )
            actual_count = chunks_result.scalar() or 0
            
            expected_count = emb_data.get("saved_count", 0)
            
            if actual_count > 0:
                console_logger.info(
                    f"✅ [{job_id}] Verified {actual_count} embeddings saved for document {document_id} "
                    f"(expected: {expected_count})"
                )
                total_saved += actual_count
                docs_processed += 1
            else:
                console_logger.warning(
                    f"⚠️ [{job_id}] No embeddings found in DB for document {document_id}"
                )
                
        except Exception as e:
            console_logger.error(f"❌ [{job_id}] Error verifying embeddings for doc {document_id}: {e}")
            # Don't fail the step, just log the error
            continue
    
    console_logger.info(
        f"✅ [{job_id}] Verified {total_saved} embeddings from {docs_processed} documents"
    )
    
    # Update job stats
    await session.execute(
        update(ProcessingJob)
        .where(ProcessingJob.project_id == uuid.UUID(project_id))
        .values(
            embeddings_created=total_saved,
            documents_processed=docs_processed
        )
    )
    await session.commit()
    
    resume_data["embeddings_saved"] = True
    resume_data["embeddings_count"] = total_saved
    
    return resume_data


async def _step_generating_snapshot(
    session: AsyncSession,
    project_id: str,
    job_id: str,
    company_name: str,
    source_url: str,
    resume_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Step 8: Generate company snapshot"""
    if not snapshot_generator.is_configured():
        console_logger.warning(f"⚠️ Snapshot generator not configured, skipping")
        return resume_data
    
    extractions = resume_data.get("extractions", [])
    
    if not extractions:
        console_logger.warning(f"⚠️ [{job_id}] No extraction data for snapshot")
        return resume_data
    
    console_logger.info(f"📸 [{job_id}] Generating company snapshot...")
    
    await progress_tracker.emit(
        job_id=job_id,
        event_type="progress",
        message="Analyzing financial data with AI...",
        step="generating_snapshot"
    )
    
    # Use first extraction - load from DB if not in resume_data
    extracted_data = None
    if extractions and len(extractions) > 0:
        # Check if we have data field (might be removed for resume)
        if "data" in extractions[0]:
            extracted_data = extractions[0]["data"]
        else:
            # Load from DB
            document_id = uuid.UUID(extractions[0]["document_id"])
            ext_result = await session.execute(
                select(ExtractionResult).where(ExtractionResult.document_id == document_id)
            )
            extraction_record = ext_result.scalar_one_or_none()
            if extraction_record and extraction_record.extracted_data:
                # Handle JSONB string format
                if isinstance(extraction_record.extracted_data, str):
                    extracted_data = extraction_record.extracted_data
                else:
                    extracted_data = str(extraction_record.extracted_data)
    
    if not extracted_data:
        raise Exception(f"No extraction data available for snapshot generation. Document may not have been extracted yet.")
    
    # Generate snapshot - this will raise exception on failure (no silent fallback)
    snapshot_data = await snapshot_generator.generate_snapshot(
        extraction_data=extracted_data,
        company_name=company_name,
        source_url=source_url,
        project_id=project_id
    )
    
    # Save snapshot
    stmt = insert(CompanySnapshot).values(
        project_id=uuid.UUID(project_id),
        snapshot_data=snapshot_data,
        generated_at=datetime.utcnow(),
        version=1
    ).on_conflict_do_update(
        index_elements=["project_id"],
        set_={
            "snapshot_data": snapshot_data,
            "updated_at": datetime.utcnow(),
            "version": CompanySnapshot.version + 1
        }
    )
    
    await session.execute(stmt)
    await session.commit()
    
    console_logger.info(f"✅ [{job_id}] Snapshot generated and saved")
    
    await progress_tracker.emit(
        job_id=job_id,
        event_type="progress",
        message="Company snapshot created successfully!",
        step="generating_snapshot"
    )
    
    return resume_data
