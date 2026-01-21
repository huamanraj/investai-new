-- SQL Commands to Resume Project from Snapshot Step
-- Project ID: dbdd502d-46fa-46c2-9682-ea17f4e01eb2

-- Step 1: Update the project status from "completed" to "pending"
UPDATE projects
SET 
    status = 'pending',
    error_message = NULL,
    updated_at = NOW()
WHERE id = 'dbdd502d-46fa-46c2-9682-ea17f4e01eb2'::UUID;

-- Step 2: Update the processing_job to allow resume from snapshot step
-- First, find the job_id for this project
-- SELECT job_id, status, last_successful_step, failed_step 
-- FROM processing_jobs 
-- WHERE project_id = 'dbdd502d-46fa-46c2-9682-ea17f4e01eb2'::UUID
-- ORDER BY updated_at DESC LIMIT 1;

-- Then update the job (replace 'YOUR_JOB_ID' with actual job_id from above query)
UPDATE processing_jobs
SET 
    status = 'failed',
    current_step = 'generating_snapshot',
    current_step_index = 7,  -- Step 8/9 (0-indexed = 7)
    last_successful_step = 'saving_embeddings',  -- Last successful step before snapshot
    failed_step = 'generating_snapshot',
    error_message = 'Manually reset to retry snapshot generation',
    can_resume = 1,
    completed_at = NULL,  -- Clear completion timestamp
    updated_at = NOW()
WHERE project_id = 'dbdd502d-46fa-46c2-9682-ea17f4e01eb2'::UUID
ORDER BY updated_at DESC
LIMIT 1;

-- Alternative: Update all jobs for this project (if multiple exist)
-- UPDATE processing_jobs
-- SET 
--     status = 'failed',
--     current_step = 'generating_snapshot',
--     current_step_index = 7,
--     last_successful_step = 'saving_embeddings',
--     failed_step = 'generating_snapshot',
--     error_message = 'Manually reset to retry snapshot generation',
--     can_resume = 1,
--     completed_at = NULL,
--     updated_at = NOW()
-- WHERE project_id = 'dbdd502d-46fa-46c2-9682-ea17f4e01eb2'::UUID;

-- Verify the changes
SELECT 
    p.id as project_id,
    p.status as project_status,
    pj.job_id,
    pj.status as job_status,
    pj.current_step,
    pj.last_successful_step,
    pj.failed_step,
    pj.can_resume,
    pj.completed_at
FROM projects p
LEFT JOIN processing_jobs pj ON p.id = pj.project_id
WHERE p.id = 'dbdd502d-46fa-46c2-9682-ea17f4e01eb2'::UUID
ORDER BY pj.updated_at DESC;
