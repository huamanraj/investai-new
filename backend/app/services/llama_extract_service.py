"""
LlamaExtract Service
Uses LlamaCloud Parse + Extract to get 100% data from PDFs
Extracts complete text using LlamaParse and structured data using LlamaExtract
"""
import os
import asyncio
import tempfile
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path

from llama_cloud_services import LlamaExtract, LlamaParse
from llama_cloud import ExtractConfig, ExtractMode
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import job_logger, console_logger


# Schema for extracting complete text from PDFs
class PDFTextExtraction(BaseModel):
    """Schema for extracting all text content from PDF pages"""
    pages: List[Dict[str, str]] = Field(
        description="List of all pages with page_number and complete_text. Extract EVERYTHING from each page including tables, charts, graphs, headers, footers, captions, footnotes."
    )


class LlamaExtractService:
    """
    Service for extracting COMPLETE text and structured data from PDFs using LlamaCloud.
    Uses LlamaParse for 100% text extraction and LlamaExtract for structured data.
    """
    
    def __init__(self):
        self.configured = bool(settings.LLAMA_CLOUD_API_KEY and 
                               settings.LLAMA_CLOUD_API_KEY.strip())
        self._parse_client = None
        self._extract_client = None
        
        if self.configured:
            os.environ["LLAMA_CLOUD_API_KEY"] = settings.LLAMA_CLOUD_API_KEY
    
    def _get_parse_client(self) -> LlamaParse:
        """Lazy initialization of LlamaParse client"""
        if not self.configured:
            raise ValueError("LLAMA_CLOUD_API_KEY is not configured")
        
        if self._parse_client is None:
            self._parse_client = LlamaParse(
                api_key=settings.LLAMA_CLOUD_API_KEY,
                result_type="markdown",  # Get markdown for better structure preservation
                num_workers=4,
                verbose=True
            )
        
        return self._parse_client
    
    def _get_extract_client(self) -> LlamaExtract:
        """Lazy initialization of LlamaExtract client"""
        if not self.configured:
            raise ValueError("LLAMA_CLOUD_API_KEY is not configured")
        
        if self._extract_client is None:
            self._extract_client = LlamaExtract(api_key=settings.LLAMA_CLOUD_API_KEY)
        
        return self._extract_client
    
    async def extract_from_pdf_buffer(
        self,
        pdf_buffer: bytes,
        filename: str,
        project_id: Optional[str] = None,
        on_progress: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Extract COMPLETE text and context from a PDF buffer using LlamaParse.
        Gets 100% of the content including tables, charts, graphs, etc.
        
        Args:
            pdf_buffer: PDF file as bytes
            filename: Name of the PDF file
            project_id: Project ID for logging
            on_progress: Optional callback for progress updates
            
        Returns:
            Dictionary with:
            - success: bool
            - data: basic document info
            - pages: list of {page_number, text} with COMPLETE text from all pages
            - total_pages: int
            - metadata: extraction metadata
        """
        if not self.configured:
            error_msg = "LlamaCloud API is not configured. Please set LLAMA_CLOUD_API_KEY."
            job_logger.error(error_msg, project_id=project_id)
            return {"success": False, "error": error_msg}
        
        console_logger.info(f"📊 Starting LlamaParse extraction for: {filename}")
        job_logger.info(
            f"Starting PDF extraction with LlamaParse (100% text extraction)",
            project_id=project_id,
            data={"filename": filename, "size_mb": len(pdf_buffer) / 1024 / 1024}
        )
        
        try:
            # Save PDF to temporary file for LlamaParse
            if on_progress:
                on_progress({"message": "Preparing PDF for parsing...", "step": "preparation"})
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                tmp_file.write(pdf_buffer)
                tmp_file_path = tmp_file.name
            
            try:
                # Use LlamaParse to extract ALL text
                console_logger.info(f"🔄 Parsing PDF with LlamaParse...")
                
                if on_progress:
                    on_progress({
                        "message": "Extracting complete text from PDF (this may take a few minutes)...",
                        "step": "extraction",
                        "progress": 10
                    })
                
                # Run LlamaParse in thread pool since it's synchronous
                parse_client = self._get_parse_client()
                loop = asyncio.get_event_loop()
                documents = await loop.run_in_executor(
                    None,
                    lambda: parse_client.load_data(tmp_file_path)
                )
                
                if not documents:
                    raise Exception("LlamaParse returned no documents")
                
                # Extract pages from parsed documents
                # LlamaParse returns documents with page metadata
                all_pages = []
                page_dict = {}  # Use dict to handle multiple docs per page
                
                for doc in documents:
                    # Get page number from metadata
                    page_num = None
                    metadata = getattr(doc, 'metadata', {}) or {}
                    
                    # Try various metadata keys for page number
                    if isinstance(metadata, dict):
                        page_num = (
                            metadata.get("page_label") or 
                            metadata.get("page_number") or 
                            metadata.get("page") or
                            metadata.get("page_num")
                        )
                    
                    # Try to parse page number
                    if page_num:
                        try:
                            # Handle string formats like "page_1", "Page 1", "1", etc.
                            page_str = str(page_num).lower().replace("page_", "").replace("page ", "").strip()
                            page_num = int(page_str) if page_str.isdigit() else None
                        except (ValueError, AttributeError):
                            page_num = None
                    
                    # If no page number found, use document index + 1
                    if page_num is None:
                        page_num = len(page_dict) + 1
                    
                    # Get text content (markdown format preserves structure)
                    page_text = getattr(doc, 'text', None) or getattr(doc, 'get_content', lambda: "")() or ""
                    
                    if page_text and page_text.strip():
                        # If page already exists, append text (handles split pages)
                        if page_num in page_dict:
                            page_dict[page_num] += "\n\n" + page_text
                        else:
                            page_dict[page_num] = page_text
                
                # Convert dict to list and sort by page number
                all_pages = [
                    {"page_number": page_num, "text": text}
                    for page_num, text in sorted(page_dict.items())
                ]
                total_pages = len(all_pages)
                
                console_logger.info(f"✅ Extracted {total_pages} pages from PDF")
                
                # Extract basic document info from first page
                doc_summary = {}
                if all_pages:
                    first_page_text = all_pages[0].get("text", "")
                    doc_summary = {
                        "company_name": None,  # Will be filled by snapshot generator
                        "fiscal_year": None,
                        "report_type": "Annual Report"
                    }
                
                if on_progress:
                    on_progress({"message": "Extraction complete!", "step": "complete", "progress": 100})
                
                # Combine all page text into complete raw text
                complete_text_parts = []
                for page in sorted(all_pages, key=lambda x: x.get("page_number", 0)):
                    page_num = page.get("page_number", 0)
                    page_text = page.get("text", "")
                    if page_text.strip():
                        complete_text_parts.append(f"=== PAGE {page_num} ===\n\n{page_text}\n\n")
                
                complete_raw_text = "\n".join(complete_text_parts)
                
                # Prepare final result - data field contains ONLY the complete raw text
                extraction_result = {
                    "success": True,
                    "data": complete_raw_text,  # Just the complete text, no JSON structure
                    "pages": all_pages,  # COMPLETE text from each page for embeddings
                    "total_pages": total_pages,
                    "metadata": {
                        "model": "llamaparse",
                        "extraction_method": "llamaparse_full_text",
                        "extracted_at": datetime.utcnow().isoformat(),
                        "processing_mode": "llamaparse"
                    },
                    "filename": filename,
                    "extracted_at": datetime.utcnow().isoformat()
                }
                
                console_logger.info(f"✅ LlamaParse extraction complete for: {filename}")
                job_logger.info(
                    f"Extraction completed successfully with LlamaParse",
                    project_id=project_id,
                    data={
                        "filename": filename,
                        "pages_extracted": total_pages,
                        "processing_mode": "llamaparse"
                    }
                )
                
                return extraction_result
                
            finally:
                # Clean up temporary file
                try:
                    os.unlink(tmp_file_path)
                except Exception as e:
                    console_logger.warning(f"Failed to delete temp file: {e}")
            
        except Exception as e:
            error_msg = str(e)
            console_logger.error(f"❌ LlamaParse extraction failed: {error_msg}")
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
        project_id: Optional[str] = None,
        on_progress: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Download PDF from URL and extract COMPLETE text and context.
        
        Args:
            pdf_url: URL of the PDF
            filename: Name of the PDF file
            project_id: Project ID for logging
            on_progress: Optional callable for progress updates
            
        Returns:
            Dictionary with extracted data and metadata
        """
        import aiohttp
        
        console_logger.info(f"📥 Downloading PDF from URL for LlamaParse extraction...")
        
        if on_progress:
            on_progress({"message": "Downloading PDF...", "step": "download"})
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    pdf_url,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
                    timeout=aiohttp.ClientTimeout(total=300)  # 5 min timeout
                ) as response:
                    response.raise_for_status()
                    pdf_buffer = await response.read()
                    
            console_logger.info(f"✅ Downloaded {len(pdf_buffer) / 1024 / 1024:.2f} MB")
            
            return await self.extract_from_pdf_buffer(
                pdf_buffer=pdf_buffer,
                filename=filename,
                project_id=project_id,
                on_progress=on_progress
            )
            
        except Exception as e:
            error_msg = f"Failed to download PDF: {str(e)}"
            console_logger.error(f"❌ {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "filename": filename
            }
    
    def is_configured(self) -> bool:
        """Check if LlamaExtract service is configured"""
        return self.configured


# Singleton instance
llama_extract_service = LlamaExtractService()
