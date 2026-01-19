"""
Projects API Router
"""
import asyncio
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db, Project, Document, CompanySnapshot
from app.schemas import (
    ProjectCreate, ProjectResponse, ProjectListResponse,
    ProjectStatusResponse, DocumentResponse, ProjectDetailResponse
)
from app.services import extract_company_name
from app.jobs import process_project, get_job_status
from app.core.logging import api_logger, console_logger

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_data: ProjectCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """Create a new project from a BSE India URL"""
    company_name = extract_company_name(project_data.source_url)
    console_logger.info(f"📝 Creating project for: {company_name}")
    
    # Check if exists
    existing = await db.execute(
        select(Project).where(Project.source_url == project_data.source_url)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Project with this URL already exists")
    
    project = Project(
        company_name=company_name,
        source_url=project_data.source_url,
        exchange="BSE",
        status="pending"
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    
    background_tasks.add_task(process_project, str(project.id), project_data.source_url)
    console_logger.info(f"✅ Project created: {project.id}")
    return project


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
    
    return ProjectDetailResponse(
        project=ProjectResponse.model_validate(project),
        documents=[DocumentResponse.model_validate(d) for d in project.documents],
        job_status=get_job_status(str(project_id))
    )


@router.get("/{project_id}/status", response_model=ProjectStatusResponse)
async def get_project_status(project_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get project status"""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectStatusResponse(project=project, job_status=get_job_status(str(project_id)))


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


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete a project"""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.delete(project)
    await db.commit()
