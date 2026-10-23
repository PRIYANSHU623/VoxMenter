import { useEffect, useState } from 'react'
import { getErrorMessage } from '../api/client'
import { getEvaluation, getQuestion, listSessions } from '../api/endpoints'
import type { Evaluation, PracticeSession, Question } from '../types/api'

export interface Attempt {
  session: PracticeSession
  question: Question | null
  evaluation: Evaluation | null
}

// Combines sessions, their questions and their saved evaluations.
// Newest sessions come first (the backend already sorts them).
export function useAttempts() {
  const [attempts, setAttempts] = useState<Attempt[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const sessions = await listSessions()
        const questionIds = [...new Set(sessions.map((s) => s.question_id))]

        const [questionEntries, evaluationEntries] = await Promise.all([
          Promise.all(
            questionIds.map(
              async (id) => [id, await getQuestion(id).catch(() => null)] as const,
            ),
          ),
          // Only completed sessions can have an evaluation, so we skip the rest.
          Promise.all(
            sessions.map(
              async (s) =>
                [
                  s.id,
                  s.status === 'completed'
                    ? await getEvaluation(s.id).catch(() => null)
                    : null,
                ] as const,
            ),
          ),
        ])

        if (cancelled) return

        const questions = new Map(questionEntries)
        const evaluations = new Map(evaluationEntries)

        setAttempts(
          sessions.map((session) => ({
            session,
            question: questions.get(session.question_id) ?? null,
            evaluation: evaluations.get(session.id) ?? null,
          })),
        )
        setError(null)
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
  }, [reloadKey])

  function reload() {
    setLoading(true)
    setError(null)
    setReloadKey((key) => key + 1)
  }

  return { attempts, loading, error, reload }
}