// ---------- Auth ----------
export interface User {
  id: number
  email: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: User
}

// ---------- Questions ----------
export interface Question {
  id: number
  title: string
  description: string | null
  category: string
  difficulty: string
  is_active: boolean
}

export interface QuestionFilters {
  category?: string
  difficulty?: string
  skip?: number
  limit?: number
}

// ---------- Practice sessions ----------
export type SessionStatus =
  | 'pending'
  | 'recording_uploaded'
  | 'transcribing'
  | 'evaluating'
  | 'completed'
  | 'failed'

export interface PracticeSession {
  id: number
  user_id: number
  question_id: number
  status: SessionStatus
  audio_key: string | null
  duration_seconds: number | null
  transcript: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
}

export interface SessionQuestion {
  id: number
  session_id: number
  question_id: number
  position: number
  status: string
  created_at: string
}

// ---------- Recordings ----------
export type RecordingStatus =
  | 'uploaded'
  | 'queued'
  | 'transcribing'
  | 'transcribed'
  | 'evaluating'
  | 'completed'
  | 'failed'

export interface Recording {
  recording_id: number
  session_question_id: number
  status: RecordingStatus
  content_type: string
  size_bytes: number
  duration_seconds: number | null
  transcript: string | null
  created_at: string
}

export interface UploadResult {
  message: string
  recording_id: number
  session_question_id: number
  session_id: number
  status: RecordingStatus
  content_type: string
  size_bytes: number
  created_at: string
}

export interface TranscriptionStart {
  recording_id: number
  status: RecordingStatus
  message: string
  task_id?: string
  transcript?: string
}

export interface TranscriptionStatus {
  recording_id: number
  status: RecordingStatus
  transcript: string | null
  error_message: string | null
  updated_at: string
}

export interface PlaybackInfo {
  recording_id: number
  playback_url: string
  expires_in: number
}

// ---------- Evaluation ----------
export type CategoryKey =
  | 'technical_correctness'
  | 'completeness'
  | 'clarity_structure'
  | 'grammar'
  | 'vocabulary'
  | 'conciseness'
  | 'fillers_repetition'

export interface CategoryScore {
  score: number
  feedback: string
}

export interface TechnicalIssue {
  issue: string
  explanation: string
  suggested_correction: string
}

export interface GrammarCorrection {
  original: string
  corrected: string
  explanation: string
}

export interface FillerAnalysis {
  counts: { word: string; count: number }[]
  repeated_phrases: string[]
  filler_percentage: number
  suggested_pauses: string[]
}

export interface EvaluationReport {
  question_type: string
  scores: Record<CategoryKey, CategoryScore>
  strengths: string[]
  improvements: string[]
  missing_points: string[]
  technical_issues: TechnicalIssue[]
  grammar_corrections: GrammarCorrection[]
  filler_analysis: FillerAnalysis
  improved_answer: string
  practice_exercise: string
  evaluation_notes: string[]
  recording_id?: number
  calculated_scores?: {
    overall_score: number
    technical_score: number
    communication_score: number
    weights?: Record<string, number>
  }
}

export interface Evaluation {
  evaluation_id: number
  session_id: number
  technical_score: number | null
  communication_score: number | null
  created_at: string
  report: EvaluationReport | null
}