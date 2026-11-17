import {
  Archive,
  BookOpen,
  Briefcase,
  CheckCircle2,
  Clock3,
  EyeOff,
  FolderOpen,
  GraduationCap,
  HeartPulse,
  Lock,
  Plane,
  ScrollText,
  Users,
  Wallet,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import clsx from 'clsx'
import type { Access, DocStatus } from '../../edo'

export const CATEGORY_ICON: Record<string, LucideIcon> = {
  personal_file: FolderOpen,
  admissions: GraduationCap,
  academic: BookOpen,
  practice: Briefcase,
  medical: HeartPulse,
  business_trips: Plane,
  hr: Users,
  orders: ScrollText,
  finance: Wallet,
}

const STATUS: Record<DocStatus, { cls: string; icon: LucideIcon }> = {
  on_approval: { cls: 'bg-amber-50 text-amber-800 ring-amber-200', icon: Clock3 },
  approved: { cls: 'bg-emerald-50 text-emerald-800 ring-emerald-200', icon: CheckCircle2 },
  rejected: { cls: 'bg-rose-50 text-rose-800 ring-rose-200', icon: XCircle },
  archived: { cls: 'bg-slate-100 text-slate-700 ring-slate-200', icon: Archive },
}

export function StatusBadge({ status, label, overdue }: { status: DocStatus; label: string; overdue?: boolean }) {
  const s = STATUS[status]
  const Icon = s.icon
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span className={clsx('inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1', s.cls)}>
        <Icon size={12} />
        {label}
      </span>
      {overdue && (
        <span className="rounded-md bg-rose-600 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-white uppercase">
          срок
        </span>
      )}
    </span>
  )
}

export function AccessBadge({ access }: { access: Access }) {
  if (access === 'full') return null
  return (
    <span
      title="Видна только карточка: файл и примечания доступны подразделению-владельцу"
      className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600"
    >
      <EyeOff size={11} /> только карточка
    </span>
  )
}

export function ConfidentialityBadge({ level }: { level: string }) {
  const map: Record<string, string> = {
    medical: 'Медицинская тайна',
    personal: 'Персональные данные',
    internal: 'Для служебного пользования',
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-navy-900/5 px-1.5 py-0.5 text-[11px] text-navy-800">
      <Lock size={11} /> {map[level] ?? level}
    </span>
  )
}

export function Kpi({
  label,
  value,
  hint,
  tone = 'default',
  icon: Icon,
}: {
  label: string
  value: number | string
  hint?: string
  tone?: 'default' | 'warn' | 'bad'
  icon: LucideIcon
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between text-xs text-slate-500">
        {label}
        <Icon
          size={16}
          className={clsx(tone === 'bad' ? 'text-rose-500' : tone === 'warn' ? 'text-amber-500' : 'text-brand-500')}
        />
      </div>
      <div className="mt-2 font-display text-3xl font-bold text-navy-900 tabular-nums">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  )
}

export function Card({ title, action, children, className }: {
  title?: React.ReactNode
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={clsx('rounded-2xl border border-slate-200 bg-white shadow-sm', className)}>
      {title && (
        <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-5 py-3">
          <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

export function Empty({ text }: { text: string }) {
  return <div className="px-5 py-10 text-center text-sm text-slate-500">{text}</div>
}
