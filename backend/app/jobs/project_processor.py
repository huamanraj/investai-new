"""
Background job for processing projects
Handles: Scraping → Downloading → Cloudinary Upload → LlamaExtract → Embeddings → Snapshot → Database Storage
Complete workflow:
  1. Scrape BSE India page for PDF links
  2. Download PDF in memory
  3. Upload to Cloudinary
  4. Extract structured data using LlamaExtract
  5. Save extraction results to database
  6. Create embeddings from extracted data
  7. Save chunks and embeddings to database
  8. Generate company snapshot using GPT
"""
import asyncio
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from app.db import async_session_maker, Project, Document, ProjectStatus, ExtractionResult, TextChunk, Embedding, DocumentPage, CompanySnapshot
from app.services import (
    scraper, 
    cloudinary_service, 
    extract_company_name,
    llama_extract_service,
    embeddings_service,
    snapshot_generator
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
    4. Extract structured data using LlamaExtract
    5. Save extraction results to database
    6. Create embeddings from extracted data
    7. Save chunks and embeddings to database
    8. Generate company snapshot using GPT
    
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
            extraction_results = []
            
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
                    continue
                
                # Create document record first (needed for foreign keys)
                document = Document(
                    project_id=uuid.UUID(project_id),
                    document_type="annual_report",
                    fiscal_year=str(pdf_info.year) if pdf_info.year else None,
                    label=pdf_info.label,
                    file_url=file_url,
                    original_url=pdf_info.url
                )
                
                session.add(document)
                await session.flush()  # Get document.id before proceeding
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
                
                # Step 3: Extract structured data using LlamaExtract
                extraction_result = None
                extraction_db_record = None
                
                if llama_extract_service.is_configured():
                    await _update_project_status(session, project_id, ProjectStatus.PROCESSING)
                    _running_jobs[project_id]["status"] = "extracting"
                    
                    console_logger.info(f"📊 [Job {job_id}] Extracting data from {pdf_info.label}...")
                    
                    extraction_result = await llama_extract_service.extract_from_pdf(
                        pdf_buffer=pdf_info.pdf_buffer,
                        filename=f"{company_name}_{pdf_info.label}.pdf",
                        project_id=project_id
                    )
                    
                    if extraction_result.get("success"):
                        extraction_results.append(extraction_result)
                        console_logger.info(f"✅ [Job {job_id}] Extraction complete for {pdf_info.label}")
                        
                        # Save extraction result to database
                        extracted_data = extraction_result.get("data", {})
                        extraction_db_record = ExtractionResult(
                            document_id=document.id,
                            extracted_data=extracted_data,
                            extraction_metadata=extraction_result.get("metadata", {}),
                            company_name=extracted_data.get("company_name"),
                            fiscal_year=extracted_data.get("fiscal_year"),
                            revenue=extracted_data.get("revenue"),
                            net_profit=extracted_data.get("net_profit")
                        )
                        session.add(extraction_db_record)
                        await session.flush()
                        
                        console_logger.info(f"💾 [Job {job_id}] Extraction result saved to database")
                        
                        # Step 4: Create embeddings from extracted data
                        if embeddings_service.is_configured():
                            _running_jobs[project_id]["status"] = "creating_embeddings"
                            console_logger.info(f"🔢 [Job {job_id}] Creating embeddings for {pdf_info.label}...")
                            
                            try:
                                # Convert extraction data into chunks
                                chunks_data = embeddings_service.chunk_extraction_data(extracted_data)
                                
                                if chunks_data:
                                    console_logger.info(f"📦 [Job {job_id}] Created {len(chunks_data)} chunks from extraction")
                                    
                                    # Extract just the content for embedding
                                    chunk_contents = [chunk["content"] for chunk in chunks_data]
                                    
                                    # Create embeddings in batch
                                    embeddings_list = await embeddings_service.create_embeddings_batch(
                                        texts=chunk_contents,
                                        project_id=project_id
                                    )
                                    
                                    # Save chunks and embeddings to database
                                    # Note: We don't have page_id, so we'll link directly to document via a workaround
                                    # Create a dummy page for extracted data
                                    dummy_page = DocumentPage(
                                        document_id=document.id,
                                        page_number=0,  # 0 = extracted structured data
                                        page_text="Structured data extracted by LlamaExtract"
                                    )
                                    session.add(dummy_page)
                                    await session.flush()
                                    
                                    chunks_saved = 0
                                    for chunk_data, embedding_vector in zip(chunks_data, embeddings_list):
                                        if embedding_vector is None:
                                            continue
                                        
                                        # Create chunk
                                        text_chunk = TextChunk(
                                            page_id=dummy_page.id,
                                            chunk_index=chunk_data["chunk_index"],
                                            content=chunk_data["content"],
                                            field=chunk_data.get("field")
                                        )
                                        session.add(text_chunk)
                                        await session.flush()
                                        
                                        # Create embedding
                                        embedding = Embedding(
                                            chunk_id=text_chunk.id,
                                            embedding=embedding_vector
                                        )
                                        session.add(embedding)
                                        chunks_saved += 1
                                    
                                    console_logger.info(
                                        f"✅ [Job {job_id}] Saved {chunks_saved} chunks with embeddings"
                                    )
                                    job_logger.info(
                                        f"Embeddings created and saved",
                                        project_id=project_id,
                                        job_id=job_id,
                                        data={
                                            "chunks_created": chunks_saved,
                                            "document_label": pdf_info.label
                                        }
                                    )
                                else:
                                    console_logger.warning(
                                        f"⚠️ [Job {job_id}] No chunks created from extraction data"
                                    )
                            
                            except Exception as e:
                                console_logger.error(
                                    f"❌ [Job {job_id}] Embedding creation failed: {e}"
                                )
                                job_logger.error(
                                    f"Embedding creation failed",
                                    project_id=project_id,
                                    job_id=job_id,
                                    data={"error": str(e)}
                                )
                                # Don't fail the entire job, just log the error
                        else:
                            console_logger.warning(
                                f"⚠️ [Job {job_id}] OpenAI not configured, skipping embeddings"
                            )
                    else:
                        console_logger.warning(
                            f"⚠️ [Job {job_id}] Extraction failed for {pdf_info.label}: "
                            f"{extraction_result.get('error', 'Unknown error')}"
                        )
                else:
                    console_logger.warning(
                        f"⚠️ [Job {job_id}] LlamaExtract not configured, skipping extraction"
                    )
            
            await session.commit()
            
            if documents_created == 0:
                await _fail_project(
                    session, project_id, job_id,
                    "Failed to upload any documents to Cloudinary"
                )
                return
            
            # Step 5: Generate Company Snapshot (if we have at least one successful extraction)
            if extraction_results and snapshot_generator.is_configured():
                _running_jobs[project_id]["status"] = "generating_snapshot"
                console_logger.info(f"📸 [Job {job_id}] Generating company snapshot...")
                
                try:
                    # Use the first successful extraction for snapshot
                    first_extraction = extraction_results[0]
                    extracted_data = first_extraction.get("data", {})
                    
                    # Generate snapshot using GPT
                    snapshot_data = await snapshot_generator.generate_snapshot(
                        extraction_data=extracted_data,
                        company_name=company_name,
                        source_url=source_url,
                        project_id=project_id
                    )
                    
                    # Save snapshot to database
                    snapshot = CompanySnapshot(
                        project_id=uuid.UUID(project_id),
                        snapshot_data=snapshot_data
                    )
                    
                    # Upsert (update if exists, insert if not)
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
                    
                    console_logger.info(f"✅ [Job {job_id}] Company snapshot generated and saved")
                    job_logger.info(
                        "Company snapshot generated",
                        project_id=project_id,
                        job_id=job_id,
                        data={"company_name": company_name}
                    )
                
                except Exception as e:
                    console_logger.error(f"❌ [Job {job_id}] Snapshot generation failed: {e}")
                    job_logger.error(
                        "Snapshot generation failed",
                        project_id=project_id,
                        job_id=job_id,
                        data={"error": str(e)}
                    )
                    # Don't fail the entire job
            else:
                if not extraction_results:
                    console_logger.warning(
                        f"⚠️ [Job {job_id}] No successful extractions, skipping snapshot"
                    )
                else:
                    console_logger.warning(
                        f"⚠️ [Job {job_id}] Snapshot generator not configured, skipping"
                    )
            
            # Step 6: Mark project as completed
            await _update_project_status(session, project_id, ProjectStatus.COMPLETED)
            _running_jobs[project_id]["status"] = "completed"
            _running_jobs[project_id]["completed_at"] = datetime.utcnow().isoformat()
            _running_jobs[project_id]["documents_created"] = documents_created
            _running_jobs[project_id]["extractions_completed"] = len(extraction_results)
            
            console_logger.info(
                f"✅ [Job {job_id}] Project processing completed! "
                f"Created {documents_created} document(s), "
                f"Extracted {len(extraction_results)} document(s)"
            )
            job_logger.info(
                f"Project processing completed",
                project_id=project_id,
                job_id=job_id,
                data={
                    "documents_created": documents_created,
                    "extractions_completed": len(extraction_results)
                }
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
