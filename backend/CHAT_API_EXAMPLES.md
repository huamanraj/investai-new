# Chat API Usage Examples

## Overview

The chat API supports multi-company conversations with SSE (Server-Sent Events) streaming for real-time responses.

## API Flow

```
1. Create Chat → 2. Send Messages (with project selection) → 3. Receive Streaming Response
```

## Endpoints

### 1. Create New Chat

```http
POST /api/chats
Content-Type: application/json

{
  "title": "Analysis of Tech Companies",
  "project_ids": ["project-uuid-1", "project-uuid-2"]
}
```

**Response:**
```json
{
  "id": "chat-uuid",
  "title": "Analysis of Tech Companies",
  "created_at": "2026-01-19T10:30:00",
  "message_count": 0
}
```

### 2. List All Chats

```http
GET /api/chats?limit=50&offset=0
```

**Response:**
```json
[
  {
    "id": "chat-uuid-1",
    "title": "Chat with TCS",
    "created_at": "2026-01-19T10:30:00",
    "message_count": 12
  },
  {
    "id": "chat-uuid-2",
    "title": "Chat with Infosys",
    "created_at": "2026-01-18T15:20:00",
    "message_count": 5
  }
]
```

### 3. Get Chat Details

```http
GET /api/chats/{chat_id}
```

**Response:**
```json
{
  "id": "chat-uuid",
  "title": "Chat with TCS",
  "created_at": "2026-01-19T10:30:00",
  "messages": [
    {
      "id": "msg-uuid-1",
      "role": "user",
      "content": "What was the revenue in FY2023?",
      "project_ids": ["project-uuid-1"],
      "created_at": "2026-01-19T10:31:00"
    },
    {
      "id": "msg-uuid-2",
      "role": "ai",
      "content": "Based on the FY2023 annual report...",
      "project_ids": ["project-uuid-1"],
      "created_at": "2026-01-19T10:31:05"
    }
  ]
}
```

### 4. Send Message (SSE Streaming)

```http
POST /api/chats/{chat_id}/messages
Content-Type: application/json

{
  "content": "Compare the revenue growth of both companies",
  "project_ids": ["project-uuid-1", "project-uuid-2"]
}
```

**SSE Response Stream:**

```
data: {"type": "status", "message": "Creating query embedding..."}

data: {"type": "status", "message": "Searching relevant documents..."}

data: {"type": "context", "chunks_found": 8}

data: {"type": "start"}

data: {"type": "chunk", "content": "Based on "}

data: {"type": "chunk", "content": "the annual "}

data: {"type": "chunk", "content": "reports...\n\n"}

data: {"type": "done", "message_id": "msg-uuid"}
```

### 5. Delete Chat

```http
DELETE /api/chats/{chat_id}
```

**Response:** 204 No Content

## Frontend Integration (JavaScript/TypeScript)

### Using EventSource for SSE

```typescript
// Create chat
async function createChat(projectIds: string[]) {
  const response = await fetch('/api/chats', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      project_ids: projectIds
    })
  });
  return await response.json();
}

// Send message with SSE streaming
function sendMessage(chatId: string, content: string, projectIds: string[]) {
  const url = `/api/chats/${chatId}/messages`;
  
  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      content: content,
      project_ids: projectIds
    })
  })
  .then(response => {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    
    function processStream() {
      reader.read().then(({ done, value }) => {
        if (done) {
          console.log('Stream complete');
          return;
        }
        
        // Decode chunk
        buffer += decoder.decode(value, { stream: true });
        
        // Process complete SSE messages
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';  // Keep incomplete message in buffer
        
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = JSON.parse(line.substring(6));
            handleSSEMessage(data);
          }
        }
        
        processStream();
      });
    }
    
    processStream();
  });
}

// Handle SSE messages
function handleSSEMessage(data: any) {
  switch (data.type) {
    case 'status':
      console.log('Status:', data.message);
      // Show loading indicator
      break;
      
    case 'context':
      console.log(`Found ${data.chunks_found} relevant chunks`);
      break;
      
    case 'start':
      // Clear any loading, start displaying response
      break;
      
    case 'chunk':
      // Append content to UI
      appendToMessage(data.content);
      break;
      
    case 'done':
      console.log('Message complete:', data.message_id);
      // Hide loading, finalize message
      break;
      
    case 'error':
      console.error('Error:', data.message);
      // Show error to user
      break;
  }
}
```

### React Example

```tsx
import { useState, useEffect } from 'react';

function ChatInterface({ chatId, projectIds }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [currentResponse, setCurrentResponse] = useState('');
  
  const sendMessage = async () => {
    if (!input.trim()) return;
    
    // Add user message to UI
    const userMessage = {
      role: 'user',
      content: input,
      project_ids: projectIds
    };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setStreaming(true);
    setCurrentResponse('');
    
    // Start SSE stream
    const response = await fetch(`/api/chats/${chatId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content: input,
        project_ids: projectIds
      })
    });
    
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';
      
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = JSON.parse(line.substring(6));
          
          if (data.type === 'chunk') {
            setCurrentResponse(prev => prev + data.content);
          } else if (data.type === 'done') {
            // Finalize AI message
            const aiMessage = {
              role: 'ai',
              content: currentResponse,
              project_ids: projectIds
            };
            setMessages(prev => [...prev, aiMessage]);
            setStreaming(false);
            setCurrentResponse('');
          }
        }
      }
    }
  };
  
  return (
    <div className="chat-interface">
      <div className="messages">
        {messages.map((msg, idx) => (
          <div key={idx} className={`message ${msg.role}`}>
            {msg.content}
          </div>
        ))}
        {streaming && (
          <div className="message ai streaming">
            {currentResponse}
            <span className="cursor">▋</span>
          </div>
        )}
      </div>
      
      <div className="input-area">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && sendMessage()}
          disabled={streaming}
          placeholder="Ask a question..."
        />
        <button onClick={sendMessage} disabled={streaming}>
          Send
        </button>
      </div>
    </div>
  );
}
```

## Key Features

### 1. Multi-Company Chat
```json
{
  "content": "Compare revenue growth across all three companies",
  "project_ids": ["tcs-uuid", "infosys-uuid", "wipro-uuid"]
}
```

The AI will analyze all three companies and provide comparative insights.

### 2. Dynamic Project Selection
Within the same chat, you can change which companies to query:

```javascript
// Message 1: Ask about TCS only
sendMessage(chatId, "What is TCS's revenue?", ["tcs-uuid"]);

// Message 2: Switch to Infosys
sendMessage(chatId, "What about Infosys?", ["infosys-uuid"]);

// Message 3: Compare both
sendMessage(chatId, "Compare them", ["tcs-uuid", "infosys-uuid"]);
```

### 3. Context-Aware Responses
The AI receives:
- Previous chat history (last 10 messages)
- Retrieved chunks from vector search
- Company names and fiscal year metadata
- Field information (financial_highlights, risk_factors, etc.)

## Error Handling

```typescript
// Handle errors in SSE stream
if (data.type === 'error') {
  console.error('Stream error:', data.message);
  
  // Common errors:
  // - "OpenAI API is not configured"
  // - "One or more project IDs not found"
  // - "Embeddings service is not configured"
}
```

## Testing with cURL

```bash
# 1. Create chat
curl -X POST http://localhost:8000/api/chats \
  -H "Content-Type: application/json" \
  -d '{"project_ids": ["project-uuid"]}'

# 2. Send message (SSE streaming)
curl -N -X POST http://localhost:8000/api/chats/{chat_id}/messages \
  -H "Content-Type: application/json" \
  -d '{"content": "What was the revenue?", "project_ids": ["project-uuid"]}'

# 3. List chats
curl http://localhost:8000/api/chats

# 4. Get chat details
curl http://localhost:8000/api/chats/{chat_id}

# 5. Delete chat
curl -X DELETE http://localhost:8000/api/chats/{chat_id}
```

## Performance Tips

1. **Batch Project Queries**: Select multiple projects in one message for comparative analysis.
2. **Context Window**: The system retrieves top 10 most relevant chunks by default.
3. **Streaming**: SSE provides immediate feedback - no need to wait for the complete response.
4. **History**: Last 10 messages are included as context for better conversation flow.
