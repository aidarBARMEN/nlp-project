import { useEffect, useMemo, useState } from 'react'
import {
  ArrowLeft,
  BookMarked,
  CheckCircle2,
  Clock3,
  Download,
  FileMinus2,
  FilePlus2,
  Loader2,
  Plus,
  RefreshCcw,
  Send,
  Trash2,
  UserRound,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import clsx from 'clsx'
import { applications, type AppType, type Application, type Block, type TypesInfo } from '../applications'
import { useAuth } from '../auth'
import ProfileForm from '../components/ProfileForm'

type Discipline = { name: string; credits_kz: string; ects: string; kind: '' | 'retake' | 'overcredit' }
const SEMESTER_NAMES: Record<string, string> = { autumn: 'Осенний', spring: 'Весенний', summer: 'Летний' }
const emptyDiscipline = (): Discipline => ({ name: '', credits_kz: '', ects: '', kind: '' })
const ICONS: Record<AppType['id'], LucideIcon> = {
  registration: FilePlus2,
  drop: FileMinus2,
  recredit: RefreshCcw,
  master_thesis: BookMarked,
}

export default function ApplicationsPage({ onLogin }: { onLogin: () => void }) {
  const { user } = useAuth()
  const [info, setInfo] = useState<TypesInfo | null>(null)
  const [type, setType] = useState<AppType['id'] | null>(null)
  const [mine, setMine] = useState<Application[]>([])
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    applications.types().then(setInfo).catch(() => undefined)
  }, [])
  useEffect(() => {
    if (user) applications.mine().then(setMine).catch(() => undefined)
  }, [user, refresh])

  if (!user) {
    return (
      <Shell>
        <div className="mt-8 rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
          <UserRound size={28} className="mx-auto text-slate-300" />
          <p className="mx-auto mt-3 max-w-md text-sm text-slate-600">
            Заявление подаётся от вашего имени, поэтому нужно войти. Данные профиля подставятся в шапку автоматически.
          </p>
          <button onClick={onLogin} className="mt-5 rounded-xl bg-navy-900 px-5 py-2.5 text-sm font-semibold text-white hover:bg-navy-800">
            Войти или зарегистрироваться
          </button>
        </div>
      </Shell>
    )
  }

  if (!info) return <Shell><Loader2 className="mx-auto mt-16 animate-spin text-slate-400" /></Shell>

  const current = info.types.find((t) => t.id === type)

  return (
    <Shell>
      {!current ? (
        <>
          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            {info.types.map((t) => {
              const Icon = ICONS[t.id]
              return (
                <button key={t.id} onClick={() => setType(t.id)}
                        className="group flex gap-4 rounded-2xl border border-slate-200 bg-white p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-navy-700/40 hover:shadow-md">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-navy-50 text-navy-800 transition group-hover:bg-navy-900 group-hover:text-white">
                    <Icon size={19} />
                  </span>
                  <span>
                    <span className="block font-semibold text-slate-900">{t.title}</span>
                    <span className="mt-1 block text-sm text-slate-500">{t.description}</span>
                    {t.audience === 'master' && <span className="mt-2 inline-block rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">магистратура</span>}
                  </span>
                </button>
              )
            })}
          </div>
          <MyApplications items={mine} />
        </>
      ) : (
        <Editor info={info} type={current} onBack={() => setType(null)} onSubmitted={() => { setType(null); setRefresh((r) => r + 1) }} />
      )}
    </Shell>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="scrollbar-thin flex-1 overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 py-8">
        <div className="text-xs font-semibold tracking-wider text-navy-700 uppercase">Деканат ШИТиИ</div>
        <h1 className="mt-1 font-display text-2xl text-navy-900">Заявления</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-500">
          Выберите вид заявления и укажите только суть — шапку, дату и формулировки система подставит по образцу деканата.
          Готовое заявление можно скачать в Word или сразу отправить в деканат.
        </p>
        {children}
      </div>
    </div>
  )
}

function Editor({ info, type, onBack, onSubmitted }: { info: TypesInfo; type: AppType; onBack: () => void; onSubmitted: () => void }) {
  const { user } = useAuth()
  const [semester, setSemester] = useState('spring')
  const [year, setYear] = useState(info.default_year)
  const [disciplines, setDisciplines] = useState<Discipline[]>([emptyDiscipline()])
  const [drop, setDrop] = useState({ discipline: '', reason: 'в связи с непрохождением пререквизита к данной дисциплине' })
  const [replacement, setReplacement] = useState<Discipline | null>(null)
  const [recredit, setRecredit] = useState({ recredited: '', recredited_ects: '' })
  const [thesis, setThesis] = useState({ program: info.master_programs[0], topic_kk: '', topic_ru: '', topic_en: '', supervisor: '' })
  const [blocks, setBlocks] = useState<Block[] | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [editProfile, setEditProfile] = useState(false)
  const [busy, setBusy] = useState<'' | 'send' | 'docx'>('')

  const clean = (list: Discipline[]) => list.filter((d) => d.name.trim())
  const data = useMemo(() => {
    if (type.id === 'registration') return { semester, academic_year: year, disciplines: clean(disciplines) }
    if (type.id === 'drop') return { semester, academic_year: year, ...drop, replacement: replacement?.name.trim() ? replacement : null }
    if (type.id === 'recredit') return { semester, academic_year: year, ...recredit, disciplines: clean(disciplines) }
    return thesis
  }, [type.id, semester, year, disciplines, drop, replacement, recredit, thesis])

  // превью обновляется при каждом изменении (с задержкой, чтобы не дёргать сервер на каждую букву)
  useEffect(() => {
    const t = setTimeout(() => {
      applications.preview(type.id, data).then((r) => { setBlocks(r.blocks); setProblem(null) }).catch((e) => setProblem(e.message))
    }, 350)
    return () => clearTimeout(t)
  }, [type.id, data, user])

  const run = async (kind: 'send' | 'docx') => {
    setBusy(kind)
    try {
      if (kind === 'docx') await applications.downloadDraft(type.id, data)
      else {
        await applications.submit(type.id, data)
        onSubmitted()
      }
    } catch (e) {
      setProblem((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  const missingProfile = problem?.startsWith('Заполните в профиле')

  return (
    <div className="mt-6">
      <button onClick={onBack} className="inline-flex items-center gap-1.5 text-sm text-slate-600 hover:text-navy-900">
        <ArrowLeft size={15} /> Все виды заявлений
      </button>
      <div className="mt-3 grid gap-6 lg:grid-cols-[1fr_minmax(0,520px)]">
        <div className="space-y-4">
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="font-semibold text-slate-900">{type.title}</h2>
            <div className="mt-4 space-y-4">
              {type.id !== 'master_thesis' && (
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Семестр">
                    <select value={semester} onChange={(e) => setSemester(e.target.value)} className={input}>
                      {Object.keys(info.semesters).map((k) => <option key={k} value={k}>{SEMESTER_NAMES[k]}</option>)}
                    </select>
                  </Field>
                  <Field label="Учебный год">
                    <input value={year} onChange={(e) => setYear(e.target.value)} className={input} />
                  </Field>
                </div>
              )}

              {type.id === 'drop' && (
                <>
                  <Field label="Какую дисциплину снять">
                    <input value={drop.discipline} onChange={(e) => setDrop({ ...drop, discipline: e.target.value })}
                           placeholder="Полное название и кредиты, например: Машинное обучение (3 кр. KZ, 5 ECTS)" className={input} />
                  </Field>
                  <Field label="Причина">
                    <input value={drop.reason} onChange={(e) => setDrop({ ...drop, reason: e.target.value })} className={input} />
                  </Field>
                  {replacement ? (
                    <div>
                      <div className="mb-1 flex items-center justify-between text-xs font-medium text-slate-600">
                        Вместо неё зарегистрировать
                        <button onClick={() => setReplacement(null)} className="text-slate-400 hover:text-rose-600">убрать</button>
                      </div>
                      <DisciplineRow value={replacement} onChange={setReplacement} />
                    </div>
                  ) : (
                    <button onClick={() => setReplacement(emptyDiscipline())} className="inline-flex items-center gap-1 text-sm font-medium text-navy-800 hover:underline">
                      <Plus size={14} /> Заменить другой дисциплиной
                    </button>
                  )}
                </>
              )}

              {type.id === 'recredit' && (
                <div className="grid grid-cols-[1fr_90px] gap-3">
                  <Field label="Перезачтённая дисциплина">
                    <input value={recredit.recredited} onChange={(e) => setRecredit({ ...recredit, recredited: e.target.value })} className={input} />
                  </Field>
                  <Field label="ECTS">
                    <input value={recredit.recredited_ects} onChange={(e) => setRecredit({ ...recredit, recredited_ects: e.target.value })} className={input} />
                  </Field>
                </div>
              )}

              {(type.id === 'registration' || type.id === 'recredit') && (
                <div>
                  <div className="mb-1 text-xs font-medium text-slate-600">
                    {type.id === 'recredit' ? 'Зарегистрировать вместо неё' : 'Дисциплины'} — полное название и кредиты
                  </div>
                  <div className="space-y-2">
                    {disciplines.map((d, i) => (
                      <DisciplineRow key={i} value={d} withKind={type.id === 'registration'}
                                     onChange={(v) => setDisciplines(disciplines.map((x, j) => (j === i ? v : x)))}
                                     onRemove={disciplines.length > 1 ? () => setDisciplines(disciplines.filter((_, j) => j !== i)) : undefined} />
                    ))}
                  </div>
                  {disciplines.length < (type.id === 'registration' ? 7 : 5) && (
                    <button onClick={() => setDisciplines([...disciplines, emptyDiscipline()])} className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-navy-800 hover:underline">
                      <Plus size={14} /> Ещё дисциплина
                    </button>
                  )}
                  {type.id === 'registration' && (
                    <p className="mt-2 text-xs text-slate-500">Регистрация — по РУПу. Для ритейка и сверхкредитов приложите квитанцию об оплате.</p>
                  )}
                </div>
              )}

              {type.id === 'master_thesis' && (
                <>
                  <Field label="Образовательная программа">
                    <select value={thesis.program} onChange={(e) => setThesis({ ...thesis, program: e.target.value })} className={input}>
                      {info.master_programs.map((p) => <option key={p}>{p}</option>)}
                    </select>
                  </Field>
                  {([['topic_kk', 'Тема на казахском'], ['topic_ru', 'Тема на русском'], ['topic_en', 'Тема на английском']] as const).map(([k, label]) => (
                    <Field key={k} label={label}>
                      <textarea value={thesis[k]} onChange={(e) => setThesis({ ...thesis, [k]: e.target.value })} rows={2} className={`${input} resize-none`} />
                    </Field>
                  ))}
                  <Field label="Научный руководитель (ФИО, степень)">
                    <input value={thesis.supervisor} onChange={(e) => setThesis({ ...thesis, supervisor: e.target.value })} className={input} />
                  </Field>
                </>
              )}
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-800">Данные в шапке заявления</h3>
              <button onClick={() => setEditProfile((v) => !v)} className="text-xs font-medium text-navy-800 hover:underline">
                {editProfile || missingProfile ? 'Свернуть' : 'Изменить'}
              </button>
            </div>
            {editProfile || missingProfile ? (
              <div className="mt-3"><ProfileForm compact onSaved={() => setEditProfile(false)} /></div>
            ) : (
              <p className="mt-2 text-sm text-slate-600">
                {user?.full_name} · {user?.course ? `${user.course} курс` : 'курс не указан'} · {user?.program || 'ОП не указана'} · {user?.phone || 'телефон не указан'}
              </p>
            )}
          </section>
        </div>

        <div className="lg:sticky lg:top-6 lg:self-start">
          <Paper blocks={blocks} problem={problem} />
          <div className="mt-4 flex flex-wrap gap-2">
            <button onClick={() => run('send')} disabled={!!busy || !!problem}
                    className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-navy-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-50">
              {busy === 'send' ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />} Отправить в деканат
            </button>
            <button onClick={() => run('docx')} disabled={!!busy || !!problem}
                    className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
              {busy === 'docx' ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />} Скачать Word
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function Paper({ blocks, problem }: { blocks: Block[] | null; problem: string | null }) {
  return (
    <div className="relative aspect-[210/297] overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg">
      <div className="absolute inset-0 overflow-y-auto px-[9%] pt-[7%] pb-[6%] pl-[14%] font-serif text-[11px] leading-[1.45] text-slate-900">
        {blocks ? blocks.map((b, i) => (
          <p key={i} className={clsx(
            { left: 'text-left', right: 'text-right', center: 'text-center', justify: 'text-justify' }[b.align],
            ['header', 'title', 'signature', 'bold'].includes(b.style) && 'font-bold',
            b.style === 'title' && 'mt-8 mb-2',
            b.style === 'indent' && 'indent-6',
            b.style === 'signature' && 'mt-10 flex justify-between whitespace-pre',
          )}>
            {b.style === 'signature' && b.text.includes('\t')
              ? b.text.split('\t').map((part) => <span key={part}>{part}</span>)
              : b.text || ' '}
          </p>
        )) : !problem && <Loader2 className="mx-auto mt-24 animate-spin text-slate-300" />}
      </div>
      {problem && (
        <div className="absolute inset-x-4 bottom-4 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900 ring-1 ring-amber-200">{problem}</div>
      )}
    </div>
  )
}

function DisciplineRow({ value, onChange, onRemove, withKind }: {
  value: Discipline
  onChange: (v: Discipline) => void
  onRemove?: () => void
  withKind?: boolean
}) {
  return (
    <div className="flex flex-wrap gap-2 sm:flex-nowrap">
      <input value={value.name} onChange={(e) => onChange({ ...value, name: e.target.value })} placeholder="Название дисциплины" className={`${input} min-w-0 flex-1`} />
      <input value={value.credits_kz} onChange={(e) => onChange({ ...value, credits_kz: e.target.value })} placeholder="кр. KZ" className={`${input} w-20`} />
      <input value={value.ects} onChange={(e) => onChange({ ...value, ects: e.target.value })} placeholder="ECTS" className={`${input} w-20`} />
      {withKind && (
        <select value={value.kind} onChange={(e) => onChange({ ...value, kind: e.target.value as Discipline['kind'] })} className={`${input} w-32`}>
          <option value="">обычная</option>
          <option value="retake">ритейк</option>
          <option value="overcredit">сверхкредит</option>
        </select>
      )}
      {onRemove && (
        <button onClick={onRemove} className="rounded-lg p-2 text-slate-400 hover:bg-rose-50 hover:text-rose-600" title="Убрать">
          <Trash2 size={15} />
        </button>
      )}
    </div>
  )
}

const STATUS_UI = {
  submitted: { icon: Clock3, cls: 'bg-amber-50 text-amber-800 ring-amber-200' },
  approved: { icon: CheckCircle2, cls: 'bg-emerald-50 text-emerald-800 ring-emerald-200' },
  rejected: { icon: XCircle, cls: 'bg-rose-50 text-rose-800 ring-rose-200' },
}

export function StatusPill({ status, label }: { status: Application['status']; label: string }) {
  const ui = STATUS_UI[status]
  return (
    <span className={clsx('inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap ring-1', ui.cls)}>
      <ui.icon size={12} /> {label}
    </span>
  )
}

function MyApplications({ items }: { items: Application[] }) {
  if (!items.length) return null
  return (
    <section className="mt-8 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <h3 className="border-b border-slate-100 px-5 py-3 text-sm font-semibold text-slate-800">Мои заявления</h3>
      <ul className="divide-y divide-slate-100">
        {items.map((a) => (
          <li key={a.id} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
            <div className="min-w-0 flex-1">
              <div className="font-medium text-slate-800">{a.type_title} <span className="font-normal text-slate-400">№ {a.id}</span></div>
              <div className="text-xs text-slate-500">
                подано {new Date(a.created_at).toLocaleDateString('ru')}
                {a.comment && <> · <span className={a.status === 'rejected' ? 'text-rose-700' : ''}>деканат: {a.comment}</span></>}
              </div>
            </div>
            <StatusPill status={a.status} label={a.status_name} />
            <a href={applications.fileUrl(a.id)} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-navy-800" title="Скачать заявление">
              <Download size={15} />
            </a>
          </li>
        ))}
      </ul>
    </section>
  )
}

const input = 'w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-navy-700 focus:ring-2 focus:ring-navy-100'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-600">{label}</span>
      {children}
    </label>
  )
}
