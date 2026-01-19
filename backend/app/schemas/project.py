"""
Pydantic schemas for Project API
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID
import re

from app.services.url_validator import validate_bse_url


class ProjectCreate(BaseModel):
    """Schema for creating a new project"""
    source_url: str = Field(
        ...,
        description="BSE India annual reports URL",
        examples=["https://www.bseindia.com/stock-share-price/vimta-labs-ltd/vimtalabs/524394/financials-annual-reports/"]
    )
    
    @field_validator('source_url')
    @classmethod
    def validate_source_url(cls, v: str) -> str:
        """Validate that the URL is a valid BSE India annual reports URL"""
        is_valid, error = validate_bse_url(v)
        if not is_valid:
            raise ValueError(error)
        return v.strip()


class ProjectResponse(BaseModel):
    """Schema for project response"""
    id: UUID
    company_name: str
    source_url: str
    exchange: str
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class ProjectListResponse(BaseModel):
    """Schema for listing projects"""
    projects: List[ProjectResponse]
    total: int


class ProjectStatusResponse(BaseModel):
    """Schema for project status with job info"""
    project: ProjectResponse
    job_status: Optional[dict] = None


class DocumentResponse(BaseModel):
    """Schema for document response"""
    id: UUID
    document_type: str
    fiscal_year: Optional[str] = None
    label: Optional[str] = None
    file_url: str
    original_url: Optional[str] = None
    page_count: Optional[int] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class ProjectDetailResponse(BaseModel):
    """Schema for project detail with documents"""
    project: ProjectResponse
    documents: List[DocumentResponse]
    job_status: Optional[dict] = None
