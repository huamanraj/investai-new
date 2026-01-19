-- Migration: Add field column to text_chunks table
-- Purpose: Store the source field name for each chunk (e.g., "financial_highlights", "risk_factors")
-- Date: 2026-01-19

-- Add field column to text_chunks
ALTER TABLE text_chunks
ADD COLUMN field VARCHAR(100);

-- Add comment for documentation
COMMENT ON COLUMN text_chunks.field IS 'Source field from extraction (e.g., financial_highlights, risk_factors)';
