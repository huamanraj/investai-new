# InvestAI Frontend - UI Specification

> **Stack**: React 18 + Vite + TypeScript + Zustand + shadcn/ui + Tailwind CSS

---

## Core Requirements

1. **Sidebar is ALWAYS visible** on all pages (collapsible option)
2. **Dark theme by default** with premium aesthetic minimal no transaprecy 
3. **Real-time SSE streaming** for project processing & chat responses
4. **Mobile-first responsive** design
5. **Pagination-based loading** for long lists (not infinite scroll)

---

## Tech Setup

```bash
npm create vite@latest invest-ai -- --template react-ts
cd invest-ai
npm install zustand axios lucide-react recharts
npx shadcn@latest init  # Select dark theme only 
npx shadcn@latest add button input card dialog sheet scroll-area checkbox badge skeleton toast
```

---

## App Structure

```
src/
├── components/
│   ├── layout/
│   │   ├── Sidebar.tsx          # Always visible, collapsible
│   │   ├── MainLayout.tsx       # Wrapper with sidebar
│   │   └── Header.tsx
│   ├── chat/
│   │   ├── ChatInterface.tsx
│   │   ├── ChatMessage.tsx
│   │   ├── ChatInput.tsx
│   │   └── ProjectChips.tsx     # Selected projects above input
│   ├── project/
│   │   ├── CreateProjectModal.tsx
│   │   ├── ProcessingProgress.tsx
│   │   ├── ProjectCard.tsx
│   │   └── SnapshotView.tsx
│   └── ui/                      # shadcn components
├── stores/
│   ├── useProjectStore.ts
│   ├── useChatStore.ts
│   └── useUIStore.ts
├── lib/
│   ├── api.ts                   # Axios instance
│   └── sse.ts                   # SSE helper
├── pages/
│   ├── HomePage.tsx
│   ├── ChatPage.tsx
│   └── ProjectPage.tsx
└── App.tsx                      # Router setup
```

---

## Page Layouts

### 1. Home Page (`/`)

First-time user sees welcome screen with two action cards.

```
┌──────────────────────────────────────────────────────────────────┐
│ [≡]  InvestAI                                              [🌙] │
├─────────────────┬────────────────────────────────────────────────┤
│                 │                                                │
│  PROJECTS       │     ╔════════════════════════════════╗         │
│  ───────────    │     ║  Welcome to InvestAI           ║         │
│  • TCS ✅       │     ║  AI Financial Analysis         ║         │
│  • Infosys ⏳   │     ╚════════════════════════════════╝         │
│                 │                                                │
│  [Show More]    │     ┌──────────────┐ ┌──────────────┐          │
│                 │     │ 📁 Create    │ │ 💬 New Chat  │          │
│  ───────────    │     │ Project      │ │              │          │
│  CHAT HISTORY   │     └──────────────┘ └──────────────┘          │
│  ───────────    │                                                │
│  • TCS Q3..     │     Recent Projects:                           │
│  • Compare..    │     [TCS • Completed • 2d ago]                 │
│                 │                                                │
│  [Show More]    │                                                │
│  ───────────    │                                                │
│  [+ New Chat]   │                                                │
│  [+ Project]    │                                                │
└─────────────────┴────────────────────────────────────────────────┘
```

### 2. Chat Page (`/chat/:chatId?`)

ChatGPT-like interface with project selection.

```
┌──────────────────────────────────────────────────────────────────┐
│ [≡]  Chat: TCS Analysis                                    [🌙] │
├─────────────────┬────────────────────────────────────────────────┤
│                 │  ┌──────────────────────────────────────────┐  │
│  [SIDEBAR]      │  │ 👤 What was TCS revenue in FY2024?       │  │
│  Same as        │  └──────────────────────────────────────────┘  │
│  home page      │                                                │
│                 │  ┌──────────────────────────────────────────┐  │
│                 │  │ 🤖 Based on the FY2024 annual report,   │  │
│                 │  │    TCS reported ₹2,40,893 Cr revenue... │  │
│                 │  │    ▊ (streaming cursor)                 │  │
│                 │  └──────────────────────────────────────────┘  │
│                 │                                                │
│                 │  ┌──────────────────────────────────────────┐  │
│                 │  │ [TCS ✕] [Infosys ✕]           [+ Add]   │  │
│                 │  ├──────────────────────────────────────────┤  │
│                 │  │ Ask about financials...            [➜]  │  │
│                 │  └──────────────────────────────────────────┘  │
└─────────────────┴────────────────────────────────────────────────┘
```

**Key Details:**

- `[+ Add]` button opens project selector dropdown (multi-select checkboxes)
- Selected projects shown as chips with ✕ to remove
- Messages stream in real-time via SSE
- Typing indicator while AI is responding

### 3. Project Snapshot Page (`/projects/:projectId`)

Company dashboard with financial data.

```
┌──────────────────────────────────────────────────────────────────┐
│ [≡]  TCS - Snapshot                                        [🌙] │
├─────────────────┬────────────────────────────────────────────────┤
│                 │  🏢 Tata Consultancy Services                  │
│  [SIDEBAR]      │  BSE: 532540 • Status: ✅ Complete             │
│                 │                                                │
│                 │  ┌─────────┐ ┌─────────┐ ┌─────────┐           │
│                 │  │Revenue  │ │Profit   │ │Margin   │           │
│                 │  │₹2.4L Cr │ │₹45.9K   │ │24.3%    │           │
│                 │  │+8.1%    │ │+8.8%    │ │         │           │
│                 │  └─────────┘ └─────────┘ └─────────┘           │
│                 │                                                │
│                 │  📈 Revenue Trend [Chart]                      │
│                 │                                                │
│                 │  📋 Highlights    ⚠️ Risks                     │
│                 │  • Strong margin  • Currency                   │
│                 │  • Digital growth • Attrition                  │
│                 │                                                │
│                 │  📄 Documents: [AR 2024] [AR 2023]             │
│                 │                                                │
│                 │  [💬 Start Chat with Project]                  │
└─────────────────┴────────────────────────────────────────────────┘
```

### 4. Create Project Flow (Modal)

```
┌───────────────────────────────────────┐
│  📊 Create New Project           [✕]  │
├───────────────────────────────────────┤
│                                       │
│  BSE Annual Report URL:               │
│  ┌─────────────────────────────────┐  │
│  │ https://bseindia.com/...        │  │
│  └─────────────────────────────────┘  │
│                                       │
│  ℹ️ Paste company's annual reports    │
│     page URL from BSE India           │
│                                       │
│        [🚀 Create Project]            │
└───────────────────────────────────────┘
```

**After Submit - Processing View:**

```
┌───────────────────────────────────────┐
│  Processing: TCS                 [✕]  │
├───────────────────────────────────────┤
│                                       │
│  ━━━━━━━━━━━━━━━━━━━━━━  45%         │
│                                       │
│  ✅ Validating Link                   │
│  ✅ Scraping Page                     │
│  ⏳ Downloading PDFs...               │
│  ○ Uploading to Cloud                 │
│  ○ Extracting Data (AI)               │
│  ○ Creating Embeddings                │
│  ○ Generating Snapshot                │
│  ○ Complete                           │
│                                       │
│  📄 Found 3 annual reports            │
│                                       │
│  [Cancel]         [Run in Background] │
└───────────────────────────────────────┘
```

- Progress streams via SSE (`/api/projects/{id}/progress-stream`)
- 8 steps total, show current step with spinner
- On complete: close modal, navigate to snapshot

---

## Sidebar Component (CRITICAL)

**Always visible on desktop, sheet overlay on mobile.**

```tsx
// Sidebar.tsx - Key features:
// 1. Two scrollable sections: Projects (top) & Chats (bottom)
// 2. Each section has "Show More" button for pagination
// 3. Click project → navigate to /projects/:id (snapshot)
// 4. Click chat → navigate to /chat/:id
// 5. "New Chat" and "New Project" buttons at bottom
// 6. Collapsible via hamburger on mobile (Sheet component)

<aside className="w-64 border-r bg-background flex flex-col h-screen">
  {/* Projects Section */}
  <div className="flex-1 overflow-hidden flex flex-col">
    <h3>PROJECTS</h3>
    <ScrollArea className="flex-1">
      {projects.map((p) => (
        <ProjectItem />
      ))}
    </ScrollArea>
    {hasMoreProjects && <Button onClick={loadMoreProjects}>Show More</Button>}
  </div>

  <Separator />

  {/* Chats Section */}
  <div className="flex-1 overflow-hidden flex flex-col">
    <h3>CHAT HISTORY</h3>
    <ScrollArea className="flex-1">
      {chats.map((c) => (
        <ChatItem />
      ))}
    </ScrollArea>
    {hasMoreChats && <Button onClick={loadMoreChats}>Show More</Button>}
  </div>

  <Separator />

  {/* Actions */}
  <div className="p-4 space-y-2">
    <Button onClick={openNewChat}>+ New Chat</Button>
    <Button onClick={openCreateProject}>+ New Project</Button>
  </div>
</aside>
```

**Mobile:** Use `<Sheet>` from shadcn, triggered by hamburger icon.

---

## Chat Input with Project Selector

```tsx
// ChatInput.tsx
<div className="border rounded-lg">
  {/* Selected project chips */}
  <div className="flex flex-wrap gap-2 p-2 border-b">
    {selectedProjects.map((p) => (
      <Badge key={p.id} variant="secondary">
        {p.company_name}
        <X
          onClick={() => removeProject(p.id)}
          className="ml-1 h-3 w-3 cursor-pointer"
        />
      </Badge>
    ))}

    {/* Add project button - opens dropdown */}
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm">
          <Plus className="h-4 w-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent>
        <h4>Select Projects</h4>
        {completedProjects.map((p) => (
          <div className="flex items-center gap-2">
            <Checkbox
              checked={selectedProjects.includes(p.id)}
              onCheckedChange={() => toggleProject(p.id)}
            />
            <span>{p.company_name}</span>
          </div>
        ))}
      </PopoverContent>
    </Popover>
  </div>

  {/* Input area */}
  <div className="flex items-center p-2">
    <Input
      placeholder="Ask about financials..."
      value={message}
      onChange={(e) => setMessage(e.target.value)}
      onKeyDown={(e) => e.key === "Enter" && sendMessage()}
    />
    <Button onClick={sendMessage}>
      <Send />
    </Button>
  </div>
</div>
```

---

## API Integration

**Base URL:** `const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'`

### Projects API

| Endpoint                            | Method | Description                                     |
| ----------------------------------- | ------ | ----------------------------------------------- |
| `/api/projects`                     | POST   | Create project `{source_url}` → returns project |
| `/api/projects?skip=0&limit=20`     | GET    | List with pagination                            |
| `/api/projects/:id`                 | GET    | Project + documents + job status                |
| `/api/projects/:id/status`          | GET    | Quick status check                              |
| `/api/projects/:id/snapshot`        | GET    | Financial snapshot data                         |
| `/api/projects/:id/progress-stream` | GET    | **SSE** - Processing progress                   |
| `/api/projects/:id/cancel`          | POST   | Cancel running job                              |
| `/api/projects/:id/resume`          | POST   | Resume failed job                               |
| `/api/projects/:id/job`             | GET    | Job details                                     |
| `/api/projects/:id`                 | DELETE | Delete project                                  |

### Chats API

| Endpoint                       | Method | Description                             |
| ------------------------------ | ------ | --------------------------------------- |
| `/api/chats`                   | POST   | Create chat `{title?, project_ids[]}`   |
| `/api/chats?limit=50&offset=0` | GET    | List with pagination                    |
| `/api/chats/:id`               | GET    | Chat with all messages                  |
| `/api/chats/:id/messages`      | POST   | **SSE** - Send message, stream response |
| `/api/chats/:id`               | DELETE | Delete chat                             |

### SSE Streaming Examples

**Project Progress:**

```typescript
const es = new EventSource(`${API}/api/projects/${id}/progress-stream`);
es.onmessage = (e) => {
  const data = JSON.parse(e.data);
  // data.type: "connected" | "step_started" | "progress" | "step_completed" | "completed" | "error"
  // data.step: "scraping" | "downloading" | "uploading" | "extracting" | "creating_embeddings" | "generating_snapshot"
  // data.step_index, data.total_steps, data.message
};
```

**Chat Message Streaming:**

```typescript
const res = await fetch(`${API}/api/chats/${chatId}/messages`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ content, project_ids }),
});

const reader = res.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  const lines = decoder.decode(value).split("\n");
  for (const line of lines) {
    if (!line.startsWith("data: ")) continue;
    const data = JSON.parse(line.slice(6));

    if (data.type === "chunk") {
      setStreamingText((prev) => prev + data.content);
    } else if (data.type === "done") {
      // Finalize message with data.message_id
    }
  }
}
```

---

## Zustand Stores

```typescript
// stores/useProjectStore.ts
interface ProjectStore {
  projects: Project[];
  total: number;
  loading: boolean;

  fetchProjects: (skip?: number, limit?: number) => Promise<void>;
  createProject: (url: string) => Promise<Project>;
  deleteProject: (id: string) => Promise<void>;
}

// stores/useChatStore.ts
interface ChatStore {
  chats: Chat[];
  currentChat: ChatDetail | null;
  selectedProjectIds: string[];
  streamingContent: string;
  isStreaming: boolean;

  fetchChats: (offset?: number, limit?: number) => Promise<void>;
  createChat: (projectIds: string[], title?: string) => Promise<Chat>;
  loadChat: (id: string) => Promise<void>;
  sendMessage: (content: string) => Promise<void>;
  selectProject: (id: string) => void;
  deselectProject: (id: string) => void;
  deleteChat: (id: string) => Promise<void>;
}

// stores/useUIStore.ts
interface UIStore {
  sidebarOpen: boolean;
  createProjectOpen: boolean;
  toggleSidebar: () => void;
  openCreateProject: () => void;
  closeCreateProject: () => void;
}
```

---

## Mobile Responsiveness

- **Desktop (≥1024px):** Sidebar always visible, fixed left
- **Tablet (768-1023px):** Sidebar collapsible, icon toggle
- **Mobile (<768px):** Sidebar as Sheet overlay, hamburger toggle

```tsx
// MainLayout.tsx
<div className="flex h-screen">
  {/* Desktop sidebar */}
  <div className="hidden lg:block">
    <Sidebar />
  </div>

  {/* Mobile sidebar (Sheet) */}
  <Sheet open={sidebarOpen} onOpenChange={setSidebarOpen}>
    <SheetContent side="left" className="p-0 w-72">
      <Sidebar />
    </SheetContent>
  </Sheet>

  {/* Main content */}
  <main className="flex-1 flex flex-col">
    <Header />
    <div className="flex-1 overflow-auto">{children}</div>
  </main>
</div>
```

---

## Key Behaviors Summary

1. **Home page:** Shows welcome + "Create Project" & "New Chat" cards
2. **Create Project:** Modal with URL input → SSE progress streaming → auto-navigate to snapshot
3. **Chat page:** Select projects via `+` button → chips show above input → messages stream in real-time
4. **Project page:** Click project in sidebar → shows company snapshot with charts & financials
5. **Sidebar:** Always present, two sections (projects/chats), pagination "Show More", click navigates
6. **New Chat:** Creates chat, user must select at least 1 project before sending message
7. **Project status:** `pending | scraping | downloading | processing | completed | failed`

---

## Design Tokens (Tailwind)

```css
/* Use shadcn dark theme defaults + customize: */
:root {
  --background: 0 0% 3.9%;
  --foreground: 0 0% 98%;
  --primary: 239 84% 67%; /* Indigo */
  --primary-foreground: 0 0% 98%;
  --secondary: 0 0% 14.9%;
  --accent: 270 67% 47%; /* Purple accent */
  --muted: 0 0% 14.9%;
  --border: 0 0% 14.9%;
}
```

**Effects:**

- Cards: `bg-card/50 backdrop-blur-sm border`
- Buttons: `hover:shadow-lg hover:shadow-primary/20 transition-all`
- Active states: `ring-2 ring-primary`

---

## Checklist

- [ ] Sidebar always visible (desktop) or accessible (mobile)
- [ ] Project creation with real-time SSE progress
- [ ] Chat with streaming AI responses
- [ ] Multi-project selection via chips + popover
- [ ] Pagination "Show More" (not infinite scroll)
- [ ] Click project → snapshot page
- [ ] Click chat → load chat history
- [ ] Mobile responsive with Sheet sidebar
- [ ] Loading skeletons & error toasts
- [ ] Premium dark theme aesthetic
