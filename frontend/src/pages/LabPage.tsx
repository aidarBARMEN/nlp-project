import { useEffect, useState } from 'react'
import { Binary, Loader2, Plus, Search, Sigma, Split, X } from 'lucide-react'
import clsx from 'clsx'
import { api, type EmbedResult, type SearchResult, type TokenizeResult } from '../api'
import { pagesLabel } from '../components/SourceCard'

type Tab = 'tokens' | 'embeddings' | 'search'

const TABS: { id: Tab; label: string; icon: typeof Binary; hint: string }[] = [
  { id: 'tokens', label: 'Токенизация', icon: Split, hint: 'BPE-токены OpenAI (tiktoken) и лексические токены BM25' },
  { id: 'embeddings', label: 'Эмбеддинги', icon: Sigma, hint: 'Векторы текстов и косинусное сходство между ними' },
  { id: 'search', label: 'Гибридный поиск', icon: Search, hint: 'Dense + BM25 → Reciprocal Rank Fusion → Rerank' },
]

export default function LabPage() {
  const [tab, setTab] = useState<Tab>('tokens')
  return (
    <div className="scrollbar-thin flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <h1 className="font-display text-2xl font-bold text-navy-900">NLP-лаборатория</h1>
        <p className="mt-1 text-sm text-slate-500">Как устроен RAG-пайплайн изнутри — на живых данных.</p>

        <div className="mt-6 flex gap-1 overflow-x-auto rounded-2xl border border-slate-200 bg-white p-1 shadow-sm">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={clsx(
                'flex flex-1 items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium whitespace-nowrap transition',
                tab === id ? 'bg-navy-900 text-white shadow' : 'text-slate-600 hover:bg-slate-100',
              )}
            >
              <Icon size={16} /> {label}
            </button>
          ))}
        </div>
        <p className="mt-3 text-xs text-slate-500">{TABS.find((t) => t.id === tab)!.hint}</p>

        <div className="mt-4">
          {tab === 'tokens' && <TokenizerLab />}
          {tab === 'embeddings' && <EmbeddingLab />}
          {tab === 'search' && <SearchLab />}
        </div>
      </div>
    </div>
  )
}

const Card = ({ children, className }: { children: React.ReactNode; className?: string }) => (
  <div className={clsx('rounded-2xl border border-slate-200 bg-white p-5 shadow-sm', className)}>{children}</div>
)

const ErrorBox = ({ error }: { error: string | null }) =>
  error ? <div className="mt-3 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div> : null

// ------------------------------------------------------------------ Tokenizer
const TOKEN_COLORS = ['bg-sky-100', 'bg-amber-100', 'bg-emerald-100', 'bg-rose-100', 'bg-violet-100', 'bg-lime-100']

function TokenizerLab() {
  const [text, setText] = useState(
    'Студент может пересдать дисциплину (Retake) не более одного раза. Студент дисциплинаны қайта тапсыра алады. GPA is calculated per semester.',
  )
  const [model, setModel] = useState('text-embedding-3-small')
  const [res, setRes] = useState<TokenizeResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showIds, setShowIds] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => {
      api
        .tokenize(text, model)
        .then((r) => {
          setRes(r)
          setError(null)
        })
        .catch((e) => setError(e.message))
    }, 250)
    return () => clearTimeout(t)
  }, [text, model])

  return (
    <div className="grid gap-4">
      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <label className="text-sm font-semibold text-slate-700">Текст</label>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm"
          >
            <option value="text-embedding-3-small">text-embedding-3 (cl100k_base)</option>
            <option value="gpt-4o-mini">gpt-4o-mini (o200k_base)</option>
          </select>
        </div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          className="w-full resize-y rounded-xl border border-slate-200 p-3 text-[15px] outline-none focus:border-brand-400 focus:ring-4 focus:ring-brand-100"
        />
        {res && (
          <div className="mt-4 grid grid-cols-3 gap-3 text-center">
            <Metric label="Токенов" value={res.token_count} />
            <Metric label="Символов" value={res.char_count} />
            <Metric label="Символов / токен" value={res.token_count ? (res.char_count / res.token_count).toFixed(2) : '—'} />
          </div>
        )}
        <ErrorBox error={error} />
      </Card>

      {res && (
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <div className="text-sm font-semibold text-slate-700">BPE-токены · {res.encoding}</div>
            <label className="flex items-center gap-2 text-xs text-slate-500">
              <input type="checkbox" checked={showIds} onChange={(e) => setShowIds(e.target.checked)} /> показать ID
            </label>
          </div>
          <div className="font-mono text-[13px] leading-8">
            {res.tokens.map((t, i) => (
              <span
                key={i}
                title={`id ${t.id}`}
                className={clsx('rounded px-0.5 py-1 whitespace-pre-wrap text-slate-800', TOKEN_COLORS[i % TOKEN_COLORS.length])}
              >
                {showIds ? `${t.id} ` : t.text.replace(/\n/g, '↵\n')}
              </span>
            ))}
          </div>
          <p className="mt-3 text-xs text-slate-500">
            Кириллица и казахские буквы дробятся на большее число токенов, чем английский текст — это влияет на стоимость и
            на размер чанков.
          </p>
        </Card>
      )}

      {res && (
        <Card>
          <div className="mb-3 text-sm font-semibold text-slate-700">
            Лексические токены BM25 <span className="font-normal text-slate-400">(lowercase → стоп-слова → стемминг Snowball)</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {res.bm25_tokens.map((t, i) => (
              <span key={i} className="rounded-md bg-navy-900 px-2 py-0.5 font-mono text-xs text-white">
                {t}
              </span>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

const Metric = ({ label, value }: { label: string; value: number | string }) => (
  <div className="rounded-xl bg-slate-50 py-3">
    <div className="font-display text-xl font-bold text-navy-900 tabular-nums">{value}</div>
    <div className="text-xs text-slate-500">{label}</div>
  </div>
)

// ------------------------------------------------------------------ Embeddings
function EmbeddingLab() {
  const [texts, setTexts] = useState([
    'Как пересдать экзамен?',
    'Правила повторного прохождения дисциплины (Retake)',
    'How can I retake a failed course?',
    'Процедура заселения в общежитие',
  ])
  const [res, setRes] = useState<EmbedResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = () => {
    setLoading(true)
    setError(null)
    api
      .embed(texts.filter((t) => t.trim()))
      .then(setRes)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }

  return (
    <div className="grid gap-4">
      <Card>
        <div className="space-y-2">
          {texts.map((t, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-xs font-semibold text-slate-600">
                {String.fromCharCode(65 + i)}
              </span>
              <input
                value={t}
                onChange={(e) => setTexts(texts.map((x, j) => (j === i ? e.target.value : x)))}
                className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand-400 focus:ring-4 focus:ring-brand-100"
              />
              {texts.length > 2 && (
                <button onClick={() => setTexts(texts.filter((_, j) => j !== i))} className="p-1 text-slate-400 hover:text-rose-500">
                  <X size={16} />
                </button>
              )}
            </div>
          ))}
        </div>
        <div className="mt-4 flex gap-2">
          {texts.length < 8 && (
            <button
              onClick={() => setTexts([...texts, ''])}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 px-3 py-2 text-sm hover:bg-slate-50"
            >
              <Plus size={15} /> Добавить
            </button>
          )}
          <button
            onClick={run}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-md shadow-brand-600/30 hover:bg-brand-700 disabled:opacity-60"
          >
            {loading ? <Loader2 size={15} className="animate-spin" /> : <Sigma size={15} />} Построить эмбеддинги
          </button>
        </div>
        <ErrorBox error={error} />
      </Card>

      {res && (
        <Card>
          <div className="mb-4 text-sm font-semibold text-slate-700">
            Косинусное сходство <span className="font-normal text-slate-400">· {res.model} · {res.dimensions} измерений</span>
          </div>
          <div className="overflow-x-auto">
            <table className="mx-auto border-separate border-spacing-1">
              <thead>
                <tr>
                  <th />
                  {res.texts.map((_, i) => (
                    <th key={i} className="w-16 text-xs font-semibold text-slate-500">
                      {String.fromCharCode(65 + i)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {res.similarity.map((row, i) => (
                  <tr key={i}>
                    <td className="pr-2 text-xs font-semibold text-slate-500">{String.fromCharCode(65 + i)}</td>
                    {row.map((v, j) => {
                      // для text-embedding-3 типичный диапазон сходства ~0.1–1.0
                      const t = Math.max(0, Math.min(1, (v - 0.1) / 0.9))
                      return (
                        <td
                          key={j}
                          className="h-12 w-16 rounded-lg text-center font-mono text-xs"
                          style={{
                            background: `rgba(42, 85, 230, ${0.08 + t * 0.85})`,
                            color: t > 0.5 ? 'white' : '#0b1739',
                          }}
                        >
                          {v.toFixed(3)}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {res && (
        <Card>
          <div className="mb-3 text-sm font-semibold text-slate-700">Первые 24 координаты векторов</div>
          <div className="space-y-2">
            {res.preview.map((vec, i) => {
              const max = Math.max(...res.preview.flat().map(Math.abs)) || 1
              return (
                <div key={i} className="flex items-center gap-2">
                  <span className="w-5 text-xs font-semibold text-slate-500">{String.fromCharCode(65 + i)}</span>
                  <div className="flex h-8 flex-1 items-center gap-px">
                    {vec.map((x, j) => (
                      <div key={j} className="flex h-full flex-1 flex-col justify-center" title={x.toString()}>
                        <div
                          className={clsx('w-full rounded-sm', x >= 0 ? 'bg-brand-500' : 'bg-amber-400')}
                          style={{ height: `${(Math.abs(x) / max) * 100}%`, alignSelf: 'center' }}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ Search
function SearchLab() {
  const [query, setQuery] = useState('Как пересдать экзамен?')
  const [rerank, setRerank] = useState(false)
  const [res, setRes] = useState<SearchResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!query.trim()) return
    setLoading(true)
    setError(null)
    api
      .search(query, 15, rerank)
      .then(setRes)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  return (
    <div className="grid gap-4">
      <Card>
        <form onSubmit={run} className="flex flex-wrap gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="min-w-60 flex-1 rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand-400 focus:ring-4 focus:ring-brand-100"
          />
          <label className="flex items-center gap-2 rounded-xl border border-slate-200 px-3 text-sm text-slate-600">
            <input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} /> LLM-реранкинг
          </label>
          <button
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-md shadow-brand-600/30 hover:bg-brand-700 disabled:opacity-60"
          >
            {loading ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />} Искать
          </button>
        </form>
        {res && res.expanded_query !== res.query && (
          <p className="mt-3 text-xs text-slate-500">
            Расширенный запрос: <span className="font-mono text-slate-700">{res.expanded_query}</span>
          </p>
        )}
        <ErrorBox error={error} />
      </Card>

      {res && (
        <Card className="p-0!">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs text-slate-500 uppercase">
                <tr>
                  <th className="px-4 py-2.5 font-medium">#</th>
                  <th className="px-3 py-2.5 font-medium">Фрагмент</th>
                  <th className="px-3 py-2.5 text-right font-medium">Dense</th>
                  <th className="px-3 py-2.5 text-right font-medium">BM25</th>
                  <th className="px-3 py-2.5 text-right font-medium">RRF</th>
                  {rerank && <th className="px-3 py-2.5 text-right font-medium">Rerank</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {res.results.map((r) => (
                  <tr key={r.id} className="align-top hover:bg-slate-50/60">
                    <td className="px-4 py-3 font-semibold text-slate-400">{r.n}</td>
                    <td className="max-w-lg px-3 py-3">
                      <div className="font-medium text-slate-800">
                        {r.title}
                        <span className="ml-2 text-xs font-normal text-slate-400">
                          {[r.section, pagesLabel(r)].filter(Boolean).join(' · ')}
                        </span>
                      </div>
                      <div className="mt-1 line-clamp-3 text-xs leading-relaxed text-slate-500">{r.text}</div>
                    </td>
                    <RankCell rank={r.dense_rank} score={r.dense_score} />
                    <RankCell rank={r.bm25_rank} score={r.bm25_score} />
                    <td className="px-3 py-3 text-right font-mono text-xs text-slate-700">{r.rrf_score?.toFixed(4)}</td>
                    {rerank && (
                      <td className="px-3 py-3 text-right">
                        <span className="rounded-md bg-navy-900 px-1.5 py-0.5 font-mono text-xs text-white">{r.rerank_score ?? '—'}</span>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {res.results.length === 0 && <p className="py-8 text-center text-sm text-slate-500">Ничего не найдено</p>}
        </Card>
      )}
    </div>
  )
}

function RankCell({ rank, score }: { rank?: number | null; score?: number | null }) {
  return (
    <td className="px-3 py-3 text-right whitespace-nowrap">
      {rank ? (
        <>
          <div className="font-semibold text-slate-700">#{rank}</div>
          <div className="font-mono text-[11px] text-slate-400">{score?.toFixed(3)}</div>
        </>
      ) : (
        <span className="text-slate-300">—</span>
      )}
    </td>
  )
}
