import { useEffect, useState } from 'react'
import { Download, GraduationCap, Plus, Trash2 } from 'lucide-react'
import { getToken, useAuth } from '../auth'

type Member = { student_id: string; full_name: string }
type Entry = { faculty: string; program: string; full_name: string; study_group: string; topic: string; supervisor: string; members: Member[]; version: number; updated_at?: string; student_id?: string }
const blank: Entry = { faculty: '', program: '', full_name: '', study_group: '', topic: '', supervisor: '', members: [], version: 0 }
const input = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100'
const primary = 'rounded-xl bg-navy-900 px-5 py-2.5 text-sm font-medium text-white disabled:opacity-50'

export default function DiplomaPage({ university = false }: { university?: boolean }) {
  // вошедший на сайт пользователь работает со своей записью без отдельного входа по Student ID
  const [token, setToken] = useState(() => sessionStorage.getItem('diploma-token') || getToken())
  const { user } = useAuth()
  const staff = !!user && (user.role === 'dean' || user.role === 'admin')
  const [student, setStudent] = useState('')
  const [password, setPassword] = useState('')
  const [register, setRegister] = useState(false)
  const [entry, setEntry] = useState<Entry>({ ...blank })
  const [ready, setReady] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [dean, setDean] = useState(university)
  const [key, setKey] = useState('')
  const [rows, setRows] = useState<Entry[] | null>(null)
  const [query, setQuery] = useState('')
  const [faculties, setFaculties] = useState<Record<string, string[]>>({})
  const [facultyFilter, setFacultyFilter] = useState('')
  const [programFilter, setProgramFilter] = useState('')
  const filterParams = new URLSearchParams({ faculty: facultyFilter, program: programFilter }).toString()
  const visibleRows = rows?.filter(r => (!facultyFilter || (facultyFilter === '__missing__' ? !r.faculty : r.faculty === facultyFilter)) && (!programFilter || r.program === programFilter)) ?? []
  useEffect(() => {
    fetch('/api/diploma/catalog').then(r => { if (!r.ok) throw new Error('Не удалось загрузить факультеты'); return r.json() })
      .then(data => setFaculties(data.faculties)).catch(e => setError(e.message))
  }, [])

  async function request(path: string, init: RequestInit = {}, access = token) {
    const response = await fetch(`/api/diploma/${path}`, { ...init, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${access}`, 'X-Dean-Key': key, ...init.headers } })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(typeof body.detail === 'string' ? body.detail : 'Проверьте заполнение полей: обязательные значения, длину и Student ID участников.')
    }
    return response
  }
  useEffect(() => {
    if (!university || !staff) return
    request('records').then(r => r.json()).then(setRows).catch(e => setError(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [university, staff])
  async function action(fn: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await fn() } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось выполнить запрос') } finally { setBusy(false) }
  }
  useEffect(() => {
    if (!token) { setReady(false); return }
    let active = true
    request('me').then(r => r.json()).then(data => {
      if (active) { setStudent(data.student_id); setEntry({ ...blank, ...data.submission }); setReady(true) }
    }).catch(e => { if (active) { setError(e.message); setToken(''); sessionStorage.removeItem('diploma-token') } })
    return () => { active = false }
  }, [token])

  return <div className="mx-auto w-full max-w-6xl overflow-y-auto p-5 md:p-10">
    <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
      <div><div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-blue-700"><GraduationCap size={18} /> Выпускная работа</div><h1 className="text-3xl font-semibold text-slate-900">{university ? 'Дипломные проекты' : 'Мой диплом'}</h1><p className="mt-2 text-sm text-slate-500">{university ? 'Все команды — в одном Excel для деканата.' : 'Тема, команда и руководитель — в одной форме.'}</p></div>
      {!university && <button className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm" onClick={() => { setDean(!dean); setError(''); setNotice(''); setRows(null); setKey('') }}>{dean ? 'Вернуться к моей форме' : 'Для деканата'}</button>}
    </div>
    {error && <div role="alert" className="mb-5 rounded-xl bg-rose-50 p-4 text-sm text-rose-700">{error}</div>}
    {notice && <div role="status" className="mb-5 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-800">{notice}</div>}
    {dean ? <section className="rounded-2xl border border-slate-200 bg-white p-6">
      <h2 className="text-xl font-semibold">Реестр дипломных работ</h2><p className="mt-2 mb-5 text-sm text-slate-500">Скачайте один Excel со всеми проектами: каждый участник — отдельная строка, каждая команда — общий блок с рамкой. Новые команды добавляются снизу. Совпадающие состав, тема и руководитель объединяются; отличающиеся сведения сохраняются отдельно.</p>
      <form className="flex flex-wrap gap-3" onSubmit={e => { e.preventDefault(); void action(async () => { setRows(null); setRows(await (await request('records')).json()) }) }}>{!staff && <input aria-label="Ключ доступа деканата" type="password" className={`${input} max-w-sm`} placeholder="Ключ доступа деканата" required value={key} onChange={e => { setKey(e.target.value); setRows(null) }} />}<button disabled={busy} className={primary}>Открыть / обновить</button></form>
      {rows && <><div className="mt-6 grid gap-4 sm:grid-cols-2">
        <label className="text-sm font-medium">Факультет<select aria-label="Фильтр факультета" className={`${input} mt-2`} value={facultyFilter} onChange={e => { setFacultyFilter(e.target.value); setProgramFilter('') }}><option value="">Все факультеты</option>{Object.keys(faculties).map(f => <option key={f}>{f}</option>)}<option value="__missing__">Не указан (старые записи)</option></select></label>
        <label className="text-sm font-medium">Специальность<select aria-label="Фильтр специальности" className={`${input} mt-2`} disabled={!faculties[facultyFilter]} value={programFilter} onChange={e => setProgramFilter(e.target.value)}><option value="">Все специальности</option>{(faculties[facultyFilter] || []).map(p => <option key={p}>{p}</option>)}</select></label>
      </div><p className="mt-3 text-xs text-slate-500">Excel учитывает факультет и специальность. Текстовый поиск ниже служит для просмотра списка.</p><div className="my-6 flex flex-wrap items-center gap-3"><input aria-label="Поиск в реестре" className={`${input} max-w-sm`} placeholder="Поиск по студенту, теме или руководителю" value={query} onChange={e => setQuery(e.target.value)} /><span className="text-sm text-slate-500">По выборке: {visibleRows.length}</span><button disabled={busy} className="ml-auto flex items-center gap-2 rounded-xl bg-emerald-700 px-4 py-2.5 text-sm text-white" onClick={() => void action(async () => { const blob = await (await request(`export?${filterParams}`)).blob(); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `diploma${facultyFilter ? '-' + (facultyFilter === '__missing__' ? 'без-факультета' : facultyFilter) : ''}${programFilter ? '-' + programFilter : ''}.xlsx`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000) })}><Download size={16} /> {facultyFilter ? 'Скачать выборку (.xlsx)' : 'Скачать все проекты (.xlsx)'}</button></div>
        {visibleRows.length === 0 ? <p className="py-10 text-center text-slate-500">По выбранным фильтрам записей пока нет.</p> : <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-slate-500"><tr>{['Студент', 'Тема диплома', 'Руководитель', 'Другие участники', 'Обновлено'].map(h => <th key={h} className="p-3">{h}</th>)}</tr></thead><tbody>{visibleRows.filter(r => JSON.stringify(r).toLowerCase().includes(query.toLowerCase())).map(r => <tr key={r.student_id} className="border-b border-slate-100"><td className="p-3"><p className="font-medium">{r.full_name}</p><p className="text-xs text-slate-500">{r.student_id} · {r.study_group}</p><p className="mt-1 text-xs text-slate-500">{r.faculty || 'Факультет не указан'} · {r.program || 'Специальность не указана'}</p></td><td className="min-w-52 p-3">{r.topic}</td><td className="p-3">{r.supervisor}</td><td className="p-3">{r.members.length ? r.members.map(m => `${m.full_name} (${m.student_id})`).join(', ') : 'Индивидуально'}</td><td className="whitespace-nowrap p-3 text-xs text-slate-500">{r.updated_at && new Date(r.updated_at).toLocaleString('ru-RU')}</td></tr>)}</tbody></table></div>}</>}
    </section> : !token ? <section className="mx-auto max-w-lg rounded-2xl border border-slate-200 bg-white p-7">
      <h2 className="text-xl font-semibold">{register ? 'Создать аккаунт студента' : 'Войти в свою форму'}</h2><p className="mt-2 mb-6 text-sm text-slate-500">Ваша запись доступна для редактирования только из вашего аккаунта.</p>
      <form className="space-y-4" onSubmit={e => { e.preventDefault(); void action(async () => { const data = await (await request(register ? 'register' : 'login', { method: 'POST', body: JSON.stringify({ student_id: student.trim(), password }) })).json(); sessionStorage.setItem('diploma-token', data.token); setToken(data.token); setPassword('') }) }}>
        <label className="block text-sm font-medium">Student ID<input className={`${input} mt-2`} autoComplete="username" pattern="[A-Za-z0-9-]{3,30}" required value={student} onChange={e => setStudent(e.target.value)} placeholder="Например, 20260001" /></label>
        <label className="block text-sm font-medium">Пароль<input className={`${input} mt-2`} type="password" autoComplete={register ? 'new-password' : 'current-password'} minLength={8} maxLength={128} required value={password} onChange={e => setPassword(e.target.value)} placeholder="Не менее 8 символов" /></label>
        <button className={`${primary} w-full`} disabled={busy}>{busy ? 'Подождите…' : register ? 'Создать аккаунт' : 'Войти'}</button>
      </form><button className="mt-5 text-sm text-blue-700" onClick={() => { setRegister(!register); setError('') }}>{register ? 'Уже есть аккаунт? Войти' : 'Первый раз? Зарегистрироваться'}</button>
      <p className="mt-6 border-t border-slate-100 pt-4 text-xs leading-relaxed text-slate-400">Учебный прототип: используйте вымышленный ID. Регистрация пока не подтверждает личность через университет. Восстановление пароля не подключено.</p>
    </section> : !ready ? <p className="text-slate-500">Загружаем вашу запись…</p> : <div className="grid items-start gap-6 lg:grid-cols-[1fr_280px]">
      <form className="space-y-6 rounded-2xl border border-slate-200 bg-white p-6 md:p-8" onSubmit={e => { e.preventDefault(); void action(async () => { const { student_id: _id, updated_at: _date, ...payload } = entry; const data = await (await request('me', { method: 'PUT', body: JSON.stringify(payload) })).json(); setEntry(data); setNotice('Сохранено. Деканат увидит обновлённые данные в общем реестре.') }) }}>
        <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Данные дипломной работы</h2><span className="rounded-lg bg-blue-50 px-3 py-1 text-xs text-blue-700">{student}</span></div>
        <div className="grid gap-4 sm:grid-cols-2">{([['full_name', 'Ваше ФИО', 150, 3], ['study_group', 'Учебная группа', 50, 2]] as const).map(([field, label, max, min]) => <label key={field} className="text-sm font-medium">{label}<input className={`${input} mt-2`} required minLength={min} maxLength={max} value={entry[field]} onChange={e => { setNotice(''); setEntry({ ...entry, [field]: e.target.value }) }} /></label>)}</div>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="text-sm font-medium">Факультет<select className={`${input} mt-2`} required value={entry.faculty} onChange={e => { setNotice(''); setEntry({ ...entry, faculty: e.target.value, program: '' }) }}><option value="">Выберите факультет</option>{Object.keys(faculties).map(f => <option key={f}>{f}</option>)}</select></label>
          <label className="text-sm font-medium">Специальность<select className={`${input} mt-2`} required disabled={!entry.faculty} value={entry.program} onChange={e => { setNotice(''); setEntry({ ...entry, program: e.target.value }) }}><option value="">Выберите специальность</option>{(faculties[entry.faculty] || []).map(p => <option key={p}>{p}</option>)}</select></label>
        </div><p className="text-xs text-slate-400">Демонстрационный справочник факультетов и специальностей. Выбор относится к вашей форме и её проекту.</p>
        <label className="block text-sm font-medium">Тема диплома<textarea className={`${input} mt-2 resize-y`} rows={3} minLength={5} maxLength={500} required placeholder="Полное название темы" value={entry.topic} onChange={e => { setNotice(''); setEntry({ ...entry, topic: e.target.value }) }} /></label>
        <label className="block text-sm font-medium">ФИО научного руководителя<input className={`${input} mt-2`} minLength={3} maxLength={150} required value={entry.supervisor} onChange={e => { setNotice(''); setEntry({ ...entry, supervisor: e.target.value }) }} /></label>
        <div className="border-t border-slate-100 pt-6"><h3 className="font-semibold">Команда</h3><p className="mt-1 mb-4 text-sm text-slate-500">Вы уже включены. Добавьте остальных участников или оставьте пустым, если работаете самостоятельно.</p>
          {entry.members.map((m, i) => <div key={i} className="mb-3 flex items-center gap-2"><div className="grid flex-1 gap-2 sm:grid-cols-[140px_1fr]"><input aria-label={`Student ID участника ${i + 1}`} className={input} placeholder="Student ID" pattern="[A-Za-z0-9-]{3,30}" required value={m.student_id} onChange={e => { setNotice(''); setEntry({ ...entry, members: entry.members.map((v, n) => n === i ? { ...v, student_id: e.target.value } : v) }) }} /><input aria-label={`ФИО участника ${i + 1}`} className={input} placeholder="ФИО участника" minLength={3} maxLength={150} required value={m.full_name} onChange={e => { setNotice(''); setEntry({ ...entry, members: entry.members.map((v, n) => n === i ? { ...v, full_name: e.target.value } : v) }) }} /></div><button type="button" aria-label={`Удалить участника ${i + 1}`} className="p-2 text-slate-400 hover:text-rose-600" onClick={() => { setNotice(''); setEntry({ ...entry, members: entry.members.filter((_, n) => n !== i) }) }}><Trash2 size={17} /></button></div>)}
          <button disabled={entry.members.length >= 9} type="button" className="flex items-center gap-2 text-sm font-medium text-blue-700 disabled:opacity-40" onClick={() => { setNotice(''); setEntry({ ...entry, members: [...entry.members, { student_id: '', full_name: '' }] }) }}><Plus size={16} /> Добавить участника</button>
        </div><div className="flex flex-wrap items-center gap-4 border-t border-slate-100 pt-6"><button disabled={busy} className={primary}>{busy ? 'Сохраняем…' : entry.version ? 'Сохранить изменения' : 'Отправить данные'}</button><span className="text-xs text-slate-400">{entry.updated_at ? `Сохранено: ${new Date(entry.updated_at).toLocaleString('ru-RU')}` : 'Ещё не отправлено'}</span></div>
      </form>
      <aside className="rounded-2xl border border-blue-100 bg-blue-50/60 p-6"><h3 className="font-semibold text-navy-900">Без общей редактируемой таблицы</h3><p className="mt-3 text-sm leading-relaxed text-slate-600">Заполните форму один раз. Если тема, команда или руководитель изменятся — вернитесь и обновите свою запись.</p><p className="mt-3 text-sm leading-relaxed text-slate-600">У каждого студента своя строка. Указание участника здесь не изменяет его запись и не подтверждает его согласие на участие.</p><button disabled={busy} className="mt-6 text-sm text-slate-500 underline" onClick={() => void action(async () => { await request('logout', { method: 'POST' }); sessionStorage.removeItem('diploma-token'); setToken(''); setEntry({ ...blank }); setStudent('') })}>Выйти из аккаунта</button></aside>
    </div>}
  </div>
}
