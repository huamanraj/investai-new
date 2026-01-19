-- Migration: Add extraction_results table
-- Stores structured data extracted from documents

CREATE TABLE IF NOT EXISTS extraction_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    extracted_data JSONB NOT NULL,          -- The structured extraction result
    extraction_metadata JSONB,              -- Citations, reasoning, etc.
    company_name TEXT,
    fiscal_year TEXT,
    revenue NUMERIC,
    net_profit NUMERIC,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Index for faster lookups
CREATE INDEX IF NOT EXISTS extraction_results_document_id_idx ON extraction_results(document_id);
