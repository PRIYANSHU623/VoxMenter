import type { CategoryKey } from '../types/api'

const CATEGORY_LABELS: Record<string, string> = {
  dsa: 'DSA',
  python: 'Python',
  dbms_sql: 'DBMS / SQL',
  oop: 'OOP',
  ai_ml: 'AI / ML',
  hr: 'HR',
  project: 'Project',
  general: 'General',
}

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category.toLowerCase().trim()] ?? category
}

export const CATEGORY_SCORE_LABELS: Record<CategoryKey, string> = {
  technical_correctness: 'Technical correctness',
  completeness: 'Completeness',
  clarity_structure: 'Clarity and structure',
  grammar: 'Grammar',
  vocabulary: 'Vocabulary',
  conciseness: 'Conciseness',
  fillers_repetition: 'Fillers and repetition',
}

export const CATEGORY_KEYS = Object.keys(CATEGORY_SCORE_LABELS) as CategoryKey[]