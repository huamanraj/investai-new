"""
Test Script: Process 13 Chunks for Existing Project
Creates embeddings and generates snapshot without modifying application
"""
import asyncio
import uuid
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, update
from app.db import (
    async_session_maker, Project, Document, DocumentPage,
    TextChunk, Embedding, CompanySnapshot, ProcessingJob
)
from app.services.embeddings import embeddings_service
from app.services.snapshot_generator import snapshot_generator
from app.core.logging import console_logger


# Project configuration
PROJECT_ID = "dbdd502d-46fa-46c2-9682-ea17f4e01eb2"
JOB_ID = "657c9f41-ad3b-4da0-bc4f-31114bd0cfcc"
COMPANY_NAME = "AETHER INDUSTRIES LTD"
CHUNKS_FOLDER = Path(__file__).parent / "chunks"  # Adjust path as needed


async def load_chunks_from_folder(folder_path: Path) -> List[Dict[str, Any]]:
    """Load chunk files from folder"""
    chunks = []
    
    if not folder_path.exists():
        console_logger.error(f"❌ Chunks folder not found: {folder_path}")
        return chunks
    
    # Find all chunk files
    chunk_files = sorted(folder_path.glob("chunk_*.txt"))
    
    if not chunk_files:
        console_logger.error(f"❌ No chunk files found in: {folder_path}")
        return chunks
    
    console_logger.info(f"📂 Found {len(chunk_files)} chunk files")
    
    for chunk_file in chunk_files:
        try:
            # Extract chunk number from filename
            chunk_num = int(chunk_file.stem.split("_")[1])
            
            # Read chunk content
            with open(chunk_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
            
            if content:
                chunks.append({
                    "chunk_index": chunk_num - 1,  # 0-indexed
                    "content": content,
                    "source_file": chunk_file.name
                })
                console_logger.info(f"✅ Loaded chunk {chunk_num}: {len(content)} chars")
        
        except Exception as e:
            console_logger.error(f"❌ Failed to load {chunk_file.name}: {e}")
    
    return chunks


async def get_or_create_document(session, project_id: uuid.UUID) -> uuid.UUID:
    """Get existing document or create a new one"""
    # Check for existing document
    result = await session.execute(
        select(Document).where(Document.project_id == project_id).limit(1)
    )
    document = result.scalar_one_or_none()
    
    if document:
        console_logger.info(f"📄 Using existing document: {document.id}")
        return document.id
    
    # Create new document
    document = Document(
        project_id=project_id,
        document_type="annual_report",
        label=f"{COMPANY_NAME} - Annual Report",
        file_url="test://chunks",
        original_url="test://chunks"
    )
    session.add(document)
    await session.flush()
    
    console_logger.info(f"📄 Created new document: {document.id}")
    return document.id


async def get_or_create_page(session, document_id: uuid.UUID) -> uuid.UUID:
    """Get existing page or create a new one"""
    # Check for existing page
    result = await session.execute(
        select(DocumentPage).where(DocumentPage.document_id == document_id).limit(1)
    )
    page = result.scalar_one_or_none()
    
    if page:
        console_logger.info(f"📄 Using existing page: {page.id}")
        return page.id
    
    # Create new page
    page = DocumentPage(
        document_id=document_id,
        page_number=1,
        page_text="Combined chunks from test data"
    )
    session.add(page)
    await session.flush()
    
    console_logger.info(f"📄 Created new page: {page.id}")
    return page.id


async def save_chunks_to_db(session, page_id: uuid.UUID, chunks: List[Dict[str, Any]]):
    """Save chunks to database"""
    console_logger.info(f"💾 Saving {len(chunks)} chunks to database...")
    
    saved_count = 0
    
    for chunk in chunks:
        # Check if chunk already exists
        result = await session.execute(
            select(TextChunk).where(
                TextChunk.page_id == page_id,
                TextChunk.chunk_index == chunk["chunk_index"]
            )
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            console_logger.info(f"⏭️ Chunk {chunk['chunk_index']} already exists")
            continue
        
        # Create new chunk
        text_chunk = TextChunk(
            page_id=page_id,
            chunk_index=chunk["chunk_index"],
            content=chunk["content"],
            field="test_chunks"
        )
        session.add(text_chunk)
        saved_count += 1
    
    await session.flush()
    console_logger.info(f"✅ Saved {saved_count} new chunks")


async def create_and_save_embeddings(session, page_id: uuid.UUID, chunks: List[Dict[str, Any]]):
    """Create embeddings and save to database"""
    if not embeddings_service.is_configured():
        console_logger.error("❌ Embeddings service not configured")
        return
    
    console_logger.info(f"🔢 Creating embeddings for {len(chunks)} chunks...")
    
    # Get chunks from database
    result = await session.execute(
        select(TextChunk).where(TextChunk.page_id == page_id).order_by(TextChunk.chunk_index)
    )
    db_chunks = result.scalars().all()
    
    if not db_chunks:
        console_logger.error("❌ No chunks found in database")
        return
    
    console_logger.info(f"📊 Creating embeddings with {embeddings_service.model}...")
    
    # Save embeddings to database
    console_logger.info(f"💾 Creating and saving embeddings one by one...")
    saved_count = 0
    
    for db_chunk in db_chunks:
        # Check if embedding already exists
        result = await session.execute(
            select(Embedding).where(Embedding.chunk_id == db_chunk.id)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            console_logger.info(f"⏭️ Embedding already exists for chunk {db_chunk.chunk_index}")
            continue
        
        # Create embedding for this chunk individually
        console_logger.info(f"🔢 Creating embedding for chunk {db_chunk.chunk_index} ({len(db_chunk.content)} chars)...")
        
        try:
            embedding_vector = await embeddings_service.create_embedding(db_chunk.content)
            
            if embedding_vector is None:
                console_logger.warning(f"⚠️ No embedding for chunk {db_chunk.chunk_index}")
                continue
            
            # Save embedding
            embedding = Embedding(
                chunk_id=db_chunk.id,
                embedding=embedding_vector
            )
            session.add(embedding)
            saved_count += 1
            
            # Commit after each embedding to avoid losing progress
            await session.flush()
            
            console_logger.info(f"✅ Saved embedding {saved_count}/{len(db_chunks)} for chunk {db_chunk.chunk_index}")
            
        except Exception as e:
            console_logger.error(f"❌ Failed to create embedding for chunk {db_chunk.chunk_index}: {e}")
            # Continue with next chunk instead of failing completely
            continue
    
    console_logger.info(f"✅ Saved {saved_count} new embeddings")
    
    return saved_count


async def generate_snapshot(session, project_id: uuid.UUID):
    """Generate company snapshot using existing embeddings"""
    if not snapshot_generator.is_configured():
        console_logger.error("❌ Snapshot generator not configured")
        return
    
    console_logger.info(f"📸 Generating company snapshot...")
    
    # Create basic extraction data
    extraction_data = {
        "company_name": COMPANY_NAME,
        "report_type": "Annual Report",
        "fiscal_year": None
    }
    
    # Generate snapshot
    snapshot_data = await snapshot_generator.generate_snapshot(
        extraction_data=extraction_data,
        company_name=COMPANY_NAME,
        source_url="test://chunks",
        project_id=str(project_id)
    )
    
    # Save or update snapshot
    result = await session.execute(
        select(CompanySnapshot).where(CompanySnapshot.project_id == project_id)
    )
    existing_snapshot = result.scalar_one_or_none()
    
    if existing_snapshot:
        console_logger.info(f"📝 Updating existing snapshot")
        existing_snapshot.snapshot_data = snapshot_data
        existing_snapshot.updated_at = datetime.utcnow()
        existing_snapshot.version += 1
    else:
        console_logger.info(f"📝 Creating new snapshot")
        snapshot = CompanySnapshot(
            project_id=project_id,
            snapshot_data=snapshot_data,
            generated_at=datetime.utcnow(),
            version=1
        )
        session.add(snapshot)
    
    await session.flush()
    console_logger.info(f"✅ Snapshot saved successfully")


async def update_job_status(session, job_id: str):
    """Update processing job status"""
    try:
        result = await session.execute(
            select(ProcessingJob).where(ProcessingJob.job_id == job_id)
        )
        job = result.scalar_one_or_none()
        
        if job:
            job.status = "completed"
            job.current_step = "completed"
            job.completed_at = datetime.utcnow()
            await session.flush()
            console_logger.info(f"✅ Updated job status to completed")
    except Exception as e:
        console_logger.warning(f"⚠️ Could not update job status: {e}")


async def main():
    """Main processing function"""
    console_logger.info("=" * 80)
    console_logger.info("🚀 Starting Chunks Processing Test Script")
    console_logger.info(f"📋 Project ID: {PROJECT_ID}")
    console_logger.info(f"🏢 Company: {COMPANY_NAME}")
    console_logger.info(f"📂 Chunks Folder: {CHUNKS_FOLDER}")
    console_logger.info("=" * 80)
    
    # Load chunks from folder
    chunks = await load_chunks_from_folder(CHUNKS_FOLDER)
    
    if not chunks:
        console_logger.error("❌ No chunks loaded. Exiting.")
        return
    
    console_logger.info(f"✅ Loaded {len(chunks)} chunks")
    
    # Process chunks
    async with async_session_maker() as session:
        try:
            project_uuid = uuid.UUID(PROJECT_ID)
            
            # Verify project exists
            result = await session.execute(
                select(Project).where(Project.id == project_uuid)
            )
            project = result.scalar_one_or_none()
            
            if not project:
                console_logger.error(f"❌ Project not found: {PROJECT_ID}")
                return
            
            console_logger.info(f"✅ Found project: {project.company_name}")
            
            # Get or create document and page
            document_id = await get_or_create_document(session, project_uuid)
            page_id = await get_or_create_page(session, document_id)
            
            # Save chunks to database
            await save_chunks_to_db(session, page_id, chunks)
            await session.commit()
            
            # Create and save embeddings
            embeddings_count = await create_and_save_embeddings(session, page_id, chunks)
            await session.commit()
            
            # Generate snapshot
            await generate_snapshot(session, project_uuid)
            await session.commit()
            
            # Update job status
            await update_job_status(session, JOB_ID)
            await session.commit()
            
            console_logger.info("=" * 80)
            console_logger.info("✅ Processing completed successfully!")
            console_logger.info(f"📊 Chunks saved: {len(chunks)}")
            console_logger.info(f"🔢 Embeddings created: {embeddings_count}")
            console_logger.info(f"📸 Snapshot generated: Yes")
            console_logger.info("=" * 80)
            
        except Exception as e:
            console_logger.error(f"❌ Error during processing: {e}")
            await session.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(main())
