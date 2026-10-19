import { useEffect, useState } from 'react'
import { Cpu } from 'lucide-react'
import { api, type ModelInfo } from '../api'

const KEY = 'kbtu-assistant:llm'

/** Выбранная LLM для чата; запоминается в браузере. */
export function useSelectedModel() {
  const [model, setModel] = useState<string>(() => {
    try {
      return localStorage.getItem(KEY) ?? ''
    } catch {
      return ''
    }
  })
  const [models, setModels] = useState<ModelInfo[]>([])

  useEffect(() => {
    api
      .models()
      .then((m) => {
        setModels(m.llms)
        // сохранённая модель могла пропасть из конфигурации — откатываемся на модель по умолчанию
        setModel((cur) => (m.llms.some((x) => x.id === cur && x.available) ? cur : m.default_llm))
      })
      .catch(() => setModels([]))
  }, [])

  const select = (id: string) => {
    setModel(id)
    try {
      localStorage.setItem(KEY, id)
    } catch {
      /* storage недоступен */
    }
  }

  return { model, models, select }
}

const PROVIDER_LABEL: Record<string, string> = {
  openai: 'OpenAI (облако)',
  groq: 'Открытые модели · Groq',
  ollama: 'Локальные · Ollama',
}

export default function ModelPicker({
  model,
  models,
  onSelect,
  disabled,
}: {
  model: string
  models: ModelInfo[]
  onSelect: (id: string) => void
  disabled?: boolean
}) {
  if (!models.length) return null
  const groups = [...new Set(models.map((m) => m.provider))]
  return (
    <label className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs text-slate-600 shadow-sm">
      <Cpu size={13} className="text-brand-600" />
      <span className="sr-only">Модель</span>
      <select
        value={model}
        disabled={disabled}
        onChange={(e) => onSelect(e.target.value)}
        className="max-w-48 cursor-pointer bg-transparent font-medium text-slate-700 outline-none disabled:cursor-not-allowed"
      >
        {groups.map((g) => (
          <optgroup key={g} label={PROVIDER_LABEL[g] ?? g}>
            {models
              .filter((m) => m.provider === g)
              .map((m) => (
                <option key={m.id} value={m.id} disabled={!m.available}>
                  {m.label}
                  {m.note ? ` — ${m.note}` : ''}
                </option>
              ))}
          </optgroup>
        ))}
      </select>
    </label>
  )
}
