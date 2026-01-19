Good question 👍
This is **the most important part** of InvestAI.
I’ll explain **slowly**, **simple English**, and **deeply**, exactly for **financial data accuracy**.

---

## 🔴 First: How to store embeddings CORRECTLY for financial PDFs

Financial data must be:

* accurate
* traceable
* page-level
* fast to search

So **DO NOT** embed whole PDF ❌
**DO NOT** embed random chunks ❌

### ✅ Correct method (industry standard)

**PDF → Pages → Structured Chunks → Embeddings**

---

## 📄 PDF Chunking Strategy (Very Important)

### Level 1: Page-based

Each PDF page is a **source of truth**.

### Level 2: Semantic chunks inside page

Inside each page:

* 300–500 tokens per chunk
* overlap: 50–80 tokens
* never mix pages

This gives:

* correct numbers
* page reference
* auditability

---

## 🧠 Why this is accurate for finance

If user asks:

> “What was operating margin in FY23?”

You can:

* retrieve chunk
* show **page number**
* avoid mixing quarters

This is how analysts work.

---

## 🗄️ DATABASE SCHEMA (PERSONAL, SINGLE-USER, FAST)

No users
No rate limits
No auth
Just **projects → documents → pages → chunks → embeddings**

---

## 1️⃣ `projects` (Company = Project)

Each BSE company = 1 project

```sql
CREATE TABLE projects (
  id UUID PRIMARY KEY,
  company_name TEXT NOT NULL,
  source_url TEXT NOT NULL,
  exchange TEXT DEFAULT 'BSE',
  created_at TIMESTAMP DEFAULT NOW()
);
```

### Explanation (simple)

* `company_name` → TCS, Infosys
* `source_url` → BSE annual report page
* One project = one company

---

## 2️⃣ `documents` (Annual reports, presentations)

```sql
CREATE TABLE documents (
  id UUID PRIMARY KEY,
  project_id UUID REFERENCES projects(id),
  document_type TEXT,  -- annual_report, q4_presentation, transcript
  fiscal_year TEXT,
  file_url TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### Why needed

* Company has **many PDFs**
* Different years
* Different types

---

## 3️⃣ `document_pages` (VERY IMPORTANT)

Each row = **1 PDF page**

```sql
CREATE TABLE document_pages (
  id UUID PRIMARY KEY,
  document_id UUID REFERENCES documents(id),
  page_number INT,
  page_text TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### Why this table matters

* Financial numbers live on pages
* Pages are never mixed
* You can show page reference later

---

## 4️⃣ `text_chunks` (Searchable units)

Each page → many chunks

```sql
CREATE TABLE text_chunks (
  id UUID PRIMARY KEY,
  page_id UUID REFERENCES document_pages(id),
  chunk_index INT,
  content TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### Chunk rules

* 300–500 tokens
* Overlap 50–80 tokens
* Same page only

---

## 5️⃣ `embeddings` (pgvector)

```sql
CREATE TABLE embeddings (
  id UUID PRIMARY KEY,
  chunk_id UUID REFERENCES text_chunks(id),
  embedding VECTOR(3072),  -- OpenAI large
  created_at TIMESTAMP DEFAULT NOW()
);
```

### Why separate table?

* Faster similarity search
* Clean design
* Easy future upgrades

---

## 🔍 Index for SPEED (Important)

```sql
CREATE INDEX embeddings_vector_idx
ON embeddings
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

This makes search **very fast**.

---

## 🧠 How Search Works (Simple)

When user asks question:

1. Convert question → embedding
2. Search embeddings table
3. Get top chunks
4. Join back:

   * chunk
   * page
   * document
   * project

So answer always knows:

* company
* document
* page number

---

## 🧾 Chat Messages Table

```sql
CREATE TABLE chats (
  id UUID PRIMARY KEY,
  title TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE messages (
  id UUID PRIMARY KEY,
  chat_id UUID REFERENCES chats(id),
  role TEXT, -- user / ai
  content TEXT,
  project_ids UUID[], -- toggles used
  created_at TIMESTAMP DEFAULT NOW()
);
```

### Why store `project_ids`?

* Toggles change per message
* History remains correct

---

## 📊 Company Snapshot Table

Precomputed summary (fast UI)

```sql
CREATE TABLE company_snapshots (
  project_id UUID PRIMARY KEY REFERENCES projects(id),
  summary TEXT,
  revenue_trend JSONB,
  profit_trend JSONB,
  risks TEXT,
  updated_at TIMESTAMP DEFAULT NOW()
);
```

---

## ⚡ Performance Tips (Very Important)

✔ Page-based chunking
✔ pgvector index
✔ background ingestion
✔ precomputed snapshot
✔ no joins during embedding search (use IDs)

This will be **very fast** even on a small server.

---

## 🧠 Accuracy Tips (Finance Specific)

* Never mix pages
* Never mix fiscal years in same chunk
* Always keep page_number
* Limit retrieval per company (5–7 chunks max)
* Force LLM:

  > “If data is missing, say NOT FOUND”

---

## 🧩 Final Mental Model

```
Company (Project)
 └── Documents
     └── Pages
         └── Chunks
             └── Embeddings
```

This is **professional-grade**, not toy.

---

## ✅ Final Answer (Short)

> **Store embeddings per chunk, per page, per document, per company**

This gives:

* accuracy
* speed
* trust
* clean comparisons

