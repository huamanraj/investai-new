# InvestAI Database Schema

## 📊 Entity Relationship Diagram (ERD)

```
┌─────────────────────┐
│     projects        │
│─────────────────────│
│ id (PK, UUID)       │
│ company_name        │
│ source_url (unique) │
│ exchange            │
│ status              │
│ error_message       │
│ created_at          │
└──────────┬──────────┘
           │
           │ 1:N
           │
    ┌──────┴──────┬────────────────┬─────────────────┐
    │             │                │                 │
┌───▼────────┐ ┌──▼────────────┐ ┌▼──────────────┐ │
│ documents  │ │company_       │ │processing_    │ │
│            │ │snapshots      │ │jobs           │ │
│ id (PK)    │ │               │ │               │ │
│project_id  │ │project_id (PK)│ │id (PK)        │ │
│            │ │               │ │project_id     │ │
└─────┬──────┘ │snapshot_data  │ │job_id (unique)│ │
      │        │generated_at   │ │status         │ │
      │        │version        │ │current_step   │ │
      │        │updated_at     │ │resume_data    │ │
      │        └───────────────┘ └───────────────┘ │
      │                                             │
      │ 1:N                                         │
      │                                             │
  ┌───┴────────────────┐                           │
  │                    │                           │
┌─▼──────────────┐ ┌───▼─────────────┐            │
│document_pages  │ │extraction_      │            │
│                │ │results          │            │
│id (PK)         │ │                 │            │
│document_id     │ │id (PK)          │            │
│page_number     │ │document_id      │            │
│page_text       │ │extracted_data   │            │
└───────┬────────┘ │extraction_      │            │
        │          │metadata         │            │
        │          │company_name     │            │
        │          │fiscal_year      │            │
        │          │revenue          │            │
        │          │net_profit       │            │
        │ 1:N      └─────────────────┘            │
        │                                         │
    ┌───▼──────────┐                             │
    │text_chunks   │                             │
    │              │                             │
    │id (PK)       │                             │
    │page_id       │                             │
    │chunk_index   │                             │
    │content       │                             │
    │field         │                             │
    └───────┬──────┘                             │
            │                                    │
            │ 1:1                                │
            │                                    │
        ┌───▼──────────┐                        │
        │embeddings    │                        │
        │              │                        │
        │id (PK)       │                        │
        │chunk_id      │                        │
        │embedding     │◄───── pgvector SEARCH │
        │(VECTOR 3072) │                        │
        └──────────────┘                        │
                                                 │
┌─────────────────┐                             │
│    chats        │                             │
│─────────────────│                             │
│ id (PK, UUID)   │                             │
│ title           │                             │
│ created_at      │                             │
└────────┬────────┘                             │
         │                                      │
         │ 1:N                                  │
         │                                      │
    ┌────▼────────────┐                        │
    │messages         │                        │
    │                 │                        │
    │id (PK)          │                        │
    │chat_id          │                        │
    │role             │                        │
    │content          │                        │
    │project_ids[]    │────────────────────────┘
    │created_at       │      references projects
    └─────────────────┘
```

## 📋 Table Definitions

### 1. projects
**Purpose:** Main entity representing a company/BSE stock listing

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK, DEFAULT uuid_generate_v4() | Unique project identifier |
| company_name | TEXT | NOT NULL | Company name (extracted from URL) |
| source_url | TEXT | NOT NULL, UNIQUE | BSE India annual reports URL |
| exchange | TEXT | DEFAULT 'BSE' | Stock exchange |
| status | TEXT | DEFAULT 'pending' | pending, scraping, downloading, processing, completed, failed |
| error_message | TEXT | NULL | Error details if status = 'failed' |
| created_at | TIMESTAMP | DEFAULT NOW() | Project creation timestamp |

**Indexes:**
- Primary key on `id`
- Unique constraint on `source_url` (prevent duplicates)

**Relationships:**
- 1:N with `documents`
- 1:1 with `company_snapshots`
- 1:N with `processing_jobs`
- Referenced by `messages.project_ids[]`

---

### 2. documents
**Purpose:** PDF documents (annual reports, presentations, transcripts)

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK, DEFAULT uuid_generate_v4() | Unique document identifier |
| project_id | UUID | FK → projects(id) ON DELETE CASCADE | Parent project |
| document_type | TEXT | NOT NULL | annual_report, presentation, transcript |
| fiscal_year | TEXT | NULL | FY2022, FY2023, FY2024-25, etc. |
| label | TEXT | NULL | Display label (e.g., "2024-25 (Revised)") |
| file_url | TEXT | NOT NULL | Cloudinary hosted PDF URL |
| original_url | TEXT | NULL | Original BSE download URL |
| page_count | INT | NULL | Number of pages in PDF |
| created_at | TIMESTAMP | DEFAULT NOW() | Document creation timestamp |

**Indexes:**
- Primary key on `id`
- Foreign key index on `project_id`

**Relationships:**
- N:1 with `projects`
- 1:N with `document_pages`
- 1:N with `extraction_results`

---

### 3. document_pages
**Purpose:** Individual PDF pages (1 row = 1 page) - critical for citation accuracy

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK, DEFAULT uuid_generate_v4() | Unique page identifier |
| document_id | UUID | FK → documents(id) ON DELETE CASCADE | Parent document |
| page_number | INT | NOT NULL | Page number (1-indexed) |
| page_text | TEXT | NOT NULL | Extracted text from this page |
| created_at | TIMESTAMP | DEFAULT NOW() | Page creation timestamp |

**Indexes:**
- Primary key on `id`
- Foreign key index on `document_id`

**Relationships:**
- N:1 with `documents`
- 1:N with `text_chunks`

**Why per-page storage?**
- Enables accurate page citations in AI responses
- Allows targeted page retrieval for context
- Facilitates debugging of extraction issues

---

### 4. extraction_results
**Purpose:** Structured data extracted from documents via GPT

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK, DEFAULT uuid_generate_v4() | Unique extraction identifier |
| document_id | UUID | FK → documents(id) ON DELETE CASCADE | Source document |
| extracted_data | JSONB | NOT NULL | Complete extraction JSON |
| extraction_metadata | JSONB | NULL | Citations, confidence scores, reasoning |
| company_name | TEXT | NULL | Extracted company name (denormalized) |
| fiscal_year | TEXT | NULL | Extracted fiscal year (denormalized) |
| revenue | NUMERIC | NULL | Extracted revenue (for quick queries) |
| net_profit | NUMERIC | NULL | Extracted net profit (for quick queries) |
| created_at | TIMESTAMP | DEFAULT NOW() | Extraction timestamp |

**Indexes:**
- Primary key on `id`
- Index on `document_id`

**Relationships:**
- N:1 with `documents`

**extracted_data Schema:**
```json
{
  "company_name": "VIMTA LABS LTD",
  "fiscal_year": "FY2024",
  "financial_highlights": {
    "revenue": 1234.56,
    "net_profit": 234.56,
    "total_assets": 5678.90,
    "shareholders_equity": 3456.78,
    "eps": 12.34,
    "roe": 15.5,
    "debt_to_equity": 0.25
  },
  "business_segments": [
    {"name": "Testing Services", "revenue": 800, "growth": 12.5},
    {"name": "Certification", "revenue": 434.56, "growth": 20.0}
  ],
  "risk_factors": [
    "Market volatility in pharmaceutical sector",
    "Regulatory changes in international markets"
  ],
  "key_initiatives": [
    "Expansion of lab facilities in Bangalore",
    "New partnerships with European clients"
  ],
  "management_outlook": "Positive growth trajectory expected...",
  "citations": [
    {"field": "revenue", "page": 23, "text": "Total revenue for FY2024..."},
    {"field": "risk_factors", "page": 45, "text": "Key risks include..."}
  ]
}
```

---

### 5. text_chunks
**Purpose:** Searchable text chunks for RAG (Retrieval-Augmented Generation)

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK, DEFAULT uuid_generate_v4() | Unique chunk identifier |
| page_id | UUID | FK → document_pages(id) ON DELETE CASCADE | Source page |
| chunk_index | INT | NOT NULL | Order of chunk in page (0-indexed) |
| content | TEXT | NOT NULL | Chunk text content (~400 chars) |
| field | VARCHAR(100) | NULL | Source field (e.g., "financial_highlights") |
| created_at | TIMESTAMP | DEFAULT NOW() | Chunk creation timestamp |

**Indexes:**
- Primary key on `id`
- Foreign key index on `page_id`

**Relationships:**
- N:1 with `document_pages`
- 1:1 with `embeddings`

**Chunking Parameters:**
- Chunk size: 400 characters
- Overlap: 80 characters
- Max chunks per page: 10

**Field Values:**
- `financial_highlights` - Financial metrics and numbers
- `risk_factors` - Risk disclosures
- `business_segments` - Segment-wise revenue/performance
- `key_initiatives` - Strategic initiatives
- `management_outlook` - Forward-looking statements
- `general` - Other content

---

### 6. embeddings
**Purpose:** Vector embeddings for semantic similarity search (pgvector)

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK, DEFAULT uuid_generate_v4() | Unique embedding identifier |
| chunk_id | UUID | FK → text_chunks(id) ON DELETE CASCADE | Source chunk |
| embedding | VECTOR(3072) | NOT NULL | OpenAI text-embedding-3-large vector |
| created_at | TIMESTAMP | DEFAULT NOW() | Embedding creation timestamp |

**Indexes:**
- Primary key on `id`
- Foreign key index on `chunk_id`
- **Vector index:** IVFFlat on `embedding` with cosine similarity

**Vector Index (CRITICAL for performance):**
```sql
CREATE INDEX embeddings_vector_idx
ON embeddings
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

**Relationships:**
- 1:1 with `text_chunks`

**Embedding Model:**
- Model: `text-embedding-3-large`
- Dimensions: 3072
- Provider: OpenAI
- Similarity: Cosine distance

**Similarity Search Query:**
```sql
SELECT 
    tc.content,
    tc.field,
    dp.page_number,
    d.document_type,
    d.fiscal_year,
    p.company_name,
    (e.embedding <=> $1) AS distance  -- cosine distance
FROM embeddings e
JOIN text_chunks tc ON tc.id = e.chunk_id
JOIN document_pages dp ON dp.id = tc.page_id
JOIN documents d ON d.id = dp.document_id
JOIN projects p ON p.id = d.project_id
WHERE d.project_id = ANY($2)  -- filter by projects
ORDER BY e.embedding <=> $1   -- nearest neighbors first
LIMIT 10;
```

---

### 7. chats
**Purpose:** Chat sessions for multi-turn conversations

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK, DEFAULT uuid_generate_v4() | Unique chat identifier |
| title | TEXT | NULL | Chat title (user-provided or auto-generated) |
| created_at | TIMESTAMP | DEFAULT NOW() | Chat creation timestamp |

**Indexes:**
- Primary key on `id`
- Index on `created_at` (for listing recent chats)

**Relationships:**
- 1:N with `messages`

**Title Generation:**
- 1 project: "Chat with {company_name}"
- 2+ projects: "Chat with {count} companies"
- User can override

---

### 8. messages
**Purpose:** Individual messages within chat sessions (user and AI)

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK, DEFAULT uuid_generate_v4() | Unique message identifier |
| chat_id | UUID | FK → chats(id) ON DELETE CASCADE | Parent chat session |
| role | TEXT | NOT NULL | 'user' or 'ai' |
| content | TEXT | NOT NULL | Message text content |
| project_ids | UUID[] | NOT NULL | Projects active for this message |
| created_at | TIMESTAMP | DEFAULT NOW() | Message timestamp |

**Indexes:**
- Primary key on `id`
- Foreign key index on `chat_id`
- Index on `created_at` (for message ordering)

**Relationships:**
- N:1 with `chats`
- References `projects` via `project_ids[]` array

**project_ids Array:**
Allows per-message project selection. User can change which projects are "toggled on" during conversation:
```
Message 1: project_ids = [proj-a]           // Ask about company A
Message 2: project_ids = [proj-a, proj-b]   // Compare A and B
Message 3: project_ids = [proj-b]           // Ask only about B
```

**RAG Context Building:**
Only searches embeddings for projects in current message's `project_ids`.

---

### 9. company_snapshots
**Purpose:** Pre-computed company summaries for instant UI loading

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| project_id | UUID | PK, FK → projects(id) ON DELETE CASCADE | Project identifier (1:1) |
| snapshot_data | JSONB | NOT NULL, DEFAULT '{}' | Complete snapshot JSON |
| generated_at | TIMESTAMP | DEFAULT NOW() | Initial generation timestamp |
| version | INT | DEFAULT 1 | Snapshot schema version |
| updated_at | TIMESTAMP | DEFAULT NOW() | Last update timestamp |

**Indexes:**
- Primary key on `project_id`

**Relationships:**
- 1:1 with `projects`

**snapshot_data Schema:**
```json
{
  "company_overview": {
    "name": "VIMTA LABS LTD",
    "description": "Leading independent testing, inspection...",
    "industry": "Testing & Certification",
    "founded": "1993",
    "headquarters": "Hyderabad, India",
    "employees": "850+",
    "website": "https://vimta.com"
  },
  "financial_metrics": {
    "revenue": [
      {"year": "FY2022", "value": 1000.5, "growth": 10.2},
      {"year": "FY2023", "value": 1200.3, "growth": 19.9},
      {"year": "FY2024", "value": 1400.8, "growth": 16.7}
    ],
    "net_profit": [...],
    "eps": [...],
    "roe": [...],
    "debt_to_equity": [...]
  },
  "performance_summary": {
    "revenue_trend": "Strong growth trajectory with 16.7% YoY increase",
    "profitability": "Consistent profit margins around 18-20%",
    "key_highlights": [
      "Market leader in pharmaceutical testing",
      "Expanding into new geographies",
      "Strong client retention rate"
    ],
    "concerns": [
      "Increasing competition",
      "Regulatory uncertainties"
    ]
  },
  "charts_data": {
    "revenue_chart": {
      "labels": ["FY2022", "FY2023", "FY2024"],
      "values": [1000.5, 1200.3, 1400.8],
      "type": "bar"
    },
    "profit_chart": {...},
    "segment_breakdown": {...}
  },
  "metadata": {
    "generated_at": "2024-01-20T10:40:00Z",
    "data_sources": [
      "Annual Report FY2024",
      "Q3 2024 Results Presentation"
    ],
    "data_coverage": "FY2022 to FY2024"
  }
}
```

**Why Pre-Compute?**
- Instant loading (<50ms vs. several seconds for LLM generation)
- Consistent UI experience
- Reduced OpenAI API costs
- Allows caching at CDN layer

---

### 10. processing_jobs
**Purpose:** Track background job progress for resumable processing

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK, DEFAULT uuid_generate_v4() | Unique job record identifier |
| project_id | UUID | FK → projects(id) ON DELETE CASCADE | Associated project |
| job_id | VARCHAR(50) | UNIQUE, NOT NULL | Short job identifier (8 chars) |
| status | VARCHAR(20) | NOT NULL, DEFAULT 'pending' | pending, running, completed, failed, cancelled |
| current_step | VARCHAR(50) | NULL | Current processing step name |
| current_step_index | INT | DEFAULT 0 | Current step number (0-based) |
| total_steps | INT | DEFAULT 8 | Total number of steps |
| progress_data | JSONB | DEFAULT '{}' | Detailed progress for each step |
| documents_processed | INT | DEFAULT 0 | Count of documents processed |
| embeddings_created | INT | DEFAULT 0 | Count of embeddings created |
| error_message | TEXT | NULL | Error details if failed |
| failed_step | VARCHAR(50) | NULL | Step where failure occurred |
| retry_count | INT | DEFAULT 0 | Number of retry attempts |
| max_retries | INT | DEFAULT 3 | Maximum retry attempts |
| started_at | TIMESTAMP | DEFAULT NOW() | Job start timestamp |
| updated_at | TIMESTAMP | DEFAULT NOW() | Last update timestamp |
| completed_at | TIMESTAMP | NULL | Job completion timestamp |
| cancelled_at | TIMESTAMP | NULL | Job cancellation timestamp |
| can_resume | BOOLEAN | DEFAULT true | Whether job can be resumed |
| last_successful_step | VARCHAR(50) | NULL | Last successfully completed step |
| resume_data | JSONB | DEFAULT '{}' | Intermediate data for resume |

**Indexes:**
- Primary key on `id`
- Unique index on `job_id`
- Index on `project_id`
- Index on `status`
- Unique index on `(project_id)` WHERE `status IN ('pending', 'running')` (prevent concurrent jobs)

**Relationships:**
- N:1 with `projects`

**Processing Steps (in order):**
1. `validate_url` - Validate BSE URL format
2. `scrape_page` - Scrape BSE page for PDF links
3. `download_pdfs` - Download PDF files to memory
4. `upload_to_cloud` - Upload to Cloudinary
5. `extract_text` - Extract text page-by-page
6. `extract_data` - Extract structured data with GPT
7. `create_embeddings` - Generate embeddings
8. `generate_snapshot` - Create company snapshot

**resume_data Schema:**
```json
{
  "pdf_buffers": {
    "doc-uuid-1": "base64_encoded_pdf_buffer",
    "doc-uuid-2": "base64_encoded_pdf_buffer"
  },
  "extraction_results": {
    "doc-uuid-1": {
      "company_name": "VIMTA LABS LTD",
      "fiscal_year": "FY2024",
      "financial_highlights": {...}
    },
    "doc-uuid-2": {...}
  },
  "pdf_info": [
    {
      "url": "https://www.bseindia.com/.../report.pdf",
      "label": "Annual Report FY2024",
      "fiscal_year": "FY2024"
    }
  ],
  "scrape_results": {
    "pdf_count": 3,
    "pdf_links": [...]
  }
}
```

**Job Lifecycle:**
```
pending → running → completed
              ↓
            failed → (resume) → running → completed
              ↓
          cancelled → (resume) → running → completed
```

**Stale Job Detection:**
If `status = 'running'` AND `updated_at < NOW() - 5 minutes`:
→ Job is considered stale (crashed/stuck)
→ Can be reset to 'failed' for resume

---

## 🔍 Key Queries

### Get project with all related data
```sql
SELECT 
    p.*,
    json_agg(DISTINCT d.*) AS documents,
    cs.snapshot_data AS snapshot,
    pj.status AS job_status,
    pj.current_step AS job_current_step
FROM projects p
LEFT JOIN documents d ON d.project_id = p.id
LEFT JOIN company_snapshots cs ON cs.project_id = p.id
LEFT JOIN processing_jobs pj ON pj.project_id = p.id
WHERE p.id = $1
GROUP BY p.id, cs.project_id, pj.id
ORDER BY pj.updated_at DESC
LIMIT 1;
```

### Search similar chunks for RAG
```sql
SELECT 
    tc.id,
    tc.content,
    tc.field,
    dp.page_number,
    d.id AS document_id,
    d.document_type,
    d.fiscal_year,
    p.company_name,
    (e.embedding <=> $1::vector) AS distance
FROM embeddings e
JOIN text_chunks tc ON tc.id = e.chunk_id
JOIN document_pages dp ON dp.id = tc.page_id
JOIN documents d ON d.id = dp.document_id
JOIN projects p ON p.id = d.project_id
WHERE d.project_id = ANY($2::uuid[])
ORDER BY e.embedding <=> $1::vector
LIMIT $3;
```

### Get chat with messages and project info
```sql
SELECT 
    c.id,
    c.title,
    c.created_at,
    json_agg(
        json_build_object(
            'id', m.id,
            'role', m.role,
            'content', m.content,
            'project_ids', m.project_ids,
            'created_at', m.created_at,
            'projects', (
                SELECT json_agg(json_build_object('id', p.id, 'name', p.company_name))
                FROM projects p
                WHERE p.id = ANY(m.project_ids)
            )
        ) ORDER BY m.created_at
    ) AS messages
FROM chats c
LEFT JOIN messages m ON m.chat_id = c.id
WHERE c.id = $1
GROUP BY c.id;
```

### Find projects needing snapshot regeneration
```sql
SELECT p.id, p.company_name, p.status
FROM projects p
LEFT JOIN company_snapshots cs ON cs.project_id = p.id
WHERE p.status = 'completed'
  AND (cs.project_id IS NULL OR cs.updated_at < p.created_at);
```

---

## 🛠️ Database Setup

### 1. Create Database
```sql
CREATE DATABASE investai;
\c investai
```

### 2. Enable Extensions
```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;
```

### 3. Run Initial Schema
```bash
psql -U username -d investai -f db/initial_schema.sql
```

### 4. Run Migrations (in order)
```bash
psql -U username -d investai -f db/migrations/001_add_status_columns.sql
psql -U username -d investai -f db/migrations/002_add_extraction_results.sql
psql -U username -d investai -f db/migrations/003_expand_company_snapshots.sql
psql -U username -d investai -f db/migrations/004_add_job_tracking.sql
psql -U username -d investai -f db/migrations/005_add_field_to_text_chunks.sql
```

### 5. Verify Setup
```sql
-- Check extensions
SELECT * FROM pg_extension WHERE extname IN ('uuid-ossp', 'vector');

-- Check tables
SELECT tablename FROM pg_tables WHERE schemaname = 'public';

-- Check vector index
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE tablename = 'embeddings';
```

---

## 🔧 Maintenance Queries

### Check database size
```sql
SELECT 
    pg_size_pretty(pg_database_size('investai')) AS database_size,
    pg_size_pretty(pg_total_relation_size('embeddings')) AS embeddings_size,
    pg_size_pretty(pg_total_relation_size('text_chunks')) AS chunks_size,
    pg_size_pretty(pg_total_relation_size('document_pages')) AS pages_size;
```

### Count records per table
```sql
SELECT 
    (SELECT COUNT(*) FROM projects) AS projects,
    (SELECT COUNT(*) FROM documents) AS documents,
    (SELECT COUNT(*) FROM document_pages) AS pages,
    (SELECT COUNT(*) FROM text_chunks) AS chunks,
    (SELECT COUNT(*) FROM embeddings) AS embeddings,
    (SELECT COUNT(*) FROM chats) AS chats,
    (SELECT COUNT(*) FROM messages) AS messages,
    (SELECT COUNT(*) FROM processing_jobs) AS jobs;
```

### Find orphaned records
```sql
-- Chunks without embeddings
SELECT COUNT(*) FROM text_chunks tc
LEFT JOIN embeddings e ON e.chunk_id = tc.id
WHERE e.id IS NULL;

-- Documents without pages
SELECT d.id, d.document_type, d.fiscal_year
FROM documents d
LEFT JOIN document_pages dp ON dp.document_id = d.id
WHERE dp.id IS NULL;
```

### Vacuum and analyze
```sql
VACUUM ANALYZE projects;
VACUUM ANALYZE embeddings;
VACUUM ANALYZE text_chunks;
```

---

## 📈 Performance Optimization

### 1. Vector Index Tuning
```sql
-- For 10k-100k vectors (current)
CREATE INDEX embeddings_vector_idx
ON embeddings
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- For >100k vectors (future)
CREATE INDEX embeddings_vector_idx_hnsw
ON embeddings
USING hnsw (embedding vector_cosine_ops);
```

### 2. Partial Indexes
```sql
-- Only index active jobs
CREATE INDEX processing_jobs_active_idx
ON processing_jobs(project_id, status, updated_at)
WHERE status IN ('pending', 'running');

-- Only index recent chats
CREATE INDEX chats_recent_idx
ON chats(created_at DESC)
WHERE created_at > NOW() - INTERVAL '30 days';
```

### 3. Materialized Views
```sql
-- Pre-aggregate project statistics
CREATE MATERIALIZED VIEW project_stats AS
SELECT 
    p.id AS project_id,
    p.company_name,
    COUNT(DISTINCT d.id) AS document_count,
    COUNT(DISTINCT dp.id) AS page_count,
    COUNT(DISTINCT tc.id) AS chunk_count,
    COUNT(DISTINCT e.id) AS embedding_count,
    MAX(d.created_at) AS latest_document_date
FROM projects p
LEFT JOIN documents d ON d.project_id = p.id
LEFT JOIN document_pages dp ON dp.document_id = d.id
LEFT JOIN text_chunks tc ON tc.page_id = dp.id
LEFT JOIN embeddings e ON e.chunk_id = tc.id
GROUP BY p.id;

-- Refresh periodically
REFRESH MATERIALIZED VIEW project_stats;
```

---

## 🔒 Security Considerations

### Row-Level Security (RLS)
```sql
-- Example: Restrict access to projects by user
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_projects ON projects
    FOR ALL
    USING (user_id = current_user_id());
```

### Audit Log Trigger
```sql
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    table_name TEXT NOT NULL,
    operation TEXT NOT NULL,
    old_data JSONB,
    new_data JSONB,
    changed_at TIMESTAMP DEFAULT NOW(),
    changed_by TEXT DEFAULT current_user
);

CREATE OR REPLACE FUNCTION audit_trigger()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO audit_log (table_name, operation, old_data, new_data)
    VALUES (TG_TABLE_NAME, TG_OP, 
            CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN row_to_json(OLD) END,
            CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN row_to_json(NEW) END);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply to sensitive tables
CREATE TRIGGER projects_audit
AFTER INSERT OR UPDATE OR DELETE ON projects
FOR EACH ROW EXECUTE FUNCTION audit_trigger();
```

---

**Document Version:** 1.0  
**Last Updated:** 2024-01-20  
**PostgreSQL Version:** 14+  
**pgvector Version:** 0.5+
