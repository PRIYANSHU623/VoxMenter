import { Link } from 'react-router-dom'
import { ArrowRight, Loader2 } from 'lucide-react'
import { useAttempts } from '../hooks/useAttempts'
import type { Attempt } from '../hooks/useAttempts'
import { useAuth } from '../hooks/useAuth'
import { formatDate } from '../utils/formatDate'
import { categoryLabel } from '../utils/labels'

const STATUS_LABELS: Record<string, string> = {
  pending: 'Not recorded',
  recording_uploaded: 'Recorded',
  transcribing: 'Transcribing',
  evaluating: 'Evaluating',
  completed: 'Evaluated',
  failed: 'Failed',
}

function average(values: number[]): number | null {
  if (values.length === 0) return null
  return values.reduce((sum, v) => sum + v, 0) / values.length
}

function show(value: number | null | undefined): string {
  return typeof value === 'number' ? String(Math.round(value)) : '—'
}

function Delta({ value }: { value: number | null }) {
  if (value === null) return null
  const rounded = Math.round(value)
  if (rounded === 0) return <span className="text-xs text-muted">no change</span>
  return (
    <span className={`text-xs ${rounded > 0 ? 'text-ok' : 'text-danger'}`}>
      {rounded > 0 ? '+' : ''}
      {rounded} since last attempt
    </span>
  )
}

function SessionRow({ attempt }: { attempt: Attempt }) {
  const { session, question, evaluation } = attempt
  // Evaluated sessions open the report; others go back to the recording room.
  const href = evaluation ? `/review/${session.id}` : `/record/${session.id}`

  return (
    <li className="border-b border-line">
      <Link
        to={href}
        className="flex flex-col gap-3 py-5 transition-colors hover:bg-surface sm:flex-row sm:items-center sm:justify-between sm:px-3"
      >
        <div className="min-w-0">
          <p className="eyebrow">
            {question ? categoryLabel(question.category) : 'Question'} ·{' '}
            {formatDate(session.created_at)}
          </p>
          <p className="mt-1 truncate font-medium">
            {question?.title ?? `Session ${session.id}`}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-6 text-sm">
          {evaluation ? (
            <>
              <span className="text-tech">
                <span className="eyebrow mr-2 text-tech">Tech</span>
                <span className="font-mono tabular-nums">{show(evaluation.technical_score)}</span>
              </span>
              <span className="text-comm">
                <span className="eyebrow mr-2 text-comm">Comm</span>
                <span className="font-mono tabular-nums">{show(evaluation.communication_score)}</span>
              </span>
            </>
          ) : (
            <span className="text-muted">{STATUS_LABELS[session.status] ?? session.status}</span>
          )}
        </div>
      </Link>
    </li>
  )
}

export default function DashboardPage() {
  const { user } = useAuth()
  const { attempts, loading, error, reload } = useAttempts()

  const name = user?.email.split('@')[0] ?? ''

  const evaluated = attempts
    .filter((a) => a.evaluation)
    .sort((a, b) =>
      (b.evaluation?.created_at ?? '').localeCompare(a.evaluation?.created_at ?? ''),
    )

  const latest = evaluated[0]?.evaluation ?? null
  const previous = evaluated[1]?.evaluation ?? null

  const technicalValues = evaluated
    .map((a) => a.evaluation?.technical_score)
    .filter((v): v is number => typeof v === 'number')
  const communicationValues = evaluated
    .map((a) => a.evaluation?.communication_score)
    .filter((v): v is number => typeof v === 'number')

  const diff = (a: number | null | undefined, b: number | null | undefined) =>
    typeof a === 'number' && typeof b === 'number' ? a - b : null

  return (
    <div>
      <p className="eyebrow">Dashboard</p>
      <div className="mt-2 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <h1 className="text-3xl font-semibold">
          Welcome back{name ? `, ${name}` : ''}
        </h1>
        <Link
          to="/practice"
          className="inline-flex h-11 items-center justify-center gap-2 rounded-md bg-accent px-5 text-sm font-medium text-accent-fg transition-colors hover:bg-accent-hover"
        >
          Start practice
          <ArrowRight size={16} aria-hidden="true" />
        </Link>
      </div>

      {loading && (
        <div className="flex justify-center py-24 text-muted">
          <Loader2 className="animate-spin" aria-label="Loading" />
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
          <p className="font-display text-2xl">Your first answer is waiting</p>
          <p className="mt-3 max-w-lg text-muted">
            Pick a question, record yourself answering it, and you’ll get a
            review of your technical accuracy, grammar and delivery. Your scores
            will show up here.
          </p>
          <Link
            to="/practice"
            className="mt-6 inline-flex h-11 items-center gap-2 rounded-md border border-ink px-5 text-sm font-medium hover:border-accent hover:bg-accent hover:text-accent-fg"
          >
            Choose a question
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </div>
      )}

      {!loading && !error && attempts.length > 0 && (
        <>
          <section
            aria-label="Progress summary"
            className="mt-10 grid divide-y divide-line border-y border-line sm:grid-cols-3 sm:divide-x sm:divide-y-0"
          >
            <div className="py-6 sm:pr-6">
              <p className="eyebrow text-tech">Latest technical</p>
              <p className="mt-2 font-display text-5xl font-semibold tabular-nums text-tech">
                {show(latest?.technical_score)}
              </p>
              <div className="mt-2 min-h-4">
                <Delta value={diff(latest?.technical_score, previous?.technical_score)} />
              </div>
            </div>
            <div className="py-6 sm:px-6">
              <p className="eyebrow text-comm">Latest communication</p>
              <p className="mt-2 font-display text-5xl font-semibold tabular-nums text-comm">
                {show(latest?.communication_score)}
              </p>
              <div className="mt-2 min-h-4">
                <Delta
                  value={diff(latest?.communication_score, previous?.communication_score)}
                />
              </div>
            </div>
            <div className="py-6 sm:pl-6">
              <p className="eyebrow">Practice so far</p>
              <p className="mt-2 font-display text-5xl font-semibold tabular-nums">
                {attempts.length}
              </p>
              <p className="mt-2 text-xs text-muted">
                {evaluated.length} evaluated
                {evaluated.length > 0 &&
                  ` · avg ${show(average(technicalValues))} tech, ${show(average(communicationValues))} comm`}
              </p>
            </div>
          </section>

          {evaluated.length === 0 && (
            <p className="mt-6 text-sm text-muted">
              Scores appear here once you finish an evaluation.
            </p>
          )}

          <section className="mt-14">
            <div className="flex items-baseline justify-between">
              <h2 className="text-2xl font-semibold">Recent sessions</h2>
              <Link to="/history" className="text-sm text-muted hover:text-ink">
                View all
              </Link>
            </div>
            <ul className="mt-4 border-t border-line">
              {attempts.slice(0, 5).map((attempt) => (
                <SessionRow key={attempt.session.id} attempt={attempt} />
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  )
}