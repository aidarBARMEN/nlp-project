import { useEffect, useState } from 'react'
import { ArrowLeft, CheckCircle2, CircleAlert, EyeOff, Loader2, Search } from 'lucide-react'
import clsx from 'clsx'
import { edo, type Meta, type Person, type PersonalFile } from '../../edo'
import { AccessBadge, Card, CATEGORY_ICON, Empty, StatusBadge } from './ui'

export default function PersonalFiles({
  role,
  meta,
  refreshKey,
  onOpen,
}: {
  role: string
  meta: Meta
  refreshKey: number
  onOpen: (id: number) => void
}) {
  const kinds = meta.person_access[role] ?? []
  const [kind, setKind] = useState(kinds[0] ?? '')
  const [q, setQ] = useState('')
  const [persons, setPersons] = useState<Person[] | null>(null)
  const [selected, setSelected] = useState<number | null>(null)

  useEffect(() => {
    setKind((k) => (kinds.includes(k) ? k : (kinds[0] ?? '')))
    setSelected(null)
  }, [role, kinds])

  useEffect(() => {
    if (!kind) return setPersons([])
    const t = setTimeout(() => edo.persons(role, { kind, q: q.trim() || undefined }).then(setPersons), 200)
    return () => clearTimeout(t)
  }, [role, kind, q, refreshKey])

  if (!kinds.length) return <Card><Empty text="Этой роли не доступны карточки студентов и сотрудников" /></Card>
  if (selected) return <PersonView role={role} id={selected} onBack={() => setSelected(null)} onOpen={onOpen} refreshKey={refreshKey} />

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-3">
        <div className="flex rounded-lg bg-slate-100 p-0.5">
          {kinds.map((k) => (
            <button
              key={k}
              onClick={() => setKind(k)}
              className={clsx('rounded-md px-3 py-1 text-xs font-medium transition',
                kind === k ? 'bg-white text-navy-900 shadow-sm' : 'text-slate-600 hover:text-slate-900')}
            >
              {{ student: 'Студенты', applicant: 'Абитуриенты', employee: 'Сотрудники' }[k]}
            </button>
          ))}
        </div>
        <label className="flex min-w-60 flex-1 items-center gap-2 rounded-lg border border-slate-200 px-3 py-1.5">
          <Search size={14} className="text-slate-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="ФИО, группа, программа"
                 className="flex-1 bg-transparent text-sm outline-none" />
        </label>
      </div>
      {!persons ? (
        <Loader2 className="mx-auto my-10 animate-spin text-slate-400" />
      ) : persons.length === 0 ? (
        <Empty text="Никого не найдено" />
      ) : (
        <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
          {persons.map((p) => (
            <button
              key={p.id}
              onClick={() => setSelected(p.id)}
              className="group rounded-xl border border-slate-200 p-4 text-left transition hover:-translate-y-0.5 hover:border-navy-800/40 hover:shadow-md"
            >
              <div className="flex items-start gap-3">
                <Avatar name={p.full_name} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold text-slate-800">{p.full_name}</div>
                  <div className="truncate text-xs text-slate-500">
                    {p.kind === 'employee' ? p.position : [p.program, p.study_group].filter(Boolean).join(' · ')}
                  </div>
                </div>
              </div>
              <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
                <span>{p.status}</span>
                <span>{p.documents} док.</span>
              </div>
              {p.completeness !== undefined && (
                <div className="mt-2">
                  <div className="flex justify-between text-[11px] text-slate-500">
                    <span>Комплектность личного дела</span>
                    <span className={clsx('font-semibold', p.completeness < 1 ? 'text-amber-700' : 'text-emerald-700')}>
                      {Math.round(p.completeness * 100)}%
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
                    <div className={clsx('h-full rounded-full', p.completeness < 1 ? 'bg-amber-500' : 'bg-emerald-600')}
                         style={{ width: `${p.completeness * 100}%` }} />
                  </div>
                </div>
              )}
            </button>
          ))}
        </div>
      )}
    </Card>
  )
}

function PersonView({ role, id, onBack, onOpen, refreshKey }: {
  role: string
  id: number
  onBack: () => void
  onOpen: (id: number) => void
  refreshKey: number
}) {
  const [file, setFile] = useState<PersonalFile | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    edo.personalFile(role, id).then(setFile).catch((e) => setError(e.message))
  }, [role, id, refreshKey])

  if (error) return <div className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>
  if (!file) return <Loader2 className="mx-auto mt-16 animate-spin text-slate-400" />
  const p = file.person
  const missing = file.checklist.filter((c) => !c.present).length

  return (
    <div className="space-y-5">
      <button onClick={onBack} className="inline-flex items-center gap-1.5 text-sm text-slate-600 hover:text-navy-900">
        <ArrowLeft size={15} /> Ко всем карточкам
      </button>

      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-wrap items-center gap-4 bg-navy-900 px-6 py-5 text-white">
          <Avatar name={p.full_name} large />
          <div className="min-w-0 flex-1">
            <div className="text-xs tracking-wide text-white/60 uppercase">
              {p.kind === 'student' ? 'Личное дело обучающегося' : p.kind === 'applicant' ? 'Дело абитуриента' : 'Личное дело сотрудника'}
            </div>
            <div className="font-display text-xl font-bold">{p.full_name}</div>
          </div>
          <span className="rounded-full bg-white/10 px-3 py-1 text-xs">{p.status}</span>
        </div>
        <dl className="grid gap-x-6 gap-y-2 px-6 py-4 text-sm sm:grid-cols-3">
          {p.school && <Field label="Школа">{p.school}</Field>}
          {p.program && <Field label="Образовательная программа">{p.program}</Field>}
          {p.course && <Field label="Курс / группа">{`${p.course} курс · ${p.study_group}`}</Field>}
          {p.position && <Field label="Должность">{p.position}</Field>}
          <Field label="ИИН">{p.iin_masked}</Field>
          <Field label="E-mail">{p.email}</Field>
        </dl>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        {file.checklist.length > 0 && (
          <Card
            title="Комплектность личного дела"
            action={
              <span className={clsx('text-xs font-semibold', missing ? 'text-amber-700' : 'text-emerald-700')}>
                {missing ? `не хватает ${missing}` : 'полное'}
              </span>
            }
          >
            <ul className="divide-y divide-slate-100">
              {file.checklist.map((c) => (
                <li key={c.type_code} className="flex items-center gap-2.5 px-5 py-2.5 text-sm">
                  {c.present ? (
                    <CheckCircle2 size={16} className="shrink-0 text-emerald-600" />
                  ) : (
                    <CircleAlert size={16} className="shrink-0 text-amber-500" />
                  )}
                  <span className={clsx(c.present ? 'text-slate-700' : 'font-medium text-slate-900')}>{c.name}</span>
                </li>
              ))}
            </ul>
            <p className="border-t border-slate-100 px-5 py-3 text-[11px] text-slate-500">
              Показан только факт наличия. Медицинские документы открывает медпункт.
            </p>
          </Card>
        )}

        <div className={clsx('space-y-4', file.checklist.length ? 'lg:col-span-2' : 'lg:col-span-3')}>
          {file.groups.length === 0 && <Card><Empty text="Доступных этой роли документов нет" /></Card>}
          {file.groups.map((g) => {
            const Icon = CATEGORY_ICON[g.category]
            return (
              <Card key={g.category} title={<span className="flex items-center gap-2">{Icon && <Icon size={15} />} {g.name}</span>}>
                <ul className="divide-y divide-slate-100">
                  {g.documents.map((d) => (
                    <li key={d.id}>
                      <button onClick={() => onOpen(d.id)} className="flex w-full items-center gap-3 px-5 py-2.5 text-left hover:bg-slate-50">
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm text-slate-800">{d.title}</div>
                          <div className="flex items-center gap-2 font-mono text-[11px] text-slate-500">
                            {d.reg_number} <AccessBadge access={d.access} />
                          </div>
                        </div>
                        <StatusBadge status={d.status} label={d.status_name} overdue={d.overdue} />
                      </button>
                    </li>
                  ))}
                </ul>
              </Card>
            )
          })}
          {file.hidden_documents > 0 && (
            <p className="flex items-center gap-2 rounded-xl bg-slate-50 px-4 py-3 text-xs text-slate-500">
              <EyeOff size={14} /> Ещё {file.hidden_documents} док. в разделах, закрытых для этой роли.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-slate-800">{children || '—'}</dd>
    </div>
  )
}

function Avatar({ name, large }: { name: string; large?: boolean }) {
  const initials = name.split(' ').slice(0, 2).map((s) => s[0]).join('')
  return (
    <span className={clsx('flex shrink-0 items-center justify-center rounded-full font-semibold',
      large ? 'h-14 w-14 bg-white text-lg text-navy-900' : 'h-10 w-10 bg-navy-900/5 text-sm text-navy-800')}>
      {initials}
    </span>
  )
}
