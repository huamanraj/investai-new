# InvestAI API - Quick Reference Guide

**For Node.js Migration - Quick Lookup Reference**

## 📋 Critical Information

### Base Configuration
- **Base URL:** `/api`
- **CORS:** Allow all origins (`*`), all methods, all headers, credentials enabled
- **Default Port:** 8000
- **Content-Type:** `application/json` (except SSE which is `text/event-stream`)

### UUID Format
- All IDs are UUIDv4
- Format: `550e8400-e29b-41d4-a716-446655440000` (lowercase with hyphens)
- Database type: PostgreSQL `UUID`
- API: string representation

### Timestamp Format
- Database: `TIMESTAMP` (UTC always)
- API: ISO 8601 with milliseconds: `2024-01-20T10:30:00.000Z`

---

## 🚀 Endpoints Summary

### Projects Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | `/api/projects` | Create project + start background job | None |
| GET | `/api/projects` | List projects (paginated) | None |
| GET | `/api/projects/{id}` | Get project + documents + job status | None |
| GET | `/api/projects/{id}/status` | Get project status (lighter) | None |
| GET | `/api/projects/{id}/snapshot` | Get company snapshot (cached) | None |
| GET | `/api/projects/{id}/job` | Get detailed job info | None |
| POST | `/api/projects/{id}/cancel` | Cancel running job | None |
| POST | `/api/projects/{id}/resume` | Resume failed/cancelled job | None |
| GET | `/api/projects/{id}/progress-stream` | SSE stream of progress updates | None |
| DELETE | `/api/projects/{id}` | Delete project (cascade) | None |

### Chats Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | `/api/chats` | Create chat session | None |
| GET | `/api/chats` | List chats (paginated) | None |
| GET | `/api/chats/{id}` | Get chat + all messages | None |
| POST | `/api/chats/{id}/messages` | Send message + stream AI response (SSE) | None |
| DELETE | `/api/chats/{id}` | Delete chat | None |

### Utility Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Root info (version, docs link) |
| GET | `/health` | Health check |

---

## 📊 Common Response Formats

### Project Response
```json
{
  "id": "uuid",
  "company_name": "COMPANY NAME",
  "source_url": "https://www.bseindia.com/...",
  "exchange": "BSE",
  "status": "pending|scraping|downloading|processing|completed|failed",
  "error_message": null | "error text",
  "created_at": "2024-01-20T10:30:00.000Z"
}
```

### Document Response
```json
{
  "id": "uuid",
  "document_type": "annual_report|presentation|transcript",
  "fiscal_year": "FY2024",
  "label": "Annual Report 2024",
  "file_url": "https://res.cloudinary.com/...",
  "original_url": "https://www.bseindia.com/...",
  "page_count": 120,
  "created_at": "2024-01-20T10:35:00.000Z"
}
```

### Job Status Response
```json
{
  "job_id": "a3f8d9e2",
  "status": "pending|running|completed|failed|cancelled",
  "current_step": "create_embeddings",
  "current_step_index": 7,
  "total_steps": 8,
  "failed_step": null | "step_name",
  "error_message": null | "error text",
  "can_resume": true,
  "updated_at": "2024-01-20T10:38:00.000Z"
}
```

### Error Response
```json
{
  "detail": "Error message"
}
```

### Validation Error (422)
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

---

## ⚠️ Critical Behaviors

### 1. Create Project (`POST /api/projects`)
**Must Do:**
1. Extract company name from URL (parse from path segment)
2. Check if URL already exists → 400 if duplicate
3. Create project with status "pending"
4. Start background job **non-blocking** (don't wait for completion)
5. Return project immediately

**URL Validation Pattern:**
```
https://www.bseindia.com/stock-share-price/{slug}/{code}/{id}/financials-annual-reports/
```

**Company Name Extraction:**
```javascript
// Example: "vimta-labs-ltd" → "VIMTA LABS LTD"
const slug = url.split('/')[4];
const companyName = slug.replace(/-/g, ' ').toUpperCase();
```

### 2. Resume Job Logic (`POST /api/projects/{id}/resume`)
**Complex Rules:**

**If no job exists:**
- Start fresh job (background task may have crashed)
- Return `"Started fresh processing job"`

**If job is "running" and stale (>5 min since last update):**
- Reset job to "failed" status
- Set `failed_step` = `current_step`
- Allow resume

**If job is "running" and NOT stale:**
- Return 400 error (job is actively running)

**If job is "failed" or "cancelled" and `can_resume = true`:**
- Reset job status to "running"
- Clear error fields
- Start background task with `is_resume = true`
- Resume from `last_successful_step`

**If project status is "completed":**
- Return 400 (already completed)

### 3. Progress Stream SSE (`GET /api/projects/{id}/progress-stream`)
**Stream Format:**
```
data: {JSON}\n\n
```

**Event Types:**
- `connected` - Initial connection
- `status` - Step update
- `progress` - Progress within step
- `detail` - Detailed info
- `completed` - Job done
- `error` - Job failed
- `cancelled` - Job cancelled
- `stream_end` - Stream closing

**Keep-Alive:**
Send `: keep-alive\n\n` every 30 seconds

**Auto-Close:**
Stream closes when job reaches terminal state

**Headers Required:**
```javascript
{
  'Content-Type': 'text/event-stream',
  'Cache-Control': 'no-cache',
  'Connection': 'keep-alive',
  'X-Accel-Buffering': 'no'  // Critical for nginx
}
```

### 4. Chat Message SSE (`POST /api/chats/{id}/messages`)
**Process Flow:**
1. Save user message to DB
2. Create query embedding (OpenAI text-embedding-3-large)
3. Search similar chunks (pgvector cosine similarity, top 10)
4. Build context from chunks
5. Stream GPT response with context + history
6. Save complete AI response to DB
7. Send `done` event with `message_id`

**SSE Events:**
```
data: {'type': 'status', 'message': 'Creating query embedding...'}
data: {'type': 'status', 'message': 'Searching relevant documents...'}
data: {'type': 'context', 'chunks_found': 8}
data: {'type': 'start'}
data: {'type': 'chunk', 'content': 'Revenue in'}
data: {'type': 'chunk', 'content': ' FY2024 was'}
data: {'type': 'done', 'message_id': 'uuid'}
```

**JSON Escaping in Chunks:**
```javascript
content = content
  .replace(/\\/g, '\\\\')   // Backslashes first!
  .replace(/"/g, '\\"')     // Quotes
  .replace(/\n/g, '\\n');   // Newlines
```

### 5. Cascade Deletes
**Delete Project:**
Automatically deletes:
- documents → document_pages → text_chunks → embeddings
- extraction_results
- company_snapshots
- processing_jobs

**Delete Chat:**
Automatically deletes:
- All messages in chat

**Must Have `ON DELETE CASCADE` in foreign keys.**

---

## 🗄️ Database Operations

### Similarity Search Query
```sql
SELECT 
    tc.content,
    tc.field,
    dp.page_number,
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
LIMIT 10;
```

### Chunking Parameters
- **Chunk Size:** 400 characters
- **Overlap:** 80 characters
- **Max per page:** 10 chunks
- **Embedding:** OpenAI text-embedding-3-large (3072 dims)

### Vector Index (MUST HAVE)
```sql
CREATE INDEX embeddings_vector_idx
ON embeddings
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

---

## 🔑 Environment Variables

### Required
```bash
DATABASE_URL=postgresql://...
OPENAI_API_KEY=sk-...
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
```

### Models
```bash
OPENAI_EMBEDDING_MODEL=text-embedding-3-large   # 3072 dims
OPENAI_CHAT_MODEL=gpt-4.1                       # Chat responses
OPENAI_EXTRACTION_MODEL=gpt-5-nano              # PDF extraction
```

### Processing
```bash
CHUNK_SIZE=400
CHUNK_OVERLAP=80
MAX_CHUNKS_PER_PAGE=10
MAX_SIMILARITY_RESULTS=25
```

---

## 📝 Processing Steps (Background Jobs)

1. **validate_url** - Check BSE URL format
2. **scrape_page** - Playwright scrape for PDFs
3. **download_pdfs** - Download to memory buffers
4. **upload_to_cloud** - Upload to Cloudinary
5. **extract_text** - Extract text page-by-page (pymupdf)
6. **extract_data** - GPT structured extraction
7. **create_embeddings** - Chunk + embed + pgvector
8. **generate_snapshot** - GPT company summary

**Resume Data Fields:**
- `pdf_buffers` - Base64 encoded PDFs (skip re-download)
- `extraction_results` - Structured data (skip re-extraction)
- `pdf_info` - Metadata about PDFs
- `scrape_results` - Links and counts

---

## ❌ Common HTTP Status Codes

| Code | When |
|------|------|
| 200 | Success |
| 201 | Created (project, chat) |
| 204 | No Content (delete) |
| 400 | Bad request (validation, duplicate URL, already completed) |
| 404 | Not found (project, chat, document, snapshot, job) |
| 422 | Validation error (Pydantic) |
| 500 | Internal server error |
| 503 | Service unavailable (OpenAI not configured, DB connection error) |

---

## 🎯 Testing Checklist

### Must Verify
- [ ] All endpoints return identical JSON structure
- [ ] UUIDs are lowercase with hyphens
- [ ] Timestamps include milliseconds (`.000Z`)
- [ ] SSE streams format correctly (`data: {...}\n\n`)
- [ ] JSON escaping in SSE chunks (backslash, quotes, newlines)
- [ ] Keep-alive in SSE every 30s
- [ ] Cascade deletes work
- [ ] Vector search uses index (check EXPLAIN)
- [ ] Background jobs don't block HTTP responses
- [ ] Resume logic handles all edge cases
- [ ] Stale job detection (>5 min threshold)
- [ ] CORS headers correct
- [ ] Error responses match format

### Edge Cases to Test
1. **Resume with no job** → Should start fresh
2. **Resume with stale running job** → Should reset to failed
3. **Resume completed project** → Should return 400
4. **Duplicate project URL** → Should return 400
5. **Invalid BSE URL** → Should return 400 with validation error
6. **Cancel non-existent job** → Should return 404
7. **Get snapshot before generation** → Should return 404
8. **Chat with non-existent projects** → Should return 404
9. **SSE client disconnect** → Should cleanup properly
10. **Large PDF (>100 pages)** → Should not timeout/crash

---

## 🚨 Critical "Don't Forget" Items

### 1. Database Connection
```javascript
// For PostgreSQL async with asyncpg equivalent
{
  dialect: 'postgres',
  dialectOptions: {
    ssl: DATABASE_URL.includes('neon.tech') ? { rejectUnauthorized: false } : false
  },
  pool: {
    max: 10,
    min: 2,
    acquire: 30000,
    idle: 10000
  }
}
```

### 2. SSE Headers
```javascript
res.setHeader('Content-Type', 'text/event-stream');
res.setHeader('Cache-Control', 'no-cache');
res.setHeader('Connection', 'keep-alive');
res.setHeader('X-Accel-Buffering', 'no');  // Don't forget!
```

### 3. Vector Search
```javascript
// PostgreSQL syntax for pgvector cosine similarity
// <=> is cosine distance operator
const query = `
  SELECT ... 
  FROM embeddings e 
  WHERE ... 
  ORDER BY e.embedding <=> $1 
  LIMIT 10
`;
```

### 4. UUID Array in Messages
```javascript
// PostgreSQL array syntax
const query = `
  UPDATE messages 
  SET project_ids = $1::uuid[] 
  WHERE id = $2
`;
// Pass array: ['uuid-1', 'uuid-2']
```

### 5. Job ID Generation
```javascript
// 8-character random hex string
const jobId = crypto.randomBytes(4).toString('hex');
// Example: "a3f8d9e2"
```

### 6. Company Name Extraction
```javascript
// From URL: .../vimta-labs-ltd/...
const parts = url.split('/');
const slug = parts[4];  // "vimta-labs-ltd"
const name = slug.replace(/-/g, ' ').toUpperCase();  // "VIMTA LABS LTD"
```

### 7. Embedding Dimensions
```javascript
// MUST be 3072 for text-embedding-3-large
// Vector index MUST match: VECTOR(3072)
const embedding = await openai.embeddings.create({
  model: 'text-embedding-3-large',
  input: text
});
// embedding.data[0].embedding.length === 3072
```

### 8. Chat History Format
```javascript
// Include all previous messages (not just last N)
const history = messages
  .filter(m => m.id !== currentMessageId)  // Exclude current
  .map(m => ({ role: m.role, content: m.content }));
```

### 9. Background Task Pattern
```javascript
// Non-blocking pattern
app.post('/api/projects', async (req, res) => {
  const project = await createProject(req.body);
  
  // Start job in background (don't await!)
  processProjectJob(project.id).catch(err => {
    console.error('Background job error:', err);
  });
  
  // Return immediately
  res.status(201).json(project);
});
```

### 10. Transaction for Multi-Step Ops
```javascript
// Example: Save message + embeddings
const transaction = await sequelize.transaction();
try {
  const message = await Message.create({...}, { transaction });
  const embedding = await Embedding.create({...}, { transaction });
  await transaction.commit();
} catch (error) {
  await transaction.rollback();
  throw error;
}
```

---

## 🔗 Quick Links

- **Full API Spec:** [API_MIGRATION_GUIDE.md](./API_MIGRATION_GUIDE.md)
- **Database Schema:** [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md)
- **OpenAPI Spec:** [openapi.json](./openapi.json)
- **Python Source:** [app/api/](./app/api/)

---

## 💡 Pro Tips

### Development Workflow
1. Deploy Node.js version alongside Python version
2. Use traffic mirroring to test both simultaneously
3. Compare responses for identical requests
4. Log discrepancies and fix iteratively
5. Gradually increase Node.js traffic (10% → 50% → 100%)

### Performance Optimization
- Use connection pooling (min 2, max 10)
- Enable database query logging in development
- Use `EXPLAIN ANALYZE` for slow queries
- Index foreign keys and commonly filtered columns
- Use Redis for progress pub/sub if scaling

### Debugging
- Log all API requests/responses in development
- Save SSE streams to files for inspection
- Log background job steps verbosely
- Use database query logging
- Monitor pgvector index usage (`EXPLAIN`)

---

**Last Updated:** 2024-01-20  
**For Migration To:** Node.js/TypeScript  
**Python Version:** 3.11+ / FastAPI 0.109.0
