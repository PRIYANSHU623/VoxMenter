import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown, Loader2 } from 'lucide-react'
import { getErrorMessage } from '../api/client'
import { listRecordings, listSessionQuestions } from '../api/endpoints'
import AudioPlayer from '../components/recording/AudioPlayer'
import { useAttempts } from '../hooks/useAttempts'
import type { Attempt } from '../hooks/useAttempts'
import type { Recording } from '../types/api'
import { formatDate } from '../utils/formatDate'
import { formatDuration } from '../utils/formatDuration'
import { categoryLabel } from '../utils/labels'

type StatusFilter = 'all' | 'evaluated' | 'unfinished'

const PAGE_SIZE = 10

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'evaluated', label: 'Evaluated' },
  { value: 'unfinished', label: 'Unfinished' },
]

function show(value: number | null | undefined): string {
  return typeof value === 'number' ? String(Math.round(value)) : '—'
}

function formatSize(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: string
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={[
        'min-h-9 rounded-full border px-4 text-sm transition-colors',
        active
          ? 'border-ink bg-ink text-canvas'
          : 'border-line text-muted hover:border-ink hover:text-ink',
      ].join(' ')}
    >
      {children}
    </button>
  )
}

// Loaded only when a row is opened, so the list itself stays fast.
function RecordingsPanel({ sessionId }: { sessionId: number }) {
  const [recordings, setRecordings] = useState<Recording[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const sessionQuestions = await listSessionQuestions(sessionId)
        const lists = await Promise.all(sessionQuestions.map((sq) => listRecordings(sq.id)))
        if (cancelled) return
        setRecordings(lists.flat().sort((a, b) => a.created_at.localeCompare(b.created_at)))
      } catch (err) {
        if (!cancelled) setError(getErrorMessage(err))
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [sessionId])

  if (error) return <p className="py-4 text-sm text-danger">{error}</p>

  if (!recordings) {
    return (
      <div className="flex py-4 text-muted">
        <Loader2 size={18} className="animate-spin" aria-label="Loading recordings" />
      </div>
    )
  }

  if (recordings.length === 0) {
    return <p className="py-4 text-sm text-muted">No recordings were saved for this session.</p>
  }

  return (
    <>
    {recordings.length >= 2 && (
      <div className="pt-4">
        <Link
          to={`/compare/${sessionId}`}
          className="inline-flex h-10 items-center rounded-md border border-ink px-4 text-sm font-medium transition-colors hover:border-accent hover:bg-accent hover:text-accent-fg"
        >
          Compare attempts
        </Link>
      </div>
    )}
    <ul className="divide-y divide-line">
      {recordings.map((recording, index) => (
        <li key={recording.recording_id} className="py-5">
          <p className="eyebrow">
            Attempt {index + 1} · {formatDate(recording.created_at)} ·{' '}
            {recording.duration_seconds != null
              ? formatDuration(recording.duration_seconds)
              : formatSize(recording.size_bytes)}
          </p>
          <div className="mt-3 max-w-md">
            <AudioPlayer recordingId={recording.recording_id} />
          </div>
          {recording.transcript ? (
            <p className="mt-4 max-h-48 max-w-3xl overflow-y-auto whitespace-pre-wrap border-l-2 border-line pl-4 text-sm leading-relaxed">
              {recording.transcript}
            </p>
          ) : (
            <p className="mt-4 text-sm text-muted">No transcript for this attempt.</p>
          )}
        </li>
      ))}
    </ul>    
    </>
  )
}


function HistoryRow({
  attempt,
  open,
  onToggle,
}: {
  attempt: Attempt
  open: boolean
  onToggle: () => void
}) {
  const { session, question, evaluation } = attempt

  return (
    <li className="border-b border-line py-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="eyebrow">
            {question ? categoryLabel(question.category) : 'Question'} ·{' '}
            {formatDate(session.created_at)}
            {session.duration_seconds != null &&
              ` · ${formatDuration(session.duration_seconds)}`}
          </p>
          <h2 className="mt-1 text-lg font-semibold">
            {question?.title ?? `Session ${session.id}`}
          </h2>
        </div>

        <div className="flex shrink-0 items-center gap-6 text-sm">
          {evaluation ? (
            <>
              <span>
                <span className="eyebrow mr-2 text-tech">Tech</span>
                <span className="font-mono tabular-nums text-tech">
                  {show(evaluation.technical_score)}
                </span>
              </span>
              <span>
                <span className="eyebrow mr-2 text-comm">Comm</span>
                <span className="font-mono tabular-nums text-comm">
                  {show(evaluation.communication_score)}
                </span>
              </span>
            </>
          ) : (
            <span className="text-muted">Not evaluated</span>
          )}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        {evaluation ? (
          <Link
            to={`/review/${session.id}`}
            className="inline-flex h-10 items-center rounded-md border border-ink px-4 text-sm font-medium transition-colors hover:border-accent hover:bg-accent hover:text-accent-fg"
          >
            Open report
          </Link>
        ) : (
          <Link
            to={`/record/${session.id}`}
            className="inline-flex h-10 items-center rounded-md bg-accent px-4 text-sm font-medium text-accent-fg hover:bg-accent-hover"
          >
            Continue
          </Link>
        )}
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm text-muted transition-colors hover:text-ink"
        >
          Recordings
          <ChevronDown
            size={16}
            aria-hidden="true"
            className={`transition-transform ${open ? 'rotate-180' : ''}`}
          />
        </button>
      </div>

      {open && (
        <div className="mt-2 border-t border-line">
          <RecordingsPanel sessionId={session.id} />
        </div>
      )}
    </li>
  )
}

export default function HistoryPage() {
  const { attempts, loading, error, reload } = useAttempts()
  const [category, setCategory] = useState('all')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)
  const [openId, setOpenId] = useState<number | null>(null)

  const categories = useMemo(
    () =>
      [...new Set(attempts.map((a) => a.question?.category).filter((c): c is string => !!c))].sort(),
    [attempts],
  )

  const filtered = attempts.filter((a) => {
    if (category !== 'all' && a.question?.category !== category) return false
    if (status === 'evaluated' && !a.evaluation) return false
    if (status === 'unfinished' && a.evaluation) return false
    return true
  })

  const shown = filtered.slice(0, visibleCount)

  function changeCategory(value: string) {
    setCategory(value)
    setVisibleCount(PAGE_SIZE)
  }

  function changeStatus(value: StatusFilter) {
    setStatus(value)
    setVisibleCount(PAGE_SIZE)
  }

  return (
    <div>
      <p className="eyebrow">History</p>
      <h1 className="mt-2 text-3xl font-semibold">Your practice sessions</h1>
      <p className="mt-2 max-w-xl text-muted">
        Revisit earlier answers, listen to your recordings and reopen any report.
      </p>

      {loading && (
        <div className="flex justify-center py-24 text-muted">
          <Loader2 className="animate-spin" aria-label="Loading history" />
        </div>
      )}

      {!loading && error && (
        <div className="mt-10">
          <p className="text-danger">{error}</p>
          <button
            type="button"
            onClick={reload}
            className="mt-4 h-11 rounded-md border border-line px-4 text-sm hover:bg-surface"
          >
            Try again
          </button>
        </div>
      )}

      {!loading && !error && attempts.length === 0 && (
        <div className="mt-12 border-y border-line py-12">
          <p className="font-display text-2xl">Nothing here yet</p>
          <p className="mt-3 max-w-lg text-muted">
            Your sessions will be listed here once you record your first answer.
          </p>
          <Link
            to="/practice"
            className="mt-6 inline-flex h-11 items-center rounded-md bg-accent px-5 text-sm font-medium text-accent-fg hover:bg-accent-hover"
          >
            Start practice
          </Link>
        </div>
      )}

      {!loading && !error && attempts.length > 0 && (
        <>
          <div className="mt-8 space-y-5">
            <div>
              <p className="eyebrow mb-2">Status</p>
              <div className="flex flex-wrap gap-2">
                {STATUS_FILTERS.map((f) => (
                  <Chip key={f.value} active={status === f.value} onClick={() => changeStatus(f.value)}>
                    {f.label}
                  </Chip>
                ))}
              </div>
            </div>
            {categories.length > 1 && (
              <div>
                <p className="eyebrow mb-2">Category</p>
                <div className="flex flex-wrap gap-2">
                  <Chip active={category === 'all'} onClick={() => changeCategory('all')}>
                    All
                  </Chip>
                  {categories.map((c) => (
                    <Chip key={c} active={category === c} onClick={() => changeCategory(c)}>
                      {categoryLabel(c)}
                    </Chip>
                  ))}
                </div>
              </div>
            )}
          </div>

          {filtered.length === 0 ? (
            <div className="mt-10 border-t border-line py-10">
              <p className="font-display text-xl">No sessions match these filters</p>
              <button
                type="button"
                onClick={() => {
                  changeCategory('all')
                  changeStatus('all')
                }}
                className="mt-4 h-11 rounded-md border border-line px-4 text-sm hover:bg-surface"
              >
                Clear filters
              </button>
            </div>
          ) : (
            <>
              <ul className="mt-8 border-t border-line">
                {shown.map((attempt) => (
                  <HistoryRow
                    key={attempt.session.id}
                    attempt={attempt}
                    open={openId === attempt.session.id}
                    onToggle={() =>
                      setOpenId(openId === attempt.session.id ? null : attempt.session.id)
                    }
                  />
                ))}
              </ul>

              <div className="mt-6 flex items-center justify-between text-sm text-muted">
                <span>
                  Showing {shown.length} of {filtered.length}
                </span>
                {filtered.length > shown.length && (
                  <button
                    type="button"
                    onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}
                    className="h-11 rounded-md border border-line px-5 text-ink hover:border-ink"
                  >
                    Show more
                  </button>
                )}
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}