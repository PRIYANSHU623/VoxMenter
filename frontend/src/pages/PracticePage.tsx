import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, ArrowRight, Loader2 } from 'lucide-react'
import { getErrorMessage } from '../api/client'
import { addSessionQuestion, createSession, listQuestions } from '../api/endpoints'
import type { Question } from '../types/api'
import { categoryLabel } from '../utils/labels'

const DIFFICULTY_ORDER = ['beginner', 'intermediate', 'advanced']

function sortDifficulties(values: string[]): string[] {
  const rank = (v: string) => {
    const index = DIFFICULTY_ORDER.indexOf(v.toLowerCase())
    return index === -1 ? DIFFICULTY_ORDER.length : index
  }
  return [...values].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
}

function FilterGroup({
  label,
  options,
  value,
  onChange,
  format = (v: string) => v,
}: {
  label: string
  options: string[]
  value: string
  onChange: (value: string) => void
  format?: (value: string) => string
}) {
  const items = ['all', ...options]
  return (
    <div>
      <p className="eyebrow mb-2">{label}</p>
      <div className="flex flex-wrap gap-2">
        {items.map((item) => {
          const active = item === value
          return (
            <button
              key={item}
              type="button"
              aria-pressed={active}
              onClick={() => onChange(item)}
              className={[
                'min-h-9 rounded-full border px-4 text-sm transition-colors',
                active
                  ? 'border-ink bg-ink text-canvas'
                  : 'border-line text-muted hover:border-ink hover:text-ink',
              ].join(' ')}
            >
              {item === 'all' ? 'All' : format(item)}
            </button>
          )
        })}
      </div>
    </div>
  )
}

export default function PracticePage() {
  const navigate = useNavigate()
  const [questions, setQuestions] = useState<Question[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  const [category, setCategory] = useState('all')
  const [difficulty, setDifficulty] = useState('all')

  const [startingId, setStartingId] = useState<number | null>(null)
  const [startError, setStartError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listQuestions({ limit: 100 })
      .then((data) => {
        if (cancelled) return
        setQuestions(data)
        setLoadError(null)
      })
      .catch((err) => {
        if (!cancelled) setLoadError(getErrorMessage(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [reloadKey])

  function retry() {
    setLoading(true)
    setLoadError(null)
    setReloadKey((key) => key + 1)
  }

  const categories = useMemo(
    () => [...new Set(questions.map((q) => q.category))].sort(),
    [questions],
  )
  const difficulties = useMemo(
    () => sortDifficulties([...new Set(questions.map((q) => q.difficulty))]),
    [questions],
  )

  const visible = questions.filter(
    (q) =>
      (category === 'all' || q.category === category) &&
      (difficulty === 'all' || q.difficulty === difficulty),
  )

  async function handleStart(question: Question) {
    if (startingId !== null) return
    setStartingId(question.id)
    setStartError(null)
    try {
      const session = await createSession(question.id)
      await addSessionQuestion(session.id, question.id)
      navigate(`/record/${session.id}`)
    } catch (err) {
      setStartError(getErrorMessage(err))
      setStartingId(null)
    }
  }

  return (
    <div>
      <p className="eyebrow">Practice</p>
      <h1 className="mt-2 text-3xl font-semibold">Choose a question</h1>
      <p className="mt-2 max-w-xl text-muted">
        Pick a question, record your answer out loud, and get a review of both
        the technical content and how you said it.
      </p>

      {!loading && !loadError && questions.length > 0 && (
        <div className="mt-8 space-y-5">
          <FilterGroup
            label="Category"
            options={categories}
            value={category}
            onChange={setCategory}
            format={categoryLabel}
          />
          <FilterGroup
            label="Difficulty"
            options={difficulties}
            value={difficulty}
            onChange={setDifficulty}
          />
        </div>
      )}

      {startError && (
        <div
          role="alert"
          className="mt-6 flex items-start gap-2 border-l-2 border-danger bg-surface px-3 py-2 text-sm text-danger"
        >
          <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>{startError}</span>
        </div>
      )}

      <div className="mt-8 border-t border-line">
        {loading && (
          <div aria-label="Loading questions" className="animate-pulse">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="border-b border-line py-6">
                <div className="h-4 w-2/3 rounded bg-surface" />
                <div className="mt-3 h-3 w-1/3 rounded bg-surface" />
              </div>
            ))}
          </div>
        )}

        {!loading && loadError && (
          <div className="py-10">
            <p className="text-danger">{loadError}</p>
            <button
              type="button"
              onClick={retry}
              className="mt-4 h-11 rounded-md border border-line px-4 text-sm hover:bg-surface"
            >
              Try again
            </button>
          </div>
        )}

        {!loading && !loadError && questions.length === 0 && (
          <div className="py-10">
            <p className="font-display text-xl">No questions yet</p>
            <p className="mt-2 max-w-md text-muted">
              The question bank is empty. Add questions through the API docs at
              /docs, then come back here.
            </p>
          </div>
        )}

        {!loading && !loadError && questions.length > 0 && visible.length === 0 && (
          <div className="py-10">
            <p className="font-display text-xl">Nothing matches these filters</p>
            <button
              type="button"
              onClick={() => {
                setCategory('all')
                setDifficulty('all')
              }}
              className="mt-4 h-11 rounded-md border border-line px-4 text-sm hover:bg-surface"
            >
              Clear filters
            </button>
          </div>
        )}

        {!loading &&
          !loadError &&
          visible.map((question) => {
            const starting = startingId === question.id
            return (
              <article
                key={question.id}
                className="flex flex-col gap-4 border-b border-line py-6 sm:flex-row sm:items-start sm:justify-between"
              >
                <div className="min-w-0">
                  <p className="eyebrow">
                    {categoryLabel(question.category)} · {question.difficulty}
                  </p>
                  <h2 className="mt-2 text-xl font-semibold">{question.title}</h2>
                  {question.description && (
                    <p className="mt-2 max-w-2xl text-sm text-muted">
                      {question.description}
                    </p>
                  )}
                </div>

                <button
                  type="button"
                  onClick={() => handleStart(question)}
                  disabled={startingId !== null}
                  className="inline-flex h-11 shrink-0 items-center justify-center gap-2 rounded-md border border-ink px-5 text-sm font-medium transition-colors hover:border-accent hover:bg-accent hover:text-accent-fg disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {starting ? (
                    <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                  ) : (
                    <ArrowRight size={16} aria-hidden="true" />
                  )}
                  {starting ? 'Starting…' : 'Start'}
                </button>
              </article>
            )
          })}
      </div>
    </div>
  )
}