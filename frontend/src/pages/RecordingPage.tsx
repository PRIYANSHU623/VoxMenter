import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  AlertCircle,
  ArrowLeft,
  Check,
  Circle,
  Loader2,
  Mic,
  RotateCcw,
  Send,
  Square,
} from 'lucide-react'
import { getErrorMessage } from '../api/client'
import {
  addSessionQuestion,
  evaluateSession,
  getQuestion,
  getSession,
  getTranscription,
  listRecordings,
  listSessionQuestions,
  startTranscription,
  uploadRecording,
} from '../api/endpoints'
import { useRecorder } from '../hooks/useRecorder'
import type { Question, RecordingStatus, SessionQuestion } from '../types/api'
import { formatDuration } from '../utils/formatDuration'
import { categoryLabel } from '../utils/labels'

type Phase = 'compose' | 'uploading' | 'transcribing' | 'failed' | 'ready' | 'evaluating'
type StepState = 'done' | 'active' | 'pending' | 'error'

const IN_FLIGHT: RecordingStatus[] = ['uploaded', 'queued', 'transcribing']
const READY: RecordingStatus[] = ['transcribed', 'evaluating', 'completed']
const POLL_INTERVAL_MS = 2000
const POLL_TIMEOUT_MS = 3 * 60 * 1000

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

function ErrorNote({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 border-l-2 border-danger bg-surface px-3 py-2 text-sm text-danger"
    >
      <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
      <span>{message}</span>
    </div>
  )
}

function StepRow({ label, state, detail }: { label: string; state: StepState; detail?: string }) {
  return (
    <li className="flex items-center gap-3 border-b border-line py-3 text-sm">
      <span className="flex h-6 w-6 items-center justify-center">
        {state === 'done' && <Check size={18} className="text-ok" aria-hidden="true" />}
        {state === 'active' && <Loader2 size={18} className="animate-spin text-accent" aria-hidden="true" />}
        {state === 'pending' && <Circle size={14} className="text-muted" aria-hidden="true" />}
        {state === 'error' && <AlertCircle size={18} className="text-danger" aria-hidden="true" />}
      </span>
      <span className={state === 'pending' ? 'text-muted' : 'text-ink'}>{label}</span>
      {detail && <span className="ml-auto text-xs text-muted">{detail}</span>}
    </li>
  )
}

const outlineButton =
  'inline-flex h-11 items-center justify-center gap-2 rounded-md border border-line px-5 text-sm font-medium transition-colors hover:border-ink disabled:cursor-not-allowed disabled:opacity-50'
const primaryButton =
  'inline-flex h-11 items-center justify-center gap-2 rounded-md bg-accent px-5 text-sm font-medium text-accent-fg transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60'

export default function RecordingPage() {
  const navigate = useNavigate()
  const sessionId = Number(useParams().sessionId)
  const invalidId = !Number.isInteger(sessionId) || sessionId < 1

  const recorder = useRecorder(300)

  const [loading, setLoading] = useState(!invalidId)
  const [loadError, setLoadError] = useState<string | null>(invalidId ? 'Invalid session.' : null)
  const [question, setQuestion] = useState<Question | null>(null)
  const [sessionQuestion, setSessionQuestion] = useState<SessionQuestion | null>(null)

  const [phase, setPhase] = useState<Phase>('compose')
  const [recordingId, setRecordingId] = useState<number | null>(null)
  const [transcript, setTranscript] = useState<string | null>(null)
  const [uploadPercent, setUploadPercent] = useState(0)
  const [pipelineError, setPipelineError] = useState<string | null>(null)

  // Refs block double clicks even before React re-renders.
  const submitLock = useRef(false)
  const evaluateLock = useRef(false)

  // ---------- Load the question, and resume an unfinished attempt ----------
  useEffect(() => {
    if (invalidId) return
    let cancelled = false

    async function load() {
      try {
        const session = await getSession(sessionId)
        const [q, existing] = await Promise.all([
          getQuestion(session.question_id),
          listSessionQuestions(sessionId),
        ])
        const sq = existing[0] ?? (await addSessionQuestion(sessionId, session.question_id))
        const recordings = await listRecordings(sq.id)
        if (cancelled) return

        setQuestion(q)
        setSessionQuestion(sq)

        const last = recordings[recordings.length - 1]
        if (last && IN_FLIGHT.includes(last.status)) {
          setRecordingId(last.recording_id)
          setPhase('transcribing')
        } else if (
          last &&
          last.status === 'transcribed' &&
          last.transcript &&
          session.status !== 'completed'
        ) {
          setRecordingId(last.recording_id)
          setTranscript(last.transcript)
          setPhase('ready')
        }
      } catch (err) {
        if (!cancelled) setLoadError(getErrorMessage(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [sessionId, invalidId])

  // ---------- Start transcription (if needed) and poll until it finishes ----------
  useEffect(() => {
    if (phase !== 'transcribing' || recordingId === null) return
    let cancelled = false
    const startedAt = Date.now()

    async function run(id: number) {
      try {
        const first = await getTranscription(id)
        if (cancelled) return
        if (first.status === 'uploaded' || first.status === 'failed') {
          await startTranscription(id)
          if (cancelled) return
        }

        while (!cancelled) {
          const current = await getTranscription(id)
          if (cancelled) return

          if (READY.includes(current.status) && current.transcript) {
            setTranscript(current.transcript)
            setPhase('ready')
            return
          }
          if (current.status === 'failed') {
            setPipelineError(current.error_message || 'Transcription failed.')
            setPhase('failed')
            return
          }
          if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
            setPipelineError(
              'Transcription is taking longer than expected. Make sure the Celery worker is running, then try again.',
            )
            setPhase('failed')
            return
          }
          await sleep(POLL_INTERVAL_MS)
        }
      } catch (err) {
        if (!cancelled) {
          setPipelineError(getErrorMessage(err))
          setPhase('failed')
        }
      }
    }

    void run(recordingId)
    return () => {
      cancelled = true
    }
  }, [phase, recordingId])

  // ---------- Actions ----------
  async function handleSubmit() {
    if (submitLock.current || !recorder.audioBlob || !sessionQuestion) return
    submitLock.current = true
    setPipelineError(null)
    setUploadPercent(0)
    setPhase('uploading')
    try {
      const result = await uploadRecording(sessionQuestion.id, recorder.audioBlob, setUploadPercent)
      setRecordingId(result.recording_id)
      setPhase('transcribing')
      recorder.reset()
    } catch (err) {
      // The take is kept, so the user can submit it again.
      setPipelineError(getErrorMessage(err))
      setPhase('compose')
    } finally {
      submitLock.current = false
    }
  }

  async function handleEvaluate() {
    if (evaluateLock.current) return
    evaluateLock.current = true
    setPipelineError(null)
    setPhase('evaluating')
    try {
      await evaluateSession(sessionId, recordingId ?? undefined)
      navigate(`/review/${sessionId}`)
    } catch (err) {
      setPipelineError(getErrorMessage(err))
      setPhase('ready')
      evaluateLock.current = false
    }
  }

  function recordAnother() {
    recorder.reset()
    setRecordingId(null)
    setTranscript(null)
    setPipelineError(null)
    setPhase('compose')
  }

  // ---------- Render ----------
  if (loading) {
    return (
      <div className="flex justify-center py-24 text-muted">
        <Loader2 className="animate-spin" aria-label="Loading" />
      </div>
    )
  }

  if (loadError || !question) {
    return (
      <div>
        <p className="font-display text-xl">We couldn’t open this session</p>
        <p className="mt-2 text-danger">{loadError ?? 'Question not found.'}</p>
        <Link to="/practice" className={`${outlineButton} mt-6`}>
          Back to practice
        </Link>
      </div>
    )
  }

  const stepStates: Record<'upload' | 'transcribe' | 'evaluate', StepState> = {
    upload: phase === 'uploading' ? 'active' : 'done',
    transcribe:
      phase === 'uploading'
        ? 'pending'
        : phase === 'transcribing'
          ? 'active'
          : phase === 'failed'
            ? 'error'
            : 'done',
    evaluate: phase === 'evaluating' ? 'active' : 'pending',
  }

  const isRecording = recorder.status === 'recording'
  const isRequesting = recorder.status === 'requesting'

  return (
    <div>
      <Link
        to="/practice"
        className="inline-flex items-center gap-2 text-sm text-muted transition-colors hover:text-ink"
      >
        <ArrowLeft size={16} aria-hidden="true" />
        All questions
      </Link>

      <p className="eyebrow mt-8">
        {categoryLabel(question.category)} · {question.difficulty}
      </p>
      <h1 className="mt-2 max-w-3xl text-3xl font-semibold">{question.title}</h1>
      {question.description && (
        <p className="mt-3 max-w-2xl text-muted">{question.description}</p>
      )}

      <section aria-label="Recorder" className="mt-10 border-y border-line py-10">
        {/* ---------- Compose: record, replay, retry, submit ---------- */}
        {phase === 'compose' && (
          <div className="flex flex-col items-center text-center">
            {!recorder.supported && (
              <div className="mb-6 w-full max-w-md text-left">
                <ErrorNote message="Audio recording isn’t supported in this browser. Try a recent Chrome, Edge, Firefox or Safari." />
              </div>
            )}

            <p className="font-mono text-5xl tabular-nums" aria-live="off">
              {formatDuration(recorder.seconds)}
            </p>
            <p className="mt-1 text-xs text-muted">
              up to {formatDuration(recorder.maxSeconds)}
            </p>

            {recorder.status !== 'recorded' && recorder.supported && (
              <>
                <button
                  type="button"
                  onClick={isRecording ? recorder.stop : recorder.start}
                  disabled={isRequesting}
                  aria-label={isRecording ? 'Stop recording' : 'Start recording'}
                  className={[
                    'mt-8 flex h-20 w-20 items-center justify-center rounded-full transition-colors disabled:cursor-wait disabled:opacity-60',
                    isRecording
                      ? 'bg-danger text-canvas ring-4 ring-danger/30'
                      : 'bg-accent text-accent-fg hover:bg-accent-hover',
                  ].join(' ')}
                >
                  {isRequesting ? (
                    <Loader2 size={28} className="animate-spin" aria-hidden="true" />
                  ) : isRecording ? (
                    <Square size={26} fill="currentColor" aria-hidden="true" />
                  ) : (
                    <Mic size={30} aria-hidden="true" />
                  )}
                </button>

                <p className="mt-4 max-w-sm text-sm text-muted" aria-live="polite">
                  {isRequesting &&
                    'Waiting for microphone permission. Choose “Allow” in your browser’s prompt.'}
                  {isRecording && 'Recording… press the square to stop.'}
                  {recorder.status === 'idle' &&
                    'Press the button to start. Your browser will ask for microphone access.'}
                  {recorder.status === 'error' && 'Press the button to try again.'}
                </p>
              </>
            )}

            {recorder.status === 'recorded' && recorder.audioUrl && (
              <div className="mt-8 w-full max-w-md">
                <p className="eyebrow mb-3">Review your take</p>
                <audio controls src={recorder.audioUrl} className="w-full" />
                <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-center">
                  <button type="button" onClick={recorder.reset} className={outlineButton}>
                    <RotateCcw size={16} aria-hidden="true" />
                    Retry
                  </button>
                  <button type="button" onClick={handleSubmit} className={primaryButton}>
                    <Send size={16} aria-hidden="true" />
                    Submit answer
                  </button>
                </div>
              </div>
            )}

            {(recorder.error || pipelineError) && (
              <div className="mt-6 w-full max-w-md text-left">
                <ErrorNote message={(recorder.error ?? pipelineError) as string} />
              </div>
            )}

            {recorder.status === 'idle' && (
              <ul className="mt-8 max-w-md space-y-1 text-left text-sm text-muted">
                <li>Answer out loud, the way you would in a real interview.</li>
                <li>One to three minutes is a good length.</li>
                <li>A quiet room gives a more accurate transcript.</li>
              </ul>
            )}
          </div>
        )}

        {/* ---------- Pipeline: upload, transcribe, evaluate ---------- */}
        {phase !== 'compose' && (
          <div className="mx-auto max-w-xl">
            <p className="eyebrow mb-3">Progress</p>
            <ul className="border-t border-line">
              <StepRow
                label="Upload recording"
                state={stepStates.upload}
                detail={phase === 'uploading' ? `${uploadPercent}%` : undefined}
              />
              <StepRow label="Transcribe speech" state={stepStates.transcribe} />
              <StepRow label="Evaluate answer" state={stepStates.evaluate} />
            </ul>

            {phase === 'transcribing' && (
              <p className="mt-4 text-sm text-muted" aria-live="polite">
                Turning your speech into text. This usually takes under a minute.
              </p>
            )}

            {phase === 'failed' && (
              <div className="mt-4 space-y-4">
                {pipelineError && <ErrorNote message={pipelineError} />}
                <div className="flex flex-col gap-3 sm:flex-row">
                  <button
                    type="button"
                    onClick={() => {
                      setPipelineError(null)
                      setPhase('transcribing')
                    }}
                    className={primaryButton}
                  >
                    Try transcription again
                  </button>
                  <button type="button" onClick={recordAnother} className={outlineButton}>
                    Record again
                  </button>
                </div>
              </div>
            )}

            {(phase === 'ready' || phase === 'evaluating') && transcript && (
              <div className="mt-8">
                <p className="eyebrow">Your transcript</p>
                <p className="mt-3 max-h-72 overflow-y-auto whitespace-pre-wrap border-l-2 border-line pl-4 leading-relaxed">
                  {transcript}
                </p>
                <p className="mt-3 text-sm text-muted">
                  The evaluation is based on this text. If it looks wrong, record another attempt.
                </p>

                {pipelineError && (
                  <div className="mt-4">
                    <ErrorNote message={pipelineError} />
                  </div>
                )}

                <div className="mt-6 flex flex-col gap-3 sm:flex-row">
                  <button
                    type="button"
                    onClick={handleEvaluate}
                    disabled={phase === 'evaluating'}
                    className={primaryButton}
                  >
                    {phase === 'evaluating' && (
                      <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                    )}
                    {phase === 'evaluating' ? 'Evaluating…' : 'Evaluate my answer'}
                  </button>
                  <button
                    type="button"
                    onClick={recordAnother}
                    disabled={phase === 'evaluating'}
                    className={outlineButton}
                  >
                    Record another attempt
                  </button>
                </div>
                {phase === 'evaluating' && (
                  <p className="mt-3 text-sm text-muted" aria-live="polite">
                    The AI review can take up to a minute. Please keep this page open.
                  </p>
                )}
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  )
}