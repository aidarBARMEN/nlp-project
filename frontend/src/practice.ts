// API автопроверки документов практики (/api/practice)

export type CheckStatus = 'fail' | 'warn' | 'info' | 'pass'

export interface Finding {
  id: string
  group: string
  title: string
  status: CheckStatus
  message: string
  where: string[]
}

export interface DocumentCheck {
  kind: 'report' | 'diary'
  title: string
  file_name: string
  ready: boolean
  counts: Record<CheckStatus, number>
  facts: Record<string, unknown>
  findings: Finding[]
}

export interface CheckResult {
  ready: boolean
  documents: DocumentCheck[]
  cross: Finding[]
}

export interface Requirements {
  report: { title: string; items: string[] }
  diary: { title: string; items: string[] }
}

async function parse<T>(res: Response): Promise<T> {
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

export const practice = {
  requirements: () => fetch('/api/practice/requirements').then((r) => parse<Requirements>(r)),
  check: (report: File | null, diary: File | null) => {
    const form = new FormData()
    if (report) form.append('report', report)
    if (diary) form.append('diary', diary)
    return fetch('/api/practice/check', { method: 'POST', body: form }).then((r) => parse<CheckResult>(r))
  },
}
