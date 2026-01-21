"""
GPT PDF Extractor Service
Uses OpenAI's GPT-4o-mini model to extract COMPLETE text and context from PDFs
Converts PDF pages to images and processes 3 images per API call sequentially (avoids rate limits)
"""
import asyncio
import base64
import io
import json
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

from openai import AsyncOpenAI
import fitz  # PyMuPDF
from PIL import Image

from app.core.config import settings
from app.core.logging import job_logger, console_logger

# Logs directory for extraction debug output
LOGS_DIR = Path(__file__).parent.parent.parent / "logs"
try:
    LOGS_DIR.mkdir(exist_ok=True)
except (OSError, PermissionError):
    LOGS_DIR = Path("/tmp/investai_logs")
    try:
        LOGS_DIR.mkdir(exist_ok=True)
    except Exception:
        LOGS_DIR = None


# Optimized prompt for fast, precise PDF extraction
COMPLETE_PDF_EXTRACTION_PROMPT = """Extract ALL content from this PDF chunk. Act as a precise parser.

Return ONLY valid JSON with this exact structure:
{
  "pages": {
    "PAGE_NUM_1": "extracted text...",
    "PAGE_NUM_2": "extracted text...",
    "PAGE_NUM_3": "extracted text..."
  }
}

For each page, extract:
- All text (headers, paragraphs, captions, footnotes, sidebars)
- Tables: All values with clear row/column structure
- Charts/Graphs: Type, title, axis labels, ALL data points with values (e.g., "Revenue: 2020: $500M, 2021: $650M, 2022: $800M")
- Lists and bullet points

Rules:
- Extract EVERYTHING visible - be comprehensive
- For graphs/charts: Brief description + all numerical values (e.g., "Bar chart - Q1: 25%, Q2: 30%, Q3: 35%, Q4: 28%")
- For tables: Preserve structure with clear headers and values
- No explanations or interpretations - only what's in the PDF
- Maintain reading order
- Use the exact page numbers provided in the keys
- Return ONLY valid JSON"""


class GPTPDFExtractor:
    """
    Service for extracting COMPLETE text and context from PDFs using OpenAI GPT-4o-mini.
    Processes large PDFs sequentially using 3-page image chunks for speed and accuracy (avoids rate limits).
    """
    
    def __init__(self):
        self.configured = bool(settings.OPENAI_API_KEY and 
                               settings.OPENAI_API_KEY != "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        self._client = None
        self.extraction_model = getattr(settings, 'OPENAI_EXTRACTION_MODEL', 'gpt-4o-mini')
        self.pages_per_chunk = 3  # Process 3 pages at a time for faster parallel processing
    
    def _get_client(self) -> AsyncOpenAI:
        """Lazy initialization of OpenAI client"""
        if not self.configured:
            raise ValueError("OPENAI_API_KEY is not configured")
        
        if self._client is None:
            self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        
        return self._client
    
    def _convert_pdf_to_images(self, pdf_buffer: bytes) -> Tuple[List[Image.Image], int]:
        """
        Convert PDF pages to images for faster processing using PyMuPDF.
        No external dependencies required!
        
        Args:
            pdf_buffer: Original PDF as bytes
            
        Returns:
            Tuple of (list of PIL Images, total_pages)
        """
        try:
            console_logger.info(f"🖼️ Converting PDF pages to images...")
            
            # Open PDF from bytes
            doc = fitz.open(stream=pdf_buffer, filetype="pdf")
            total_pages = len(doc)
            
            images = []
            # Convert each page to image
            for page_num in range(total_pages):
                page = doc[page_num]
                
                # Render page to pixmap (image)
                # zoom=1.5 gives ~150 DPI (balance between quality and speed)
                mat = fitz.Matrix(1.5, 1.5)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                
                # Convert pixmap to PIL Image
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                images.append(img)
            
            doc.close()
            
            console_logger.info(f"✅ Converted {total_pages} pages to images")
            
            return images, total_pages
            
        except Exception as e:
            console_logger.error(f"❌ Failed to convert PDF to images: {e}")
            raise
    
    def _image_to_base64(self, image: Image.Image) -> str:
        """
        Convert PIL Image to base64 string for API transmission.
        
        Args:
            image: PIL Image object
            
        Returns:
            Base64 encoded string with data URI prefix
        """
        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Compress to JPEG with good quality
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=85, optimize=True)
        buffer.seek(0)
        
        # Encode to base64
        img_base64 = base64.standard_b64encode(buffer.read()).decode('utf-8')
        return f"data:image/jpeg;base64,{img_base64}"
    
    def _parse_json_object_from_text(self, text: str) -> Dict[str, Any]:
        """Best-effort parse of a JSON object from model output_text."""
        raw = (text or "").strip()
        if not raw:
            return {}

        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {"pages": [raw]}
        except json.JSONDecodeError:
            # Try to salvage the first JSON object substring.
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                candidate = raw[start : end + 1]
                try:
                    obj = json.loads(candidate)
                    return obj if isinstance(obj, dict) else {"pages": [raw]}
                except json.JSONDecodeError:
                    pass

        return {"pages": [raw]}

    async def _extract_chunk(
        self,
        images: List[Image.Image],
        page_numbers: List[int],
        chunk_index: int,
        filename: str,
        project_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Extract text from 3 PDF pages (as images) in a single API call.
        
        Args:
            images: List of PIL Images (3 pages)
            page_numbers: List of page numbers for these images
            chunk_index: Index of this chunk (for logging)
            filename: Original filename
            project_id: Project ID for logging
            
        Returns:
            List of page dictionaries with page_number and text
        """
        client = self._get_client()
        
        num_pages = len(images)
        start_page = page_numbers[0]
        end_page = page_numbers[-1]
        page_numbers_str = ", ".join(str(p) for p in page_numbers)
        
        console_logger.info(f"📄 Extracting chunk {chunk_index + 1} (pages {start_page}-{end_page})...")
        
        try:
            # Build content array with text prompt + all images
            content = [
                {
                    "type": "input_text",
                    "text": (
                        f"Extract content from these {num_pages} PDF pages (pages {page_numbers_str}). "
                        f"Use these EXACT page numbers as keys in your JSON response. "
                        f"{COMPLETE_PDF_EXTRACTION_PROMPT}"
                    ),
                }
            ]
            
            # Add all images to the content
            for idx, image in enumerate(images):
                image_base64 = self._image_to_base64(image)
                content.append({
                    "type": "input_image",
                    "image_url": image_base64,
                })
            
            # Make API call with all 3 images
            response = await client.responses.create(
                model=self.extraction_model,
                input=[{
                    "role": "user",
                    "content": content,
                }],
            )

            # Parse response
            result_raw = (getattr(response, "output_text", None) or "").strip()

            # Save debug output in development mode
            if settings.ENV == "development" and LOGS_DIR:
                try:
                    debug_dir = LOGS_DIR / "gpt_debug"
                    debug_dir.mkdir(exist_ok=True)
                    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                    debug_file = debug_dir / f"chunk_{chunk_index + 1}_{timestamp}.txt"
                    with open(debug_file, "w", encoding="utf-8") as f:
                        f.write(f"=== CHUNK {chunk_index + 1} - Pages {page_numbers_str} ===\n\n")
                        f.write(result_raw)
                    console_logger.info(f"💾 Debug: Saved chunk {chunk_index + 1} response to {debug_file.name}")
                except Exception as e:
                    console_logger.warning(f"Failed to save debug output: {e}")
            
            result = self._parse_json_object_from_text(result_raw)
            page_data = result.get("pages", {})

            # Parse page data - handle both dict (new format) and list (old format)
            pages: List[Dict[str, Any]] = []
            
            if isinstance(page_data, dict):
                # New format: {"pages": {"1": "text", "2": "text", "3": "text"}}
                for page_key, text in page_data.items():
                    try:
                        # Parse page number from key (could be "1", "PAGE_1", etc.)
                        page_num_str = ''.join(filter(str.isdigit, str(page_key)))
                        page_num = int(page_num_str) if page_num_str else None
                        
                        if page_num is None:
                            console_logger.warning(f"⚠️ Could not parse page number from key: {page_key}")
                            continue
                        
                        page_text = text if isinstance(text, str) else str(text)
                        pages.append({"page_number": page_num, "text": page_text})
                    except (ValueError, TypeError) as e:
                        console_logger.warning(f"⚠️ Error parsing page {page_key}: {e}")
                        continue
            
            elif isinstance(page_data, list):
                # Old format fallback: {"pages": ["text1", "text2", "text3"]}
                for idx, text in enumerate(page_data):
                    page_text = text if isinstance(text, str) else str(text)
                    pages.append({"page_number": page_numbers[idx], "text": page_text})
            
            # Sort pages by page_number to ensure correct order
            pages.sort(key=lambda x: x["page_number"])

            # If GPT returned fewer pages than expected, log warning
            if len(pages) < num_pages:
                console_logger.warning(
                    f"⚠️ Chunk {chunk_index + 1}: Expected {num_pages} pages, "
                    f"got {len(pages)} from GPT. Some pages may be missing."
                )
            
            console_logger.info(f"✅ Extracted {len(pages)} pages from chunk {chunk_index + 1}")
            return pages
            
        except Exception as e:
            console_logger.error(f"❌ Failed to extract chunk {chunk_index + 1}: {e}")
            # Return empty to continue with other chunks
            return []
    
    async def extract_from_pdf_buffer(
        self,
        pdf_buffer: bytes,
        filename: str,
        project_id: Optional[str] = None,
        on_progress: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Extract COMPLETE text and context from a PDF buffer.
        Converts PDF pages to images and processes 3 images per API call SEQUENTIALLY to avoid rate limits.
        
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
            error_msg = "OpenAI API is not configured. Please set OPENAI_API_KEY."
            job_logger.error(error_msg, project_id=project_id)
            return {"success": False, "error": error_msg}
        
        console_logger.info(f"📊 Starting COMPLETE PDF text extraction for: {filename}")
        job_logger.info(
            f"Starting PDF extraction with GPT-4o-mini (sequential image processing)",
            project_id=project_id,
            data={"filename": filename, "size_mb": len(pdf_buffer) / 1024 / 1024}
        )
        
        try:
            # Step 1: Convert PDF pages to images
            if on_progress:
                on_progress({"message": "Converting PDF pages to images...", "step": "preparation"})
            
            images, total_pages = self._convert_pdf_to_images(pdf_buffer)
            
            # Step 2: Group images into chunks of 3
            images_per_chunk = self.pages_per_chunk
            total_chunks = (total_pages + images_per_chunk - 1) // images_per_chunk
            
            console_logger.info(f"📄 Processing {total_pages} pages in {total_chunks} chunks ({images_per_chunk} images per API call) SEQUENTIALLY...")
            
            # Step 3: Process chunks sequentially (one at a time to avoid rate limits)
            all_pages = []
            
            for chunk_idx in range(total_chunks):
                start_idx = chunk_idx * images_per_chunk
                end_idx = min(start_idx + images_per_chunk, total_pages)
                
                # Get images for this chunk
                chunk_images = images[start_idx:end_idx]
                # Page numbers are 1-indexed
                chunk_page_numbers = list(range(start_idx + 1, end_idx + 1))
                
                # Update progress
                if on_progress:
                    progress = int((chunk_idx / total_chunks) * 90) + 10  # 10-100%
                    on_progress({
                        "message": f"Extracting pages {chunk_page_numbers[0]}-{chunk_page_numbers[-1]} ({chunk_idx + 1}/{total_chunks})...",
                        "step": "extraction",
                        "progress": progress
                    })
                
                # Extract this chunk (3 images in one API call)
                try:
                    chunk_pages = await self._extract_chunk(
                        images=chunk_images,
                        page_numbers=chunk_page_numbers,
                        chunk_index=chunk_idx,
                        filename=filename,
                        project_id=project_id
                    )
                    
                    if isinstance(chunk_pages, list):
                        all_pages.extend(chunk_pages)
                        
                except Exception as e:
                    console_logger.error(f"❌ Chunk {chunk_idx + 1} failed: {e}")
                    continue
            
            # Sort pages by page number to ensure correct order
            all_pages.sort(key=lambda x: x.get("page_number", 0))
            
            console_logger.info(f"✅ Extracted text from {len(all_pages)} pages total (sequential processing)")
            
            # Step 3: Extract basic document info from first few pages
            doc_summary = {}
            if all_pages:
                # Try to extract company name and fiscal year from first page
                first_page_text = all_pages[0].get("text", "")
                # Simple extraction - snapshot generator will do detailed analysis
                doc_summary = {
                    "company_name": None,  # Will be filled by snapshot generator
                    "fiscal_year": None,
                    "report_type": "Annual Report"
                }
            
            if on_progress:
                on_progress({"message": "Extraction complete!", "step": "complete", "progress": 100})
            
            # Prepare final result
            extraction_result = {
                "success": True,
                "data": {
                    "company_name": doc_summary.get("company_name"),
                    "fiscal_year": doc_summary.get("fiscal_year"),
                    "report_type": doc_summary.get("report_type"),
                    # These will be filled by snapshot generator using embeddings
                    "revenue": None,
                    "revenue_unit": None,
                    "net_profit": None,
                    "operating_profit": None,
                    "eps": None,
                    "revenue_growth": None,
                    "profit_growth": None,
                    "key_highlights": [],
                    "business_segments": [],
                    "risk_factors": [],
                    "outlook": None,
                    "auditor": None,
                    "registered_office": None,
                    "charts_data": []
                },
                "pages": all_pages,  # COMPLETE text from each page for embeddings
                "total_pages": total_pages,
                "metadata": {
                    "model": self.extraction_model,
                    "extraction_method": "sequential_image_based",
                    "chunks_processed": total_chunks,
                    "images_per_chunk": self.pages_per_chunk,
                    "extracted_at": datetime.utcnow().isoformat(),
                    "processing_mode": "sequential_images"
                },
                "filename": filename,
                "extracted_at": datetime.utcnow().isoformat()
            }
            
            # Save extraction log
            self._save_extraction_log(project_id, filename, extraction_result)
            
            console_logger.info(f"✅ GPT extraction complete for: {filename} (sequential image processing)")
            job_logger.info(
                f"Extraction completed successfully with sequential image processing",
                project_id=project_id,
                data={
                    "filename": filename,
                    "pages_extracted": len(all_pages),
                    "chunks_processed": total_chunks,
                    "processing_mode": "sequential_images"
                }
            )
            
            return extraction_result
            
        except Exception as e:
            error_msg = str(e)
            console_logger.error(f"❌ GPT extraction failed: {error_msg}")
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
        
        console_logger.info(f"📥 Downloading PDF from URL for GPT extraction...")
        
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
    
    def _save_extraction_log(
        self,
        project_id: Optional[str],
        filename: str,
        result: Dict[str, Any]
    ):
        """Save extraction result to local logs folder for debugging"""
        if LOGS_DIR is None:
            return
        
        try:
            extraction_logs_dir = LOGS_DIR / "gpt_extractions"
            extraction_logs_dir.mkdir(exist_ok=True)
            
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            safe_filename = "".join(c if c.isalnum() else "_" for c in filename)[:50]
            log_filename = f"{timestamp}_{safe_filename}.json"
            
            log_path = extraction_logs_dir / log_filename
            
            # Save summary (not full page text to save space)
            log_data = {
                "timestamp": result.get('extracted_at', 'N/A'),
                "project_id": project_id,
                "filename": filename,
                "success": result.get('success', False),
                "data": result.get('data', {}),
                "total_pages": result.get('total_pages', 0),
                "pages_extracted": len(result.get('pages', [])),
                "metadata": result.get('metadata', {})
            }
            
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(log_data, f, indent=2, default=str, ensure_ascii=False)
            
            console_logger.info(f"📝 Extraction log saved: logs/gpt_extractions/{log_filename}")
            
        except Exception as e:
            console_logger.warning(f"Failed to save extraction log: {e}")
    
    def is_configured(self) -> bool:
        """Check if GPT PDF extractor is configured"""
        return self.configured


# Singleton instance
gpt_pdf_extractor = GPTPDFExtractor()
