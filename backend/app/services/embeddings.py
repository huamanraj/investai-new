"""
OpenAI Embeddings Service
Creates embeddings from extracted text for vector search
"""
import json
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import asyncio

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.logging import job_logger, console_logger


class EmbeddingsService:
    """Service for creating embeddings using OpenAI API"""
    
    def __init__(self):
        self.configured = bool(settings.OPENAI_API_KEY and 
                               settings.OPENAI_API_KEY != "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        self._client = None
        self.model = settings.OPENAI_EMBEDDING_MODEL  # text-embedding-3-large
        self.chunk_size = settings.CHUNK_SIZE  # 400 tokens
        self.chunk_overlap = settings.CHUNK_OVERLAP  # 80 tokens
    
    def _get_client(self) -> AsyncOpenAI:
        """Lazy initialization of OpenAI client"""
        if not self.configured:
            raise ValueError("OPENAI_API_KEY is not configured")
        
        if self._client is None:
            self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        
        return self._client
    
    async def create_embedding(self, text: str) -> Optional[List[float]]:
        """
        Create embedding for a single text string.
        
        Args:
            text: Text to embed
            
        Returns:
            List of floats representing the embedding vector (3072 dimensions)
        """
        if not text or not text.strip():
            return None
        
        try:
            client = self._get_client()
            
            response = await client.embeddings.create(
                model=self.model,
                input=text.strip()
            )
            
            return response.data[0].embedding
            
        except Exception as e:
            console_logger.error(f"❌ Embedding creation failed: {e}")
            raise
    
    async def create_embeddings_batch(
        self, 
        texts: List[str],
        project_id: Optional[str] = None
    ) -> List[Optional[List[float]]]:
        """
        Create embeddings for multiple texts in batch.
        OpenAI supports up to 2048 texts per batch.
        
        Args:
            texts: List of texts to embed
            project_id: Project ID for logging
            
        Returns:
            List of embedding vectors (same order as input)
        """
        if not texts:
            return []
        
        # Filter empty texts but keep track of positions
        valid_texts = []
        valid_indices = []
        for i, text in enumerate(texts):
            if text and text.strip():
                valid_texts.append(text.strip())
                valid_indices.append(i)
        
        if not valid_texts:
            return [None] * len(texts)
        
        console_logger.info(f"📊 Creating embeddings for {len(valid_texts)} chunks...")
        job_logger.info(
            f"Creating embeddings batch",
            project_id=project_id,
            data={"chunk_count": len(valid_texts)}
        )
        
        try:
            client = self._get_client()
            
            # OpenAI batch limit is 2048 texts
            batch_size = 2048
            all_embeddings = []
            
            for i in range(0, len(valid_texts), batch_size):
                batch = valid_texts[i:i + batch_size]
                
                response = await client.embeddings.create(
                    model=self.model,
                    input=batch
                )
                
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)
                
                console_logger.info(
                    f"✅ Processed batch {i//batch_size + 1}: "
                    f"{len(batch)} embeddings"
                )
            
            # Reconstruct full list with None for empty texts
            result = [None] * len(texts)
            for idx, embedding in zip(valid_indices, all_embeddings):
                result[idx] = embedding
            
            console_logger.info(f"✅ Created {len(all_embeddings)} embeddings")
            job_logger.info(
                f"Embeddings created successfully",
                project_id=project_id,
                data={"embeddings_created": len(all_embeddings)}
            )
            
            return result
            
        except Exception as e:
            console_logger.error(f"❌ Batch embedding failed: {e}")
            job_logger.error(
                f"Batch embedding failed",
                project_id=project_id,
                data={"error": str(e)}
            )
            raise
    
    def chunk_text(
        self, 
        text: str, 
        chunk_size: Optional[int] = None,
        overlap: Optional[int] = None
    ) -> List[str]:
        """
        Split text into overlapping chunks for embedding.
        Uses character-based chunking with word boundary awareness.
        
        Args:
            text: Text to chunk
            chunk_size: Approximate characters per chunk (default from settings)
            overlap: Overlap between chunks (default from settings)
            
        Returns:
            List of text chunks
        """
        if not text:
            return []
        
        # Convert token settings to approximate characters (1 token ≈ 4 chars)
        char_chunk_size = (chunk_size or self.chunk_size) * 4
        char_overlap = (overlap or self.chunk_overlap) * 4
        
        # Split into sentences for better chunking
        sentences = self._split_into_sentences(text)
        
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            # If adding this sentence exceeds chunk size, save current and start new
            if len(current_chunk) + len(sentence) > char_chunk_size and current_chunk:
                chunks.append(current_chunk.strip())
                
                # Start new chunk with overlap from end of previous
                overlap_text = current_chunk[-char_overlap:] if len(current_chunk) > char_overlap else current_chunk
                current_chunk = overlap_text + " " + sentence
            else:
                current_chunk += " " + sentence if current_chunk else sentence
        
        # Don't forget the last chunk
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        return chunks
    
    def _split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences"""
        import re
        
        # Simple sentence splitting
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]
    
    def chunk_extraction_data(
        self, 
        extraction_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Convert extraction data into chunks suitable for embedding.
        Each chunk includes metadata about its source field.
        
        Args:
            extraction_data: The extracted data from LlamaExtract
            
        Returns:
            List of chunk dictionaries with content and metadata
        """
        chunks = []
        
        # Company overview chunk
        overview_parts = []
        if extraction_data.get("company_name"):
            overview_parts.append(f"Company: {extraction_data['company_name']}")
        if extraction_data.get("fiscal_year"):
            overview_parts.append(f"Fiscal Year: {extraction_data['fiscal_year']}")
        if extraction_data.get("report_type"):
            overview_parts.append(f"Report Type: {extraction_data['report_type']}")
        
        if overview_parts:
            chunks.append({
                "content": " | ".join(overview_parts),
                "field": "company_overview",
                "chunk_index": 0
            })
        
        # Financial highlights chunk
        financial_parts = []
        if extraction_data.get("revenue"):
            unit = extraction_data.get("revenue_unit", "")
            financial_parts.append(f"Revenue: {extraction_data['revenue']} {unit}")
        if extraction_data.get("net_profit"):
            financial_parts.append(f"Net Profit: {extraction_data['net_profit']}")
        if extraction_data.get("operating_profit"):
            financial_parts.append(f"Operating Profit: {extraction_data['operating_profit']}")
        if extraction_data.get("eps"):
            financial_parts.append(f"EPS: {extraction_data['eps']}")
        if extraction_data.get("revenue_growth"):
            financial_parts.append(f"Revenue Growth: {extraction_data['revenue_growth']}")
        if extraction_data.get("profit_growth"):
            financial_parts.append(f"Profit Growth: {extraction_data['profit_growth']}")
        
        if financial_parts:
            chunks.append({
                "content": "Financial Highlights: " + " | ".join(financial_parts),
                "field": "financial_highlights",
                "chunk_index": 1
            })
        
        # Key highlights - each as separate chunk
        key_highlights = extraction_data.get("key_highlights", [])
        if key_highlights:
            for i, highlight in enumerate(key_highlights):
                if highlight:
                    chunks.append({
                        "content": f"Key Highlight: {highlight}",
                        "field": "key_highlights",
                        "chunk_index": len(chunks)
                    })
        
        # Business segments
        segments = extraction_data.get("business_segments", [])
        if segments:
            chunks.append({
                "content": "Business Segments: " + ", ".join(segments),
                "field": "business_segments",
                "chunk_index": len(chunks)
            })
        
        # Risk factors - each as separate chunk for better retrieval
        risk_factors = extraction_data.get("risk_factors", [])
        if risk_factors:
            for i, risk in enumerate(risk_factors):
                if risk:
                    # Split long risk factors into smaller chunks
                    risk_chunks = self.chunk_text(risk)
                    for rc in risk_chunks:
                        chunks.append({
                            "content": f"Risk Factor: {rc}",
                            "field": "risk_factors",
                            "chunk_index": len(chunks)
                        })
        
        # Outlook
        if extraction_data.get("outlook"):
            outlook_chunks = self.chunk_text(extraction_data["outlook"])
            for oc in outlook_chunks:
                chunks.append({
                    "content": f"Future Outlook: {oc}",
                    "field": "outlook",
                    "chunk_index": len(chunks)
                })
        
        # Auditor and registered office
        if extraction_data.get("auditor"):
            chunks.append({
                "content": f"Auditor: {extraction_data['auditor']}",
                "field": "auditor",
                "chunk_index": len(chunks)
            })
        
        if extraction_data.get("registered_office"):
            chunks.append({
                "content": f"Registered Office: {extraction_data['registered_office']}",
                "field": "registered_office",
                "chunk_index": len(chunks)
            })
        
        return chunks
    
    def is_configured(self) -> bool:
        """Check if OpenAI is configured"""
        return self.configured


# Singleton instance
embeddings_service = EmbeddingsService()
