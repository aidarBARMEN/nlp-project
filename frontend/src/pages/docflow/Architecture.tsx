import {
  Archive,
  ArrowDown,
  ArrowRight,
  Database,
  FileCheck2,
  FileInput,
  Fingerprint,
  GitBranch,
  KeyRound,
  ScanLine,
  ShieldCheck,
  Stethoscope,
  UserCog,
  type LucideIcon,
} from 'lucide-react'
import clsx from 'clsx'
import type { Meta } from '../../edo'
import { Card, CATEGORY_ICON } from './ui'

const FLOW: { icon: LucideIcon; title: string; items: string[] }[] = [
  {
    icon: FileInput,
    title: 'Поступление',
    items: ['Портал приёма абитуриентов', 'Заявления студентов (Uninet)', 'Подразделения и медпункт',
            'Базы практики, госорганы', 'Сканы бумажных оригиналов'],
  },
  {
    icon: FileCheck2,
    title: 'Регистрация',
    items: ['Рег. номер по номенклатуре: ЛД-2026/00042', 'Тип, раздел, гриф доступа', 'Привязка к личному делу',
            'Срок хранения рассчитывается сразу'],
  },
  {
    icon: GitBranch,
    title: 'Согласование',
    items: ['Маршрут задан типом документа', 'Решение только текущего шага', 'Отклонение — с причиной',
            'Контроль сроков и просрочек'],
  },
  {
    icon: Database,
    title: 'Хранение',
    items: ['Карточки и маршруты — БД', 'Файлы — защищённое хранилище', 'Контрольная сумма SHA-256',
            'Журнал всех действий'],
  },
  {
    icon: Archive,
    title: 'Архив',
    items: ['Передача утверждённых дел', 'Хранение 5–75 лет / постоянно', 'Экспертная комиссия по истечении срока'],
  },
]

const PRINCIPLES: { icon: LucideIcon; title: string; text: string; done: boolean }[] = [
  { icon: KeyRound, title: 'Минимально необходимый доступ',
    text: 'Роль видит только свои разделы. Для чужих разделов — карточка без файла и примечаний или ничего.', done: true },
  { icon: Stethoscope, title: 'Медицинская тайна',
    text: 'Содержимое медицинских документов открывает только медпункт; деканат и регистратор видят лишь факт наличия справки.', done: true },
  { icon: ShieldCheck, title: 'Журнал действий',
    text: 'Регистрация, решения, скачивание и каждый просмотр персональных данных записываются с ролью и временем.', done: true },
  { icon: Fingerprint, title: 'Целостность файлов',
    text: 'Для каждого скана хранится SHA-256: подмену файла в хранилище можно обнаружить.', done: true },
  { icon: ScanLine, title: 'Изоляция от ИИ-ассистента',
    text: 'Документы ЭДО не индексируются в базу знаний чат-бота и не передаются во внешние языковые модели.', done: true },
  { icon: UserCog, title: 'Вход через SSO и ЭЦП',
    text: 'Сейчас роль выбирается в интерфейсе. Для внедрения: вход через учётную запись КБТУ и подписание через NCALayer.', done: false },
]

export default function Architecture({ meta }: { meta: Meta }) {
  const roles = meta.roles

  return (
    <div className="space-y-6">
      <Card title="Документопоток университета">
        <div className="grid gap-3 p-5 lg:grid-cols-[repeat(5,minmax(0,1fr))]">
          {FLOW.map((s, i) => (
            <div key={s.title} className="relative">
              <div className="h-full rounded-xl border border-slate-200 bg-gradient-to-b from-white to-slate-50 p-4">
                <div className="flex items-center gap-2">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-navy-900 text-white">
                    <s.icon size={16} />
                  </span>
                  <span className="text-[11px] font-semibold text-slate-400">0{i + 1}</span>
                </div>
                <div className="mt-3 text-sm font-semibold text-navy-900">{s.title}</div>
                <ul className="mt-2 space-y-1 text-xs text-slate-600">
                  {s.items.map((t) => (
                    <li key={t} className="flex gap-1.5">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-navy-800/50" />
                      {t}
                    </li>
                  ))}
                </ul>
              </div>
              {i < FLOW.length - 1 && (
                <>
                  <ArrowRight size={16} className="absolute top-1/2 -right-3 z-10 hidden -translate-y-1/2 rounded-full bg-white text-navy-800 lg:block" />
                  <ArrowDown size={16} className="mx-auto mt-2 text-navy-800 lg:hidden" />
                </>
              )}
            </div>
          ))}
        </div>
      </Card>

      <Card title="Разделы документооборота">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-[11px] text-slate-500 uppercase">
              <tr>
                <th className="px-5 py-2.5 font-medium">Раздел</th>
                <th className="px-3 py-2.5 font-medium">Индекс</th>
                <th className="px-3 py-2.5 font-medium">Гриф</th>
                <th className="px-3 py-2.5 font-medium">Регистрирует</th>
                <th className="px-3 py-2.5 font-medium">Типы документов</th>
                <th className="px-3 py-2.5 font-medium whitespace-nowrap">Хранение</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {meta.categories.map((c) => {
                const Icon = CATEGORY_ICON[c.code]
                const types = meta.doc_types.filter((t) => t.category === c.code)
                const years = types.map((t) => t.retention_years)
                const min = Math.min(...years)
                const max = Math.max(...years)
                return (
                  <tr key={c.code} className="align-top">
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-2 font-medium text-slate-800">
                        {Icon && <Icon size={15} className="text-navy-800" />} {c.name}
                      </div>
                      <div className="mt-0.5 max-w-xs text-xs text-slate-500">{c.description}</div>
                    </td>
                    <td className="px-3 py-3 font-mono text-xs text-slate-600">{c.prefix}</td>
                    <td className="px-3 py-3 text-xs text-slate-600">
                      {{ medical: 'Медтайна', personal: 'ПД', internal: 'ДСП' }[c.confidentiality]}
                    </td>
                    <td className="px-3 py-3 text-xs text-slate-600">
                      {c.create.map((r) => roles.find((x) => x.code === r)?.name).join(', ')}
                    </td>
                    <td className="px-3 py-3 text-xs text-slate-600">{types.map((t) => t.name).join('; ')}</td>
                    <td className="px-3 py-3 text-xs whitespace-nowrap text-slate-600">
                      {max >= 99 ? (min >= 99 ? 'постоянно' : `${min} лет — постоянно`)
                        : min === max ? `${min} лет` : `${min}–${max} лет`}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="border-t border-slate-100 px-5 py-3 text-[11px] text-slate-500">
          Сроки хранения — демонстрационные; при внедрении сверяются с утверждённой номенклатурой дел КБТУ.
        </p>
      </Card>

      <Card title="Матрица доступа ролей">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-slate-50 text-slate-500">
                <th className="px-5 py-2.5 text-left font-medium">Раздел</th>
                {roles.map((r) => (
                  <th key={r.code} className="px-2 py-2.5 text-center font-medium">
                    {r.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {meta.categories.map((c) => (
                <tr key={c.code}>
                  <td className="px-5 py-2 font-medium whitespace-nowrap text-slate-700">{c.name}</td>
                  {roles.map((r) => {
                    const a = c.access[r.code]
                    const creates = c.create.includes(r.code)
                    return (
                      <td key={r.code} className="px-2 py-2 text-center">
                        <span
                          title={a === 'full' ? 'Полный доступ' : a === 'meta' ? 'Только карточка' : 'Нет доступа'}
                          className={clsx(
                            'inline-flex h-6 min-w-6 items-center justify-center rounded-md px-1 font-semibold',
                            a === 'full' && 'bg-navy-900 text-white',
                            a === 'meta' && 'bg-navy-900/10 text-navy-800',
                            !a && 'text-slate-300',
                          )}
                        >
                          {a === 'full' ? (creates ? 'R+W' : 'R') : a === 'meta' ? 'K' : '—'}
                        </span>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap gap-4 border-t border-slate-100 px-5 py-3 text-[11px] text-slate-500">
          <span><b className="text-navy-900">R+W</b> — читает и регистрирует</span>
          <span><b className="text-navy-900">R</b> — полный просмотр</span>
          <span><b className="text-navy-800">K</b> — только карточка, без файла</span>
          <span>— раздел скрыт</span>
        </div>
      </Card>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {PRINCIPLES.map((p) => (
          <div key={p.title} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <p.icon size={16} className="text-navy-800" />
              <span className="flex-1 text-sm font-semibold text-slate-800">{p.title}</span>
              <span className={clsx('rounded-md px-1.5 py-0.5 text-[10px] font-medium',
                p.done ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500')}>
                {p.done ? 'реализовано' : 'план'}
              </span>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-slate-600">{p.text}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
