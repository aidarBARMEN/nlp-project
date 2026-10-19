import { useCallback, useEffect, useMemo, useState } from 'react'
import { BarChart3, CheckCircle2, Database, Loader2, MessageSquareText, Play, Search, XCircle } from 'lucide-react'
import clsx from 'clsx'
import {
  api,
  type EvalKind,
  type EvalResults,
  type EvalStatus,
  type GenerationSummary,
  type ModelInfo,
  type RetrievalMethod,
} from '../api'

// ------------------------------------------------------------------ описания метрик
type Col<T> = {
  key: keyof T & string
  label: string
  hint: string
  /** максимум шкалы для полосы; null — без полосы */
  scale: number | null
  better: 'higher' | 'lower'
  fmt?: (v: number) => string
}

const pct = (v: number) => `${(v * 100).toFixed(0)}%`

const RETRIEVAL_COLS: Col<RetrievalMethod>[] = [
  { key: 'hit@1', label: 'Hit@1', hint: 'Эталонный фрагмент найден первым', scale: 1, better: 'higher', fmt: pct },
  { key: 'hit@5', label: 'Hit@5', hint: 'Эталонный фрагмент в топ-5 (столько попадает в промпт)', scale: 1, better: 'higher', fmt: pct },
  { key: 'hit@10', label: 'Hit@10', hint: 'Эталонный фрагмент в топ-10', scale: 1, better: 'higher', fmt: pct },
  { key: 'mrr@10', label: 'MRR@10', hint: 'Mean Reciprocal Rank: среднее 1/позиция эталона', scale: 1, better: 'higher', fmt: (v) => v.toFixed(3) },
  { key: 'ndcg@10', label: 'nDCG@10', hint: 'Normalized DCG: штраф за низкую позицию (1/log2(rank+1))', scale: 1, better: 'higher', fmt: (v) => v.toFixed(3) },
  { key: 'doc_hit@5', label: 'Doc@5', hint: 'Нужный документ среди первых 5 документов', scale: 1, better: 'higher', fmt: pct },
  { key: 'query_ms_mean', label: 'Запрос, мс', hint: 'Среднее время эмбеддинга одного запроса', scale: null, better: 'lower', fmt: (v) => v.toFixed(0) },
]

const GENERATION_COLS: Col<GenerationSummary>[] = [
  { key: 'faithfulness', label: 'Faithfulness', hint: 'Доля утверждений, подтверждённых контекстом (нет галлюцинаций)', scale: 1, better: 'higher', fmt: pct },
  { key: 'relevance', label: 'Relevance', hint: 'Ответ по существу вопроса, 1–5', scale: 5, better: 'higher', fmt: (v) => v.toFixed(2) },
  { key: 'correctness', label: 'Correctness', hint: 'Совпадение с эталонным ответом, 1–5', scale: 5, better: 'higher', fmt: (v) => v.toFixed(2) },
  { key: 'refusal_accuracy', label: 'Отказ, где нужно', hint: 'Доля вопросов вне базы, на которые модель честно отказала', scale: 1, better: 'higher', fmt: pct },
  { key: 'false_refusal_rate', label: 'Ложный отказ', hint: 'Доля вопросов с ответом в базе, на которые модель отказала (меньше — лучше)', scale: 1, better: 'lower', fmt: pct },
  { key: 'citation_rate', label: 'Цитаты', hint: 'Доля ответов со ссылками [n] на источники', scale: 1, better: 'higher', fmt: pct },
  { key: 'language_ok', label: 'Язык', hint: 'Доля ответов на русском (вопросы на русском)', scale: 1, better: 'higher', fmt: pct },
  { key: 'latency_s', label: 'Время, с', hint: 'Среднее полное время генерации ответа', scale: null, better: 'lower', fmt: (v) => v.toFixed(1) },
  { key: 'tokens_per_s', label: 'Ток/с', hint: 'Скорость генерации', scale: null, better: 'higher', fmt: (v) => v.toFixed(0) },
]

const PROVIDER: Record<string, string> = {
  openai: 'OpenAI · облако',
  groq: 'Groq · открытая модель',
  ollama: 'Ollama · локально',
  local: 'локально',
}

const FAMILY: Record<string, { label: string; cls: string }> = {
  lexical: { label: 'лексический', cls: 'bg-slate-100 text-slate-600' },
  dense: { label: 'векторный', cls: 'bg-brand-50 text-brand-700' },
  hybrid: { label: 'гибридный', cls: 'bg-navy-900 text-white' },
}

export default function MetricsPage() {
  const [results, setResults] = useState<EvalResults | null>(null)
  const [status, setStatus] = useState<EvalStatus | null>(null)
  const [models, setModels] = useState<{ llms: ModelInfo[]; embedders: ModelInfo[] } | null>(null)
  const [selectedLlms, setSelectedLlms] = useState<string[]>([])
  const [genLimit, setGenLimit] = useState(15)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api.evalResults().then(setResults).catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    load()
    api.evalStatus().then(setStatus).catch(() => undefined)
    api
      .models()
      .then((m) => {
        setModels(m)
        setSelectedLlms(m.llms.filter((x) => x.available).map((x) => x.id))
      })
      .catch(() => undefined)
  }, [load])

  // пока идёт оценка — опрашиваем статус; по окончании перечитываем результаты
  useEffect(() => {
    if (!status?.running) return
    const t = setInterval(() => {
      api.evalStatus().then((s) => {
        setStatus(s)
        if (!s.running) load()
      })
    }, 1500)
    return () => clearInterval(t)
  }, [status?.running, load])

  const run = (kind: EvalKind, modelIds: string[] = [], limit?: number) => {
    setError(null)
    api
      .evalRun(kind, modelIds, limit)
      .then(setStatus)
      .catch((e) => setError(e.message))
  }

  const running = !!status?.running
  const hasDataset = !!results?.dataset

  return (
    <div className="scrollbar-thin flex-1 overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 py-8">
        <h1 className="font-display text-2xl font-bold text-navy-900">Метрики моделей</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Сравнение OpenAI с открытыми моделями на документах КБТУ: эмбеддинги — по качеству поиска, LLM — по качеству
          ответов. Датасет вопросов генерируется из базы знаний, эталонный фрагмент для каждого вопроса известен.
        </p>

        {models && <ModelsOverview llms={models.llms} embedders={models.embedders} />}

        {/* ---------------------------------------------------- шаги */}
        <div className="mt-6 grid gap-3 md:grid-cols-3">
          <Step
            n={1}
            icon={Database}
            title="Датасет вопросов"
            done={hasDataset}
            text={
              hasDataset
                ? `${results!.dataset!.answerable} вопросов по базе + ${results!.dataset!.unanswerable} вне базы`
                : 'GPT формулирует вопросы студентов к случайным фрагментам документов'
            }
            action={hasDataset ? 'Пересоздать' : 'Создать датасет'}
            disabled={running}
            onRun={() => run('dataset', [], 40)}
          />
          <Step
            n={2}
            icon={Search}
            title="Оценка поиска"
            done={!!results?.retrieval}
            text="Эмбеддинг-модели, BM25 и гибрид (RRF): Hit@k, MRR, nDCG, скорость"
            action="Оценить поиск"
            disabled={running || !hasDataset}
            onRun={() => run('retrieval')}
          />
          <Step
            n={3}
            icon={MessageSquareText}
            title="Оценка генерации"
            done={!!results?.generation}
            text="LLM отвечают по одному и тому же контексту, судья оценивает ответы"
            action="Оценить генерацию"
            disabled={running || !hasDataset || !selectedLlms.length}
            onRun={() => run('generation', selectedLlms, genLimit)}
          >
            {models && (
              <div className="mt-3 space-y-1.5 border-t border-slate-100 pt-3">
                {models.llms.map((m) => (
                  <label key={m.id} className={clsx('flex items-center gap-2 text-xs', !m.available && 'text-slate-400')}>
                    <input
                      type="checkbox"
                      disabled={!m.available || running}
                      checked={selectedLlms.includes(m.id)}
                      onChange={(e) =>
                        setSelectedLlms((cur) => (e.target.checked ? [...cur, m.id] : cur.filter((x) => x !== m.id)))
                      }
                    />
                    {m.label}
                    {m.note && <span className="text-slate-400">({m.note})</span>}
                  </label>
                ))}
                <label className="flex items-center gap-2 pt-1 text-xs text-slate-600">
                  Вопросов:
                  <input
                    type="number"
                    min={3}
                    max={200}
                    value={genLimit}
                    onChange={(e) => setGenLimit(Math.max(3, Number(e.target.value) || 3))}
                    className="w-16 rounded-md border border-slate-200 px-2 py-0.5"
                  />
                </label>
              </div>
            )}
          </Step>
        </div>

        {status && (status.running || status.error) && <Progress status={status} />}
        {error && <div className="mt-4 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}

        {results?.retrieval && (
          <Section
            title="Поиск: эмбеддинг-модели"
            meta={`${results.retrieval.questions} вопросов · корпус ${results.retrieval.corpus_chunks} фрагментов · ${fmtDate(results.retrieval.created_at)}`}
          >
            <MetricTable
              rows={results.retrieval.methods}
              cols={RETRIEVAL_COLS}
              rowKey={(r) => r.method}
              renderName={(r) => (
                <div>
                  <div className="font-medium text-slate-800">{r.method}</div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-400">
                    <span className={clsx('rounded px-1.5 py-px font-medium', FAMILY[r.family]?.cls)}>{FAMILY[r.family]?.label}</span>
                    {r.dimensions && <span>{r.dimensions} dim</span>}
                    {r.max_seq_length && <span>· до {r.max_seq_length} ток.</span>}
                  </div>
                </div>
              )}
            />
            <p className="mt-3 text-xs text-slate-500">
              Метрики считаются по эталонному фрагменту, из которого сгенерирован вопрос. Модели с коротким окном
              (max_seq_length) видят только начало фрагмента — это заметно снижает их качество на длинных регламентах.
            </p>
          </Section>
        )}

        {results?.generation && (
          <Section
            title="Генерация: LLM"
            meta={`${results.generation.questions} вопросов (${results.generation.answerable} с ответом в базе) · судья ${results.generation.judge} · ${fmtDate(results.generation.created_at)}`}
          >
            <MetricTable
              rows={results.generation.models}
              cols={GENERATION_COLS}
              rowKey={(r) => r.model}
              renderName={(r) => (
                <div>
                  <div className="font-medium text-slate-800">{r.label}</div>
                  <div className="mt-0.5 text-[11px] text-slate-400">
                    {PROVIDER[r.provider] ?? r.provider}
                    {r.errors > 0 && <span className="text-rose-500"> · ошибок: {r.errors}</span>}
                  </div>
                </div>
              )}
            />
            <p className="mt-3 text-xs text-slate-500">
              Все модели получают одинаковый контекст (поиск фиксирован), поэтому разница — только в генерации.
              Faithfulness, Relevance и Correctness выставляет LLM-судья; судья из семейства OpenAI может слегка завышать
              оценки своей же модели.
            </p>
            <AnswersBrowser results={results.generation} />
          </Section>
        )}

        {!results?.retrieval && !results?.generation && !running && (
          <div className="mt-8 flex flex-col items-center rounded-2xl border border-dashed border-slate-300 bg-white/60 py-12 text-center">
            <BarChart3 size={32} className="text-slate-300" />
            <p className="mt-3 max-w-md text-sm text-slate-500">
              Результатов пока нет. Создайте датасет, затем запустите оценку поиска и генерации.
            </p>
          </div>
        )}

        <Glossary />
      </div>
    </div>
  )
}

const fmtDate = (iso: string) => new Date(iso).toLocaleString('ru', { dateStyle: 'short', timeStyle: 'short' })

// ------------------------------------------------------------------ компоненты
function ModelsOverview({ llms, embedders }: { llms: ModelInfo[]; embedders: ModelInfo[] }) {
  const group = (title: string, items: ModelInfo[]) => (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">{title}</div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((m) => (
          <span
            key={m.id}
            title={m.note ?? 'доступна'}
            className={clsx(
              'inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-xs',
              m.available ? 'border-slate-200 text-slate-700' : 'border-dashed border-slate-300 text-slate-400',
            )}
          >
            {m.available ? (
              <CheckCircle2 size={12} className="text-emerald-500" />
            ) : (
              <XCircle size={12} className="text-slate-300" />
            )}
            {m.label}
            <span className="text-slate-400">· {PROVIDER[m.provider] ?? m.provider}</span>
          </span>
        ))}
      </div>
    </div>
  )
  return (
    <div className="mt-6 grid gap-3 md:grid-cols-2">
      {group('LLM для ответов', llms)}
      {group('Эмбеддинг-модели', embedders)}
    </div>
  )
}

function Step(props: {
  n: number
  icon: typeof Database
  title: string
  text: string
  action: string
  done: boolean
  disabled: boolean
  onRun: () => void
  children?: React.ReactNode
}) {
  const Icon = props.icon
  return (
    <div className="flex flex-col rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
          <Icon size={15} />
        </span>
        <span className="text-sm font-semibold text-slate-800">
          {props.n}. {props.title}
        </span>
        {props.done && <CheckCircle2 size={15} className="ml-auto text-emerald-500" />}
      </div>
      <p className="mt-2 text-xs leading-relaxed text-slate-500">{props.text}</p>
      {props.children}
      <button
        onClick={props.onRun}
        disabled={props.disabled}
        className="mt-auto inline-flex items-center justify-center gap-1.5 rounded-xl bg-brand-600 px-3 py-2 text-sm font-medium text-white shadow-md shadow-brand-600/30 transition hover:bg-brand-700 disabled:bg-slate-200 disabled:text-slate-400 disabled:shadow-none [&:not(:first-child)]:mt-4"
      >
        <Play size={13} /> {props.action}
      </button>
    </div>
  )
}

function Progress({ status }: { status: EvalStatus }) {
  const ratio = status.total ? Math.min(1, (status.done ?? 0) / status.total) : null
  return (
    <div
      className={clsx(
        'mt-4 rounded-2xl border p-4',
        status.error ? 'border-rose-200 bg-rose-50' : 'border-brand-200 bg-brand-50/60',
      )}
    >
      <div className="flex items-center gap-2 text-sm">
        {status.running ? <Loader2 size={15} className="animate-spin text-brand-600" /> : <XCircle size={15} className="text-rose-500" />}
        <span className="font-medium text-slate-800">{status.error ? 'Ошибка оценки' : status.stage}</span>
        {status.running && ratio !== null && (
          <span className="ml-auto font-mono text-xs text-slate-500">
            {status.done}/{status.total}
          </span>
        )}
      </div>
      {status.error && <p className="mt-1 text-sm text-rose-700">{status.error}</p>}
      {status.running && (
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white">
          <div
            className={clsx('h-full rounded-full bg-brand-500 transition-all', ratio === null && 'w-1/3 animate-pulse')}
            style={ratio !== null ? { width: `${Math.max(2, ratio * 100)}%` } : undefined}
          />
        </div>
      )}
    </div>
  )
}

function Section({ title, meta, children }: { title: string; meta: string; children: React.ReactNode }) {
  return (
    <section className="mt-8">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-display text-lg font-bold text-navy-900">{title}</h2>
        <span className="text-xs text-slate-400">{meta}</span>
      </div>
      <div className="mt-3">{children}</div>
    </section>
  )
}

function MetricTable<T extends object>({
  rows,
  cols,
  rowKey,
  renderName,
}: {
  rows: T[]
  cols: Col<T>[]
  rowKey: (r: T) => string
  renderName: (r: T) => React.ReactNode
}) {
  // лучшее значение по каждой метрике с учётом направления
  const best = useMemo(() => {
    const out: Record<string, number> = {}
    for (const c of cols) {
      const vals = rows.map((r) => (r as Record<string, unknown>)[c.key]).filter((v): v is number => typeof v === 'number')
      if (vals.length > 1) out[c.key] = c.better === 'higher' ? Math.max(...vals) : Math.min(...vals)
    }
    return out
  }, [rows, cols])

  return (
    <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-[11px] text-slate-500 uppercase">
          <tr>
            <th className="sticky left-0 bg-slate-50 px-4 py-2.5 font-medium">Модель</th>
            {cols.map((c) => (
              <th key={c.key} title={c.hint} className="cursor-help px-3 py-2.5 text-right font-medium whitespace-nowrap">
                {c.label}
                {c.better === 'lower' && <span className="ml-0.5 normal-case">↓</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r) => (
            <tr key={rowKey(r)} className="hover:bg-slate-50/60">
              <td className="sticky left-0 bg-white px-4 py-3">{renderName(r)}</td>
              {cols.map((c) => {
                const v = (r as Record<string, unknown>)[c.key]
                if (typeof v !== 'number') {
                  return (
                    <td key={c.key} className="px-3 py-3 text-right text-slate-300">
                      —
                    </td>
                  )
                }
                const isBest = best[c.key] === v
                const text = c.fmt ? c.fmt(v) : String(v)
                return (
                  <td key={c.key} className="px-3 py-3 text-right" title={`${c.label}: ${text} — ${c.hint}`}>
                    <div className={clsx('tabular-nums', isBest ? 'font-semibold text-navy-900' : 'text-slate-600')}>
                      {text}
                      {isBest && <span className="ml-1 text-[10px] text-emerald-600">★</span>}
                    </div>
                    {c.scale !== null && (
                      <div className="mt-1 ml-auto h-1 w-16 overflow-hidden rounded-full bg-slate-100">
                        <div
                          className={clsx('h-full rounded-full', isBest ? 'bg-brand-600' : 'bg-brand-400/70')}
                          style={{ width: `${Math.max(2, Math.min(100, (v / c.scale) * 100))}%` }}
                        />
                      </div>
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AnswersBrowser({ results }: { results: NonNullable<EvalResults['generation']> }) {
  const questions = useMemo(() => {
    const seen = new Map<string, { id: string; question: string; reference: string }>()
    for (const a of results.answers) if (!seen.has(a.id)) seen.set(a.id, { id: a.id, question: a.question, reference: a.reference })
    return [...seen.values()]
  }, [results])
  const [qid, setQid] = useState(questions[0]?.id)
  const q = questions.find((x) => x.id === qid)
  const labels = Object.fromEntries(results.models.map((m) => [m.model, m.label]))

  if (!q) return null
  return (
    <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-slate-700">Ответы моделей</span>
        <select
          value={qid}
          onChange={(e) => setQid(e.target.value)}
          className="max-w-full min-w-0 flex-1 rounded-lg border border-slate-200 px-2 py-1 text-sm"
        >
          {questions.map((x) => (
            <option key={x.id} value={x.id}>
              {x.id} · {x.question}
            </option>
          ))}
        </select>
      </div>
      <div className="mt-3 rounded-xl bg-slate-50 p-3 text-xs text-slate-600">
        <span className="font-semibold text-slate-700">Эталон: </span>
        {q.reference}
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        {results.answers
          .filter((a) => a.id === qid)
          .map((a) => (
            <div key={a.model} className="rounded-xl border border-slate-200 p-3">
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className="font-semibold text-slate-800">{labels[a.model] ?? a.model}</span>
                {a.faithfulness !== undefined && <Chip>faith {pct(a.faithfulness)}</Chip>}
                {a.correctness !== undefined && <Chip>correct {a.correctness}/5</Chip>}
                {a.refused && <Chip>отказ</Chip>}
                {a.latency_s !== undefined && <span className="ml-auto text-slate-400">{a.latency_s} с</span>}
              </div>
              <p className="mt-2 max-h-56 overflow-y-auto text-[13px] leading-relaxed whitespace-pre-wrap text-slate-700">
                {a.error ? <span className="text-rose-600">{a.error}</span> : a.answer}
              </p>
              {a.judge_comment && <p className="mt-2 text-[11px] text-slate-400 italic">Судья: {a.judge_comment}</p>}
            </div>
          ))}
      </div>
    </div>
  )
}

const Chip = ({ children }: { children: React.ReactNode }) => (
  <span className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600">{children}</span>
)

function Glossary() {
  return (
    <details className="mt-8 rounded-2xl border border-slate-200 bg-white p-4 text-sm text-slate-600 shadow-sm">
      <summary className="cursor-pointer font-semibold text-slate-700">Как считаются метрики</summary>
      <div className="mt-3 grid gap-4 md:grid-cols-2">
        <div>
          <div className="mb-1 font-semibold text-slate-700">Поиск</div>
          <ul className="list-disc space-y-1 pl-5 text-xs">
            {RETRIEVAL_COLS.map((c) => (
              <li key={c.key}>
                <b>{c.label}</b> — {c.hint}
              </li>
            ))}
            <li>
              <b>Гибрид</b> — объединение векторного поиска и BM25 через Reciprocal Rank Fusion (k=60).
            </li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold text-slate-700">Генерация</div>
          <ul className="list-disc space-y-1 pl-5 text-xs">
            {GENERATION_COLS.map((c) => (
              <li key={c.key}>
                <b>{c.label}</b> — {c.hint}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </details>
  )
}
