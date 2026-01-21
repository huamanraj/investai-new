"""
Resumable Background Job Processor
Supports cancellation and resuming from the last successful step
Uses GPT-4o-mini for PDF extraction (replaced LlamaParse/LlamaExtract)
"""
import asyncio
import uuid
import aiohttp
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum

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
    gpt_pdf_extractor,  # New GPT-based extractor
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
                        resume_data = await _step_extracting_with_gpt(
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
                        # CRITICAL: Verify we have pages before creating embeddings
                        if not resume_data.get("pages") and not resume_data.get("pages_metadata"):
                            # Try to get pages from DB
                            pages_from_db = await _get_pages_from_db(session, project_id)
                            if pages_from_db:
                                resume_data["pages_metadata"] = pages_from_db
                            else:
                                raise Exception("No page data available for embeddings. Extraction step may have failed.")
                        resume_data = await _step_creating_embeddings(
                            session, project_id, job_id, resume_data
                        )
                    
                    elif step == JobStep.SAVING_EMBEDDINGS:
                        resume_data = await _step_saving_embeddings(
                            session, project_id, job_id, resume_data
                        )
                    
                    elif step == JobStep.GENERATING_SNAPSHOT:
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
    PDF buffers are excluded (too large), but all structured data is saved.
    """
    # Remove in-memory buffers before saving (too large for JSON)
    resume_data_clean = {
        k: v for k, v in resume_data.items() 
        if not k.startswith("_") and k != "pdf_buffers"
    }
    
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


async def _step_extracting_with_gpt(
    session: AsyncSession,
    project_id: str,
    job_id: str,
    company_name: str,
    resume_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Step 3: Extract COMPLETE text and structured data using GPT-4o-mini.
    
    This replaces both LlamaParse and LlamaExtract with a single GPT-based extraction.
    Ensures ALL text is extracted - nothing missing.
    """
    if not gpt_pdf_extractor.is_configured():
        raise Exception("OpenAI API is not configured. Cannot extract PDF content.")
    
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
        
        # Extract using configured OpenAI extraction model
        console_logger.info(
            f"📊 [{job_id}] Extracting with {getattr(gpt_pdf_extractor, 'extraction_model', 'openai')}: {doc_info['label']}..."
        )
        
        await progress_tracker.emit(
            job_id=job_id,
            event_type="progress",
            message=f"Extracting complete text from: {doc_info['label']} (this may take several minutes)...",
            step="extracting",
            data={"current": idx + 1, "total": len(saved_docs)}
        )
        
        extraction_result = await gpt_pdf_extractor.extract_from_pdf_buffer(
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
    
    # CRITICAL: Save extraction results to resume_data
    resume_data["extractions"] = extractions
    resume_data["pages"] = all_pages  # This is used for page saving and embeddings
    resume_data["parsed_pages"] = all_pages  # Legacy compatibility
    
    if not extractions and not all_pages:
        raise Exception("Failed to extract any content from PDFs")
    
    return resume_data


async def _step_saving_extraction(
    session: AsyncSession,
    project_id: str,
    job_id: str,
    resume_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Step 4: Save extraction results to database"""
    extractions = resume_data.get("extractions", [])
    
    if not extractions:
        console_logger.info(f"⚠️ [{job_id}] No extraction data to save")
        return resume_data
    
    console_logger.info(f"💾 [{job_id}] Saving {len(extractions)} extraction result(s)...")
    
    await progress_tracker.emit(
        job_id=job_id,
        event_type="progress",
        message=f"Saving extraction data to database...",
        step="saving_extraction"
    )
    
    for extraction in extractions:
        document_id = uuid.UUID(extraction["document_id"])
        
        # Check if already exists (resume scenario)
        existing = await session.execute(
            select(ExtractionResult).where(ExtractionResult.document_id == document_id)
        )
        if existing.scalar_one_or_none():
            console_logger.info(f"⏭️ [{job_id}] Extraction already saved for document {document_id}")
            continue
        
        extracted_data = extraction["data"]
        
        extraction_record = ExtractionResult(
            document_id=document_id,
            extracted_data=extracted_data,
            extraction_metadata=extraction.get("metadata", {}),
            company_name=extracted_data.get("company_name"),
            fiscal_year=extracted_data.get("fiscal_year"),
            revenue=extracted_data.get("revenue"),
            net_profit=extracted_data.get("net_profit")
        )
        session.add(extraction_record)
    
    await session.commit()
    console_logger.info(f"✅ [{job_id}] Extraction results saved")
    
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
    """Step 6: Create embeddings from page text"""
    if not embeddings_service.is_configured():
        console_logger.warning(f"⚠️ Embeddings service not configured, skipping")
        return resume_data
    
    pages_metadata = resume_data.get("pages_metadata", [])
    saved_docs = resume_data.get("uploaded_documents", [])
    
    # Determine documents to process
    documents_to_process = []
    if pages_metadata:
        for meta in pages_metadata:
            documents_to_process.append({
                "document_id": meta["document_id"],
                "label": next((d.get("label", "") for d in saved_docs if d["id"] == meta["document_id"]), "Unknown")
            })
    elif saved_docs:
        for doc_info in saved_docs:
            documents_to_process.append({
                "document_id": doc_info["id"],
                "label": doc_info.get("label", "Unknown")
            })
    
    if not documents_to_process:
        console_logger.warning(f"⚠️ [{job_id}] No documents for embeddings")
        return resume_data
    
    console_logger.info(f"🔢 [{job_id}] Creating embeddings for {len(documents_to_process)} document(s)...")
    
    await progress_tracker.emit(
        job_id=job_id,
        event_type="progress",
        message="Converting text into searchable vectors...",
        step="creating_embeddings"
    )
    
    embeddings_data = []
    
    for doc_info in documents_to_process:
        document_id = uuid.UUID(doc_info["document_id"])
        
        # Fetch pages from database
        pages_result = await session.execute(
            select(DocumentPage).where(DocumentPage.document_id == document_id).order_by(DocumentPage.page_number)
        )
        db_pages = pages_result.scalars().all()
        
        if not db_pages:
            console_logger.warning(f"⚠️ [{job_id}] No pages found for document {document_id}")
            continue
        
        # Check if embeddings already exist
        first_page = db_pages[0]
        existing_chunks = await session.execute(
            select(TextChunk).where(TextChunk.page_id == first_page.id).limit(1)
        )
        if existing_chunks.scalar_one_or_none():
            console_logger.info(f"⏭️ [{job_id}] Embeddings already exist for document {document_id}")
            continue
        
        # Chunk all pages
        all_chunks = []
        for page in db_pages:
            if not page.page_text or not page.page_text.strip():
                continue
            
            page_chunks = embeddings_service.chunk_text(page.page_text)
            
            for chunk_idx, chunk_text in enumerate(page_chunks):
                all_chunks.append({
                    "page_id": str(page.id),
                    "page_number": page.page_number,
                    "chunk_index": chunk_idx,
                    "content": chunk_text
                })
        
        if not all_chunks:
            continue
        
        console_logger.info(f"📦 [{job_id}] Created {len(all_chunks)} chunks from {len(db_pages)} pages")
        
        await progress_tracker.emit(
            job_id=job_id,
            event_type="progress",
            message=f"Creating embeddings for {len(all_chunks)} chunks...",
            step="creating_embeddings",
            data={"document": doc_info["label"], "chunk_count": len(all_chunks)}
        )
        
        # Create embeddings
        chunk_contents = [chunk["content"] for chunk in all_chunks]
        embeddings_list = await embeddings_service.create_embeddings_batch(
            texts=chunk_contents,
            project_id=project_id
        )
        
        embeddings_data.append({
            "document_id": doc_info["document_id"],
            "chunks": all_chunks,
            "embeddings": [
                emb if emb else None
                for emb in embeddings_list
            ]
        })
    
    resume_data["embeddings_data"] = embeddings_data
    console_logger.info(f"✅ [{job_id}] Embeddings created for {len(embeddings_data)} documents")
    
    return resume_data


async def _step_saving_embeddings(
    session: AsyncSession,
    project_id: str,
    job_id: str,
    resume_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Step 7: Save embeddings to database"""
    embeddings_data = resume_data.get("embeddings_data", [])
    
    if not embeddings_data:
        console_logger.info(f"⚠️ [{job_id}] No embeddings to save")
        return resume_data
    
    console_logger.info(f"💾 [{job_id}] Saving embeddings to database...")
    
    await progress_tracker.emit(
        job_id=job_id,
        event_type="progress",
        message="Saving embeddings to vector database...",
        step="saving_embeddings"
    )
    
    total_saved = 0
    docs_processed = 0
    
    for emb_data in embeddings_data:
        document_id = uuid.UUID(emb_data["document_id"])
        
        # Check if embeddings already exist
        existing_check = await session.execute(
            select(TextChunk)
            .join(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .limit(1)
        )
        if existing_check.scalar_one_or_none():
            console_logger.info(f"⏭️ [{job_id}] Embeddings already saved for document {document_id}")
            continue
        
        try:
            chunks = emb_data.get("chunks", [])
            embeddings = emb_data.get("embeddings", [])
            
            pair_count = min(len(chunks), len(embeddings))
            
            for i in range(pair_count):
                chunk_data = chunks[i]
                embedding_vector = embeddings[i]
                
                if embedding_vector is None:
                    continue
                
                page_id_str = chunk_data.get("page_id")
                if not page_id_str:
                    continue
                
                page_id = uuid.UUID(page_id_str)
                
                text_chunk = TextChunk(
                    page_id=page_id,
                    chunk_index=chunk_data.get("chunk_index", i),
                    content=chunk_data.get("content", ""),
                    field=chunk_data.get("field")
                )
                session.add(text_chunk)
                await session.flush()
                
                embedding = Embedding(
                    chunk_id=text_chunk.id,
                    embedding=embedding_vector
                )
                session.add(embedding)
                total_saved += 1
            
            docs_processed += 1
            
            await progress_tracker.emit(
                job_id=job_id,
                event_type="progress",
                message=f"Saved embeddings {docs_processed}/{len(embeddings_data)}",
                step="saving_embeddings",
                data={"saved": total_saved}
            )
            
        except Exception as e:
            console_logger.error(f"❌ [{job_id}] Error saving embeddings for doc {document_id}: {e}")
            await session.rollback()
            raise
    
    await session.commit()
    console_logger.info(f"✅ [{job_id}] Saved {total_saved} embeddings from {docs_processed} documents")
    
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
    
    # Use first extraction
    extracted_data = extractions[0]["data"]
    
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
