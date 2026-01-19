"""
SQLAlchemy models matching the database schema
"""
import uuid
from datetime import datetime
from typing import List, Optional
from sqlalchemy import (
    Column, String, Text, DateTime, Integer, ForeignKey, Enum, ARRAY, Numeric
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from enum import Enum as PyEnum

from app.db.database import Base


class ProjectStatus(str, PyEnum):
    """Project processing status"""
    PENDING = "pending"
    SCRAPING = "scraping"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Project(Base):
    """Company project - each BSE company = 1 project"""
    __tablename__ = "projects"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name = Column(Text, nullable=False)
    source_url = Column(Text, nullable=False)
    exchange = Column(String(10), default="BSE")
    status = Column(String(20), default=ProjectStatus.PENDING.value)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    documents = relationship("Document", back_populates="project", cascade="all, delete-orphan")


class Document(Base):
    """Annual reports, presentations, transcripts etc."""
    __tablename__ = "documents"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    document_type = Column(String(50), nullable=False)  # annual_report, presentation, transcript
    fiscal_year = Column(String(20), nullable=True)  # FY2022, FY2023, etc.
    label = Column(Text, nullable=True)  # e.g., "2024-25 (Revised)"
    file_url = Column(Text, nullable=False)  # Cloudinary URL
    original_url = Column(Text, nullable=True)  # Original BSE URL
    page_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    project = relationship("Project", back_populates="documents")
    pages = relationship("DocumentPage", back_populates="document", cascade="all, delete-orphan")
    extraction_results = relationship("ExtractionResult", back_populates="document", cascade="all, delete-orphan")


class ExtractionResult(Base):
    """Structured data extracted from documents via LlamaExtract"""
    __tablename__ = "extraction_results"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    extracted_data = Column(JSONB, nullable=False)  # Full extraction result
    extraction_metadata = Column(JSONB, nullable=True)  # Citations, reasoning, etc.
    company_name = Column(Text, nullable=True)
    fiscal_year = Column(Text, nullable=True)
    revenue = Column(Numeric, nullable=True)
    net_profit = Column(Numeric, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    document = relationship("Document", back_populates="extraction_results")


class DocumentPage(Base):
    """1 row = 1 PDF page - VERY IMPORTANT for accuracy"""
    __tablename__ = "document_pages"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_number = Column(Integer, nullable=False)
    page_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    document = relationship("Document", back_populates="pages")
    chunks = relationship("TextChunk", back_populates="page", cascade="all, delete-orphan")


class TextChunk(Base):
    """Searchable text chunks inside a page"""
    __tablename__ = "text_chunks"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    page_id = Column(UUID(as_uuid=True), ForeignKey("document_pages.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    field = Column(String(100), nullable=True)  # Source field (e.g., "financial_highlights", "risk_factors")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    page = relationship("DocumentPage", back_populates="chunks")
    embedding = relationship("Embedding", back_populates="chunk", uselist=False, cascade="all, delete-orphan")


class Embedding(Base):
    """Vector embeddings for text chunks (pgvector)"""
    __tablename__ = "embeddings"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chunk_id = Column(UUID(as_uuid=True), ForeignKey("text_chunks.id", ondelete="CASCADE"), nullable=False)
    embedding = Column(Vector(3072), nullable=False)  # OpenAI text-embedding-3-large
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    chunk = relationship("TextChunk", back_populates="embedding")


class Chat(Base):
    """Chat sessions"""
    __tablename__ = "chats"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan")


class Message(Base):
    """Chat messages with project toggles"""
    __tablename__ = "messages"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id = Column(UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(10), nullable=False)  # user / ai
    content = Column(Text, nullable=False)
    project_ids = Column(ARRAY(UUID(as_uuid=True)), nullable=False)  # Toggles ON at that time
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    chat = relationship("Chat", back_populates="messages")


class CompanySnapshot(Base):
    """Pre-computed company summary for fast UI rendering"""
    __tablename__ = "company_snapshots"
    
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    snapshot_data = Column(JSONB, nullable=False, default={})  # Complete snapshot JSON
    generated_at = Column(DateTime, default=datetime.utcnow)
    version = Column(Integer, default=1)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

