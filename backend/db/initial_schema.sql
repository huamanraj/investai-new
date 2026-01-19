-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

--------------------------------------------------
-- 1. PROJECTS (Each company = one project)
--------------------------------------------------
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    exchange TEXT DEFAULT 'BSE',
    status TEXT DEFAULT 'pending',  -- pending, scraping, downloading, processing, completed, failed
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

--------------------------------------------------
-- 2. DOCUMENTS (Annual reports, transcripts, etc.)
--------------------------------------------------
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    document_type TEXT NOT NULL,   -- annual_report, presentation, transcript
    fiscal_year TEXT,              -- FY2022, FY2023, etc.
    label TEXT,                    -- e.g., "2024-25 (Revised)"
    file_url TEXT NOT NULL,
    original_url TEXT,             -- Original BSE URL
    page_count INT,
    created_at TIMESTAMP DEFAULT NOW()
);

--------------------------------------------------
-- 3. DOCUMENT PAGES (1 row = 1 PDF page)
--------------------------------------------------
CREATE TABLE document_pages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INT NOT NULL,
    page_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

--------------------------------------------------
-- 4. TEXT CHUNKS (Chunks inside a page)
--------------------------------------------------
CREATE TABLE text_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    page_id UUID NOT NULL REFERENCES document_pages(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

--------------------------------------------------
-- 5. EMBEDDINGS (pgvector)
--------------------------------------------------
CREATE TABLE embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    chunk_id UUID NOT NULL REFERENCES text_chunks(id) ON DELETE CASCADE,
    embedding VECTOR(3072) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Vector index for FAST similarity search
CREATE INDEX embeddings_vector_idx
ON embeddings
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

--------------------------------------------------
-- 6. CHATS (One chat screen)
--------------------------------------------------
CREATE TABLE chats (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

--------------------------------------------------
-- 7. MESSAGES (Per-message project toggles)
--------------------------------------------------
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    chat_id UUID NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role TEXT NOT NULL,            -- user / ai
    content TEXT NOT NULL,
    project_ids UUID[] NOT NULL,   -- toggles ON at that time
    created_at TIMESTAMP DEFAULT NOW()
);

--------------------------------------------------
-- 8. COMPANY SNAPSHOT (One-pager summary)
--------------------------------------------------
CREATE TABLE company_snapshots (
    project_id UUID PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    summary TEXT,
    revenue_trend JSONB,
    profit_trend JSONB,
    risks TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);
