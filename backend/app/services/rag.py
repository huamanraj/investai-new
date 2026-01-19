"""
RAG Service - Vector search and streaming chat responses
Handles retrieval from embeddings and GPT-4o-mini streaming
"""
import uuid
from typing import List, Dict, Any, Optional, AsyncGenerator
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from openai import AsyncOpenAI

from app.db import TextChunk, Embedding, DocumentPage, Document, Project
from app.core.config import settings
from app.core.logging import console_logger


class RAGService:
    """Service for RAG (Retrieval Augmented Generation) chat"""
    
    def __init__(self):
        self.configured = bool(settings.OPENAI_API_KEY and 
                               settings.OPENAI_API_KEY != "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        self._client = None
        self.chat_model = "gpt-4o-mini"
        self.embedding_model = settings.OPENAI_EMBEDDING_MODEL
        self.top_k = 10  # Number of chunks to retrieve
    
    def _get_client(self) -> AsyncOpenAI:
        """Lazy initialization of OpenAI client"""
        if not self.configured:
            raise ValueError("OPENAI_API_KEY is not configured")
        
        if self._client is None:
            self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        
        return self._client
    
    async def create_query_embedding(self, query: str) -> List[float]:
        """
        Create embedding for user query.
        
        Args:
            query: User's question
            
        Returns:
            Embedding vector
        """
        client = self._get_client()
        
        response = await client.embeddings.create(
            model=self.embedding_model,
            input=query.strip()
        )
        
        return response.data[0].embedding
    
    async def search_similar_chunks(
        self,
        session: AsyncSession,
        query_embedding: List[float],
        project_ids: List[str],
        top_k: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for similar chunks using pgvector cosine similarity.
        
        Args:
            session: Database session
            query_embedding: Query vector
            project_ids: List of project UUIDs to search in
            top_k: Number of results to return
            
        Returns:
            List of chunks with metadata and similarity scores
        """
        if not project_ids:
            return []
        
        k = top_k or self.top_k
        
        # Convert project_ids to UUIDs
        project_uuids = [uuid.UUID(pid) for pid in project_ids]
        
        # Build the query with pgvector cosine similarity
        # Join: Embedding -> TextChunk -> DocumentPage -> Document -> Project
        query = (
            select(
                TextChunk.content,
                TextChunk.field,
                TextChunk.chunk_index,
                DocumentPage.page_number,
                Document.label,
                Document.fiscal_year,
                Project.company_name,
                Project.id.label("project_id"),
                Embedding.embedding.cosine_distance(query_embedding).label("distance")
            )
            .join(TextChunk, Embedding.chunk_id == TextChunk.id)
            .join(DocumentPage, TextChunk.page_id == DocumentPage.id)
            .join(Document, DocumentPage.document_id == Document.id)
            .join(Project, Document.project_id == Project.id)
            .where(Project.id.in_(project_uuids))
            .order_by("distance")
            .limit(k)
        )
        
        result = await session.execute(query)
        rows = result.all()
        
        chunks = []
        for row in rows:
            chunks.append({
                "content": row.content,
                "field": row.field,
                "chunk_index": row.chunk_index,
                "page_number": row.page_number,
                "document_label": row.label,
                "fiscal_year": row.fiscal_year,
                "company_name": row.company_name,
                "project_id": str(row.project_id),
                "similarity": 1 - row.distance  # Convert distance to similarity
            })
        
        console_logger.info(f"🔍 Retrieved {len(chunks)} similar chunks from {len(project_ids)} project(s)")
        
        return chunks
    
    def build_context(self, chunks: List[Dict[str, Any]]) -> str:
        """
        Build context string from retrieved chunks.
        
        Args:
            chunks: List of chunk dictionaries
            
        Returns:
            Formatted context string
        """
        if not chunks:
            return "No relevant information found."
        
        context_parts = []
        
        # Group chunks by company
        from collections import defaultdict
        chunks_by_company = defaultdict(list)
        
        for chunk in chunks:
            company = chunk["company_name"]
            chunks_by_company[company].append(chunk)
        
        # Format context
        for company, company_chunks in chunks_by_company.items():
            context_parts.append(f"\n## {company}")
            
            for chunk in company_chunks:
                fiscal_year = chunk.get("fiscal_year", "N/A")
                doc_label = chunk.get("document_label", "N/A")
                field = chunk.get("field", "general")
                
                context_parts.append(
                    f"\n[{fiscal_year} - {doc_label} - {field}]\n{chunk['content']}\n"
                )
        
        return "\n".join(context_parts)
    
    async def stream_chat_response(
        self,
        query: str,
        context: str,
        chat_history: List[Dict[str, str]],
        project_names: List[str]
    ) -> AsyncGenerator[str, None]:
        """
        Stream chat response using GPT-4o-mini.
        
        Args:
            query: User's question
            context: Retrieved context from vector search
            chat_history: Previous messages (list of {role, content})
            project_names: Names of selected projects for system prompt
            
        Yields:
            Chunks of the response text
        """
        client = self._get_client()
        
        # Build system prompt
        if project_names:
            projects_str = ", ".join(project_names)
            system_prompt = f"""You are an AI financial analyst assistant. You help users analyze annual reports and financial data from BSE India companies.

Currently analyzing: {projects_str}

Use the provided context from the company's annual reports to answer questions accurately. If the context doesn't contain enough information, acknowledge this limitation.

Format your responses clearly:
- Use bullet points for lists
- Highlight key numbers and metrics
- Compare data across years when relevant
- Cite the fiscal year and document when referencing specific data

Context:
{context}
"""
        else:
            system_prompt = """You are an AI financial analyst assistant. You help users analyze annual reports and financial data from BSE India companies.

Please ask the user to select at least one company/project to start the conversation."""
        
        # Build messages array
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add chat history (last 10 messages for context)
        messages.extend(chat_history[-10:])
        
        # Add current query
        messages.append({"role": "user", "content": query})
        
        console_logger.info(f"🤖 Streaming response from {self.chat_model}...")
        
        # Stream response
        stream = await client.chat.completions.create(
            model=self.chat_model,
            messages=messages,
            stream=True,
            temperature=0.7,
            max_tokens=2000
        )
        
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    
    def is_configured(self) -> bool:
        """Check if OpenAI is configured"""
        return self.configured


# Singleton instance
rag_service = RAGService()
