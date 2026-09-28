export interface Source {
  n: number
  id: string
  doc_id: string
  title: string
  file_name: string
  section: string | null
  page_start: number | null
  page_end: number | null
  url: string | null
  text: string
  dense_score?: number | null
  dense_rank?: number | null
  bm25_score?: number | null
  bm25_rank?: number | null
  rrf_score?: number | null
  rerank_score?: number | null
  token_count?: number | null
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
  query?: string
  meta?: { retrieval_ms?: number; total_ms?: number }
  error?: string
}

export interface Health {
  status: string
  openai_key: boolean
  chat_model: string
  embedding_model: string
  vector_db: string
  reranker: string
  chunk_size: number
  chunk_overlap: number
  documents: number
  chunks: number
  tokens: number
}

export interface DocumentInfo {
  doc_id: string
  file_name: string
  title: string
  category: string | null
  academic_year: string | null
  target_audience: string | null
  url: string | null
  indexed_at: string | null
  chunks: number
  tokens: number
  pages: number | null
}

export interface SyncReport {
  indexed: { file_name: string; chunks: number; tokens: number }[]
  skipped: string[]
  removed: string[]
  errors: { file_name: string; error: string }[]
}

export interface TokenizeResult {
  encoding: string
  model: string
  token_count: number
  char_count: number
  tokens: { id: number; text: string }[]
  bm25_tokens: string[]
}

export interface EmbedResult {
  model: string
  dimensions: number
  texts: string[]
  preview: number[][]
  similarity: number[][]
}

export interface SearchResult {
  query: string
  expanded_query: string
  results: Source[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init)
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* not json */
    }
    throw new Error(detail)
  }
  return res.json()
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  health: () => request<Health>('/health'),
  documents: () => request<DocumentInfo[]>('/documents'),
  sync: (reset = false) => request<SyncReport>(`/documents/sync?reset=${reset}`, { method: 'POST' }),
  deleteDocument: (id: string) => request<{ deleted: string }>(`/documents/${id}`, { method: 'DELETE' }),
  upload: (files: File[]) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return request<{ indexed: SyncReport['indexed']; errors: SyncReport['errors'] }>('/documents/upload', {
      method: 'POST',
      body: form,
    })
  },
  fileUrl: (docId: string, page?: number | null) => `/api/documents/${docId}/file${page ? `#page=${page}` : ''}`,
  tokenize: (text: string, model?: string) => request<TokenizeResult>('/nlp/tokenize', json({ text, model })),
  embed: (texts: string[]) => request<EmbedResult>('/nlp/embed', json({ texts })),
  search: (query: string, top_k = 10, rerank = false) => request<SearchResult>('/search', json({ query, top_k, rerank })),
}

export interface StreamHandlers {
  onSources: (data: { query: string; sources: Source[] }) => void
  onToken: (token: string) => void
  onDone: (meta: { retrieval_ms?: number; total_ms?: number }) => void
  onError: (detail: string) => void
}

/** POST /api/chat/stream и разбор Server-Sent Events. */
export async function streamChat(
  question: string,
  history: { role: string; content: string }[],
  h: StreamHandlers,
  signal?: AbortSignal,
) {
  let res: Response
  try {
    res = await fetch('/api/chat/stream', { ...json({ question, history }), signal })
  } catch (e) {
    if ((e as Error).name !== 'AbortError') h.onError('Сервер недоступен. Запущен ли backend на :8000?')
    return
  }
  if (!res.ok || !res.body) {
    h.onError(`Ошибка сервера: ${res.status}`)
    return
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let idx
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const raw = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        let event = 'message'
        let data = ''
        for (const line of raw.split('\n')) {
          if (line.startsWith('event: ')) event = line.slice(7)
          else if (line.startsWith('data: ')) data += line.slice(6)
        }
        const payload = data ? JSON.parse(data) : null
        if (event === 'sources') h.onSources(payload)
        else if (event === 'token') h.onToken(payload)
        else if (event === 'done') h.onDone(payload ?? {})
        else if (event === 'error') h.onError(payload?.detail ?? 'Неизвестная ошибка')
      }
    }
  } catch (e) {
    if ((e as Error).name !== 'AbortError') h.onError(String(e))
  }
}
