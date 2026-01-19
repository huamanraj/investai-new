-- Migration: Expand company_snapshots table for detailed snapshot data
-- Stores comprehensive company overview, financials, charts, and analysis

-- Drop existing simple columns and add comprehensive JSONB structure
ALTER TABLE company_snapshots DROP COLUMN IF EXISTS summary;
ALTER TABLE company_snapshots DROP COLUMN IF EXISTS revenue_trend;
ALTER TABLE company_snapshots DROP COLUMN IF EXISTS profit_trend;
ALTER TABLE company_snapshots DROP COLUMN IF EXISTS risks;

-- Add comprehensive snapshot data as JSONB
ALTER TABLE company_snapshots ADD COLUMN IF NOT EXISTS snapshot_data JSONB NOT NULL DEFAULT '{}';

-- Add generation metadata
ALTER TABLE company_snapshots ADD COLUMN IF NOT EXISTS generated_at TIMESTAMP DEFAULT NOW();
ALTER TABLE company_snapshots ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1;

-- Add index for faster queries
CREATE INDEX IF NOT EXISTS company_snapshots_project_id_idx ON company_snapshots(project_id);

-- Comment on the table
COMMENT ON COLUMN company_snapshots.snapshot_data IS 'Complete snapshot JSON including company_overview, financial_metrics, performance_summary, charts_data, and metadata';
