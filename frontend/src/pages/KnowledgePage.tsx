import { useCallback, useEffect, useRef, useState } from 'react'
import { CheckCircle2, Database, ExternalLink, FileText, Layers, Loader2, RefreshCw, Trash2, UploadCloud, XCircle } from 'lucide-react'
import clsx from 'clsx'
import { api, type DocumentInfo, type Health } from '../api'

const ACCEPT = '.pdf,.docx,.md,.txt,.html,.htm,.xlsx,.csv'

export default function KnowledgePage({ onChange, health }: { onChange: () => void; health: Health | null }) {
  const [docs, setDocs] = useState<DocumentInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [drag, setDrag] = useState(false)
  const [log, setLog] = useState<{ ok: boolean; text: string }[]>([])
  const inputRef = useRef<HTMLInputElement>(null)

  const load = useCallback(() => {
    api
      .documents()
      .then(setDocs)
      .catch((e) => setLog((l) => [{ ok: false, text: e.message }, ...l]))
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  const run = async (label: string, fn: () => Promise<{ ok: boolean; text: string }[]>) => {
    setBusy(label)
    try {
      const entries = await fn()
      setLog((l) => [...entries, ...l].slice(0, 30))
    } catch (e) {
      setLog((l) => [{ ok: false, text: (e as Error).message }, ...l])
    } finally {
      setBusy(null)
      load()
      onChange()
    }
  }

  const upload = (files: File[]) =>
    files.length &&
    run('upload', async () => {
      const r = await api.upload(files)
      return [
        ...r.indexed.map((d) => ({ ok: true, text: `${d.file_name}: ${d.status === 'pending' ? 'подготовлен, ожидает индексации' : 'проиндексирован'}, ${d.chunks} фрагментов` })),
        ...r.errors.map((e) => ({ ok: false, text: `${e.file_name}: ${e.error}` })),
      ]
    })

  const sync = (reset: boolean) =>
    run(reset ? 'reset' : 'sync', async () => {
      const r = await api.sync(reset)
      return [
        ...r.indexed.map((d) => ({ ok: true, text: `${d.file_name}: ${d.status === 'pending' ? 'подготовлен' : 'проиндексирован'} (${d.chunks} фрагментов)` })),
        ...r.removed.map((f) => ({ ok: true, text: `Удалён из базы ${f}` })),
        ...r.errors.map((e) => ({ ok: false, text: `${e.file_name}: ${e.error}` })),
        { ok: true, text: `Синхронизация: +${r.indexed.length}, без изменений ${r.skipped.length}, удалено ${r.removed.length}` },
      ]
    })

  const remove = (d: DocumentInfo) =>
    confirm(`Убрать «${d.title}» из поиска? Оригинал и история останутся в архиве.`) &&
    run('delete', async () => {
      await api.deleteDocument(d.doc_id)
      return [{ ok: true, text: `Отправлен в архив ${d.file_name}` }]
    })

  const verify = (d: DocumentInfo) =>
    confirm(`Вы проверили, что «${d.title}» — официальный документ КБТУ? После индексации он сможет использоваться в ответах.`) &&
    run('trust', async () => {
      await api.setTrust(d.doc_id, 'official', 'Оператор подтвердил официальный источник в интерфейсе')
      return [{ ok: true, text: `Подтверждён источник: ${d.title}` }]
    })

  const revoke = (d: DocumentInfo) => run('trust', async () => {
    await api.setTrust(d.doc_id, 'unverified', 'Оператор отправил источник на повторную проверку')
    return [{ ok: true, text: `Документ отправлен на проверку: ${d.title}` }]
  })

  return (
    <div className="scrollbar-thin flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-display text-2xl font-bold text-navy-900">База знаний</h1>
            <p className="mt-1 text-sm text-slate-500">
              Загрузите документы и подтвердите их происхождение. В ответах используются только действующие официальные источники.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => sync(false)}
              disabled={!!busy}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium shadow-sm transition hover:border-slate-300 disabled:opacity-50"
            >
              <RefreshCw size={15} className={clsx(busy === 'sync' && 'animate-spin')} /> Обновить базу
            </button>
            <button
              onClick={() => confirm('Пересчитать embeddings всех сохранённых документов через OpenAI? Это использует API.') && sync(true)}
              disabled={!!busy}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-600 shadow-sm transition hover:border-rose-200 hover:text-rose-600 disabled:opacity-50"
            >
              {busy === 'reset' ? <Loader2 size={15} className="animate-spin" /> : <Database size={15} />} Переиндексировать
            </button>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat icon={FileText} label="Документы" value={health?.documents} />
          <Stat icon={Layers} label="Чанки (векторы)" value={health?.chunks} />
          <Stat icon={Database} label="Токены" value={health?.tokens} />
          <Stat icon={RefreshCw} label="Реранкер" value={health?.reranker === 'llm' ? 'LLM' : 'выкл.'} />
        </div>

        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDrag(true)
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDrag(false)
            upload(Array.from(e.dataTransfer.files))
          }}
          onClick={() => !busy && inputRef.current?.click()}
          className={clsx(
            'mt-6 flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition',
            drag ? 'border-brand-500 bg-brand-50' : 'border-slate-300 bg-white/60 hover:border-brand-400 hover:bg-white',
          )}
        >
          {busy === 'upload' ? (
            <Loader2 size={36} className="animate-spin text-brand-500" />
          ) : (
            <UploadCloud size={36} className="text-brand-500" />
          )}
          <div className="mt-3 font-semibold text-slate-800">
            {busy === 'upload' ? 'Индексирую документы…' : 'Перетащите файлы или нажмите для выбора'}
          </div>
          <div className="mt-1 text-xs text-slate-500">PDF, DOCX, Markdown, TXT, HTML, XLSX, CSV</div>
          <div className="mt-2 text-xs text-slate-500">
            {health?.openai_key ? 'После загрузки подтвердите официальный источник в списке ниже.' : 'Без API-ключа файлы будут подготовлены. После настройки ключа нажмите «Обновить базу».'}
          </div>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => {
              upload(Array.from(e.target.files ?? []))
              e.target.value = ''
            }}
          />
        </div>

        {log.length > 0 && (
          <div className="mt-4 space-y-1 rounded-xl border border-slate-200 bg-white p-3 text-sm">
            {log.slice(0, 8).map((l, i) => (
              <div key={i} className="flex items-start gap-2">
                {l.ok ? (
                  <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-emerald-500" />
                ) : (
                  <XCircle size={15} className="mt-0.5 shrink-0 text-rose-500" />
                )}
                <span className={l.ok ? 'text-slate-600' : 'text-rose-600'}>{l.text}</span>
              </div>
            ))}
          </div>
        )}

        <div className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 px-5 py-3 text-sm font-semibold text-slate-700">
            Документы и состояние обработки
          </div>
          {loading ? (
            <div className="flex justify-center py-10">
              <Loader2 className="animate-spin text-slate-400" />
            </div>
          ) : docs.length === 0 ? (
            <div className="px-5 py-10 text-center text-sm text-slate-500">
              Пока пусто. Загрузите файлы выше или добавьте их в <code className="rounded bg-slate-100 px-1">data/inbox/manual</code> и
              нажмите «Обновить базу».
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs text-slate-500 uppercase">
                  <tr>
                    <th className="px-5 py-2.5 font-medium">Документ</th>
                    <th className="px-3 py-2.5 font-medium">Статус</th>
                    <th className="px-3 py-2.5 text-right font-medium">Стр.</th>
                    <th className="px-3 py-2.5 text-right font-medium">Чанки</th>
                    <th className="px-3 py-2.5 text-right font-medium">Токены</th>
                    <th className="px-3 py-2.5" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {docs.map((d) => (
                    <tr key={d.doc_id} className="hover:bg-slate-50/60">
                      <td className="px-5 py-3">
                        <div className="font-medium text-slate-800">{d.title}</div>
                        <div className="text-xs text-slate-400">
                          {d.file_name}
                          {d.academic_year && ` · ${d.academic_year}`}
                          {d.target_audience && ` · ${d.target_audience}`}
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        <div className="text-xs text-slate-600">{{ pending: 'Ожидает индексации', processing: 'Индексируется', processed: 'Проиндексирован', needs_ocr: 'Нужно распознавание', failed: 'Ошибка' }[d.status]}</div>
                        <div className={clsx('mt-1 text-xs', d.trust_level === 'official' ? 'text-emerald-700' : 'text-amber-700')}>
                          {d.trust_level === 'official' ? (d.is_current ? 'Официальный · действующий' : 'Официальный') : 'Источник не подтверждён'}
                        </div>
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums text-slate-600">{d.pages ?? '—'}</td>
                      <td className="px-3 py-3 text-right tabular-nums text-slate-600">{d.chunks}</td>
                      <td className="px-3 py-3 text-right tabular-nums text-slate-600">{d.tokens.toLocaleString('ru')}</td>
                      <td className="px-3 py-3">
                        <div className="flex justify-end gap-1">
                          <button
                            onClick={() => d.trust_level === 'official' ? revoke(d) : verify(d)}
                            disabled={!!busy}
                            className="rounded-lg px-2 py-1 text-xs text-brand-700 hover:bg-brand-50 disabled:opacity-50"
                          >
                            {d.trust_level === 'official' ? 'На проверку' : 'Подтвердить'}
                          </button>
                          <a
                            href={api.fileUrl(d.doc_id)}
                            target="_blank"
                            rel="noreferrer"
                            className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-brand-600"
                            title="Открыть"
                          >
                            <ExternalLink size={15} />
                          </a>
                          <button
                            onClick={() => remove(d)}
                            disabled={!!busy}
                            className="rounded-lg p-1.5 text-slate-400 transition hover:bg-rose-50 hover:text-rose-600"
                            title="Убрать в архив"
                          >
                            <Trash2 size={15} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Stat({ icon: Icon, label, value }: { icon: typeof FileText; label: string; value: number | string | undefined }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <Icon size={14} /> {label}
      </div>
      <div className="mt-1.5 font-display text-2xl font-bold text-navy-900 tabular-nums">
        {typeof value === 'number' ? value.toLocaleString('ru') : (value ?? '—')}
      </div>
    </div>
  )
}
