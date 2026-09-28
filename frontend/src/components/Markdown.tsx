import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/** [1], [1, 3], [2][4] -> кликабельные ссылки на источники */
function linkifyCitations(text: string) {
  return text.replace(/\[(\d{1,2}(?:\s*[,;]\s*\d{1,2})*)\](?!\()/g, (_, nums: string) =>
    nums
      .split(/\s*[,;]\s*/)
      .map((n) => `[${n}](#cite-${n})`)
      .join(''),
  )
}

export default function Markdown({ text, onCite }: { text: string; onCite?: (n: number) => void }) {
  return (
    <div className="prose prose-slate max-w-none prose-headings:font-semibold prose-p:leading-relaxed prose-a:text-brand-600 prose-code:rounded prose-code:bg-slate-100 prose-code:px-1 prose-code:before:content-none prose-code:after:content-none prose-table:text-sm prose-th:bg-slate-50 prose-li:my-0.5">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            if (href?.startsWith('#cite-')) {
              const n = Number(href.slice(6))
              return (
                <button
                  onClick={() => onCite?.(n)}
                  className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-0.5 items-center justify-center rounded-md bg-brand-100 px-1 align-middle text-[11px] font-semibold text-brand-700 no-underline transition hover:bg-brand-600 hover:text-white"
                >
                  {n}
                </button>
              )
            }
            return (
              <a href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            )
          },
        }}
      >
        {linkifyCitations(text)}
      </ReactMarkdown>
    </div>
  )
}
