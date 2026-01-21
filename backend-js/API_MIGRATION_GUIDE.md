# InvestAI Backend - API Migration Guide (Python to Node.js)

## 📋 Overview

This document provides a complete specification of the InvestAI backend API to ensure **zero breaking changes** during migration from Python/FastAPI to Node.js. The frontend depends on exact API contracts documented here.

**Current Stack:**
- Framework: FastAPI (Python)
- Database: PostgreSQL with pgvector
- ORM: SQLAlchemy (async)
- Authentication: None (currently open API)

**Application:**
- BSE India financial document scraping and analysis
- PDF processing with GPT-based extraction
- RAG-based chat system with embeddings
- Resumable background job processing

---

## 🗄️ Database Schema

### Required PostgreSQL Extensions
```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;  -- pgvector for embeddings
```

### Table: `projects`
Main entity representing a company/BSE stock.

```sql
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_name TEXT NOT NULL,
    source_url TEXT NOT NULL,           -- BSE India URL
    exchange TEXT DEFAULT 'BSE',        -- Stock exchange
    status TEXT DEFAULT 'pending',      -- pending, scraping, downloading, processing, completed, failed
    error_message TEXT,                 -- Error details if failed
    created_at TIMESTAMP DEFAULT NOW()
);
```

**Status Values:**
- `pending` - Project created, not yet processing
- `scraping` - Actively scraping BSE page for PDFs
- `downloading` - Downloading PDF files
- `processing` - Extracting data and creating embeddings
- `completed` - All processing finished successfully
- `failed` - Processing failed (error in error_message)

### Table: `documents`
PDF documents (annual reports, presentations, etc.) belonging to projects.

```sql
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    document_type TEXT NOT NULL,        -- annual_report, presentation, transcript
    fiscal_year TEXT,                   -- FY2022, FY2023, FY2024-25, etc.
    label TEXT,                         -- e.g., "2024-25 (Revised)"
    file_url TEXT NOT NULL,             -- Cloudinary URL (permanently hosted)
    original_url TEXT,                  -- Original BSE URL
    page_count INT,                     -- Number of pages in PDF
    created_at TIMESTAMP DEFAULT NOW()
);
```

**Document Types:**
- `annual_report` - Annual/quarterly financial reports
- `presentation` - Investor presentations
- `transcript` - Earnings call transcripts

### Table: `document_pages`
Each PDF page stored separately (1 row = 1 page). **Critical for accuracy.**

```sql
CREATE TABLE document_pages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INT NOT NULL,           -- 1-indexed page number
    page_text TEXT NOT NULL,            -- Extracted text from this page
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Table: `extraction_results`
Structured data extracted from documents via GPT.

```sql
CREATE TABLE extraction_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    extracted_data JSONB NOT NULL,      -- Complete extraction JSON
    extraction_metadata JSONB,          -- Citations, reasoning, confidence
    company_name TEXT,
    fiscal_year TEXT,
    revenue NUMERIC,                    -- Extracted revenue (for quick queries)
    net_profit NUMERIC,                 -- Extracted net profit
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX extraction_results_document_id_idx ON extraction_results(document_id);
```

**extraction_data JSONB Structure:**
```json
{
  "company_name": "VIMTA LABS LTD",
  "fiscal_year": "FY2024",
  "financial_highlights": {
    "revenue": 1234.56,
    "net_profit": 234.56,
    "total_assets": 5678.90,
    "eps": 12.34
  },
  "risk_factors": ["Market volatility", "Regulatory changes"],
  "key_metrics": {...}
}
```

### Table: `text_chunks`
Searchable text chunks from pages (for RAG system).

```sql
CREATE TABLE text_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    page_id UUID NOT NULL REFERENCES document_pages(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,           -- Order of chunk in page (0-indexed)
    content TEXT NOT NULL,              -- Chunk text content
    field VARCHAR(100),                 -- Source field (e.g., "financial_highlights", "risk_factors")
    created_at TIMESTAMP DEFAULT NOW()
);
```

**Chunking Strategy:**
- Chunk size: 400 characters
- Overlap: 80 characters
- Max chunks per page: 10
- Field indicates which extracted field this chunk came from

### Table: `embeddings`
Vector embeddings for semantic search (pgvector).

```sql
CREATE TABLE embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    chunk_id UUID NOT NULL REFERENCES text_chunks(id) ON DELETE CASCADE,
    embedding VECTOR(3072) NOT NULL,    -- OpenAI text-embedding-3-large
    created_at TIMESTAMP DEFAULT NOW()
);

-- CRITICAL: Vector similarity search index
CREATE INDEX embeddings_vector_idx
ON embeddings
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

**Embedding Model:** `text-embedding-3-large` (3072 dimensions)
**Similarity Method:** Cosine similarity

### Table: `chats`
Chat sessions for multi-turn conversations.

```sql
CREATE TABLE chats (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT,                         -- Chat title (auto-generated or user-provided)
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Table: `messages`
Individual messages within chats.

```sql
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    chat_id UUID NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role TEXT NOT NULL,                 -- 'user' or 'ai'
    content TEXT NOT NULL,              -- Message text
    project_ids UUID[] NOT NULL,        -- Projects active for this message
    created_at TIMESTAMP DEFAULT NOW()
);
```

**Important:** `project_ids` is a PostgreSQL array storing which projects were "toggled on" for each specific message. This allows context switching during conversation.

### Table: `company_snapshots`
Pre-computed company summaries for fast UI rendering.

```sql
CREATE TABLE company_snapshots (
    project_id UUID PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    snapshot_data JSONB NOT NULL DEFAULT '{}',  -- Complete snapshot JSON
    generated_at TIMESTAMP DEFAULT NOW(),
    version INTEGER DEFAULT 1,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX company_snapshots_project_id_idx ON company_snapshots(project_id);
```

**snapshot_data Structure:**
```json
{
  "company_overview": {
    "name": "VIMTA LABS LTD",
    "description": "Testing and certification company...",
    "industry": "Testing Services",
    "founded": "1993"
  },
  "financial_metrics": {
    "revenue": [
      {"year": "FY2022", "value": 1000},
      {"year": "FY2023", "value": 1200},
      {"year": "FY2024", "value": 1400}
    ],
    "net_profit": [...],
    "eps": [...]
  },
  "performance_summary": "Revenue grew 16.7% YoY...",
  "charts_data": {
    "revenue_chart": [...],
    "profit_chart": [...]
  },
  "metadata": {
    "generated_at": "2024-01-20T10:30:00Z",
    "data_sources": ["FY2024 Annual Report", "Q3 2024 Results"]
  }
}
```

### Table: `processing_jobs`
Background job tracking for resumable processing.

```sql
CREATE TABLE processing_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id VARCHAR(50) NOT NULL UNIQUE, -- Short identifier (8 chars, e.g., "a3f8d9e2")
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed, cancelled
    current_step VARCHAR(50),           -- Current processing step
    current_step_index INTEGER DEFAULT 0,
    total_steps INTEGER DEFAULT 8,      -- Total number of steps
    
    -- Progress tracking
    progress_data JSONB DEFAULT '{}',   -- Step-by-step progress details
    documents_processed INTEGER DEFAULT 0,
    embeddings_created INTEGER DEFAULT 0,
    
    -- Error handling
    error_message TEXT,
    failed_step VARCHAR(50),            -- Step where failure occurred
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    
    -- Timestamps
    started_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    cancelled_at TIMESTAMP,
    
    -- Resume support
    can_resume BOOLEAN DEFAULT true,
    last_successful_step VARCHAR(50),
    resume_data JSONB DEFAULT '{}'      -- Intermediate data for resume
);

CREATE INDEX processing_jobs_project_id_idx ON processing_jobs(project_id);
CREATE INDEX processing_jobs_job_id_idx ON processing_jobs(job_id);
CREATE INDEX processing_jobs_status_idx ON processing_jobs(status);

-- Only one active job per project
CREATE UNIQUE INDEX processing_jobs_active_project_idx 
ON processing_jobs(project_id) 
WHERE status IN ('pending', 'running');
```

**Processing Steps (in order):**
1. `validate_url` - Validate BSE URL
2. `scrape_page` - Scrape BSE page for PDFs
3. `download_pdfs` - Download PDF files
4. `upload_to_cloud` - Upload to Cloudinary
5. `extract_text` - Extract text from PDFs
6. `extract_data` - Extract structured data with GPT
7. `create_embeddings` - Generate vector embeddings
8. `generate_snapshot` - Create company snapshot

**resume_data JSONB:**
```json
{
  "pdf_buffers": {
    "doc_uuid_1": "base64_encoded_pdf_content",
    "doc_uuid_2": "base64_encoded_pdf_content"
  },
  "extraction_results": {
    "doc_uuid_1": {...},
    "doc_uuid_2": {...}
  },
  "pdf_info": [
    {
      "url": "https://...",
      "label": "Annual Report FY2024",
      "fiscal_year": "FY2024"
    }
  ]
}
```

---

## 🌐 API Endpoints

### Base Configuration

**Base URL:** `/api`  
**CORS:** Allow all origins (`*`), all methods, all headers, credentials enabled  
**Content-Type:** `application/json` (except SSE endpoints)  
**Error Format:**
```json
{
  "detail": "Error message"
}
```

### Root Endpoints

#### `GET /`
Root endpoint with API info.

**Response (200):**
```json
{
  "name": "InvestAI",
  "version": "0.1.0",
  "status": "running",
  "docs": "/docs"
}
```

#### `GET /health`
Health check endpoint.

**Response (200):**
```json
{
  "status": "healthy"
}
```

---

## 📁 Projects API

### 1. Create Project

**`POST /api/projects`**

Create a new project from BSE India URL. Starts background processing automatically.

**Request Body:**
```json
{
  "source_url": "https://www.bseindia.com/stock-share-price/vimta-labs-ltd/vimtalabs/524394/financials-annual-reports/"
}
```

**Validation Rules:**
- URL must match pattern: `https://www.bseindia.com/stock-share-price/*/financials-annual-reports/`
- URL must not already exist in database

**Response (201):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "company_name": "VIMTA LABS LTD",
  "source_url": "https://www.bseindia.com/stock-share-price/vimta-labs-ltd/vimtalabs/524394/financials-annual-reports/",
  "exchange": "BSE",
  "status": "pending",
  "error_message": null,
  "created_at": "2024-01-20T10:30:00.000Z"
}
```

**Errors:**
- `400` - Project with URL already exists
- `400` - Invalid BSE URL format
- `422` - Validation error
- `503` - Database connection error

**Behavior:**
1. Extract company name from URL (parse from URL path)
2. Check if project with same URL exists (return 400 if yes)
3. Create project with status "pending"
4. Start background job via `process_project_resumable()` (non-blocking)
5. Return project immediately

### 2. List Projects

**`GET /api/projects?skip=0&limit=20`**

List all projects with pagination.

**Query Parameters:**
- `skip` (integer, default: 0) - Number of records to skip
- `limit` (integer, default: 20) - Max records to return

**Response (200):**
```json
{
  "projects": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "company_name": "VIMTA LABS LTD",
      "source_url": "https://www.bseindia.com/...",
      "exchange": "BSE",
      "status": "completed",
      "error_message": null,
      "created_at": "2024-01-20T10:30:00.000Z"
    }
  ],
  "total": 42
}
```

**Ordering:** Most recent first (`created_at DESC`)

### 3. Get Project Details

**`GET /api/projects/{project_id}`**

Get project with all documents and latest job status.

**Path Parameters:**
- `project_id` (UUID) - Project ID

**Response (200):**
```json
{
  "project": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "company_name": "VIMTA LABS LTD",
    "source_url": "https://...",
    "exchange": "BSE",
    "status": "completed",
    "error_message": null,
    "created_at": "2024-01-20T10:30:00.000Z"
  },
  "documents": [
    {
      "id": "660e8400-e29b-41d4-a716-446655440000",
      "document_type": "annual_report",
      "fiscal_year": "FY2024",
      "label": "Annual Report 2024",
      "file_url": "https://res.cloudinary.com/.../report.pdf",
      "original_url": "https://www.bseindia.com/.../file.pdf",
      "page_count": 120,
      "created_at": "2024-01-20T10:35:00.000Z"
    }
  ],
  "job_status": {
    "job_id": "a3f8d9e2",
    "status": "completed",
    "current_step": "generate_snapshot",
    "current_step_index": 8,
    "total_steps": 8,
    "failed_step": null,
    "error_message": null,
    "can_resume": true,
    "updated_at": "2024-01-20T10:40:00.000Z"
  }
}
```

**Errors:**
- `404` - Project not found

**Behavior:**
- Eager load documents relationship
- Fetch latest processing job (by `updated_at DESC`)
- `job_status` is `null` if no job exists

### 4. Get Project Status

**`GET /api/projects/{project_id}/status`**

Get project status with job info (lighter than full details).

**Response (200):**
```json
{
  "project": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "company_name": "VIMTA LABS LTD",
    "source_url": "https://...",
    "exchange": "BSE",
    "status": "processing",
    "error_message": null,
    "created_at": "2024-01-20T10:30:00.000Z"
  },
  "job_status": {
    "job_id": "a3f8d9e2",
    "status": "running",
    "current_step": "create_embeddings",
    "current_step_index": 7,
    "total_steps": 8,
    "failed_step": null,
    "error_message": null,
    "can_resume": true,
    "updated_at": "2024-01-20T10:38:00.000Z"
  }
}
```

**Special Behavior:**
If job has terminal status (`completed`, `failed`, `cancelled`) but project status is stale (e.g., still "scraping"), the response automatically reflects the job's terminal status and attempts to update the database.

### 5. Get Project Snapshot

**`GET /api/projects/{project_id}/snapshot`**

Get pre-computed company snapshot (fast summary for UI).

**Response (200):**
```json
{
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "company_name": "VIMTA LABS LTD",
  "snapshot": {
    "company_overview": {
      "name": "VIMTA LABS LTD",
      "description": "Leading testing and certification company...",
      "industry": "Testing Services"
    },
    "financial_metrics": {
      "revenue": [
        {"year": "FY2022", "value": 1000},
        {"year": "FY2023", "value": 1200},
        {"year": "FY2024", "value": 1400}
      ],
      "net_profit": [...]
    },
    "performance_summary": "Strong revenue growth of 16.7% YoY...",
    "charts_data": {...}
  },
  "generated_at": "2024-01-20T10:40:00.000Z",
  "updated_at": "2024-01-20T10:40:00.000Z",
  "version": 1
}
```

**Errors:**
- `404` - Project not found
- `404` - Snapshot not yet generated (still processing)

### 6. Get Job Details

**`GET /api/projects/{project_id}/job`**

Get detailed job information (for debugging/admin).

**Response (200):**
```json
{
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "has_job": true,
  "job_id": "a3f8d9e2",
  "status": "running",
  "current_step": "create_embeddings",
  "current_step_index": 7,
  "total_steps": 8,
  "progress_percentage": 87.5,
  "last_successful_step": "extract_data",
  "failed_step": null,
  "error_message": null,
  "can_resume": true,
  "documents_processed": 3,
  "embeddings_created": 450,
  "started_at": "2024-01-20T10:32:00.000Z",
  "updated_at": "2024-01-20T10:38:00.000Z",
  "completed_at": null,
  "cancelled_at": null
}
```

**If no job exists:**
```json
{
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "has_job": false,
  "message": "No processing job found for this project"
}
```

### 7. Cancel Project Job

**`POST /api/projects/{project_id}/cancel`**

Cancel a running job. Job can be resumed later.

**Response (200):**
```json
{
  "message": "Job cancelled successfully",
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "can_resume": true
}
```

**Errors:**
- `404` - Project not found
- `404` - No active job found

**Behavior:**
1. Find active job for project (status = "running")
2. Set job status to "cancelled"
3. Set `cancelled_at` timestamp
4. Set project status to "failed" with message "Job cancelled"
5. Job remains resumable (`can_resume = true`)

### 8. Resume Project Job

**`POST /api/projects/{project_id}/resume`**

Resume a failed/cancelled job from last successful step, or start fresh if no job exists.

**Response (200):**
```json
{
  "message": "Job resumed successfully",
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "resuming_from_step": "extract_data",
  "failed_step": "create_embeddings"
}
```

**Or if starting fresh:**
```json
{
  "message": "Started fresh processing job (no previous job found)",
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "resuming_from_step": null,
  "failed_step": null
}
```

**Errors:**
- `404` - Project not found
- `400` - Project already completed
- `400` - Job is currently running
- `400` - Job exists but cannot be resumed

**Special Behaviors:**

**Stale Job Detection:**
If job status is "running" but `updated_at` is >5 minutes old, job is considered stale (crashed). It's automatically reset to "failed" status to allow resume.

**No Job Scenario:**
If no job exists at all (e.g., background task crashed before creating job record), a fresh job is started automatically.

**Resume Conditions:**
- Job status must be "failed" or "cancelled"
- `can_resume` must be true

**Resume Process:**
1. Reset project status to "pending"
2. Reset job status to "running"
3. Clear error fields
4. Start background processing from `last_successful_step`

### 9. Stream Progress (SSE)

**`GET /api/projects/{project_id}/progress-stream`**

Real-time Server-Sent Events stream of job progress.

**Response:** `Content-Type: text/event-stream`

**SSE Event Format:**
```
data: {"type": "connected", "job_id": "a3f8d9e2", "message": "Progress stream connected", "already_finished": false}

data: {"type": "status", "step": "scrape_page", "message": "Scraping BSE page for PDFs"}

data: {"type": "progress", "step": "download_pdfs", "step_index": 3, "total_steps": 8, "message": "Downloading 3 PDFs"}

data: {"type": "completed", "message": "Project processing completed"}

data: {"type": "stream_end", "reason": "completed"}
```

**Event Types:**
- `connected` - Initial connection established
- `status` - Step started or status update
- `progress` - Progress update within step
- `detail` - Detailed information (e.g., "Found 3 PDFs")
- `completed` - Job completed successfully
- `error` - Job failed
- `cancelled` - Job cancelled
- `stream_end` - Stream closing

**Keep-Alive:**
Every 30 seconds: `: keep-alive\n\n`

**Headers:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

**Stream Termination:**
Stream automatically closes when job reaches terminal state (`completed`, `error`, `cancelled`).

**Errors:**
- `404` - Project not found
- `404` - No processing job found

### 10. Delete Project

**`DELETE /api/projects/{project_id}`**

Delete project and all associated data (cascade delete).

**Response:** `204 No Content`

**Errors:**
- `404` - Project not found

**Behavior:**
1. Cancel any running jobs first
2. Delete project (cascades to all related tables)
3. Return 204

**Cascade Deletes:**
- documents → document_pages → text_chunks → embeddings
- extraction_results
- company_snapshots
- processing_jobs

---

## 💬 Chats API

### 1. Create Chat

**`POST /api/chats`**

Create new chat session.

**Request Body:**
```json
{
  "title": "Chat about VIMTA LABS",
  "project_ids": [
    "550e8400-e29b-41d4-a716-446655440000"
  ]
}
```

**Fields:**
- `title` (optional) - Auto-generated if not provided
- `project_ids` (required, min 1) - Initial projects to chat with

**Auto-Title Logic:**
- 1 project: "Chat with {company_name}"
- 2+ projects: "Chat with {count} companies"

**Response (201):**
```json
{
  "id": "770e8400-e29b-41d4-a716-446655440000",
  "title": "Chat with VIMTA LABS LTD",
  "created_at": "2024-01-20T11:00:00.000Z",
  "message_count": 0
}
```

**Errors:**
- `404` - One or more project IDs not found
- `422` - Validation error

### 2. List Chats

**`GET /api/chats?limit=50&offset=0`**

List all chats with pagination.

**Query Parameters:**
- `limit` (integer, default: 50) - Max chats to return
- `offset` (integer, default: 0) - Pagination offset

**Response (200):**
```json
[
  {
    "id": "770e8400-e29b-41d4-a716-446655440000",
    "title": "Chat with VIMTA LABS LTD",
    "created_at": "2024-01-20T11:00:00.000Z",
    "message_count": 6
  }
]
```

**Ordering:** Most recent first (`created_at DESC`)

### 3. Get Chat Details

**`GET /api/chats/{chat_id}`**

Get chat with all messages.

**Response (200):**
```json
{
  "id": "770e8400-e29b-41d4-a716-446655440000",
  "title": "Chat with VIMTA LABS LTD",
  "created_at": "2024-01-20T11:00:00.000Z",
  "messages": [
    {
      "id": "880e8400-e29b-41d4-a716-446655440000",
      "role": "user",
      "content": "What was the revenue in FY2024?",
      "project_ids": ["550e8400-e29b-41d4-a716-446655440000"],
      "created_at": "2024-01-20T11:01:00.000Z"
    },
    {
      "id": "990e8400-e29b-41d4-a716-446655440000",
      "role": "ai",
      "content": "In FY2024, VIMTA LABS LTD reported revenue of ₹1,400 crores...",
      "project_ids": ["550e8400-e29b-41d4-a716-446655440000"],
      "created_at": "2024-01-20T11:01:05.000Z"
    }
  ]
}
```

**Message Ordering:** Chronological (`created_at ASC`)

**Errors:**
- `404` - Chat not found

### 4. Send Message (SSE)

**`POST /api/chats/{chat_id}/messages`**

Send message and get streaming AI response.

**Request Body:**
```json
{
  "content": "What was the revenue growth in FY2024?",
  "project_ids": [
    "550e8400-e29b-41d4-a716-446655440000"
  ]
}
```

**Response:** `Content-Type: text/event-stream`

**SSE Stream:**
```
data: {'type': 'status', 'message': 'Creating query embedding...'}

data: {'type': 'status', 'message': 'Searching relevant documents...'}

data: {'type': 'context', 'chunks_found': 8}

data: {'type': 'start'}

data: {'type': 'chunk', 'content': 'In FY2024'}

data: {'type': 'chunk', 'content': ', VIMTA LABS'}

data: {'type': 'chunk', 'content': ' reported revenue'}

data: {'type': 'done', 'message_id': '990e8400-e29b-41d4-a716-446655440000'}
```

**Event Types:**
- `status` - Processing status update
- `context` - Context search completed (includes `chunks_found`)
- `start` - AI response streaming started
- `chunk` - Incremental AI response text chunk
- `done` - Response complete (includes saved `message_id`)
- `error` - Error occurred

**Important:** Content in `chunk` events must be JSON-escaped:
- Escape backslashes: `\` → `\\`
- Escape quotes: `"` → `\"`
- Escape newlines: `\n` → `\\n`

**RAG Processing Flow:**
1. Save user message to database
2. Create embedding for user query (OpenAI text-embedding-3-large)
3. Search similar chunks using pgvector cosine similarity (top 10)
4. Build context from retrieved chunks
5. Stream GPT response with context + chat history
6. Save complete AI response to database
7. Send `done` event

**Errors:**
- `404` - Chat not found
- `404` - One or more project IDs not found
- `503` - OpenAI API not configured
- `503` - Embeddings service not configured

**Headers:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

### 5. Delete Chat

**`DELETE /api/chats/{chat_id}`**

Delete chat and all messages.

**Response:** `204 No Content`

**Errors:**
- `404` - Chat not found

**Behavior:** Cascade deletes all messages in the chat.

---

## ⚙️ Environment Configuration

### Required Environment Variables

```bash
# Database (PostgreSQL with pgvector)
DATABASE_URL=postgresql://user:password@host:port/dbname

# OpenAI API
OPENAI_API_KEY=sk-...
OPENAI_EMBEDDING_MODEL=text-embedding-3-large   # 3072 dimensions
OPENAI_CHAT_MODEL=gpt-4.1                       # For chat responses
OPENAI_EXTRACTION_MODEL=gpt-5-nano              # For PDF extraction

# Cloudinary (PDF hosting)
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret

# Application
APP_NAME=InvestAI
ENV=development                                  # or production
DEBUG=true
HOST=0.0.0.0
PORT=8000

# Playwright (for web scraping)
PLAYWRIGHT_HEADLESS=true
PLAYWRIGHT_TIMEOUT=30000                         # milliseconds

# PDF Processing
CHUNK_SIZE=400                                   # characters
CHUNK_OVERLAP=80                                 # characters overlap
MAX_CHUNKS_PER_PAGE=10                          # max chunks per page

# RAG Settings
MAX_SIMILARITY_RESULTS=25                       # max chunks to retrieve
MAX_PROJECTS_PER_CHAT=5                         # limit projects per chat

# Logging
LOG_LEVEL=INFO                                  # DEBUG, INFO, WARNING, ERROR

# Optional: LlamaCloud (deprecated, use GPT extraction)
LLAMA_CLOUD_API_KEY=llx_...
```

### Database Connection

**Important:** When using async SQLAlchemy with PostgreSQL:
1. Use `postgresql+asyncpg://` scheme (not `postgresql://`)
2. Remove `sslmode` from query params (asyncpg doesn't support it)
3. Use `connect_args={"ssl": True}` for SSL connections
4. Enable `pool_pre_ping=True` to avoid stale connections

---

## 🔧 Important Business Logic

### URL Validation

BSE India URL must match pattern:
```
https://www.bseindia.com/stock-share-price/{company-slug}/{code}/{id}/financials-annual-reports/
```

Company name extraction regex:
```python
# Extract from URL path segment (e.g., "vimta-labs-ltd" → "VIMTA LABS LTD")
company_slug = url.split('/')[4]  # "vimta-labs-ltd"
company_name = company_slug.replace('-', ' ').upper()  # "VIMTA LABS LTD"
```

### Background Job Processing

**Key Points:**
1. Jobs are **non-blocking** - API returns immediately after creating project
2. Jobs are **resumable** - can be cancelled and resumed from last successful step
3. Progress is **real-time** via SSE streaming
4. Intermediate data is saved in `resume_data` JSONB field

**Step Execution Order:**
1. `validate_url` - Check if URL is valid BSE India URL
2. `scrape_page` - Use Playwright to scrape BSE page for PDF links
3. `download_pdfs` - Download all PDFs to memory buffers
4. `upload_to_cloud` - Upload PDFs to Cloudinary, save Document records
5. `extract_text` - Extract text from PDFs page-by-page (save DocumentPages)
6. `extract_data` - Use GPT to extract structured data (save ExtractionResults)
7. `create_embeddings` - Chunk text, create embeddings, save to pgvector
8. `generate_snapshot` - Use GPT to generate company snapshot

**Resume Data Management:**
- PDF buffers stored as base64 in `resume_data.pdf_buffers`
- Extraction results stored in `resume_data.extraction_results`
- Allows skipping expensive re-download and re-extraction

**Job Cancellation:**
- Sets status to "cancelled"
- Job remains in database with `can_resume = true`
- Sets project status to "failed"

**Stale Job Handling:**
If job is "running" but hasn't updated in >5 minutes:
- Considered crashed/stale
- Automatically reset to "failed" when resume endpoint is called
- Allows recovery from unexpected failures

### Embeddings & Vector Search

**Embedding Creation:**
1. Chunk extraction results text into 400-char chunks with 80-char overlap
2. For each chunk, create embedding using OpenAI `text-embedding-3-large`
3. Store in `embeddings` table with pgvector type (3072 dimensions)

**Similarity Search (RAG):**
```sql
SELECT tc.content, tc.field, dp.page_number, d.document_type, d.fiscal_year
FROM embeddings e
JOIN text_chunks tc ON tc.id = e.chunk_id
JOIN document_pages dp ON dp.id = tc.page_id
JOIN documents d ON d.id = dp.document_id
WHERE d.project_id IN (?)
ORDER BY e.embedding <=> query_embedding  -- cosine similarity
LIMIT 10;
```

**Context Building:**
Format retrieved chunks for GPT prompt:
```
[Document: Annual Report FY2024, Page: 23, Field: financial_highlights]
Chunk content here...

[Document: Annual Report FY2024, Page: 45, Field: risk_factors]
Another chunk content...
```

### Chat System

**Multi-Turn Conversations:**
- Each message stores `project_ids` array (which projects were active)
- Chat history sent to GPT (all previous messages in order)
- RAG search scoped to current message's `project_ids`

**Project Toggles:**
Users can change which projects are active mid-conversation:
```json
Message 1: {"project_ids": ["proj-a"]}  // Ask about company A
Message 2: {"project_ids": ["proj-a", "proj-b"]}  // Compare A and B
Message 3: {"project_ids": ["proj-b"]}  // Ask only about B
```

### PDF Text Extraction

**Two-Phase Approach:**
1. **Phase 1:** Use `pymupdf` to extract raw text page-by-page
2. **Phase 2:** Use GPT to structure and clean extracted text

**GPT Extraction Prompt:**
```
You are an expert financial document analyzer. Extract structured data from this annual report text.

Extract the following:
1. Company name and fiscal year
2. Financial highlights (revenue, profit, EPS, etc.)
3. Key metrics and ratios
4. Risk factors and challenges
5. Business segments and products
6. Management discussion and analysis

Return JSON with citations to page numbers.
```

**Chunking Strategy:**
Text is chunked AFTER extraction to preserve semantic boundaries:
- Chunk by field (e.g., all "financial_highlights" together)
- Then split into 400-char chunks with overlap
- Store field name in `text_chunks.field` for better retrieval

### Snapshot Generation

**Triggered:** After embeddings are created (final step)

**GPT Prompt:**
```
Generate a comprehensive company snapshot based on the extracted financial data.

Include:
1. Company Overview (1-2 paragraphs)
2. Financial Metrics (3-year trends for revenue, profit, EPS)
3. Performance Summary (key insights, growth rates)
4. Charts Data (formatted for frontend charting)
5. Metadata (data sources, generation timestamp)

Return JSON matching the snapshot schema.
```

**Caching:** Snapshot is pre-computed and cached in `company_snapshots` table for instant UI loading.

---

## 🚨 Error Handling Patterns

### HTTP Status Codes

- `200` - Success
- `201` - Created (project/chat)
- `204` - No Content (delete operations)
- `400` - Bad Request (validation, business logic errors)
- `404` - Not Found (resource doesn't exist)
- `422` - Unprocessable Entity (Pydantic validation errors)
- `500` - Internal Server Error (unexpected errors)
- `503` - Service Unavailable (external API not configured)

### Validation Errors (422)

**Format:**
```json
{
  "detail": [
    {
      "loc": ["body", "source_url"],
      "msg": "Invalid BSE URL format",
      "type": "value_error"
    }
  ]
}
```

### Database Errors

**Connection Errors:**
Return `503` with user-friendly message:
```json
{
  "detail": "Database connection error. Please try again in a moment."
}
```

**Constraint Violations:**
Return `400` with specific message:
```json
{
  "detail": "Project with this URL already exists"
}
```

### External API Errors

**OpenAI API:**
- Check if API key is configured before operations
- Return `503` if not configured
- Log errors but don't expose API keys in responses

**Cloudinary:**
- Retry uploads 3 times before failing
- Log detailed error for debugging
- Return generic error to user

---

## 📊 Logging

### Structured Logging

**Two Log Streams:**

1. **Console Logger** (human-readable, with emojis):
```
✅ Project created: 550e8400-e29b-41d4-a716-446655440000
📝 Creating project for: VIMTA LABS LTD
❌ Database error creating project: connection refused
```

2. **JSON Logger** (machine-readable, for aggregation):
```json
{"timestamp": "2024-01-20T10:30:00Z", "level": "INFO", "message": "Project created", "data": {"project_id": "550e...", "company": "VIMTA LABS"}}
{"timestamp": "2024-01-20T10:30:05Z", "level": "ERROR", "message": "Database error", "data": {"error": "connection refused", "query": "INSERT..."}}
```

**Log Files:**
- `logs/api.jsonl` - API requests/responses
- `logs/jobs.jsonl` - Background job events
- `logs/scraper.jsonl` - Web scraping logs
- `logs/extractions/{timestamp}_{company}.txt` - GPT extraction results

**Log Rotation:** Daily rotation, keep last 7 days

---

## 🔒 Security Notes

**Current State:**
- **No authentication** - All endpoints are public
- **No rate limiting** - Should be added in Node.js version
- **CORS:** Allow all origins (fine for development, tighten for production)

**Recommendations for Node.js Version:**
1. Add JWT authentication for projects/chats
2. Implement rate limiting (e.g., 100 req/min per IP)
3. Add input sanitization for chat messages (prevent XSS)
4. Validate UUIDs in path parameters
5. Add API key authentication for admin endpoints
6. Implement CSRF protection for mutations
7. Tighten CORS to specific origins in production

---

## 🎯 Critical Implementation Details

### 1. SSE Streaming

**Must-Have Headers:**
```javascript
{
  'Content-Type': 'text/event-stream',
  'Cache-Control': 'no-cache',
  'Connection': 'keep-alive',
  'X-Accel-Buffering': 'no'  // Critical for nginx
}
```

**Event Format:**
```
data: {JSON}\n\n
```

**Keep-Alive:**
Send `: keep-alive\n\n` every 30 seconds to prevent timeout.

### 2. UUID Handling

- All IDs are UUIDv4
- Database stores as PostgreSQL `UUID` type
- API accepts/returns as strings
- Validate UUID format in path parameters

### 3. Timestamp Format

- Database: `TIMESTAMP` (UTC)
- API: ISO 8601 strings (`2024-01-20T10:30:00.000Z`)
- Always use UTC, never local time

### 4. JSON Escaping in SSE

When sending JSON in SSE data field, escape:
```javascript
content = content
  .replace(/\\/g, '\\\\')   // Backslashes first
  .replace(/"/g, '\\"')     // Quotes
  .replace(/\n/g, '\\n');   // Newlines
```

### 5. Cascade Deletes

Ensure foreign keys have `ON DELETE CASCADE`:
```sql
FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
```

Critical for clean data deletion.

### 6. Transaction Handling

Use database transactions for multi-step operations:
- Creating project + starting job
- Saving message + embeddings
- Updating job status + project status

### 7. Connection Pooling

Configure database pool:
```javascript
{
  max: 10,           // Max connections
  min: 2,            // Min idle connections
  idle: 10000,       // Close idle after 10s
  acquire: 30000,    // Timeout acquiring connection
  evict: 1000,       // Check for idle every 1s
  handleDisconnects: true
}
```

### 8. Vector Search Performance

**Index Type:** IVFFlat (Inverted File Flat)
**Lists Parameter:** 100 (for ~10k-100k vectors)
**Operator:** `vector_cosine_ops` (cosine similarity)

For better performance with >100k vectors, consider HNSW index:
```sql
CREATE INDEX ON embeddings 
USING hnsw (embedding vector_cosine_ops);
```

### 9. Background Job Isolation

Jobs should:
- Run in separate async tasks (not blocking HTTP thread)
- Have their own database sessions
- Handle exceptions gracefully
- Update job status on every step
- Save intermediate results in `resume_data`

### 10. Progress Tracking

Use in-memory pub/sub for real-time progress:
```python
# Pseudo-code
progress_tracker.emit(job_id, {
  'type': 'progress',
  'step': 'download_pdfs',
  'message': 'Downloaded 2/3 PDFs'
})

# All subscribed SSE clients receive this event
```

**Implementation:** Use event emitters or Redis pub/sub.

---

## ✅ Testing Checklist

### API Compatibility Tests

- [ ] All endpoints return exact same response structure
- [ ] All status codes match original behavior
- [ ] SSE streams work identically (format, timing, keep-alive)
- [ ] Error responses have same format
- [ ] Validation errors have same field paths
- [ ] Timestamps are ISO 8601 with milliseconds
- [ ] UUIDs are lowercase with hyphens
- [ ] CORS headers are identical

### Database Tests

- [ ] All tables created with correct schema
- [ ] Cascade deletes work properly
- [ ] UUID generation works (uuid_generate_v4())
- [ ] pgvector extension installed
- [ ] Vector similarity search returns correct results
- [ ] Indexes exist and are used (check EXPLAIN)
- [ ] Transactions rollback on error

### Business Logic Tests

- [ ] URL validation rejects invalid BSE URLs
- [ ] Company name extraction matches Python version
- [ ] Job resumability works (save/load resume_data)
- [ ] Stale job detection (>5 min threshold)
- [ ] Progress events emitted at correct times
- [ ] Embeddings match OpenAI text-embedding-3-large
- [ ] Chat history includes all previous messages
- [ ] Project toggles work in multi-turn chat

### Performance Tests

- [ ] SSE streams don't buffer (nginx)
- [ ] Database connections pooled and reused
- [ ] Vector search uses index (not seq scan)
- [ ] Large PDFs don't cause memory issues
- [ ] Concurrent job processing works
- [ ] No memory leaks in long-running streams

---

## 📚 Additional Resources

### Python Dependencies (for reference)

```txt
fastapi==0.109.0
uvicorn[standard]==0.27.0
sqlalchemy==2.0.25
asyncpg==0.29.0
psycopg2-binary==2.9.9
pgvector==0.2.4
pydantic==2.5.3
pydantic-settings==2.1.0
openai==1.10.0
playwright==1.41.0
pymupdf==1.23.8
cloudinary==1.38.0
httpx==0.26.0
python-multipart==0.0.6
```

### Node.js Recommended Libraries

- **Framework:** Express or Fastify
- **Database:** Sequelize or Prisma with pg driver
- **Vector:** pgvector with pg extension
- **Validation:** Joi or Zod
- **OpenAI:** openai npm package
- **PDF:** pdf-parse or pdf.js
- **Scraping:** Puppeteer or Playwright
- **Upload:** cloudinary npm package
- **SSE:** Built-in (res.write) or sse-express

### Migration Strategy

1. **Phase 1:** Set up Node.js project with dependencies
2. **Phase 2:** Implement database layer (models, migrations)
3. **Phase 3:** Implement API endpoints (no business logic yet)
4. **Phase 4:** Test API compatibility with existing frontend
5. **Phase 5:** Implement background jobs and RAG system
6. **Phase 6:** Test end-to-end with real BSE URLs
7. **Phase 7:** Deploy both versions side-by-side
8. **Phase 8:** Gradually switch traffic to Node.js version

---

## 📞 Support

If you encounter discrepancies between this doc and actual Python behavior during migration, the **Python code is the source of truth**. This document is comprehensive but implementation details may have subtle differences.

**Validation Approach:**
1. Deploy Node.js version alongside Python version
2. Mirror production traffic to both (dark launch)
3. Compare responses for identical requests
4. Fix discrepancies until 100% match
5. Switch traffic gradually (10% → 50% → 100%)

---

**Document Version:** 1.0  
**Last Updated:** 2024-01-20  
**Python Version:** 3.11+  
**FastAPI Version:** 0.109.0  
**Database:** PostgreSQL 14+ with pgvector 0.5+
