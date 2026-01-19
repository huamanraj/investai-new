# InvestAI Backend Development Log

## Project Overview

Building a FastAPI backend for an investment AI agent that processes BSE India annual reports. The system scrapes PDFs, extracts structured financial data, and creates vector embeddings for RAG-based analysis.

## 1. Core Infrastructure

- **FastAPI Application**: Set up `app/main.py` with CORS, logging, and database initialization.
- **Database**:
  - PostgreSQL with `asyncpg` and `SQLAlchemy`.
  - `pgvector` extension enabled for vector embeddings.
  - Initial schema designed for Projects, Documents, Pages, Chunks, Embeddings, and Chats.
- **Configuration**: `pydantic-settings` for `.env` management (Database, OpenAI, Cloudinary, LlamaCloud).
- **Logging**: Custom JSON file logging (`logs/`) and console logging.

## 2. Feature Implementation

### A. PDF Scraping & Acquisition

- **Playwright Scraper**:
  - Implemented `BSEScraper` service (`app/services/scraper.py`).
  - **Fixed**: Solved Windows asyncio/subprocess issues by using Playwright's **Sync API** within a thread pool executor.
  - Logic: Scrapes BSE India pages, filters for the latest annual report, and downloads securely in-memory.
- **URL Validation**: Regex-based validation for BSE India URLs.

### B. Cloudinary Integration

- **Upload Service**:
  - `CloudinaryService` (`app/services/cloudinary_service.py`) handles PDF uploads.
  - Supports large file chunking (>10MB).
  - Organizes files by Company Name and Fiscal Year.

### C. Data Extraction (LlamaExtract)

- **Extraction Service**:
  - `LlamaExtractService` (`app/services/llama_extract.py`) integrates with Llama Cloud.
  - **Schema**: `FinancialReportSchema` defines structured fields (Revenue, Net Profit, EPS, Risk Factors, Key Highlights, Outlook).
  - **Features**: Uses `MULTIMODAL` mode for charts/tables, enables citations and reasoning.
  - **Logging**: Saves raw extraction results to `logs/extractions/` for debugging.
  - **Database**: Added `extraction_results` table to store the structured JSON output.

### D. Embeddings & RAG Prep

- **Embeddings Service**:
  - `EmbeddingsService` (`app/services/embeddings.py`) integrates with OpenAI (`text-embedding-3-large`).
  - **Batch Processing**: Handles bulk creation of embeddings (up to 2048 texts).
  - **Smart Chunking**:
    - **Text Chunking**: Character-based chunking with sentence boundary awareness.
    - **Data Chunking**: Converts structured LlamaExtract JSON (Financials, Risks, Highlights) into semantic text chunks for better retrieval.

### E. Background Processing

- **Job Orchestration**:
  - `process_project` job (`app/jobs/project_processor.py`) manages the end-to-end pipeline.
  - **Workflow**:
    1. Scrape PDF URL -> 2. Download PDF -> 3. Upload to Cloudinary -> 4. Extract Data (LlamaExtract) -> 5. Create Embeddings (In Progress) -> 6. Save to DB.
  - Tracks status in real-time (`scraping`, `downloading`, `extracting`, `completed`).

## 3. Current State

- **Completed**: 
  - ✅ Scraping, Cloudinary Upload
  - ✅ LlamaExtract data extraction
  - ✅ Extraction results saved to `extraction_results` table
  - ✅ Embeddings service integration
  - ✅ Chunks and embeddings saved to database
  
- **Background Job Workflow** (`process_project`):
  1. ✅ Scrape PDF URL from BSE India
  2. ✅ Download PDF in memory
  3. ✅ Upload to Cloudinary
  4. ✅ Create Document record
  5. ✅ Extract structured data with LlamaExtract
  6. ✅ Save extraction result to `extraction_results` table
  7. ✅ Convert extracted data into semantic chunks using `chunk_extraction_data()`
  8. ✅ Create embeddings in batch using OpenAI
  9. ✅ Save chunks to `text_chunks` table (linked via a dummy page with page_number=0)
  10. ✅ Save embeddings to `embeddings` table with pgvector
  11. ✅ Generate company snapshot using GPT-4o-mini
  12. ✅ Save snapshot to `company_snapshots` table

## 4. Technical Details

### Embeddings Integration

- **Chunk Creation**: `embeddings_service.chunk_extraction_data()` converts structured LlamaExtract JSON into searchable text chunks:
  - Company overview (name, fiscal year, report type)
  - Financial highlights (revenue, profit, EPS, growth metrics)
  - Key business highlights (each as separate chunk)
  - Business segments
  - Risk factors (split into smaller chunks if long)
  - Future outlook
  - Auditor and registered office

- **Batch Processing**: Uses `create_embeddings_batch()` to generate embeddings for all chunks at once (up to 2048 texts per batch).

- **Database Storage**: 
  - Creates a dummy `DocumentPage` (page_number=0) to represent structured extraction data
  - Links `TextChunk` records to this page with field metadata
  - Stores 3072-dimension vectors in `Embedding` table using pgvector

- **Error Handling**: Embedding failures don't block the entire job - extraction results are still saved.

### F. Chat & RAG System

- **RAG Service** (`app/services/rag.py`):
  - **Vector Search**: Uses pgvector cosine similarity to find relevant chunks across selected projects.
  - **Context Building**: Groups chunks by company and formats them with fiscal year/document metadata.
  - **Streaming**: GPT-4o-mini streaming responses via OpenAI API.
  - **Multi-Company Support**: Can search and chat with multiple companies simultaneously.

- **Chat API** (`app/api/chats.py`):
  - **POST /api/chats**: Create new chat session with initial project selection.
  - **GET /api/chats**: List all chats with message counts.
  - **GET /api/chats/{chat_id}**: Get chat details with full message history.
  - **POST /api/chats/{chat_id}/messages**: Send message and get SSE streaming response.
  - **DELETE /api/chats/{chat_id}**: Delete chat and all messages.

- **UX Features**:
  - ✅ Chat history independent of projects
  - ✅ Dynamic project selection per message
  - ✅ Multi-company chat support
  - ✅ Real-time streaming responses via SSE
  - ✅ Context-aware responses with citation metadata

### G. Company Snapshot Generation

- **Snapshot Generator** (`app/services/snapshot_generator.py`):
  - **GPT-Powered Analysis**: Uses GPT-4o-mini to analyze extraction data and create structured snapshots.
  - **Comprehensive Data**: Generates company overview, financial metrics, performance summary, chart data, and risk analysis.
  - **Fallback Mode**: If OpenAI is not configured, generates basic snapshot from extraction data.
  - **Auto-Generation**: Runs automatically after successful extraction in the project processing workflow.

- **Snapshot Structure**:
  - **Company Overview**: Name, CIN, registered office, industry sector, stock info
  - **Financial Metrics**: Revenue, profit, EBITDA, EPS with YoY comparison and change percentages
  - **Performance Summary**: Recent highlights, management guidance, business segments
  - **Charts Data**: Revenue trend, profit trend, key margins (ready for charting libraries)
  - **Risk Summary**: Top 3 risk factors from annual report
  - **Metadata**: Generation timestamp, data source, version

- **API Endpoint**:
  - **GET /api/projects/{project_id}/snapshot**: Retrieve complete snapshot JSON for UI rendering

## 5. Database Schema Updates

### Migration 003: Expanded Company Snapshots
- **Changed**: `company_snapshots` table structure
- **Removed**: Simple columns (summary, revenue_trend, profit_trend, risks)
- **Added**: `snapshot_data` JSONB column to store complete structured snapshot
- **Added**: `generated_at`, `version` columns for tracking
- **Purpose**: Store comprehensive company overview data generated by GPT for fast UI rendering

## 6. API Endpoints Summary

### Projects
- `POST /api/projects` - Create project and start background processing
- `GET /api/projects` - List all projects
- `GET /api/projects/{id}` - Get project details
- `GET /api/projects/{id}/snapshot` - Get company snapshot (overview, financials, charts)
- `GET /api/projects/{id}/status` - Get processing status
- `DELETE /api/projects/{id}` - Delete project

### Chats
- `POST /api/chats` - Create new chat session
- `GET /api/chats` - List all chats
- `GET /api/chats/{chat_id}` - Get chat with messages
- `POST /api/chats/{chat_id}/messages` - Send message (SSE streaming)
- `DELETE /api/chats/{chat_id}` - Delete chat

### H. Resumable Background Jobs

- **Job Tracking System** (`processing_jobs` table):
  - Tracks detailed job progress across 8 processing steps
  - Saves intermediate results after each step (PDF buffers, extractions, embeddings)
  - Enables resume from last successful step on failure or cancellation
  
- **Resumable Processor** (`app/jobs/resumable_processor.py`):
  - **Step-by-Step Processing**: Breaks job into 8 discrete, resumable steps
  - **State Preservation**: Saves progress and intermediate data to `resume_data` JSONB field
  - **Failure Recovery**: Can resume from exactly where it failed
  - **Cancellation Support**: Users can cancel and resume later
  
- **API Endpoints**:
  - **GET /api/projects/{id}/job**: Get detailed job status and progress
  - **POST /api/projects/{id}/cancel**: Cancel running job (resumable)
  - **POST /api/projects/{id}/resume**: Resume failed/cancelled job

- **Features**:
  - ✅ No data loss - all completed work preserved
  - ✅ Progress tracking (percentage, current step, documents/embeddings count)
  - ✅ Error details stored for debugging
  - ✅ Only one active job per project (prevents conflicts)
  - ✅ Automatic state saving after each step

## 7. Next Steps

1. **Frontend Integration**: 
   - Build the UI for chat interface with SSE handling
   - Add Cancel/Resume buttons for project jobs
   - Show job progress bar with current step
2. **Performance**: Add caching for frequently searched queries
3. **Analytics**: Track popular questions and search patterns
4. **Job Cleanup**: Implement periodic cleanup of old completed jobs
