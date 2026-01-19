# Testing Your Backend with cURL

Here's a comprehensive guide to test all the features you've built:

## 1. Basic Health Check

```bash
# Check if server is running
curl http://localhost:8000/

# Health check
curl http://localhost:8000/health
```

## 2. Create a Project (Start Processing)

```bash
# Create a new project - this starts the background job
curl -X POST http://localhost:8000/api/projects \
  -H "Content-Type: application/json" \
  -d '{
    "source_url": "https://www.bseindia.com/stock-share-price/tata-consultancy-services-ltd/tcs/532540/financials-annual-reports/"
  }'

# Response will include project_id - save this!
# Example response:
# {
#   "id": "123e4567-e89b-12d3-a456-426614174000",
#   "company_name": "TCS",
#   "status": "pending",
#   ...
# }
```

## 3. Stream Real-Time Progress (NEW!)

```bash
# Replace {project_id} with the actual ID from step 2
# This will show live updates as the job progresses
curl -N http://localhost:8000/api/projects/{project_id}/progress-stream

# You'll see events like:
# data: {"type":"connected","job_id":"a1b2c3d4","message":"Progress stream connected"}
# data: {"type":"started","message":"Starting project processing","step_index":0,...}
# data: {"type":"step_started","message":"Starting: Scraping","step":"scraping",...}
# data: {"type":"progress","message":"Validating BSE India URL...","step":"scraping"}
# data: {"type":"progress","message":"Found 1 annual report(s). Downloading...","step":"scraping"}
# data: {"type":"step_completed","message":"Completed: Scraping","step":"scraping",...}
# ... continues until completion
```

## 4. Get Job Details

```bash
# Get detailed job status and progress
curl http://localhost:8000/api/projects/{project_id}/job

# Response shows:
# - Current step
# - Progress percentage
# - Documents processed
# - Embeddings created
# - Can resume?
# - Error messages if any
```

## 5. List All Projects

```bash
# Get all projects
curl http://localhost:8000/api/projects

# With pagination
curl "http://localhost:8000/api/projects?skip=0&limit=10"
```

## 6. Get Project Details

```bash
# Get project with documents
curl http://localhost:8000/api/projects/{project_id}
```

## 7. Cancel a Running Job

```bash
# Cancel the job (it can be resumed later)
curl -X POST http://localhost:8000/api/projects/{project_id}/cancel

# Response:
# {
#   "message": "Job cancelled successfully",
#   "project_id": "...",
#   "can_resume": true
# }
```

## 8. Resume a Cancelled/Failed Job

```bash
# Resume from where it left off
curl -X POST http://localhost:8000/api/projects/{project_id}/resume

# Response:
# {
#   "message": "Job resumed successfully",
#   "resuming_from_step": "uploading",
#   "failed_step": null
# }
```

## 9. Get Company Snapshot

```bash
# Once job completes, get the AI-generated snapshot
curl http://localhost:8000/api/projects/{project_id}/snapshot

# Returns comprehensive JSON with:
# - Company overview
# - Financial metrics
# - Performance summary
# - Chart data
# - Risk analysis
```

## 10. Chat Features

### Create a Chat Session

```bash
curl -X POST http://localhost:8000/api/chats \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Analysis of TCS",
    "project_ids": ["{project_id}"]
  }'

# Save the chat_id from response
```

### Send a Message (with SSE Streaming)

```bash
# This will stream the AI response in real-time
curl -N -X POST http://localhost:8000/api/chats/{chat_id}/messages \
  -H "Content-Type: application/json" \
  -d '{
    "content": "What was the revenue in the latest annual report?",
    "project_ids": ["{project_id}"]
  }'

# You'll see SSE events:
# data: {"type":"status","message":"Creating query embedding..."}
# data: {"type":"status","message":"Searching relevant documents..."}
# data: {"type":"context","chunks_found":8}
# data: {"type":"start"}
# data: {"type":"chunk","content":"Based on "}
# data: {"type":"chunk","content":"the FY2024-25 "}
# ... (streaming response)
# data: {"type":"done","message_id":"..."}
```

### List All Chats

```bash
curl http://localhost:8000/api/chats
```

### Get Chat Details

```bash
curl http://localhost:8000/api/chats/{chat_id}
```

## Complete Testing Workflow

Here's a step-by-step test scenario:

```bash
# Step 1: Create project
PROJECT_ID=$(curl -s -X POST http://localhost:8000/api/projects \
  -H "Content-Type: application/json" \
  -d '{"source_url": "https://www.bseindia.com/stock-share-price/tata-consultancy-services-ltd/tcs/532540/financials-annual-reports/"}' \
  | jq -r '.id')

echo "Project ID: $PROJECT_ID"

# Step 2: Stream progress in real-time (in a separate terminal)
curl -N http://localhost:8000/api/projects/$PROJECT_ID/progress-stream

# Step 3: Check job status (in another terminal while streaming)
curl http://localhost:8000/api/projects/$PROJECT_ID/job | jq

# Step 4: Test cancel (optional)
# curl -X POST http://localhost:8000/api/projects/$PROJECT_ID/cancel

# Step 5: Test resume (if cancelled)
# curl -X POST http://localhost:8000/api/projects/$PROJECT_ID/resume

# Step 6: Wait for completion, then get snapshot
curl http://localhost:8000/api/projects/$PROJECT_ID/snapshot | jq

# Step 7: Create chat
CHAT_ID=$(curl -s -X POST http://localhost:8000/api/chats \
  -H "Content-Type: application/json" \
  -d "{\"project_ids\": [\"$PROJECT_ID\"]}" \
  | jq -r '.id')

echo "Chat ID: $CHAT_ID"

# Step 8: Send message and stream response
curl -N -X POST http://localhost:8000/api/chats/$CHAT_ID/messages \
  -H "Content-Type: application/json" \
  -d "{\"content\": \"What was the revenue?\", \"project_ids\": [\"$PROJECT_ID\"]}"
```

## Tips for Testing

1. **Use `-N` flag** for SSE streaming endpoints (progress-stream, chat messages)
2. **Use `jq`** to prettify JSON responses: `| jq`
3. **Save IDs** in variables for easier testing
4. **Open multiple terminals** to:
   - Terminal 1: Stream progress
   - Terminal 2: Check job status
   - Terminal 3: Cancel/resume operations

## Testing Progress Stream with Watch

```bash
# Watch job progress every 2 seconds (alternative to streaming)
watch -n 2 "curl -s http://localhost:8000/api/projects/$PROJECT_ID/job | jq '.progress_percentage, .current_step, .status'"
```

## Testing Error Scenarios

```bash
# Test with invalid URL
curl -X POST http://localhost:8000/api/projects \
  -H "Content-Type: application/json" \
  -d '{"source_url": "https://invalid-url.com"}'

# Test resume without failed job
curl -X POST http://localhost:8000/api/projects/{project_id}/resume

# Test cancel non-existent job
curl -X POST http://localhost:8000/api/projects/00000000-0000-0000-0000-000000000000/cancel
```

## Swagger UI (Interactive Testing)

The easiest way to test is actually via Swagger UI:

```bash
# Open in browser:
http://localhost:8000/docs

# You can:
# - See all endpoints
# - Try them interactively
# - See request/response schemas
# - Test SSE streaming
```

That's it! The progress streaming endpoint (`/progress-stream`) is the most interesting one to test - you'll see real-time updates as your job processes through all 8 steps! 🚀