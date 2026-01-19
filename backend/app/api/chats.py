"""
Chat API endpoints
Handles chat sessions, messages, and SSE streaming
"""
import uuid
import asyncio
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db, Chat, Message, Project
from app.services.rag import rag_service
from app.services.embeddings import embeddings_service
from app.core.logging import api_logger, console_logger


router = APIRouter(prefix="/chats", tags=["chats"])


# Pydantic models
class CreateChatRequest(BaseModel):
    title: Optional[str] = Field(None, description="Chat title (optional, auto-generated if not provided)")
    project_ids: List[str] = Field(..., description="Initial project IDs to chat with", min_items=1)


class SendMessageRequest(BaseModel):
    content: str = Field(..., description="Message content", min_length=1)
    project_ids: List[str] = Field(..., description="Selected project IDs", min_items=1)


class ChatResponse(BaseModel):
    id: str
    title: Optional[str]
    created_at: str
    message_count: int


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    project_ids: List[str]
    created_at: str


class ChatDetailResponse(BaseModel):
    id: str
    title: Optional[str]
    created_at: str
    messages: List[MessageResponse]


@router.post("", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
async def create_chat(
    request: CreateChatRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new chat session.
    
    - **title**: Optional chat title
    - **project_ids**: List of project UUIDs to start chatting with
    """
    # Validate project IDs exist
    project_uuids = [uuid.UUID(pid) for pid in request.project_ids]
    result = await db.execute(
        select(Project).where(Project.id.in_(project_uuids))
    )
    projects = result.scalars().all()
    
    if len(projects) != len(request.project_ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more project IDs not found"
        )
    
    # Generate title if not provided
    title = request.title
    if not title:
        company_names = [p.company_name for p in projects]
        if len(company_names) == 1:
            title = f"Chat with {company_names[0]}"
        else:
            title = f"Chat with {len(company_names)} companies"
    
    # Create chat
    chat = Chat(title=title)
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    
    console_logger.info(f"💬 Created new chat: {chat.id}")
    api_logger.info("Chat created", data={"chat_id": str(chat.id), "title": title})
    
    return ChatResponse(
        id=str(chat.id),
        title=chat.title,
        created_at=chat.created_at.isoformat(),
        message_count=0
    )


@router.get("", response_model=List[ChatResponse])
async def list_chats(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    """
    List all chat sessions, ordered by most recent first.
    
    - **limit**: Maximum number of chats to return (default: 50)
    - **offset**: Offset for pagination (default: 0)
    """
    # Get chats with message count
    result = await db.execute(
        select(Chat)
        .order_by(desc(Chat.created_at))
        .limit(limit)
        .offset(offset)
    )
    chats = result.scalars().all()
    
    # Get message counts
    chat_responses = []
    for chat in chats:
        msg_result = await db.execute(
            select(Message).where(Message.chat_id == chat.id)
        )
        message_count = len(msg_result.scalars().all())
        
        chat_responses.append(ChatResponse(
            id=str(chat.id),
            title=chat.title,
            created_at=chat.created_at.isoformat(),
            message_count=message_count
        ))
    
    return chat_responses


@router.get("/{chat_id}", response_model=ChatDetailResponse)
async def get_chat(
    chat_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get chat details with all messages.
    
    - **chat_id**: Chat UUID
    """
    # Get chat
    result = await db.execute(
        select(Chat).where(Chat.id == uuid.UUID(chat_id))
    )
    chat = result.scalar_one_or_none()
    
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found"
        )
    
    # Get messages
    result = await db.execute(
        select(Message)
        .where(Message.chat_id == chat.id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()
    
    message_responses = [
        MessageResponse(
            id=str(msg.id),
            role=msg.role,
            content=msg.content,
            project_ids=[str(pid) for pid in msg.project_ids],
            created_at=msg.created_at.isoformat()
        )
        for msg in messages
    ]
    
    return ChatDetailResponse(
        id=str(chat.id),
        title=chat.title,
        created_at=chat.created_at.isoformat(),
        messages=message_responses
    )


@router.post("/{chat_id}/messages")
async def send_message(
    chat_id: str,
    request: SendMessageRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Send a message and get streaming AI response via SSE.
    
    - **chat_id**: Chat UUID
    - **content**: Message content
    - **project_ids**: Selected project UUIDs for this message
    
    Returns: Server-Sent Events stream with AI response
    """
    # Verify chat exists
    result = await db.execute(
        select(Chat).where(Chat.id == uuid.UUID(chat_id))
    )
    chat = result.scalar_one_or_none()
    
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found"
        )
    
    # Validate project IDs
    project_uuids = [uuid.UUID(pid) for pid in request.project_ids]
    result = await db.execute(
        select(Project).where(Project.id.in_(project_uuids))
    )
    projects = result.scalars().all()
    
    if len(projects) != len(request.project_ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more project IDs not found"
        )
    
    project_names = [p.company_name for p in projects]
    
    # Check services are configured
    if not rag_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI API is not configured"
        )
    
    if not embeddings_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embeddings service is not configured"
        )
    
    console_logger.info(f"💬 Processing message in chat {chat_id}")
    
    # Save user message
    user_message = Message(
        chat_id=chat.id,
        role="user",
        content=request.content,
        project_ids=project_uuids
    )
    db.add(user_message)
    await db.commit()
    
    # Get chat history
    result = await db.execute(
        select(Message)
        .where(Message.chat_id == chat.id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()
    
    chat_history = [
        {"role": msg.role, "content": msg.content}
        for msg in messages[:-1]  # Exclude the just-added user message
    ]
    
    async def generate_sse():
        """Generate Server-Sent Events stream"""
        try:
            # Step 1: Create query embedding
            yield f"data: {{'type': 'status', 'message': 'Creating query embedding...'}}\n\n"
            
            query_embedding = await rag_service.create_query_embedding(request.content)
            
            # Step 2: Search similar chunks
            yield f"data: {{'type': 'status', 'message': 'Searching relevant documents...'}}\n\n"
            
            chunks = await rag_service.search_similar_chunks(
                session=db,
                query_embedding=query_embedding,
                project_ids=request.project_ids,
                top_k=10
            )
            
            # Step 3: Build context
            context = rag_service.build_context(chunks)
            
            yield f"data: {{'type': 'context', 'chunks_found': {len(chunks)}}}\n\n"
            
            # Step 4: Stream AI response
            yield f"data: {{'type': 'start'}}\n\n"
            
            full_response = ""
            async for chunk in rag_service.stream_chat_response(
                query=request.content,
                context=context,
                chat_history=chat_history,
                project_names=project_names
            ):
                full_response += chunk
                # Escape newlines and quotes for JSON
                escaped_chunk = chunk.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
                yield f"data: {{'type': 'chunk', 'content': \"{escaped_chunk}\"}}\n\n"
            
            # Step 5: Save AI response to database
            ai_message = Message(
                chat_id=chat.id,
                role="ai",
                content=full_response,
                project_ids=project_uuids
            )
            db.add(ai_message)
            await db.commit()
            
            yield f"data: {{'type': 'done', 'message_id': '{str(ai_message.id)}'}}\n\n"
            
            console_logger.info(f"✅ Message processed successfully in chat {chat_id}")
            
        except Exception as e:
            console_logger.error(f"❌ Error in SSE stream: {e}")
            error_msg = str(e).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            yield f"data: {{'type': 'error', 'message': \"{error_msg}\"}}\n\n"
    
    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a chat and all its messages.
    
    - **chat_id**: Chat UUID
    """
    result = await db.execute(
        select(Chat).where(Chat.id == uuid.UUID(chat_id))
    )
    chat = result.scalar_one_or_none()
    
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found"
        )
    
    await db.delete(chat)
    await db.commit()
    
    console_logger.info(f"🗑️ Deleted chat {chat_id}")
    api_logger.info("Chat deleted", data={"chat_id": chat_id})
    
    return None
