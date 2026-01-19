-- Migration: Add job tracking for resumable background processing
-- Stores detailed job state, progress, and allows resume/cancel operations

CREATE TABLE IF NOT EXISTS processing_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id VARCHAR(50) NOT NULL UNIQUE,  -- Short job identifier (8 chars)
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed, cancelled
    current_step VARCHAR(50),  -- scraping, downloading, extracting, embedding, snapshot
    current_step_index INTEGER DEFAULT 0,
    total_steps INTEGER DEFAULT 8,
    
    -- Progress tracking
    progress_data JSONB DEFAULT '{}',  -- Detailed progress info for each step
    documents_processed INTEGER DEFAULT 0,
    embeddings_created INTEGER DEFAULT 0,
    
    -- Error handling
    error_message TEXT,
    failed_step VARCHAR(50),
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    
    -- Metadata
    started_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    cancelled_at TIMESTAMP,
    
    -- Resume support
    can_resume BOOLEAN DEFAULT true,
    last_successful_step VARCHAR(50),
    resume_data JSONB DEFAULT '{}'  -- Data needed to resume (e.g., pdf_buffers, extraction_results)
);

-- Indexes for faster queries
CREATE INDEX IF NOT EXISTS processing_jobs_project_id_idx ON processing_jobs(project_id);
CREATE INDEX IF NOT EXISTS processing_jobs_job_id_idx ON processing_jobs(job_id);
CREATE INDEX IF NOT EXISTS processing_jobs_status_idx ON processing_jobs(status);

-- Only one active job per project at a time
CREATE UNIQUE INDEX IF NOT EXISTS processing_jobs_active_project_idx 
ON processing_jobs(project_id) 
WHERE status IN ('pending', 'running');

-- Comments
COMMENT ON TABLE processing_jobs IS 'Tracks background job progress for resumable processing';
COMMENT ON COLUMN processing_jobs.resume_data IS 'Stores intermediate results needed to resume job (PDFs, extraction data, etc.)';
COMMENT ON COLUMN processing_jobs.progress_data IS 'Detailed progress information for UI display';
