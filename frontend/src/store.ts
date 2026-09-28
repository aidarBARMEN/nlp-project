import { useEffect, useState } from 'react'
import type { ChatMessage } from './api'

export interface Conversation {
  id: string
  title: string
  messages: ChatMessage[]
  updatedAt: number
}

const KEY = 'kbtu-assistant:conversations'

function load(): Conversation[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '[]')
  } catch {
    return []
  }
}

export const newConversation = (): Conversation => ({
  id: crypto.randomUUID(),
  title: 'Новый чат',
  messages: [],
  updatedAt: Date.now(),
})

export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>(load)
  const [activeId, setActiveId] = useState<string | null>(() => load()[0]?.id ?? null)

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(conversations.filter((c) => c.messages.length).slice(0, 50)))
    } catch {
      /* storage недоступен — работаем без сохранения */
    }
  }, [conversations])

  const active = conversations.find((c) => c.id === activeId) ?? null

  const create = () => {
    const c = newConversation()
    setConversations((prev) => [c, ...prev.filter((p) => p.messages.length)])
    setActiveId(c.id)
    return c
  }

  const update = (id: string, fn: (c: Conversation) => Conversation) =>
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...fn(c), updatedAt: Date.now() } : c)).sort((a, b) => b.updatedAt - a.updatedAt),
    )

  const remove = (id: string) => {
    setConversations((prev) => prev.filter((c) => c.id !== id))
    if (id === activeId) setActiveId(null)
  }

  return { conversations, active, activeId, setActiveId, create, update, remove }
}
