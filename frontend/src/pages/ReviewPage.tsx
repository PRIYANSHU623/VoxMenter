import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AlertCircle, ArrowLeft, Loader2, Play } from 'lucide-react'
import { getErrorMessage } from '../api/client'
import {
  getEvaluation,
  getPlaybackInfo,
  getQuestion,
  getSession,
  listRecordings,
  listSessionQuestions,
} from '../api/endpoints'
import type {
  CategoryKey,
  Evaluation,
  Question,
  Recording,
} from '../types/api'
import { categoryLabel } from '../utils/labels'

const CATEGORY_LABELS: Record<CategoryKey, string> = {
  technical_correctness: 'Technical correctness',
  completeness: 'Completeness',
  clarity_structure: 'Clarity and structure',
  grammar: 'Grammar',
  vocabulary: 'Vocabulary',
  conciseness: 'Conciseness',
  fillers_repetition: 'Fillers and repetition',
}

const TECHNICAL_KEYS: CategoryKey[] = ['technical_correctness', 'completeness']
const COMMUNICATION_KEYS: CategoryKey[] = [
  'clarity_structure',
  'grammar',
  'vocabulary',
  'conciseness',
  'fillers_repetition',
]

type Tone = 'tech' | 'comm' | 'accent'

const TONE_BG: Record<Tone, string> = {
  tech: 'bg-tech',
  comm: 'bg-comm',
  accent: 'bg-accent',
}
const TONE_TEXT: Record<Tone, string> = {
  tech: 'text-tech',
  comm: 'text-comm',
  accent: 'text-accent',
}

function formatScore(value: number | null | undefined): string {
  return typeof value === 'number' ? String(Math.round(value)) : '—'
}

function ScoreBar({ score, tone }: { score: number; tone: Tone }) {
  const safe = Math.max(0, Math.min(100, score))
  return (
    <div
      role="img"
      aria-label={`${Math.round(safe)} out of 100`}
      className="h-1.5 w-full overflow-hidden rounded-full bg-line"
    >
      <div
        className={`h-full rounded-full ${TONE_BG[tone]} transition-[width] duration-500`}
        style={{ width: `${safe}%` }}
      />
    </div>
  )
}

function Section({
  eyebrow,
  title,
  tone,
  children,
}: {
  eyebrow: string
  title: string
  tone: Tone
  children: ReactNode
}) {
  return (
    <section className="mt-14">
      <div className="flex items-center gap-3">
        <span aria-hidden="true" className={`h-4 w-1 rounded-full ${TONE_BG[tone]}`} />
        <p className="eyebrow">{eyebrow}</p>
      </div>
      <h2 className="mt-2 text-2xl font-semibold">{title}</h2>
      <div className="mt-6">{children}</div>
    </section>
  )
}

function BulletList({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) return <p className="text-sm text-muted">{empty}</p>
  return (
    <ul className="space-y-3">
      {items.map((item, index) => (
        <li key={index} className="flex gap-3 leading-relaxed">
          <span aria-hidden="true" className="mt-2.5 h-1 w-1 shrink-0 rounded-full bg-muted" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  )
}

function CategoryRows({
  keys,
  report,
  tone,
}: {
  keys: CategoryKey[]
  report: NonNullable<Evaluation['report']>
  tone: Tone
}) {
  return (
    <div className="divide-y divide-line border-y border-line">
      {keys.map((key) => {
        const item = report.scores?.[key]
        if (!item) return null
        return (
          <div key={key} className="py-5">
            <div className="flex items-baseline justify-between gap-4">
              <h3 className="font-sans text-base font-semibold">{CATEGORY_LABELS[key]}</h3>
              <span className={`font-mono text-sm tabular-nums ${TONE_TEXT[tone]}`}>
                {Math.round(item.score)}/100
              </span>
            </div>
            <div className="mt-3">
              <ScoreBar score={item.score} tone={tone} />
            </div>
            <p className="mt-3 text-sm leading-relaxed text-muted">{item.feedback}</p>
          </div>
        )
      })}
    </div>
  )
}

function RecordingAudio({ recordingId }: { recordingId: number }) {
  const [state, setState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setState('loading')
    setError(null)
    try {
      // The link is temporary, so we request a fresh one when the user presses play.
      const info = await getPlaybackInfo(recordingId)
      setUrl(info.playback_url)
      setState('ready')
    } catch (err) {
      setError(getErrorMessage(err))
      setState('error')
    }
  }

  if (state === 'ready' && url) {
    return (
      <audio
        controls
        autoPlay
        src={url}
        className="w-full"
        onError={() => {
          setError('The audio link expired or could not be played. Try loading it again.')
          setState('error')
        }}
      />
    )
  }

  return (
    <div>
      <button
        type="button"
        onClick={load}
        disabled={state === 'loading'}
        className="inline-flex h-11 items-center gap-2 rounded-md border border-line px-5 text-sm font-medium transition-colors hover:border-ink disabled:opacity-60"
      >
        {state === 'loading' ? (
          <Loader2 size={16} className="animate-spin" aria-hidden="true" />
        ) : (
          <Play size={16} aria-hidden="true" />
        )}
        {state === 'loading' ? 'Loading audio…' : 'Play recording'}
      </button>
      {error && <p className="mt-3 text-sm text-danger">{error}</p>}
    </div>
  )
}

export default function ReviewPage() {
  const sessionId = Number(useParams().sessionId)
  const invalidId = !Number.isInteger(sessionId) || sessionId < 1

  const [loading, setLoading] = useState(!invalidId)
  const [error, setError] = useState<string | null>(invalidId ? 'Invalid session.' : null)
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null)
  const [question, setQuestion] = useState<Question | null>(null)
  const [recording, setRecording] = useState<Recording | null>(null)

  useEffect(() => {
    if (invalidId) return
    let cancelled = false

    async function load() {
      try {
        const [session, evalData, sessionQuestions] = await Promise.all([
          getSession(sessionId),
          getEvaluation(sessionId),
          listSessionQuestions(sessionId),
        ])
        const [q, recordingLists] = await Promise.all([
          getQuestion(session.question_id),
          Promise.all(sessionQuestions.map((sq) => listRecordings(sq.id))),
        ])
        if (cancelled) return

        // Same rule the backend uses: the latest transcribed recording.
        const withTranscript = recordingLists
          .flat()
          .filter((r) => r.transcript && r.transcript.trim() !== '')
          .sort((a, b) => b.created_at.localeCompare(a.created_at))

        // Prefer the exact attempt this evaluation scored. Older evaluations
        // have no recording_id, so they fall back to the latest recording.
        const scoredId = evalData?.report?.recording_id
        const latest =
          withTranscript.find((r) => r.recording_id === scoredId) ?? withTranscript[0]

        setEvaluation(evalData)
        setQuestion(q)
        setRecording(latest ?? null)
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
  }, [sessionId, invalidId])

  if (loading) {
    return (
      <div className="flex justify-center py-24 text-muted">
        <Loader2 className="animate-spin" aria-label="Loading evaluation" />
      </div>
    )
  }

  if (error) {
    return (
      <div>
        <p className="font-display text-xl">We couldn’t load this report</p>
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

  // No evaluation yet, or an evaluation without a usable report.
  if (!evaluation || !evaluation.report) {
    return (
      <div>
        <p className="eyebrow">Evaluation</p>
        <h1 className="mt-2 text-3xl font-semibold">
          {evaluation ? 'This report is incomplete' : 'No evaluation yet'}
        </h1>
        <p className="mt-3 max-w-xl text-muted">
          {evaluation
            ? 'The evaluation was saved without its detailed feedback. Record another attempt to get a full report.'
            : 'This session hasn’t been evaluated. Record an answer and run the evaluation first.'}
        </p>
        <Link
          to={`/record/${sessionId}`}
          className="mt-6 inline-flex h-11 items-center rounded-md bg-accent px-5 text-sm font-medium text-accent-fg hover:bg-accent-hover"
        >
          Go to the recording room
        </Link>
      </div>
    )
  }

  const report = evaluation.report
  const overall = report.calculated_scores?.overall_score
  const technical = evaluation.technical_score
  const communication = evaluation.communication_score

  const strengths = report.strengths ?? []
  const improvements = report.improvements ?? []
  const missingPoints = report.missing_points ?? []
  const technicalIssues = report.technical_issues ?? []
  const grammarCorrections = report.grammar_corrections ?? []
  const notes = report.evaluation_notes ?? []
  const fillers = report.filler_analysis
  const fillerCounts = fillers?.counts ?? []
  const fillerTotal = fillerCounts.reduce((sum, item) => sum + item.count, 0)

  return (
    <div>
      <Link
        to="/history"
        className="inline-flex items-center gap-2 text-sm text-muted transition-colors hover:text-ink"
      >
        <ArrowLeft size={16} aria-hidden="true" />
        History
      </Link>

      <p className="eyebrow mt-8">
        {question ? categoryLabel(question.category) : 'Evaluation'} ·{' '}
        {new Date(evaluation.created_at).toLocaleDateString(undefined, {
          day: 'numeric',
          month: 'short',
          year: 'numeric',
        })}
      </p>
      <h1 className="mt-2 max-w-3xl text-3xl font-semibold">
        {question?.title ?? `Session ${sessionId}`}
      </h1>

      {/* ---------- Scores ---------- */}
      <section
        aria-label="Scores"
        className="mt-10 grid divide-y divide-line border-y border-line sm:grid-cols-3 sm:divide-x sm:divide-y-0"
      >
        <div className="py-6 sm:pr-6">
          <p className="eyebrow">Overall</p>
          <p className="mt-2 font-display text-6xl font-semibold tabular-nums">
            {formatScore(overall)}
            <span className="ml-1 text-lg text-muted">/100</span>
          </p>
        </div>
        <div className="py-6 sm:px-6">
          <p className="eyebrow text-tech">Technical</p>
          <p className="mt-2 font-display text-5xl font-semibold tabular-nums text-tech">
            {formatScore(technical)}
          </p>
          {typeof technical === 'number' && (
            <div className="mt-3">
              <ScoreBar score={technical} tone="tech" />
            </div>
          )}
        </div>
        <div className="py-6 sm:pl-6">
          <p className="eyebrow text-comm">Communication</p>
          <p className="mt-2 font-display text-5xl font-semibold tabular-nums text-comm">
            {formatScore(communication)}
          </p>
          {typeof communication === 'number' && (
            <div className="mt-3">
              <ScoreBar score={communication} tone="comm" />
            </div>
          )}
        </div>
      </section>

      {/* ---------- Technical ---------- */}
      <Section eyebrow="Technical" title="What you said" tone="tech">
        <CategoryRows keys={TECHNICAL_KEYS} report={report} tone="tech" />

        <h3 className="mt-8 font-sans text-base font-semibold">Points you missed</h3>
        <div className="mt-3">
          <BulletList items={missingPoints} empty="No missing points were identified." />
        </div>

        <h3 className="mt-8 font-sans text-base font-semibold">Technical corrections</h3>
        <div className="mt-3">
          {technicalIssues.length === 0 ? (
            <p className="text-sm text-muted">No technical issues were reported.</p>
          ) : (
            <div className="space-y-5">
              {technicalIssues.map((item, index) => (
                <div key={index} className="border-l-2 border-tech pl-4">
                  <p className="font-semibold">{item.issue}</p>
                  <p className="mt-1 text-sm leading-relaxed text-muted">{item.explanation}</p>
                  <p className="mt-2 text-sm leading-relaxed">
                    <span className="eyebrow mr-2">Better</span>
                    {item.suggested_correction}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </Section>

      {/* ---------- Communication ---------- */}
      <Section eyebrow="Communication" title="How you said it" tone="comm">
        <CategoryRows keys={COMMUNICATION_KEYS} report={report} tone="comm" />

        <h3 className="mt-8 font-sans text-base font-semibold">Grammar corrections</h3>
        <div className="mt-3">
          {grammarCorrections.length === 0 ? (
            <p className="text-sm text-muted">No grammar corrections were reported.</p>
          ) : (
            <div className="space-y-6">
              {grammarCorrections.map((item, index) => (
                <div key={index} className="space-y-2">
                  <p className="border-l-2 border-danger pl-4 text-sm leading-relaxed">
                    {item.original}
                  </p>
                  <p className="border-l-2 border-ok pl-4 text-sm leading-relaxed">
                    {item.corrected}
                  </p>
                  <p className="pl-4 text-sm leading-relaxed text-muted">{item.explanation}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        <h3 className="mt-8 font-sans text-base font-semibold">Filler words</h3>
        <div className="mt-3">
          {fillers ? (
            <>
              <p className="text-sm text-muted">
                {fillerTotal} filler{fillerTotal === 1 ? '' : 's'} found ·{' '}
                {Math.round(fillers.filler_percentage * 10) / 10}% of your words
              </p>
              {fillerCounts.length > 0 && (
                <ul className="mt-3 flex flex-wrap gap-2">
                  {fillerCounts.map((item, index) => (
                    <li
                      key={`${item.word}-${index}`}
                      className="rounded-full border border-line px-3 py-1 text-sm"
                    >
                      “{item.word}” <span className="font-mono text-muted">×{item.count}</span>
                    </li>
                  ))}
                </ul>
              )}
              {(fillers.repeated_phrases ?? []).length > 0 && (
                <div className="mt-5">
                  <p className="eyebrow mb-2">Repeated phrases</p>
                  <BulletList items={fillers.repeated_phrases} empty="" />
                </div>
              )}
              {(fillers.suggested_pauses ?? []).length > 0 && (
                <div className="mt-5">
                  <p className="eyebrow mb-2">Try this instead</p>
                  <BulletList items={fillers.suggested_pauses} empty="" />
                </div>
              )}
              <p className="mt-5 text-xs text-muted">
                Based on the transcript only. It can’t measure tone, pauses or speaking speed.
              </p>
            </>
          ) : (
            <p className="text-sm text-muted">No filler analysis was returned.</p>
          )}
        </div>
      </Section>

      {/* ---------- Summary ---------- */}
      <Section eyebrow="Summary" title="Keep and change" tone="accent">
        <div className="grid gap-10 md:grid-cols-2">
          <div>
            <h3 className="mb-3 font-sans text-base font-semibold">Strengths</h3>
            <BulletList items={strengths} empty="No strengths were listed." />
          </div>
          <div>
            <h3 className="mb-3 font-sans text-base font-semibold">To improve</h3>
            <BulletList items={improvements} empty="No suggestions were listed." />
          </div>
        </div>
      </Section>

      <Section eyebrow="Model answer" title="A stronger version" tone="accent">
        {report.improved_answer ? (
          <p className="max-w-3xl whitespace-pre-wrap border-l-2 border-accent pl-5 leading-relaxed">
            {report.improved_answer}
          </p>
        ) : (
          <p className="text-sm text-muted">No improved answer was returned.</p>
        )}

        <h3 className="mt-8 font-sans text-base font-semibold">Practice exercise</h3>
        <p className="mt-2 max-w-3xl leading-relaxed">
          {report.practice_exercise || 'No exercise was returned.'}
        </p>
      </Section>

      {/* ---------- Transcript and audio ---------- */}
      <Section eyebrow="Your attempt" title="Transcript and recording" tone="accent">
        {recording ? (
          <>
            <RecordingAudio recordingId={recording.recording_id} />
            <p className="mt-6 max-h-96 max-w-3xl overflow-y-auto whitespace-pre-wrap border-l-2 border-line pl-5 leading-relaxed">
              {recording.transcript}
            </p>
          </>
        ) : (
          <p className="text-sm text-muted">The recording or transcript isn’t available.</p>
        )}
      </Section>

      {notes.length > 0 && (
        <Section eyebrow="Notes" title="Evaluation notes" tone="accent">
          <BulletList items={notes} empty="" />
        </Section>
      )}

      <div className="mt-14 flex flex-col gap-3 border-t border-line pt-8 sm:flex-row">
        <Link
          to={`/record/${sessionId}`}
          className="inline-flex h-11 items-center justify-center rounded-md bg-accent px-5 text-sm font-medium text-accent-fg hover:bg-accent-hover"
        >
          Record another attempt
        </Link>
        <Link
          to="/practice"
          className="inline-flex h-11 items-center justify-center rounded-md border border-line px-5 text-sm font-medium hover:border-ink"
        >
          Choose a different question
        </Link>
      </div>
    </div>
  )
}