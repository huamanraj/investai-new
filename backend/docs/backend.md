Below is a **full backend explanation** for your **InvestAI** system.
I will explain **slowly**, **very simple**, and **step-by-step**, like you are building it from zero.

No complex words. No skipping logic.

---

# 🧠 InvestAI Backend – COMPLETE EXPLANATION

You are building **an AI system that reads financial documents and chats accurately**.

Your backend stack:

* **FastAPI** – backend server
* **Playwright** – web scraping (BSE links)
* **Cloudinary** – PDF file storage
* **LlamaExtract (LlamaIndex)** – PDF text extraction
* **OpenAI** – embeddings + chat
* **PostgreSQL + pgvector** – store data + vector search

This is a **professional RAG system**.

---

## 1️⃣ BIG PICTURE (ONE LINE)

> User adds a company → system downloads PDFs → converts to embeddings → user chats and compares companies in one chat using toggles

---

## 2️⃣ USER FLOW (What user experiences)

### STEP 1: Create Project

* User pastes **BSE company link**
* Clicks **Create Project**
* Project name = company name

UI shows:

> “Processing documents…”

---

### STEP 2: Backend Starts Working (Background)

User does NOTHING.
Backend does everything.

---

### STEP 3: Project Ready

* Company snapshot page appears
* Chat is enabled
* Toggles for projects visible

---

### STEP 4: Chat & Compare

* User opens chat
* Turns **ON/OFF** companies
* Asks questions
* Gets answers + comparisons

All in **same chat screen**.

---

## 3️⃣ BACKEND DATA FLOW (MOST IMPORTANT)

Now I’ll explain **what happens inside backend**, step-by-step.

---

## 🔁 FLOW A: Project Creation (BSE Link → Data)

### A1️⃣ User sends BSE link

API:

```
POST /projects
```

Backend:

* Creates row in `projects` table
* Starts background job

---

### A2️⃣ Scrape BSE page (Playwright)

Why Playwright?

* BSE pages are dynamic
* PDFs load via JS

Playwright:

* Opens page
* Finds **Annual Report / Results PDF**
* Extracts PDF URLs

---

### A3️⃣ Download PDF

* PDF downloaded temporarily
* Sent to **Cloudinary**
* Cloudinary returns **file URL**

Store URL in:

```
documents.file_url
```

Why Cloudinary?

* Fast
* Cheap
* No server disk issues

---

### A4️⃣ Extract Text from PDF (LlamaExtract)

You use:

* `llamaindex.llama_extract`

What it does:

* Reads PDF
* Keeps structure
* Extracts **page-by-page text**

For each page:

* Save page number
* Save full text

Stored in:

```
document_pages
```

📌 This is critical for financial accuracy.

---

### A5️⃣ Chunk the Page Text

For **each page**:

* Split into chunks
* 300–500 tokens
* 50–80 overlap
* NEVER mix pages

Stored in:

```
text_chunks
```

Why?

* Smaller chunks = better search
* Page isolation = correct numbers

---

### A6️⃣ Create Embeddings (OpenAI)

For each chunk:

* Send text to OpenAI embedding API
* Get vector
* Save vector in pgvector

Stored in:

```
embeddings
```

Now your company data is **searchable**.

---

## 4️⃣ FLOW B: Company Snapshot Page

This is a **pre-calculated summary**.

### What backend does:

* Runs special prompts like:

  * “Summarize financial highlights”
  * “Extract revenue trend”
  * “List major risks”

Uses:

* Only company’s embeddings

Result:

* JSON data
* Text summary

Stored in:

```
company_snapshots
```

Frontend just **shows charts**.
No AI calls needed later → very fast.

---

## 5️⃣ FLOW C: Chat System (Core Feature)

This is the **heart of InvestAI**.

---

## 🧩 Chat Design Rule (VERY IMPORTANT)

* Chat does **NOT** belong to a company
* Each **message** decides which companies are active

This allows:

* Toggle ON/OFF anytime
* Same chat
* Clean history

---

## 6️⃣ Chat Message Flow (Step-by-step)

### C1️⃣ User types message

Example:

> “Compare revenue growth and risks”

User toggles:

* TCS ✅
* Infosys ✅
* Wipro ❌

---

### C2️⃣ Frontend sends API request

```json
{
  "chat_id": "123",
  "message": "Compare revenue growth and risks",
  "active_project_ids": ["tcs_id", "infosys_id"]
}
```

---

### C3️⃣ Backend creates query embedding

* User question → OpenAI embedding

---

### C4️⃣ Vector search (pgvector)

SQL logic:

* Search embeddings
* Only where `project_id IN active_project_ids`
* Get top 25 chunks

This guarantees:

* Only selected companies
* No data leakage

---

### C5️⃣ Group chunks by company

Backend groups data like:

```
TCS → chunks
Infosys → chunks
```

So AI knows which data belongs to which company.

---

### C6️⃣ Build comparison prompt

Backend prompt logic:

* “Use only given data”
* “Separate company answers”
* “Do not guess numbers”

This avoids hallucination.

---

### C7️⃣ OpenAI Chat Completion

* AI generates answer
* Clean comparison
* Accurate financial tone

---

### C8️⃣ Save message

Stored in `messages` table:

* content
* role
* project_ids used

So history stays correct even if toggles change later.

---

## 7️⃣ Toggle ON / OFF (Mid-chat)

This is **simple but powerful**.

* Toggles affect **NEXT message only**
* Old messages remain unchanged
* Backend doesn’t store toggle state globally

This makes system:

* Predictable
* Debuggable
* Professional

---

## 8️⃣ Comparison Logic (Multiple Companies)

Backend rules:

* Max 5 companies per message
* Retrieve chunks per company
* Balance context

This ensures:

* Clear comparison
* No confusion
* Good AI quality

---

## 9️⃣ Accuracy Guarantees (Finance-grade)

Your backend ensures accuracy because:

✔ Page-level storage
✔ Chunk-level embeddings
✔ No mixed years
✔ Explicit company grouping
✔ Source traceability
✔ Snapshot pre-computation

This is how **real research tools** work.

---

## 10️⃣ Performance Guarantees

Fast because:

* pgvector index
* background ingestion
* Cloudinary storage
* no auth / no rate limits
* prebuilt snapshots

Even on small server → works well.

---

## 🔁 COMPLETE DATA FLOW (ONE VIEW)

```
BSE Link
 → Playwright
 → PDF URLs
 → Cloudinary
 → LlamaExtract
 → Pages
 → Chunks
 → OpenAI Embeddings
 → pgvector

Chat Question
 → Embedding
 → Vector Search
 → Group by Company
 → OpenAI Chat
 → Answer
```

