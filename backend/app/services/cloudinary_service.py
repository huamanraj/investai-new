"""
Cloudinary service for PDF storage
Handles large PDF uploads (200+ pages) with chunked upload support
"""
import cloudinary
import cloudinary.uploader
from typing import Optional, Tuple
import io
import hashlib
from urllib.parse import quote

from app.core.config import settings
from app.core.logging import cloudinary_logger, console_logger


# Configure Cloudinary
cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET
)


# Max file size for direct upload (10MB) - larger files use chunked upload
DIRECT_UPLOAD_LIMIT = 10 * 1024 * 1024  # 10MB

# Chunk size for large uploads
CHUNK_SIZE = 6 * 1024 * 1024  # 6MB chunks


class CloudinaryService:
    """Service for uploading PDFs to Cloudinary"""
    
    def __init__(self):
        self.configured = all([
            settings.CLOUDINARY_CLOUD_NAME,
            settings.CLOUDINARY_API_KEY,
            settings.CLOUDINARY_API_SECRET,
            settings.CLOUDINARY_CLOUD_NAME != "your_cloud_name"
        ])
    
    async def upload_pdf(
        self, 
        pdf_buffer: bytes, 
        company_name: str,
        fiscal_year: str,
        project_id: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Upload PDF to Cloudinary.
        Handles large files (200+ pages) with chunked upload.
        
        Args:
            pdf_buffer: PDF file as bytes
            company_name: Company name for folder organization
            fiscal_year: Fiscal year label
            project_id: Project ID for logging
            
        Returns:
            Tuple of (success, file_url, error_message)
        """
        if not self.configured:
            error_msg = "Cloudinary is not configured. Please set CLOUDINARY_* environment variables."
            cloudinary_logger.error(error_msg, project_id=project_id)
            return False, None, error_msg
        
        file_size_mb = len(pdf_buffer) / 1024 / 1024
        
        cloudinary_logger.info(
            f"Starting PDF upload to Cloudinary",
            project_id=project_id,
            data={
                "company": company_name,
                "fiscal_year": fiscal_year,
                "size_mb": round(file_size_mb, 2)
            }
        )
        console_logger.info(f"☁️ Uploading PDF to Cloudinary ({file_size_mb:.2f} MB)...")
        
        try:
            # Generate a unique public_id
            company_slug = company_name.lower().replace(" ", "_").replace(".", "")[:50]
            year_slug = fiscal_year.replace("-", "_").replace(" ", "_")[:20] if fiscal_year else "unknown"
            
            # Create hash for uniqueness
            file_hash = hashlib.md5(pdf_buffer[:1024]).hexdigest()[:8]
            
            public_id = f"investai/{company_slug}/{year_slug}_{file_hash}"
            
            # Prepare upload options
            upload_options = {
                "resource_type": "raw",  # For PDF files
                "public_id": public_id,
                "folder": "annual_reports",
                "use_filename": True,
                "unique_filename": True,
                "overwrite": True,
                "invalidate": True,
                "format": "pdf"
            }
            
            # For large files, use chunked upload
            if len(pdf_buffer) > DIRECT_UPLOAD_LIMIT:
                console_logger.info(f"📦 Using chunked upload for large file ({file_size_mb:.2f} MB)")
                cloudinary_logger.info(
                    "Using chunked upload for large file",
                    project_id=project_id,
                    data={"size_mb": round(file_size_mb, 2)}
                )
                upload_options["chunk_size"] = CHUNK_SIZE
            
            # Upload to Cloudinary
            result = cloudinary.uploader.upload(
                io.BytesIO(pdf_buffer),
                **upload_options
            )
            
            file_url = result.get("secure_url")
            
            if not file_url:
                # Try alternative URL construction
                file_url = result.get("url", "").replace("http://", "https://")
            
            cloudinary_logger.info(
                f"PDF uploaded successfully",
                project_id=project_id,
                data={
                    "url": file_url,
                    "public_id": result.get("public_id"),
                    "bytes": result.get("bytes"),
                    "format": result.get("format")
                }
            )
            console_logger.info(f"✅ PDF uploaded to Cloudinary: {file_url}")
            
            return True, file_url, None
        
        except cloudinary.exceptions.Error as e:
            error_msg = f"Cloudinary upload error: {str(e)}"
            cloudinary_logger.error(error_msg, project_id=project_id, data={"error": str(e)})
            console_logger.error(f"❌ Cloudinary error: {e}")
            return False, None, error_msg
        
        except Exception as e:
            error_msg = f"Upload failed: {str(e)}"
            cloudinary_logger.error(error_msg, project_id=project_id, data={"error": str(e)})
            console_logger.error(f"❌ Upload error: {e}")
            return False, None, error_msg
    
    def is_configured(self) -> bool:
        """Check if Cloudinary is properly configured"""
        return self.configured


# Singleton instance
cloudinary_service = CloudinaryService()
