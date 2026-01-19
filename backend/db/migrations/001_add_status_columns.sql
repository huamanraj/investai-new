-- Migration: Add status tracking columns
-- Run this to update your existing database schema

-- Add status and error_message to projects table
ALTER TABLE projects 
ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending';

ALTER TABLE projects 
ADD COLUMN IF NOT EXISTS error_message TEXT;

-- Add label, original_url, page_count to documents table  
ALTER TABLE documents 
ADD COLUMN IF NOT EXISTS label TEXT;

ALTER TABLE documents 
ADD COLUMN IF NOT EXISTS original_url TEXT;

ALTER TABLE documents 
ADD COLUMN IF NOT EXISTS page_count INT;

-- Verify changes
SELECT column_name, data_type, column_default 
FROM information_schema.columns 
WHERE table_name IN ('projects', 'documents')
ORDER BY table_name, ordinal_position;
