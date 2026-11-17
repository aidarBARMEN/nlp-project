import { useCallback, useEffect, useRef, useState } from 'react'
import { Camera, Check, ClipboardList, FileSpreadsheet, HelpCircle, Loader2, Plus, Printer, ScanLine, X } from 'lucide-react'
import clsx from 'clsx'
import { attendance, parseRoster, type Mark, type Sheet } from '../attendance'

const today = () => new Date().toLocaleDateString('ru', { day: '2-digit', month: '2-digit', year: 'numeric' })

export default function AttendancePage() {
  const [sheets, setSheets] = useState<Sheet[] | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    attendance.sheets().then((s) => {
      setSheets(s)
      setSelected((cur) => cur ?? s[0]?.id ?? null)
      if (!s.length) setCreating(true)
    }).catch((e) => setError(e.message))
  }, [])
  useEffect(load, [load])

  return (
    <div className="scrollbar-thin flex-1 overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 py-8">
        <div className="text-xs font-semibold tracking-wider text-navy-700 uppercase">Преподавателям</div>
        <h1 className="mt-1 font-display text-2xl text-navy-900">Посещаемость по фото листа</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Распечатайте лист со списком группы, дайте студентам расписаться и сфотографируйте его телефоном.
          Система выровняет фото по угловым меткам, найдёт подписи и отметит присутствующих — останется проверить
          и выгрузить Excel для импорта в портал.
        </p>
        {error && <div className="mt-4 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}

        <div className="mt-6 grid gap-5 lg:grid-cols-[280px_1fr]">
          <aside className="space-y-2">
            <button onClick={() => setCreating(true)}
                    className="flex w-full items-center justify-center gap-2 rounded-xl bg-navy-900 py-2.5 text-sm font-semibold text-white hover:bg-navy-800">
              <Plus size={16} /> Новый лист
            </button>
            {sheets?.map((s) => (
              <button key={s.id} onClick={() => { setSelected(s.id); setCreating(false) }}
                      className={clsx('w-full rounded-xl border px-4 py-3 text-left transition',
                        selected === s.id && !creating ? 'border-navy-700/40 bg-navy-50' : 'border-slate-200 bg-white hover:border-slate-300')}>
                <div className="truncate text-sm font-medium text-slate-800">{s.course}</div>
                <div className="text-xs text-slate-500">{s.group} · {s.date}</div>
                <div className="mt-1 text-[11px] text-slate-500">
                  {s.scanned_pages.length ? `присутствовали ${s.counts.present} из ${s.students.length}` : 'ещё не отсканирован'}
                </div>
              </button>
            ))}
          </aside>
          <div>
            {creating ? (
              <NewSheet onCreated={(s) => { setCreating(false); setSelected(s.id); load() }} onCancel={sheets?.length ? () => setCreating(false) : undefined} />
            ) : selected ? (
              <SheetView key={selected} id={selected} onChange={load} />
            ) : (
              <Loader2 className="mx-auto mt-16 animate-spin text-slate-400" />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function NewSheet({ onCreated, onCancel }: { onCreated: (s: Sheet) => void; onCancel?: () => void }) {
  const [course, setCourse] = useState('')
  const [group, setGroup] = useState('')
  const [date, setDate] = useState(today())
  const [roster, setRoster] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const students = parseRoster(roster)

  const fromExcel = async (file: File) => {
    try {
      const r = await attendance.roster(file)
      setRoster(r.students.map((s) => `${s.name}; ${s.student_id}`).join('\n'))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onCreated(await attendance.create({ course, group, date, students }))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="font-semibold text-slate-900">Новый лист посещаемости</h2>
      <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_140px_140px]">
        <Field label="Дисциплина"><input value={course} onChange={(e) => setCourse(e.target.value)} required className={input} /></Field>
        <Field label="Группа"><input value={group} onChange={(e) => setGroup(e.target.value)} required className={input} /></Field>
        <Field label="Дата"><input value={date} onChange={(e) => setDate(e.target.value)} pattern="\d{2}\.\d{2}\.\d{4}" required className={input} /></Field>
      </div>
      <div className="mt-4">
        <div className="mb-1 flex items-center justify-between">
          <span className="text-xs font-medium text-slate-600">Список группы — по строке на студента: «ФИО; Student ID»</span>
          <label className="cursor-pointer text-xs font-medium text-navy-800 hover:underline">
            Загрузить из Excel
            <input type="file" accept=".xlsx" className="hidden" onChange={(e) => e.target.files?.[0] && fromExcel(e.target.files[0])} />
          </label>
        </div>
        <textarea value={roster} onChange={(e) => setRoster(e.target.value)} rows={10}
                  placeholder={'Аманова Айгерим Ерлановна; 23B030001\nБекенов Нурлан Маратович; 23B030002'}
                  className={`${input} font-mono text-[13px]`} />
        <p className="mt-1 text-xs text-slate-500">Студентов: {students.length}{students.length > 22 && ` · лист займёт ${Math.ceil(students.length / 22)} страницы`}</p>
      </div>
      {error && <div className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}
      <div className="mt-4 flex gap-2">
        <button disabled={busy || !students.length}
                className="inline-flex items-center gap-2 rounded-xl bg-navy-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-50">
          {busy ? <Loader2 size={15} className="animate-spin" /> : <ClipboardList size={15} />} Создать лист
        </button>
        {onCancel && <button type="button" onClick={onCancel} className="rounded-xl px-4 py-2.5 text-sm text-slate-600 hover:bg-slate-100">Отмена</button>}
      </div>
    </form>
  )
}

const MARK_UI: Record<Exclude<Mark, null>, { label: string; cls: string; icon: typeof Check }> = {
  present: { label: 'Присутствовал', cls: 'bg-emerald-50 text-emerald-800 ring-emerald-200', icon: Check },
  absent: { label: 'Отсутствовал', cls: 'bg-rose-50 text-rose-800 ring-rose-200', icon: X },
  uncertain: { label: 'Проверить', cls: 'bg-amber-50 text-amber-800 ring-amber-200', icon: HelpCircle },
}

function SheetView({ id, onChange }: { id: number; onChange: () => void }) {
  const [sheet, setSheet] = useState<Sheet | null>(null)
  const [overlay, setOverlay] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    attendance.sheet(id).then(setSheet).catch((e) => setError(e.message))
  }, [id])

  const scan = async (file: File) => {
    setBusy(true)
    setError(null)
    try {
      const r = await attendance.scan(file, id)
      if (r.sheet.id !== id) setError(`На фото лист № ${r.sheet.id}, а открыт № ${id}. Результат записан в лист № ${r.sheet.id}.`)
      else setSheet(r.sheet)
      setOverlay(r.overlay)
      onChange()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const mark = async (index: number, status: 'present' | 'absent') => {
    setSheet(await attendance.setMarks(id, { [index]: status }))
    onChange()
  }

  if (!sheet) return error ? <div className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div> : <Loader2 className="mx-auto mt-16 animate-spin text-slate-400" />
  const c = sheet.counts
  const ready = sheet.scanned_pages.length > 0 && !c.uncertain && !c.unknown

  return (
    <div className="space-y-4">
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-semibold text-slate-900">{sheet.course}</h2>
            <p className="text-sm text-slate-500">{sheet.group} · {sheet.date} · лист № {sheet.id}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <a href={attendance.pdfUrl(sheet.id)} target="_blank" rel="noreferrer"
               className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
              <Printer size={15} /> Печать листа
            </a>
            <button onClick={() => fileRef.current?.click()} disabled={busy}
                    className="inline-flex items-center gap-1.5 rounded-xl bg-navy-900 px-3 py-2 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-60">
              {busy ? <Loader2 size={15} className="animate-spin" /> : <Camera size={15} />} Загрузить фото
            </button>
            <input ref={fileRef} type="file" accept="image/*" capture="environment" className="hidden"
                   onChange={(e) => { if (e.target.files?.[0]) scan(e.target.files[0]); e.target.value = '' }} />
            <a href={ready ? attendance.exportUrl(sheet.id) : undefined} aria-disabled={!ready}
               title={ready ? 'Excel для импорта в портал' : 'Сначала отсканируйте лист и проверьте отмеченные жёлтым'}
               className={clsx('inline-flex items-center gap-1.5 rounded-xl border px-3 py-2 text-sm font-medium',
                 ready ? 'border-emerald-300 text-emerald-800 hover:bg-emerald-50' : 'pointer-events-none border-slate-200 text-slate-400')}>
              <FileSpreadsheet size={15} /> Excel для портала
            </a>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Count label="Присутствовали" value={c.present} cls="text-emerald-700" />
          <Count label="Отсутствовали" value={c.absent} cls="text-rose-700" />
          <Count label="Проверить" value={c.uncertain} cls="text-amber-700" />
          <Count label="Не отсканировано" value={c.unknown} cls="text-slate-500" />
        </div>
        {sheet.pages > 1 && (
          <p className="mt-3 text-xs text-slate-500">Лист на {sheet.pages} страницах: сфотографируйте каждую — номер страницы читается из QR-кода.</p>
        )}
      </section>

      {error && <div className="rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-900 ring-1 ring-amber-200">{error}</div>}

      <div className={clsx('grid gap-4', overlay && 'xl:grid-cols-[1fr_340px]')}>
        <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-[11px] text-slate-500 uppercase">
              <tr>
                <th className="px-4 py-2.5 font-medium">№</th>
                <th className="px-3 py-2.5 font-medium">Студент</th>
                <th className="px-3 py-2.5 font-medium">Статус</th>
                <th className="px-3 py-2.5 text-right font-medium">Исправить</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {sheet.students.map((s) => {
                const ui = s.status ? MARK_UI[s.status] : null
                return (
                  <tr key={s.index} className={clsx(s.status === 'uncertain' && 'bg-amber-50/40')}>
                    <td className="px-4 py-2.5 text-slate-400">{s.index + 1}</td>
                    <td className="px-3 py-2.5">
                      <div className="text-slate-800">{s.name}</div>
                      <div className="font-mono text-[11px] text-slate-400">{s.student_id}</div>
                    </td>
                    <td className="px-3 py-2.5">
                      {ui ? (
                        <span className={clsx('inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1', ui.cls)}>
                          <ui.icon size={12} /> {ui.label}
                        </span>
                      ) : <span className="text-xs text-slate-400">—</span>}
                      {s.manual && <span className="ml-1.5 text-[10px] text-slate-400">вручную</span>}
                      {s.ink != null && !s.manual && <span className="ml-1.5 text-[10px] text-slate-400" title="Доля заполненности клетки подписи">{Math.round(s.ink * 100)}%</span>}
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <div className="inline-flex rounded-lg bg-slate-100 p-0.5">
                        {(['present', 'absent'] as const).map((m) => (
                          <button key={m} onClick={() => mark(s.index, m)} title={MARK_UI[m].label}
                                  className={clsx('rounded-md px-2 py-1 transition',
                                    s.status === m ? (m === 'present' ? 'bg-emerald-600 text-white' : 'bg-rose-600 text-white') : 'text-slate-500 hover:text-slate-800')}>
                            {m === 'present' ? <Check size={13} /> : <X size={13} />}
                          </button>
                        ))}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </section>
        {overlay && (
          <section className="self-start rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
            <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-600"><ScanLine size={14} /> Как система прочитала фото</div>
            <img src={overlay} alt="Выпрямленный лист с найденными подписями" className="w-full rounded-lg border border-slate-100" />
            <p className="mt-2 text-[11px] text-slate-500">Зелёная рамка — подпись найдена, красная — пусто, жёлтая — проверьте вручную.</p>
          </section>
        )}
      </div>
    </div>
  )
}

function Count({ label, value, cls }: { label: string; value: number; cls: string }) {
  return (
    <div className="rounded-xl bg-slate-50 px-3 py-2">
      <div className={clsx('text-xl font-semibold tabular-nums', cls)}>{value}</div>
      <div className="text-[11px] text-slate-500">{label}</div>
    </div>
  )
}

const input = 'w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-navy-700 focus:ring-2 focus:ring-navy-100'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-600">{label}</span>
      {children}
    </label>
  )
}
