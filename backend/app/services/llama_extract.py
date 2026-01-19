"""
LlamaExtract service for extracting structured data from financial PDFs
Uses MULTIMODAL mode for charts, graphs, and tables in annual reports
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from enum import Enum

from app.core.config import settings
from app.core.logging import job_logger, console_logger

# Logs directory for extraction debug output
LOGS_DIR = Path(__file__).parent.parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)


class FinancialReportSchema(BaseModel):
    """Schema for extracting data from annual reports"""
    
    company_name: str = Field(description="The official name of the company")
    fiscal_year: str = Field(description="The fiscal year of the report (e.g., 2024-25, FY2025)")
    report_type: str = Field(description="Type of report (Annual Report, Quarterly Report, etc.)")
    
    # Financial Highlights
    revenue: Optional[float] = Field(default=None, description="Total revenue/income for the period in millions/crores")
    revenue_unit: Optional[str] = Field(default=None, description="Unit of revenue (millions, crores, lakhs)")
    net_profit: Optional[float] = Field(default=None, description="Net profit for the period")
    operating_profit: Optional[float] = Field(default=None, description="Operating profit/EBITDA")
    eps: Optional[float] = Field(default=None, description="Earnings per share")
    
    # Growth Metrics
    revenue_growth: Optional[str] = Field(default=None, description="Year-over-year revenue growth percentage")
    profit_growth: Optional[str] = Field(default=None, description="Year-over-year profit growth percentage")
    
    # Business Highlights
    key_highlights: Optional[List[str]] = Field(default=None, description="Key business highlights or achievements")
    business_segments: Optional[List[str]] = Field(default=None, description="Major business segments or divisions")
    
    # Risk Factors
    risk_factors: Optional[List[str]] = Field(default=None, description="Major risk factors mentioned in the report")
    
    # Future Outlook
    outlook: Optional[str] = Field(default=None, description="Management's outlook or guidance for the future")
    
    # Additional Info
    auditor: Optional[str] = Field(default=None, description="Name of the auditor")
    registered_office: Optional[str] = Field(default=None, description="Registered office address")


class LlamaExtractService:
    """Service for extracting structured data from PDFs using LlamaExtract"""
    
    def __init__(self):
        self.configured = bool(settings.LLAMA_CLOUD_API_KEY and 
                               settings.LLAMA_CLOUD_API_KEY != "your_llama_cloud_api_key")
        self._extractor = None
        self._agent = None
    
    def _get_extractor(self):
        """Lazy initialization of LlamaExtract client"""
        if not self.configured:
            raise ValueError("LLAMA_CLOUD_API_KEY is not configured")
        
        if self._extractor is None:
            from llama_cloud_services import LlamaExtract
            self._extractor = LlamaExtract(api_key=settings.LLAMA_CLOUD_API_KEY)
        
        return self._extractor
    
    def _get_or_create_agent(self):
        """Get or create the financial report extraction agent"""
        if self._agent is not None:
            return self._agent
        
        extractor = self._get_extractor()
        
        # Try to get existing agent
        try:
            agents = extractor.list_agents()
            for agent in agents:
                if agent.name == "investai-financial-report":
                    self._agent = agent
                    console_logger.info("📋 Using existing LlamaExtract agent")
                    return self._agent
        except Exception as e:
            console_logger.warning(f"Could not list agents: {e}")
        
        # Create new agent with config
        try:
            from llama_cloud import ExtractConfig, ExtractMode
            
            config = ExtractConfig(
                extraction_mode=ExtractMode.MULTIMODAL,  # Best for charts, graphs, tables
                cite_sources=True,  # Enable citations for verification
                use_reasoning=True,  # Enable reasoning for accuracy
                system_prompt="""You are a financial analyst extracting data from Indian company annual reports.
                Focus on accurate numerical extraction. 
                For monetary values, note the unit (crores, lakhs, millions).
                Extract key performance metrics and business highlights.
                If information is not found, leave it as null."""
            )
            
            self._agent = extractor.create_agent(
                name="investai-financial-report",
                data_schema=FinancialReportSchema,
                config=config
            )
            console_logger.info("✅ Created new LlamaExtract agent")
            
        except Exception as e:
            console_logger.error(f"Failed to create agent: {e}")
            raise
        
        return self._agent
    
    async def extract_from_pdf(
        self,
        pdf_buffer: bytes,
        filename: str,
        project_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extract structured data from a PDF buffer.
        
        Args:
            pdf_buffer: PDF file as bytes
            filename: Name of the PDF file
            project_id: Project ID for logging
            
        Returns:
            Dictionary with extracted data and metadata
        """
        if not self.configured:
            error_msg = "LlamaExtract is not configured. Please set LLAMA_CLOUD_API_KEY."
            job_logger.error(error_msg, project_id=project_id)
            return {"success": False, "error": error_msg}
        
        console_logger.info(f"📊 Starting LlamaExtract for: {filename}")
        job_logger.info(
            f"Starting PDF extraction",
            project_id=project_id,
            data={"filename": filename, "size_bytes": len(pdf_buffer)}
        )
        
        try:
            agent = self._get_or_create_agent()
            
            # Use SourceText for bytes extraction
            from llama_cloud_services import SourceText
            
            console_logger.info("🔄 Running extraction (this may take a minute)...")
            
            # Run extraction
            result = agent.extract(SourceText(file=pdf_buffer, filename=filename))
            
            # Extract the data
            extracted_data = result.data if hasattr(result, 'data') else {}
            extraction_metadata = result.extraction_metadata if hasattr(result, 'extraction_metadata') else {}
            
            console_logger.info(f"✅ Extraction complete for: {filename}")
            
            # Prepare result
            extraction_result = {
                "success": True,
                "data": extracted_data,
                "metadata": extraction_metadata,
                "filename": filename,
                "extracted_at": datetime.utcnow().isoformat()
            }
            
            # Save to local logs for debugging
            self._save_extraction_log(
                project_id=project_id,
                filename=filename,
                result=extraction_result
            )
            
            job_logger.info(
                f"Extraction completed successfully",
                project_id=project_id,
                data={
                    "filename": filename,
                    "fields_extracted": len(extracted_data) if isinstance(extracted_data, dict) else 0
                }
            )
            
            return extraction_result
            
        except Exception as e:
            error_msg = str(e)
            console_logger.error(f"❌ Extraction failed: {error_msg}")
            job_logger.error(
                f"Extraction failed",
                project_id=project_id,
                data={"filename": filename, "error": error_msg}
            )
            
            return {
                "success": False,
                "error": error_msg,
                "filename": filename,
                "extracted_at": datetime.utcnow().isoformat()
            }
    
    async def extract_from_url(
        self,
        pdf_url: str,
        filename: str,
        project_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Download PDF from URL and extract data.
        
        Args:
            pdf_url: URL of the PDF (e.g., Cloudinary URL)
            filename: Name of the PDF file
            project_id: Project ID for logging
            
        Returns:
            Dictionary with extracted data and metadata
        """
        import requests
        
        console_logger.info(f"📥 Downloading PDF from URL for extraction...")
        
        try:
            response = requests.get(pdf_url, timeout=120)
            response.raise_for_status()
            pdf_buffer = response.content
            
            console_logger.info(f"✅ Downloaded {len(pdf_buffer) / 1024 / 1024:.2f} MB")
            
            return await self.extract_from_pdf(
                pdf_buffer=pdf_buffer,
                filename=filename,
                project_id=project_id
            )
            
        except requests.RequestException as e:
            error_msg = f"Failed to download PDF: {str(e)}"
            console_logger.error(f"❌ {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "filename": filename
            }
    
    def _save_extraction_log(
        self,
        project_id: Optional[str],
        filename: str,
        result: Dict[str, Any]
    ):
        """Save extraction result to local logs folder for debugging"""
        try:
            # Create extraction logs subfolder
            extraction_logs_dir = LOGS_DIR / "extractions"
            extraction_logs_dir.mkdir(exist_ok=True)
            
            # Generate filename with timestamp
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            safe_filename = "".join(c if c.isalnum() else "_" for c in filename)[:50]
            log_filename = f"{timestamp}_{safe_filename}.txt"
            
            log_path = extraction_logs_dir / log_filename
            
            # Format the log content
            log_content = f"""
================================================================================
LLAMA EXTRACT RESULT
================================================================================
Timestamp: {result.get('extracted_at', 'N/A')}
Project ID: {project_id or 'N/A'}
Filename: {filename}
Success: {result.get('success', False)}

================================================================================
EXTRACTED DATA
================================================================================
{json.dumps(result.get('data', {}), indent=2, default=str)}

================================================================================
EXTRACTION METADATA
================================================================================
{json.dumps(result.get('metadata', {}), indent=2, default=str)}

================================================================================
"""
            
            # Write to file
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(log_content)
            
            console_logger.info(f"📝 Extraction log saved: logs/extractions/{log_filename}")
            
        except Exception as e:
            console_logger.warning(f"Failed to save extraction log: {e}")
    
    def is_configured(self) -> bool:
        """Check if LlamaExtract is configured"""
        return self.configured


# Singleton instance
llama_extract_service = LlamaExtractService()
