import { useEffect, useState } from 'react'
import { BookOpenCheck, FileCheck2, FileText, Loader2, NotebookPen, RotateCcw, Upload, X } from 'lucide-react'
import clsx from 'clsx'
import { practice, type CheckResult, type Requirements } from '../practice'
import { DocumentCheckCard, FindingRow } from '../components/CheckResults'

export default function PracticeCheckPage() {
  const [report, setReport] = useState<File | null>(null)
  const [diary, setDiary] = useState<File | null>(null)
  const [result, setResult] = useState<CheckResult | null>(null)
  const [reqs, setReqs] = useState<Requirements | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    practice.requirements().then(setReqs).catch(() => undefined)
  }, [])

  const run = async () => {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      setResult(await practice.check(report, diary))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const reset = () => {
    setReport(null)
    setDiary(null)
    setResult(null)
    setError(null)
  }

  return (
    <div className="scrollbar-thin flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="text-xs font-semibold tracking-wider text-brand-600 uppercase">Для студентов</div>
        <h1 className="mt-1 font-display text-2xl font-bold text-navy-900">Проверка документов практики</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-500">
          Загрузите отчёт и дневник практики в формате Word — система проверит оформление по требованиям деканата
          и покажет, что исправить. Если ошибок нет, документы можно сдавать без очереди на проверку.
        </p>

        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <DropZone
            icon={FileText}
            title="Отчёт по практике"
            hint="Industrial Practice Report, .docx"
            file={report}
            onFile={setReport}
          />
          <DropZone
            icon={NotebookPen}
            title="Дневник практики"
            hint="Бланк дневника, .docx"
            file={diary}
            onFile={setDiary}
          />
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            onClick={run}
            disabled={busy || (!report && !diary)}
            className="inline-flex items-center gap-2 rounded-xl bg-navy-900 px-5 py-3 text-sm font-semibold text-white shadow-md shadow-navy-900/20 transition hover:bg-navy-800 disabled:bg-slate-200 disabled:text-slate-400 disabled:shadow-none"
          >
            {busy ? <Loader2 size={17} className="animate-spin" /> : <FileCheck2 size={17} />}
            Проверить оформление
          </button>
          {(report || diary || result) && (
            <button onClick={reset} className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800">
              <RotateCcw size={14} /> Начать заново
            </button>
          )}
          <span className="text-xs text-slate-400">Файлы проверяются на сервере университета и не сохраняются.</span>
        </div>

        {error && <div className="mt-5 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}

        {result && (
          <div className="mt-6 animate-fade-in space-y-4">
            <div
              className={clsx(
                'rounded-2xl px-6 py-5 text-white',
                result.ready ? 'bg-gradient-to-r from-emerald-600 to-emerald-500' : 'bg-gradient-to-r from-rose-600 to-rose-500',
              )}
            >
              <div className="font-display text-xl font-bold">
                {result.ready ? 'Документы оформлены правильно' : 'Есть ошибки оформления'}
              </div>
              <p className="mt-1 text-sm text-white/90">
                {result.ready
                  ? 'Можно распечатать, подписать у руководителя и сдать в деканат. Замечания ниже желательно учесть.'
                  : 'Исправьте ошибки, отмеченные красным, и проверьте документы ещё раз.'}
              </p>
            </div>

            {result.cross.length > 0 && (
              <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
                <div className="border-b border-slate-100 px-5 py-3 text-sm font-semibold text-slate-800">
                  Сверка отчёта и дневника
                </div>
                <ul className="divide-y divide-slate-100">
                  {result.cross.map((f) => (
                    <FindingRow key={f.id} f={f} />
                  ))}
                </ul>
              </section>
            )}

            {result.documents.map((d) => (
              <DocumentCheckCard key={d.kind} doc={d} />
            ))}
          </div>
        )}

        {reqs && (
          <details className="mt-8 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" open={!result}>
            <summary className="flex cursor-pointer items-center gap-2 text-sm font-semibold text-slate-800">
              <BookOpenCheck size={16} className="text-navy-800" /> Что проверяется
            </summary>
            <div className="mt-4 grid gap-6 md:grid-cols-2">
              {[reqs.report, reqs.diary].map((r) => (
                <div key={r.title}>
                  <div className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">{r.title}</div>
                  <ul className="space-y-1.5 text-sm text-slate-600">
                    {r.items.map((i) => (
                      <li key={i} className="flex gap-2">
                        <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-navy-800" />
                        {i}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
            <p className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-500">
              Подписи руководителя и печать предприятия проверяются на бумажном оригинале в деканате.
            </p>
          </details>
        )}
      </div>
    </div>
  )
}

function DropZone({
  icon: Icon,
  title,
  hint,
  file,
  onFile,
}: {
  icon: typeof FileText
  title: string
  hint: string
  file: File | null
  onFile: (f: File | null) => void
}) {
  const [drag, setDrag] = useState(false)
  return (
    <label
      onDragOver={(e) => {
        e.preventDefault()
        setDrag(true)
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDrag(false)
        onFile(e.dataTransfer.files[0] ?? null)
      }}
      className={clsx(
        'relative flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-8 text-center transition',
        file ? 'border-navy-800/40 bg-navy-900/[0.03]' : drag ? 'border-brand-500 bg-brand-50' : 'border-slate-300 bg-white hover:border-brand-400',
      )}
    >
      <Icon size={30} className={file ? 'text-navy-800' : 'text-slate-400'} />
      <div className="mt-2 font-semibold text-slate-800">{title}</div>
      {file ? (
        <div className="mt-1 flex max-w-full items-center gap-1.5 text-sm text-navy-800">
          <span className="truncate">{file.name}</span>
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault()
              onFile(null)
            }}
            className="rounded p-0.5 text-slate-400 hover:bg-slate-200 hover:text-slate-700"
            aria-label="Убрать файл"
          >
            <X size={14} />
          </button>
        </div>
      ) : (
        <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-500">
          <Upload size={13} /> {hint} — перетащите или нажмите
        </div>
      )}
      <input
        type="file"
        accept=".docx"
        className="hidden"
        onChange={(e) => {
          onFile(e.target.files?.[0] ?? null)
          e.target.value = ''
        }}
      />
    </label>
  )
}
