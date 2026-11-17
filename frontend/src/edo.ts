// API модуля документооборота (/api/edo). Роль передаётся заголовком X-EDO-Role.
import type { DocumentCheck } from './practice'

export type Access = 'full' | 'meta' | null
export type DocStatus = 'on_approval' | 'approved' | 'rejected' | 'archived'

export interface Role {
  code: string
  name: string
  unit: string
}

export interface Category {
  code: string
  name: string
  prefix: string
  description: string
  confidentiality: 'personal' | 'internal' | 'medical'
  access: Record<string, 'full' | 'meta'>
  create: string[]
  my_access: Access
}

export interface DocType {
  code: string
  name: string
  category: string
  retention_years: number
  route: string[]
  route_names: string[]
}

export interface Meta {
  roles: Role[]
  categories: Category[]
  doc_types: DocType[]
  creatable_types: string[]
  statuses: Record<DocStatus, string>
  person_kinds: Record<string, string>
  person_access: Record<string, string[]>
  checklist: { code: string; name: string }[]
  max_file_mb: number
}

export interface DocCard {
  id: number
  reg_number: string
  type_code: string
  type_name: string
  category: string
  category_name: string
  person_id: number | null
  person_name: string | null
  title: string
  status: DocStatus
  status_name: string
  confidentiality: string
  created_by: string
  created_at: string
  updated_at: string
  due_date: string | null
  retention_until: string
  notes: string | null
  file_name: string | null
  file_size: number | null
  file_sha256: string | null
  has_file: boolean
  overdue: boolean
  access: Access
  is_demo: number
  format_check: DocumentCheck | null
}

export interface RouteStep {
  id: number
  step: number
  role: string
  role_name: string
  status: 'pending' | 'approved' | 'rejected' | 'skipped'
  comment: string | null
  decided_at: string | null
}

export interface AuditEntry {
  id: number
  at: string
  role: string
  role_name: string
  action: string
  action_name: string
  details: string | null
}

export interface DocDetail extends DocCard {
  route: RouteStep[]
  audit: AuditEntry[]
  can_decide: boolean
  can_archive: boolean
}

export interface Dashboard {
  totals: Record<'all' | 'overdue' | 'new_30d' | DocStatus, number>
  pending_for_me: number
  by_category: { category: string; name: string; count: number; on_approval: number; access: Access }[]
  pending: DocCard[]
  recent: (AuditEntry & { document_id: number; reg_number: string; title: string })[]
  expiring: { id: number; reg_number: string; title: string; retention_until: string }[]
}

export interface Person {
  id: number
  kind: 'student' | 'applicant' | 'employee'
  kind_name: string
  full_name: string
  iin_masked: string | null
  school: string | null
  program: string | null
  course: number | null
  study_group: string | null
  position: string | null
  status: string
  email: string | null
  documents: number
  completeness?: number
  is_demo: number
}

export interface PersonalFile {
  person: Person
  groups: { category: string; name: string; documents: DocCard[] }[]
  checklist: { type_code: string; name: string; present: boolean; category_name: string }[]
  hidden_documents: number
}

async function call<T>(role: string, path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api/edo${path}`, { ...init, headers: { ...(init.headers || {}), 'X-EDO-Role': role } })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      /* не JSON */
    }
    throw new Error(detail)
  }
  return res.json()
}

const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== null && v !== '' && p.set(k, String(v)))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const edo = {
  meta: (role: string) => call<Meta>(role, '/meta'),
  dashboard: (role: string) => call<Dashboard>(role, '/dashboard'),
  documents: (
    role: string,
    f: { category?: string; status?: string; q?: string; person_id?: number; pending_for_me?: boolean } = {},
  ) => call<DocCard[]>(role, `/documents${qs(f)}`),
  document: (role: string, id: number) => call<DocDetail>(role, `/documents/${id}`),
  decide: (role: string, id: number, decision: 'approve' | 'reject', comment?: string) =>
    call<DocDetail>(role, `/documents/${id}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, comment }),
    }),
  archive: (role: string, id: number) => call<DocDetail>(role, `/documents/${id}/archive`, { method: 'POST' }),
  register: (role: string, form: FormData) => call<DocDetail>(role, '/documents', { method: 'POST', body: form }),
  fileUrl: (role: string, id: number) => `/api/edo/documents/${id}/file?role=${encodeURIComponent(role)}`,
  persons: (role: string, f: { kind?: string; q?: string } = {}) => call<Person[]>(role, `/persons${qs(f)}`),
  personalFile: (role: string, id: number) => call<PersonalFile>(role, `/persons/${id}`),
}

export const fmtDate = (iso: string | null | undefined, withTime = false) =>
  iso
    ? new Date(iso).toLocaleString('ru', withTime ? { dateStyle: 'short', timeStyle: 'short' } : { dateStyle: 'medium' })
    : '—'
