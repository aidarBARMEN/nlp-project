import { useState } from 'react'
import { ChevronDown, ExternalLink, FileText } from 'lucide-react'
import clsx from 'clsx'
import { api, type Source } from '../api'

export function pagesLabel(s: Pick<Source, 'page_start' | 'page_end'>) {
  if (!s.page_start) return null
  return s.page_start === s.page_end || !s.page_end ? `стр. ${s.page_start}` : `стр. ${s.page_start}–${s.page_end}`
}

export default function SourceCard({ source, highlighted }: { source: Source; highlighted?: boolean }) {
  const [open, setOpen] = useState(false)
  const pages = pagesLabel(source)

  return (
    <div
      id={`src-${source.id}`}
      className={clsx(
        'rounded-xl border bg-white transition',
        highlighted ? 'border-brand-400 ring-4 ring-brand-100' : 'border-slate-200 hover:border-slate-300',
      )}
    >
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-start gap-3 p-3 text-left">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-navy-900 text-xs font-semibold text-white">
          {source.n}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-sm font-medium text-slate-800">
            <FileText size={14} className="shrink-0 text-slate-400" />
            <span className="truncate">{source.title}</span>
          </div>
          <div className="mt-0.5 truncate text-xs text-slate-500">
            {[source.section, pages].filter(Boolean).join(' · ') || source.file_name}
          </div>
        </div>
        <ChevronDown size={16} className={clsx('mt-1 shrink-0 text-slate-400 transition', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="animate-fade-in border-t border-slate-100 px-3 pt-2 pb-3">
          <p className="scrollbar-thin max-h-60 overflow-y-auto text-[13px] leading-relaxed whitespace-pre-wrap text-slate-600">
            {source.text}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <Score label="Dense #" value={source.dense_rank} />
            <Score label="BM25 #" value={source.bm25_rank} />
            <Score label="RRF" value={source.rrf_score?.toFixed(4)} />
            <Score label="Rerank" value={source.rerank_score} />
            <a
              href={source.url || api.fileUrl(source.doc_id, source.page_start)}
              target="_blank"
              rel="noreferrer"
              className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700"
            >
              Открыть документ <ExternalLink size={12} />
            </a>
          </div>
        </div>
      )}
    </div>
  )
}

function Score({ label, value }: { label: string; value: number | string | null | undefined }) {
  if (value === null || value === undefined) return null
  return (
    <span className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">
      {label} {value}
    </span>
  )
}
