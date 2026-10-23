import { isAxiosError } from 'axios'
import { api } from './client'
import type {
  Evaluation,
  PlaybackInfo,
  PracticeSession,
  Question,
  QuestionFilters,
  Recording,
  SessionQuestion,
  TokenResponse,
  TranscriptionStart,
  TranscriptionStatus,
  UploadResult,
  User,
} from '../types/api'

// ---------- Auth ----------
export const register = (email: string, password: string) =>
  api.post<User>('/api/auth/register', { email, password }).then((r) => r.data)

export const login = (email: string, password: string) =>
  api
    .post<TokenResponse>('/api/auth/login', { email, password })
    .then((r) => r.data)

export const getMe = () => api.get<User>('/api/auth/me').then((r) => r.data)

// ---------- Questions ----------
// The trailing slash matters: the backend route is "/api/questions/".
export const listQuestions = (filters: QuestionFilters = {}) =>
  api
    .get<Question[]>('/api/questions/', { params: filters })
    .then((r) => r.data)

export const getQuestion = (id: number) =>
  api.get<Question>(`/api/questions/${id}`).then((r) => r.data)

// ---------- Practice sessions ----------
export const createSession = (questionId: number) =>
  api
    .post<PracticeSession>('/api/practice/sessions', { question_id: questionId })
    .then((r) => r.data)

export const listSessions = () =>
  api.get<PracticeSession[]>('/api/practice/sessions').then((r) => r.data)

export const getSession = (id: number) =>
  api.get<PracticeSession>(`/api/practice/sessions/${id}`).then((r) => r.data)

export const addSessionQuestion = (sessionId: number, questionId: number) =>
  api
    .post<SessionQuestion>(`/api/practice/sessions/${sessionId}/questions`, {
      question_id: questionId,
    })
    .then((r) => r.data)

export const listSessionQuestions = (sessionId: number) =>
  api
    .get<SessionQuestion[]>(`/api/practice/sessions/${sessionId}/questions`)
    .then((r) => r.data)

// ---------- Recordings ----------
// Browsers record as "audio/webm;codecs=opus", but the backend only accepts
// the plain type ("audio/webm"). We strip the codec part before uploading.
export function uploadRecording(
  sessionQuestionId: number,
  audio: Blob,
  onProgress?: (percent: number) => void,
) {
  const baseType = (audio.type || 'audio/webm').split(';')[0].trim()
  const extension = baseType.split('/')[1]?.replace('x-', '') ?? 'webm'
  const file = new File([audio], `recording.${extension}`, { type: baseType })

  const form = new FormData()
  form.append('file', file)

  return api
    .post<UploadResult>(
      `/api/session-questions/${sessionQuestionId}/recordings`,
      form,
      {
        timeout: 120000,
        onUploadProgress: (event) => {
          if (onProgress && event.total) {
            onProgress(Math.round((event.loaded / event.total) * 100))
          }
        },
      },
    )
    .then((r) => r.data)
}

export const listRecordings = (sessionQuestionId: number) =>
  api
    .get<Recording[]>(`/api/session-questions/${sessionQuestionId}/recordings`)
    .then((r) => r.data)

// The playback URL is temporary (5 minutes). Fetch a fresh one when playing.
export const getPlaybackInfo = (recordingId: number) =>
  api
    .get<PlaybackInfo>(`/api/recordings/${recordingId}/playback`)
    .then((r) => r.data)

export const deleteRecording = (recordingId: number) =>
  api.delete(`/api/recordings/${recordingId}`).then((r) => r.data)

export const startTranscription = (recordingId: number) =>
  api
    .post<TranscriptionStart>(`/api/recordings/${recordingId}/transcription`)
    .then((r) => r.data)

export const getTranscription = (recordingId: number) =>
  api
    .get<TranscriptionStatus>(`/api/recordings/${recordingId}/transcription`)
    .then((r) => r.data)

// ---------- Evaluation ----------
// Each call creates a new evaluation and uses the Gemini API,
// so the UI must prevent double clicks.
// Pass recordingId to score a specific attempt; otherwise the backend
// uses the latest transcribed recording.
export const evaluateSession = (sessionId: number, recordingId?: number) =>
  api
    .post<Evaluation>(`/api/practice/sessions/${sessionId}/evaluate`, null, {
      params: recordingId ? { recording_id: recordingId } : undefined,
      timeout: 120000,
    })
    .then((r) => r.data)

// All evaluations of a session, oldest first.
export const listEvaluations = (sessionId: number) =>
  api
    .get<Evaluation[]>(`/api/practice/sessions/${sessionId}/evaluations`)
    .then((r) => r.data)

// Returns null when the session has no evaluation yet (404).
export async function getEvaluation(sessionId: number): Promise<Evaluation | null> {
  try {
    const { data } = await api.get<Evaluation>(
      `/api/practice/sessions/${sessionId}/evaluation`,
    )
    return data
  } catch (error) {
    if (isAxiosError(error) && error.response?.status === 404) return null
    throw error
  }
}