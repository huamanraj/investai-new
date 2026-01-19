"""
Resumable Background Job Processor
Supports cancellation and resuming from the last successful step
"""
import asyncio
import uuid
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
    cloudinary_service, 
    extract_company_name,
    llama_extract_service,
    embeddings_service,
    snapshot_generator
)
from app.core.logging import job_logger, console_logger
from app.services.progress_tracker import progress_tracker


class JobStep(str, Enum):
    """Job processing steps"""
    SCRAPING = "scraping"
    DOWNLOADING = "downloading"
    UPLOADING = "uploading"
    EXTRACTING = "extracting"
    SAVING_EXTRACTION = "saving_extraction"
    CREATING_EMBEDDINGS = "creating_embeddings"
    SAVING_EMBEDDINGS = "saving_embeddings"
    GENERATING_SNAPSHOT = "generating_snapshot"
    COMPLETED = "completed"


STEP_ORDER = [
    JobStep.SCRAPING,
    JobStep.DOWNLOADING,
    JobStep.UPLOADING,
    JobStep.EXTRACTING,
    JobStep.SAVING_EXTRACTION,
    JobStep.CREATING_EMBEDDINGS,
    JobStep.SAVING_EMBEDDINGS,
    JobStep.GENERATING_SNAPSHOT,
    JobStep.COMPLETED
]


async def process_project_resumable(project_id: str, source_url: str, resume: bool = False):
    """
    Resumable background job to process a project.
    
    Args:
        project_id: UUID of the project
        source_url: BSE India annual reports URL
        resume: Whether this is a resume operation
    """
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
            else:
                job_id = str(uuid.uuid4())[:8]
                job = await _create_job(session, project_id, job_id)
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
                except (ValueError, IndexError):
                    start_step_index = 0
            
            # Resume data storage
            resume_data = job.resume_data or {}
            
            # Execute steps
            for step_index in range(start_step_index, len(STEP_ORDER)):
                step = STEP_ORDER[step_index]
                
                # Check if job was cancelled
                await session.refresh(job)
                if job.status == "cancelled":
                    console_logger.warning(f"⚠️ Job {job_id} was cancelled")
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
                        # Already done in scraping (PDF buffer available)
                        pass
                    
                    elif step == JobStep.UPLOADING:
                        resume_data = await _step_uploading(
                            session, project_id, job_id, company_name, resume_data
                        )
                    
                    elif step == JobStep.EXTRACTING:
                        resume_data = await _step_extracting(
                            session, project_id, job_id, company_name, resume_data
                        )
                    
                    elif step == JobStep.SAVING_EXTRACTION:
                        resume_data = await _step_saving_extraction(
                            session, project_id, job_id, resume_data
                        )
                    
                    elif step == JobStep.CREATING_EMBEDDINGS:
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
                                "embeddings_created": resume_data.get("embeddings_created", 0)
                            }
                        )
                        
                        # Cleanup progress after a delay
                        await asyncio.sleep(5)
                        progress_tracker.cleanup_job(job_id)
                        return
                    
                    # Mark step as successful
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
                    
                    await _mark_job_failed(session, job.id, project_id, step, error_msg, resume_data)
                    
                    # Emit error event
                    await progress_tracker.emit(
                        job_id=job_id,
                        event_type="error",
                        message=f"Failed at {step.value.replace('_', ' ').title()}: {error_msg}",
                        step=step.value,
                        step_index=step_index,
                        total_steps=len(STEP_ORDER),
                        data={"error": error_msg, "can_resume": True}
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
        
        return True


# Helper functions for each step

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
    # Note: Job status may be "running" if the API endpoint already reset it for resume
    result = await session.execute(
        select(ProcessingJob).where(
            ProcessingJob.project_id == uuid.UUID(project_id)
        ).order_by(ProcessingJob.updated_at.desc())
    )
    job = result.scalar_one_or_none()
    
    # Return job if it can be resumed (either explicitly resumable or running for resume)
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
    """Mark step as successful and save resume data"""
    await session.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job_id)
        .values(
            last_successful_step=step.value,
            resume_data=resume_data,
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
    """Mark job as failed"""
    await session.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job_id)
        .values(
            status="failed",
            failed_step=failed_step.value,
            error_message=error_message,
            can_resume=1,
            resume_data=resume_data,
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
        raise Exception(f"Scraping failed: {scrape_result.error}")
    
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
        message=f"Found {len(scrape_result.pdfs)} annual report(s). Downloading...",
        step="scraping",
        data={"pdf_count": len(scrape_result.pdfs)}
    )
    
    # Save PDF info to resume data
    resume_data["pdfs"] = [
        {
            "label": pdf.label,
            "url": pdf.url,
            "year": pdf.year,
            "has_buffer": pdf.pdf_buffer is not None,
            "buffer_size": len(pdf.pdf_buffer) if pdf.pdf_buffer else 0
        }
        for pdf in scrape_result.pdfs
    ]
    
    # Store actual PDF buffers (note: this could be large - consider external storage for production)
    resume_data["pdf_buffers"] = [
        pdf.pdf_buffer.hex() if pdf.pdf_buffer else None 
        for pdf in scrape_result.pdfs
    ]
    
    return resume_data


async def _step_uploading(
    session: AsyncSession,
    project_id: str,
    job_id: str,
    company_name: str,
    resume_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Step 3: Upload PDFs to Cloudinary"""
    await session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(project_id))
        .values(status=ProjectStatus.DOWNLOADING.value)
    )
    await session.commit()
    
    pdfs_info = resume_data.get("pdfs", [])
    pdf_buffers_hex = resume_data.get("pdf_buffers", [])
    
    console_logger.info(f"☁️ [{job_id}] Uploading {len(pdfs_info)} PDF(s) to Cloudinary...")
    
    await progress_tracker.emit(
        job_id=job_id,
        event_type="progress",
        message=f"Uploading {len(pdfs_info)} PDF(s) to cloud storage...",
        step="uploading",
        data={"total_pdfs": len(pdfs_info)}
    )
    
    uploaded_documents = []
    
    for idx, (pdf_info, buffer_hex) in enumerate(zip(pdfs_info, pdf_buffers_hex)):
        if not buffer_hex:
            continue
        
        # Convert hex back to bytes
        pdf_buffer = bytes.fromhex(buffer_hex)
        
        # Upload to Cloudinary
        success, file_url, error = await cloudinary_service.upload_pdf(
            pdf_buffer=pdf_buffer,
            company_name=company_name,
            fiscal_year=pdf_info["label"],
            project_id=project_id
        )
        
        if not success:
            console_logger.warning(f"⚠️ Upload failed for {pdf_info['label']}: {error}")
            continue
        
        # Create document record
        document = Document(
            project_id=uuid.UUID(project_id),
            document_type="annual_report",
            fiscal_year=str(pdf_info["year"]) if pdf_info["year"] else None,
            label=pdf_info["label"],
            file_url=file_url,
            original_url=pdf_info["url"]
        )
        
        session.add(document)
        await session.flush()
        
        await progress_tracker.emit(
            job_id=job_id,
            event_type="progress",
            message=f"Uploaded: {pdf_info['label']} ({idx + 1}/{len(pdfs_info)})",
            step="uploading",
            data={"current": idx + 1, "total": len(pdfs_info)}
        )
        
        uploaded_documents.append({
            "id": str(document.id),
            "label": pdf_info["label"],
            "file_url": file_url,
            "buffer_index": idx
        })
    
    await session.commit()
    
    if not uploaded_documents:
        raise Exception("Failed to upload any documents")
    
    resume_data["uploaded_documents"] = uploaded_documents
    return resume_data


async def _step_extracting(
    session: AsyncSession,
    project_id: str,
    job_id: str,
    company_name: str,
    resume_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Step 4: Extract data using LlamaExtract"""
    if not llama_extract_service.is_configured():
        console_logger.warning(f"⚠️ LlamaExtract not configured, skipping")
        return resume_data
    
    await session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(project_id))
        .values(status=ProjectStatus.PROCESSING.value)
    )
    await session.commit()
    
    uploaded_docs = resume_data.get("uploaded_documents", [])
    pdf_buffers_hex = resume_data.get("pdf_buffers", [])
    
    await progress_tracker.emit(
        job_id=job_id,
        event_type="progress",
        message=f"Starting AI-powered data extraction from {len(uploaded_docs)} document(s)...",
        step="extracting",
        data={"total_documents": len(uploaded_docs)}
    )
    
    extractions = []
    
    for doc_info in uploaded_docs:
        buffer_idx = doc_info["buffer_index"]
        buffer_hex = pdf_buffers_hex[buffer_idx]
        
        if not buffer_hex:
            continue
        
        pdf_buffer = bytes.fromhex(buffer_hex)
        
        console_logger.info(f"📊 [{job_id}] Extracting data from {doc_info['label']}...")
        
        await progress_tracker.emit(
            job_id=job_id,
            event_type="progress",
            message=f"Extracting: {doc_info['label']} (This may take 1-2 minutes)...",
            step="extracting"
        )
        
        extraction_result = await llama_extract_service.extract_from_pdf(
            pdf_buffer=pdf_buffer,
            filename=f"{company_name}_{doc_info['label']}.pdf",
            project_id=project_id
        )
        
        if extraction_result.get("success"):
            extractions.append({
                "document_id": doc_info["id"],
                "data": extraction_result.get("data", {}),
                "metadata": extraction_result.get("metadata", {})
            })
            console_logger.info(f"✅ [{job_id}] Extraction complete for {doc_info['label']}")
    
    if not extractions:
        console_logger.warning(f"⚠️ No successful extractions")
    
    resume_data["extractions"] = extractions
    return resume_data


async def _step_saving_extraction(
    session: AsyncSession,
    project_id: str,
    job_id: str,
    resume_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Step 5: Save extraction results to database"""
    extractions = resume_data.get("extractions", [])
    
    if not extractions:
        return resume_data
    
    console_logger.info(f"💾 [{job_id}] Saving {len(extractions)} extraction result(s)...")
    
    for extraction in extractions:
        extracted_data = extraction["data"]
        
        extraction_record = ExtractionResult(
            document_id=uuid.UUID(extraction["document_id"]),
            extracted_data=extracted_data,
            extraction_metadata=extraction["metadata"],
            company_name=extracted_data.get("company_name"),
            fiscal_year=extracted_data.get("fiscal_year"),
            revenue=extracted_data.get("revenue"),
            net_profit=extracted_data.get("net_profit")
        )
        session.add(extraction_record)
    
    await session.commit()
    console_logger.info(f"✅ [{job_id}] Extraction results saved")
    
    return resume_data


async def _step_creating_embeddings(
    session: AsyncSession,
    project_id: str,
    job_id: str,
    resume_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Step 6: Create embeddings from extraction data"""
    if not embeddings_service.is_configured():
        console_logger.warning(f"⚠️ Embeddings service not configured, skipping")
        return resume_data
    
    extractions = resume_data.get("extractions", [])
    
    if not extractions:
        return resume_data
    
    console_logger.info(f"🔢 [{job_id}] Creating embeddings...")
    
    await progress_tracker.emit(
        job_id=job_id,
        event_type="progress",
        message="Converting extracted data into searchable chunks...",
        step="creating_embeddings"
    )
    
    embeddings_data = []
    
    for extraction in extractions:
        extracted_data = extraction["data"]
        
        # Convert to chunks
        chunks_data = embeddings_service.chunk_extraction_data(extracted_data)
        
        if not chunks_data:
            continue
        
        console_logger.info(f"📦 [{job_id}] Created {len(chunks_data)} chunks")
        
        await progress_tracker.emit(
            job_id=job_id,
            event_type="progress",
            message=f"Creating vector embeddings for {len(chunks_data)} chunks...",
            step="creating_embeddings",
            data={"chunk_count": len(chunks_data)}
        )
        
        # Create embeddings
        chunk_contents = [chunk["content"] for chunk in chunks_data]
        embeddings_list = await embeddings_service.create_embeddings_batch(
            texts=chunk_contents,
            project_id=project_id
        )
        
        embeddings_data.append({
            "document_id": extraction["document_id"],
            "chunks": chunks_data,
            "embeddings": [
                emb.tolist() if hasattr(emb, 'tolist') else emb 
                for emb in embeddings_list if emb is not None
            ]
        })
    
    resume_data["embeddings_data"] = embeddings_data
    console_logger.info(f"✅ [{job_id}] Embeddings created")
    
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
        console_logger.info(f"⚠️ [{job_id}] No embeddings data to save")
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
        
        # Check if embeddings already exist for this document (resume scenario)
        existing_check = await session.execute(
            select(DocumentPage).where(DocumentPage.document_id == document_id)
        )
        existing_page = existing_check.scalar_one_or_none()
        
        if existing_page:
            # Check if embeddings exist for this page
            existing_embeddings = await session.execute(
                select(TextChunk).where(TextChunk.page_id == existing_page.id)
            )
            if existing_embeddings.scalars().first():
                console_logger.info(f"⏭️ [{job_id}] Embeddings already exist for document {document_id}, skipping")
                continue
        
        try:
            # Create dummy page for structured data
            dummy_page = DocumentPage(
                document_id=document_id,
                page_number=0,
                page_text="Structured data extracted by LlamaExtract"
            )
            session.add(dummy_page)
            await session.flush()
            
            chunks = emb_data.get("chunks", [])
            embeddings = emb_data.get("embeddings", [])
            
            if len(chunks) != len(embeddings):
                console_logger.warning(
                    f"⚠️ [{job_id}] Chunk/embedding count mismatch for doc {document_id}: "
                    f"{len(chunks)} chunks vs {len(embeddings)} embeddings"
                )
                # Use minimum to avoid index errors
                pair_count = min(len(chunks), len(embeddings))
            else:
                pair_count = len(chunks)
            
            # Save chunks and embeddings
            for i in range(pair_count):
                chunk_data = chunks[i]
                embedding_vector = embeddings[i]
                
                text_chunk = TextChunk(
                    page_id=dummy_page.id,
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
                message=f"Saved embeddings for document {docs_processed}/{len(embeddings_data)}",
                step="saving_embeddings",
                data={"saved": total_saved, "docs": docs_processed}
            )
            
        except Exception as e:
            console_logger.error(f"❌ [{job_id}] Error saving embeddings for doc {document_id}: {e}")
            # Rollback this document's changes and continue with others
            await session.rollback()
            raise  # Re-raise to trigger job failure and allow resume
    
    await session.commit()
    console_logger.info(f"✅ [{job_id}] Saved {total_saved} embeddings from {docs_processed} documents")
    
    # Update job progress
    await session.execute(
        update(ProcessingJob)
        .where(ProcessingJob.project_id == uuid.UUID(project_id))
        .values(
            embeddings_created=total_saved,
            documents_processed=docs_processed
        )
    )
    await session.commit()
    
    # Mark embeddings as saved in resume data
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
