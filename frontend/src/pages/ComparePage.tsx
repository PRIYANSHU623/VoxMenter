import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AlertCircle, ArrowLeft, Loader2 } from 'lucide-react'
import { getErrorMessage } from '../api/client'
import {
  evaluateSession,
  getQuestion,
  getSession,
  listEvaluations,
  listRecordings,
  listSessionQuestions,
} from '../api/endpoints'
import AudioPlayer from '../components/recording/AudioPlayer'
import type { CategoryKey, Evaluation, Question, Recording } from '../types/api'
import { formatDate } from '../utils/formatDate'
import { formatDuration } from '../utils/formatDuration'
import { CATEGORY_KEYS, CATEGORY_SCORE_LABELS, categoryLabel } from '../utils/labels'

interface Attempt {
  recording: Recording
  number: number
  evaluation: Evaluation | null
}

function show(value: number | null | undefined): string {
  return typeof value === 'number' ? String(Math.round(value)) : '—'
}

function diff(a: number | null | undefined, b: number | null | undefined): number | null {
  return typeof a === 'number' && typeof b === 'number' ? b - a : null
}

function Delta({ value }: { value: number | null }) {
  if (value === null) return <span className="text-muted">—</span>
  const rounded = Math.round(value)
  if (rounded === 0) return <span className="text-muted">0</span>
  return (
    <span className={rounded > 0 ? 'text-ok' : 'text-danger'}>
      {rounded > 0 ? '+' : ''}
      {rounded}
    </span>
  )
}

function attemptMeta(attempt: Attempt): string {
  const { recording } = attempt
  const length =
    recording.duration_seconds != null ? ` · ${formatDuration(recording.duration_seconds)}` : ''
  return `${formatDate(recording.created_at)}${length}`
}

function ScoreRow({
  label,
  a,
  b,
  className = '',
}: {
  label: string
  a: number | null | undefined
  b: number | null | undefined
  className?: string
}) {
  return (
    <div
      className={`grid grid-cols-[1fr_3.5rem_3.5rem_3.5rem] items-baseline gap-2 border-b border-line py-3 text-sm ${className}`}
    >
      <span>{label}</span>
      <span className="text-right font-mono tabular-nums">{show(a)}</span>
      <span className="text-right font-mono tabular-nums">{show(b)}</span>
      <span className="text-right font-mono tabular-nums">
        <Delta value={diff(a, b)} />
      </span>
    </div>
  )
}

function List({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) return <p className="text-sm text-muted">{empty}</p>
  return (
    <ul className="space-y-2 text-sm leading-relaxed">
      {items.map((item, index) => (
        <li key={index} className="flex gap-3">
          <span aria-hidden="true" className="mt-2 h-1 w-1 shrink-0 rounded-full bg-muted" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  )
}

const selectClass =
  'mt-2 h-11 w-full rounded-md border border-line bg-raised px-3 text-base text-ink focus:border-accent'

export default function ComparePage() {
  const sessionId = Number(useParams().sessionId)
  const invalidId = !Number.isInteger(sessionId) || sessionId < 1

  const [loading, setLoading] = useState(!invalidId)
  const [error, setError] = useState<string | null>(invalidId ? 'Invalid session.' : null)
  const [question, setQuestion] = useState<Question | null>(null)
  const [attempts, setAttempts] = useState<Attempt[]>([])
  const [selection, setSelection] = useState<{ a: number; b: number } | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  const [evaluatingId, setEvaluatingId] = useState<number | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const evaluateLock = useRef(false)

  useEffect(() => {
    if (invalidId) return
    let cancelled = false

    async function load() {
      try {
        const [session, sessionQuestions] = await Promise.all([
          getSession(sessionId),
          listSessionQuestions(sessionId),
        ])
        const [q, recordingLists, evaluations] = await Promise.all([
          getQuestion(session.question_id),
          Promise.all(sessionQuestions.map((sq) => listRecordings(sq.id))),
          listEvaluations(sessionId),
        ])
        if (cancelled) return

        // Newest evaluation wins when an attempt was evaluated more than once.
        // Older evaluations without a recording_id can't be matched to an attempt.
        const byRecording = new Map<number, Evaluation>()
        for (const evaluation of evaluations) {
          const id = evaluation.report?.recording_id
          if (typeof id === 'number') byRecording.set(id, evaluation)
        }

        const built: Attempt[] = recordingLists
          .flat()
          .filter((r) => r.transcript && r.transcript.trim() !== '')
          .sort((x, y) => x.created_at.localeCompare(y.created_at))
          .map((recording, index) => ({
            recording,
            number: index + 1,
            evaluation: byRecording.get(recording.recording_id) ?? null,
          }))

        setQuestion(q)
        setAttempts(built)
        // Keep the user's choice on refresh; otherwise default to the last two attempts.
        setSelection((previous) => {
          if (previous) return previous
          if (built.length < 2) return null
          return {
            a: built[built.length - 2].recording.recording_id,
            b: built[built.length - 1].recording.recording_id,
          }
        })
      } catch (err) {
        if (!cancelled) setError(getErrorMessage(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [sessionId, invalidId, reloadKey])

  async function handleEvaluate(recordingId: number) {
    if (evaluateLock.current) return
    evaluateLock.current = true
    setEvaluatingId(recordingId)
    setActionError(null)
    try {
      await evaluateSession(sessionId, recordingId)
      setReloadKey((key) => key + 1)
    } catch (err) {
      setActionError(getErrorMessage(err))
    } finally {
      evaluateLock.current = false
      setEvaluatingId(null)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-24 text-muted">
        <Loader2 className="animate-spin" aria-label="Loading attempts" />
      </div>
    )
  }

  if (error) {
    return (
      <div>
        <p className="font-display text-xl">We couldn’t load this comparison</p>
        <p className="mt-2 flex items-start gap-2 text-danger">
          <AlertCircle size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
          {error}
        </p>
        <Link
          to="/history"
          className="mt-6 inline-flex h-11 items-center rounded-md border border-line px-5 text-sm hover:border-ink"
        >
          Back to history
        </Link>
      </div>
    )
  }

  const backLink = (
    <Link
      to="/history"
      className="inline-flex items-center gap-2 text-sm text-muted transition-colors hover:text-ink"
    >
      <ArrowLeft size={16} aria-hidden="true" />
      History
    </Link>
  )

  if (attempts.length < 2 || !selection) {
    return (
      <div>
        {backLink}
        <p className="eyebrow mt-8">Compare attempts</p>
        <h1 className="mt-2 text-3xl font-semibold">You need two attempts to compare</h1>
        <p className="mt-3 max-w-xl text-muted">
          {attempts.length === 0
            ? 'This question has no transcribed recordings yet.'
            : 'This question has one transcribed attempt so far. Record another answer to see how you changed.'}
        </p>
        <Link
          to={`/record/${sessionId}`}
          className="mt-6 inline-flex h-11 items-center rounded-md bg-accent px-5 text-sm font-medium text-accent-fg hover:bg-accent-hover"
        >
          Record another attempt
        </Link>
      </div>
    )
  }

  const picked = [selection.a, selection.b]
    .map((id) => attempts.find((a) => a.recording.recording_id === id))
    .filter((a): a is Attempt => a !== undefined)
    .sort((x, y) => x.number - y.number)

  const [first, second] = picked
  if (!first || !second) return null

  const reportA = first.evaluation?.report ?? null
  const reportB = second.evaluation?.report ?? null
  const bothEvaluated = reportA !== null && reportB !== null

  const categoryChanges = CATEGORY_KEYS.map((key: CategoryKey) => {
    const a = reportA?.scores?.[key]?.score
    const b = reportB?.scores?.[key]?.score
    return { key, a, b, delta: diff(a, b) }
  })

  const improved = categoryChanges
    .filter((c) => c.delta !== null && c.delta > 0)
    .sort((x, y) => (y.delta ?? 0) - (x.delta ?? 0))
    .slice(0, 3)
  const slipped = categoryChanges
    .filter((c) => c.delta !== null && c.delta < 0)
    .sort((x, y) => (x.delta ?? 0) - (y.delta ?? 0))
    .slice(0, 3)

  const unevaluated = [first, second].filter((a) => !a.evaluation)

  return (
    <div>
      {backLink}

      <p className="eyebrow mt-8">
        Compare attempts{question ? ` · ${categoryLabel(question.category)}` : ''}
      </p>
      <h1 className="mt-2 max-w-3xl text-3xl font-semibold">
        {question?.title ?? `Session ${sessionId}`}
      </h1>

      {/* ---------- Pick two attempts ---------- */}
      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        {(['a', 'b'] as const).map((slot, index) => {
          const other = slot === 'a' ? selection.b : selection.a
          return (
            <div key={slot}>
              <label htmlFor={`attempt-${slot}`} className="eyebrow">
                {index === 0 ? 'Compare' : 'With'}
              </label>
              <select
                id={`attempt-${slot}`}
                value={selection[slot]}
                onChange={(e) =>
                  setSelection({ ...selection, [slot]: Number(e.target.value) })
                }
                className={selectClass}
              >
                {attempts.map((attempt) => (
                  <option
                    key={attempt.recording.recording_id}
                    value={attempt.recording.recording_id}
                    disabled={attempt.recording.recording_id === other}
                  >
                    Attempt {attempt.number} · {attemptMeta(attempt)}
                  </option>
                ))}
              </select>
            </div>
          )
        })}
      </div>

      {/* ---------- Missing evaluations ---------- */}
      {unevaluated.length > 0 && (
        <div className="mt-8 border-l-2 border-warn bg-surface px-4 py-3 text-sm">
          <p>
            {unevaluated.length === 2
              ? 'Neither attempt has an evaluation yet, so scores can’t be compared.'
              : `Attempt ${unevaluated[0].number} has no evaluation yet, so its scores can’t be compared.`}
          </p>
          <div className="mt-3 flex flex-wrap gap-3">
            {unevaluated.map((attempt) => (
              <button
                key={attempt.recording.recording_id}
                type="button"
                onClick={() => handleEvaluate(attempt.recording.recording_id)}
                disabled={evaluatingId !== null}
                className="inline-flex h-10 items-center gap-2 rounded-md bg-accent px-4 font-medium text-accent-fg hover:bg-accent-hover disabled:opacity-60"
              >
                {evaluatingId === attempt.recording.recording_id && (
                  <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                )}
                {evaluatingId === attempt.recording.recording_id
                  ? 'Evaluating…'
                  : `Evaluate attempt ${attempt.number}`}
              </button>
            ))}
          </div>
          {actionError && <p className="mt-3 text-danger">{actionError}</p>}
        </div>
      )}

      {/* ---------- Audio ---------- */}
      <section className="mt-12" aria-label="Recordings">
        <h2 className="text-2xl font-semibold">Listen</h2>
        <div className="mt-5 grid gap-8 md:grid-cols-2">
          {[first, second].map((attempt) => (
            <div key={attempt.recording.recording_id}>
              <p className="eyebrow mb-3">
                Attempt {attempt.number} · {attemptMeta(attempt)}
              </p>
              <AudioPlayer recordingId={attempt.recording.recording_id} />
            </div>
          ))}
        </div>
      </section>

      {/* ---------- Scores ---------- */}
      <section className="mt-14" aria-label="Score changes">
        <h2 className="text-2xl font-semibold">Score changes</h2>
        <div className="mt-5 border-t border-line">
          <div className="grid grid-cols-[1fr_3.5rem_3.5rem_3.5rem] gap-2 border-b border-line py-2">
            <span />
            <span className="eyebrow text-right">#{first.number}</span>
            <span className="eyebrow text-right">#{second.number}</span>
            <span className="eyebrow text-right">Change</span>
          </div>
          <ScoreRow
            label="Overall"
            a={reportA?.calculated_scores?.overall_score}
            b={reportB?.calculated_scores?.overall_score}
            className="font-semibold"
          />
          <ScoreRow
            label="Technical"
            a={first.evaluation?.technical_score}
            b={second.evaluation?.technical_score}
            className="text-tech"
          />
          <ScoreRow
            label="Communication"
            a={first.evaluation?.communication_score}
            b={second.evaluation?.communication_score}
            className="text-comm"
          />
        </div>

        <h3 className="mt-10 font-sans text-base font-semibold">By category</h3>
        <div className="mt-3 border-t border-line">
          {categoryChanges.map(({ key, a, b }) => (
            <ScoreRow key={key} label={CATEGORY_SCORE_LABELS[key]} a={a} b={b} />
          ))}
        </div>
      </section>

      {/* ---------- Progress and what's left ---------- */}
      {bothEvaluated && reportB && (
        <section className="mt-14" aria-label="Improvements and weaknesses">
          <h2 className="text-2xl font-semibold">What changed</h2>
          <div className="mt-6 grid gap-10 md:grid-cols-2">
            <div>
              <h3 className="mb-3 font-sans text-base font-semibold">Improved</h3>
              {improved.length === 0 ? (
                <p className="text-sm text-muted">No category went up between these attempts.</p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {improved.map((c) => (
                    <li key={c.key} className="flex justify-between gap-4 border-b border-line py-2">
                      <span>{CATEGORY_SCORE_LABELS[c.key]}</span>
                      <span className="font-mono tabular-nums text-ok">
                        +{Math.round(c.delta ?? 0)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {slipped.length > 0 && (
                <>
                  <h3 className="mb-3 mt-8 font-sans text-base font-semibold">Slipped</h3>
                  <ul className="space-y-2 text-sm">
                    {slipped.map((c) => (
                      <li key={c.key} className="flex justify-between gap-4 border-b border-line py-2">
                        <span>{CATEGORY_SCORE_LABELS[c.key]}</span>
                        <span className="font-mono tabular-nums text-danger">
                          {Math.round(c.delta ?? 0)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>

            <div>
              <h3 className="mb-3 font-sans text-base font-semibold">
                Still to work on (attempt {second.number})
              </h3>
              <List items={reportB.improvements ?? []} empty="No suggestions were listed." />
              <h3 className="mb-3 mt-8 font-sans text-base font-semibold">Points still missing</h3>
              <List items={reportB.missing_points ?? []} empty="No missing points were identified." />
            </div>
          </div>
        </section>
      )}

      {/* ---------- Transcripts ---------- */}
      <section className="mt-14" aria-label="Transcripts">
        <h2 className="text-2xl font-semibold">Transcripts</h2>
        <div className="mt-5 grid gap-8 md:grid-cols-2">
          {[first, second].map((attempt) => (
            <div key={attempt.recording.recording_id} className="min-w-0">
              <p className="eyebrow mb-3">Attempt {attempt.number}</p>
              <p className="max-h-96 overflow-y-auto whitespace-pre-wrap border-l-2 border-line pl-4 leading-relaxed">
                {attempt.recording.transcript}
              </p>
            </div>
          ))}
        </div>
      </section>

      <p className="mt-14 border-t border-line pt-6 text-xs text-muted">
        Only attempts with a transcript are listed. Evaluations saved before attempts were
        tracked can’t be matched to a recording, so those attempts show as not evaluated.
      </p>
    </div>
  )
}