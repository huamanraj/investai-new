# Resumable Background Jobs Guide

## Overview

The project processing jobs are now **fully resumable**. If a job fails at any step, you can resume it from where it left off without losing progress or re-doing completed work.

## Features

✅ **Automatic Progress Saving** - Every step saves its state to database
✅ **Resume from Failure** - Continue from last successful step
✅ **Manual Cancellation** - Cancel running jobs and resume later
✅ **Detailed Tracking** - See exactly which step failed and why
✅ **No Data Loss** - All completed work is preserved

## Processing Steps

The job is broken down into 8 resumable steps:

1. **Scraping** - Scrape BSE India page for PDF links
2. **Downloading** - Download PDFs (done with scraping)
3. **Uploading** - Upload PDFs to Cloudinary
4. **Extracting** - Extract data with LlamaExtract
5. **Saving Extraction** - Save extraction results to DB
6. **Creating Embeddings** - Generate embeddings from extracted data
7. **Saving Embeddings** - Save embeddings to vector DB
8. **Generating Snapshot** - Create company snapshot with GPT

## API Endpoints

### 1. Get Job Details

```http
GET /api/projects/{project_id}/job
```

**Response:**
```json
{
  "project_id": "uuid",
  "has_job": true,
  "job_id": "a1b2c3d4",
  "status": "failed",
  "current_step": "extracting",
  "current_step_index": 3,
  "total_steps": 8,
  "progress_percentage": 37.5,
  "last_successful_step": "uploading",
  "failed_step": "extracting",
  "error_message": "LlamaExtract API timeout",
  "can_resume": true,
  "documents_processed": 1,
  "embeddings_created": 0,
  "started_at": "2026-01-19T10:00:00Z",
  "updated_at": "2026-01-19T10:05:00Z",
  "completed_at": null,
  "cancelled_at": null
}
```

### 2. Cancel Job

```http
POST /api/projects/{project_id}/cancel
```

**Response:**
```json
{
  "message": "Job cancelled successfully",
  "project_id": "uuid",
  "can_resume": true
}
```

**Use Cases:**
- User wants to pause processing
- System maintenance needed
- Resource constraints

### 3. Resume Job

```http
POST /api/projects/{project_id}/resume
```

**Response:**
```json
{
  "message": "Job resumed successfully",
  "project_id": "uuid",
  "resuming_from_step": "uploading",
  "failed_step": "extracting"
}
```

**Use Cases:**
- Resume after failure
- Resume after cancellation
- Retry failed step

## Frontend Integration

### React Example

```tsx
import { useState, useEffect } from 'react';

function ProjectJobControl({ projectId }) {
  const [jobDetails, setJobDetails] = useState(null);
  const [loading, setLoading] = useState(false);
  
  // Fetch job details
  const fetchJobDetails = async () => {
    const res = await fetch(`/api/projects/${projectId}/job`);
    const data = await res.json();
    setJobDetails(data);
  };
  
  // Auto-refresh while job is running
  useEffect(() => {
    fetchJobDetails();
    
    const interval = setInterval(() => {
      if (jobDetails?.status === 'running') {
        fetchJobDetails();
      }
    }, 3000); // Poll every 3 seconds
    
    return () => clearInterval(interval);
  }, [projectId, jobDetails?.status]);
  
  // Cancel job
  const handleCancel = async () => {
    setLoading(true);
    try {
      await fetch(`/api/projects/${projectId}/cancel`, { method: 'POST' });
      await fetchJobDetails();
      alert('Job cancelled successfully');
    } catch (error) {
      alert('Failed to cancel job');
    }
    setLoading(false);
  };
  
  // Resume job
  const handleResume = async () => {
    setLoading(true);
    try {
      await fetch(`/api/projects/${projectId}/resume`, { method: 'POST' });
      await fetchJobDetails();
      alert('Job resumed successfully');
    } catch (error) {
      alert('Failed to resume job');
    }
    setLoading(false);
  };
  
  if (!jobDetails?.has_job) {
    return <div>No job found for this project</div>;
  }
  
  const { status, current_step, progress_percentage, error_message, can_resume } = jobDetails;
  
  return (
    <div className="job-control">
      {/* Progress Bar */}
      <div className="progress-bar">
        <div 
          className="progress-fill" 
          style={{ width: `${progress_percentage}%` }}
        />
      </div>
      
      {/* Status */}
      <div className="job-status">
        <span className={`status-badge ${status}`}>{status}</span>
        <span className="current-step">{current_step}</span>
        <span className="progress">{progress_percentage}%</span>
      </div>
      
      {/* Error Message */}
      {error_message && (
        <div className="error-message">
          <strong>Error:</strong> {error_message}
        </div>
      )}
      
      {/* Action Buttons */}
      <div className="job-actions">
        {status === 'running' && (
          <button 
            onClick={handleCancel} 
            disabled={loading}
            className="btn-cancel"
          >
            ⏸️ Cancel Job
          </button>
        )}
        
        {(status === 'failed' || status === 'cancelled') && can_resume && (
          <button 
            onClick={handleResume} 
            disabled={loading}
            className="btn-resume"
          >
            ▶️ Resume Job
          </button>
        )}
        
        {status === 'completed' && (
          <div className="success-message">
            ✅ Job completed successfully!
          </div>
        )}
      </div>
      
      {/* Step Details */}
      <div className="step-details">
        <p>Documents Processed: {jobDetails.documents_processed}</p>
        <p>Embeddings Created: {jobDetails.embeddings_created}</p>
        {jobDetails.last_successful_step && (
          <p>Last Successful Step: {jobDetails.last_successful_step}</p>
        )}
      </div>
    </div>
  );
}
```

### CSS Example

```css
.job-control {
  padding: 20px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: white;
}

.progress-bar {
  width: 100%;
  height: 8px;
  background: #e5e7eb;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 16px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #8b5cf6);
  transition: width 0.3s ease;
}

.job-status {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
}

.status-badge {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
}

.status-badge.running {
  background: #dbeafe;
  color: #1e40af;
}

.status-badge.completed {
  background: #dcfce7;
  color: #166534;
}

.status-badge.failed {
  background: #fee2e2;
  color: #991b1b;
}

.status-badge.cancelled {
  background: #f3f4f6;
  color: #4b5563;
}

.job-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}

.btn-cancel {
  padding: 8px 16px;
  background: #ef4444;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}

.btn-resume {
  padding: 8px 16px;
  background: #10b981;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}

.error-message {
  padding: 12px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 6px;
  color: #991b1b;
  margin-top: 12px;
}
```

## How It Works

### 1. Progress Tracking

Every step saves:
- Completed work (documents, extractions, embeddings)
- Intermediate data needed for next steps
- Current status and progress percentage

### 2. Resume Logic

When resuming:
1. Check last successful step
2. Load saved intermediate data
3. Skip completed steps
4. Continue from next step

### 3. Data Storage

The `processing_jobs` table stores:
- **resume_data**: PDF buffers, extraction results, chunks, embeddings
- **progress_data**: Detailed step information
- **last_successful_step**: Where to resume from

## Error Handling

### Automatic Retry

Jobs DO NOT automatically retry by default. Users must manually resume.

To add automatic retry (optional):
```python
if job.retry_count < job.max_retries:
    # Retry logic
    pass
```

### Manual Resume

1. Job fails at step X
2. System saves state before step X
3. User clicks "Resume"
4. Job starts from step X with saved data
5. No re-processing of completed steps

## Best Practices

### For Frontend Developers

1. **Poll job status** every 3-5 seconds when status is "running"
2. **Stop polling** when status is "completed", "failed", or "cancelled"
3. **Show progress bar** with percentage and current step
4. **Display error messages** clearly
5. **Enable resume button** only when `can_resume` is true

### For Backend Developers

1. **Save progress frequently** - After each major operation
2. **Keep resume data small** - Don't store unnecessary data
3. **Clean up old jobs** - Implement periodic cleanup of completed jobs
4. **Handle cancellation gracefully** - Check job status between steps

## Testing

### Test Scenarios

```bash
# 1. Normal flow
curl -X POST http://localhost:8000/api/projects \
  -H "Content-Type: application/json" \
  -d '{"source_url": "https://..."}'

# 2. Check job progress
curl http://localhost:8000/api/projects/{id}/job

# 3. Cancel job
curl -X POST http://localhost:8000/api/projects/{id}/cancel

# 4. Resume job
curl -X POST http://localhost:8000/api/projects/{id}/resume

# 5. Get job details after resume
curl http://localhost:8000/api/projects/{id}/job
```

## Database Schema

```sql
CREATE TABLE processing_jobs (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id),
    job_id VARCHAR(50) UNIQUE,
    status VARCHAR(20),  -- pending, running, completed, failed, cancelled
    current_step VARCHAR(50),
    current_step_index INTEGER,
    last_successful_step VARCHAR(50),
    can_resume BOOLEAN,
    resume_data JSONB,  -- Saved state for resume
    error_message TEXT,
    -- ... more fields
);
```

## Limitations

1. **Resume data size**: Large PDFs stored in JSONB may be inefficient
   - Consider external storage (S3, filesystem) for production
   
2. **Concurrent jobs**: Only one active job per project at a time
   - Enforced by unique index
   
3. **Resume timeframe**: Resume data persists indefinitely
   - Implement cleanup for old jobs if needed

## Future Enhancements

- [ ] External storage for PDF buffers
- [ ] Automatic retry with exponential backoff
- [ ] Job priority queue
- [ ] Scheduled job execution
- [ ] Job chaining (run multiple projects sequentially)
- [ ] Webhook notifications on completion/failure
