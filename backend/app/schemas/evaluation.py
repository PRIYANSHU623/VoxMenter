
from typing import Literal

from pydantic import BaseModel, Field


QuestionType = Literal[
    "dsa",
    "python",
    "dbms_sql",
    "oop",
    "ai_ml",
    "hr",
    "project",
    "general",
]


class CategoryScore(BaseModel):
    score: int = Field(ge=0, le=100)
    feedback: str = Field(min_length=1)


class SentenceCorrection(BaseModel):
    original: str
    corrected: str
    explanation: str


class TechnicalIssue(BaseModel):
    issue: str
    explanation: str
    suggested_correction: str



class FillerWordCount(BaseModel):
    word: str
    count: int = Field(ge=0)


class FillerAnalysis(BaseModel):
    # Use a list instead of dict[str, int] because the Gemini
    # structured-output schema currently rejects this dict schema.
    counts: list[FillerWordCount] = Field(default_factory=list)
    repeated_phrases: list[str] = Field(default_factory=list)
    filler_percentage: float = Field(ge=0, le=100)
    suggested_pauses: list[str] = Field(default_factory=list)


class EvaluationScores(BaseModel):
    technical_correctness: CategoryScore
    completeness: CategoryScore
    clarity_structure: CategoryScore
    grammar: CategoryScore
    vocabulary: CategoryScore
    conciseness: CategoryScore
    fillers_repetition: CategoryScore


class EvaluationResult(BaseModel):
    question_type: QuestionType
    scores: EvaluationScores

    strengths: list[str]
    improvements: list[str] = Field(max_length=3)
    missing_points: list[str]
    technical_issues: list[TechnicalIssue]
    grammar_corrections: list[SentenceCorrection]

    filler_analysis: FillerAnalysis

    improved_answer: str
    practice_exercise: str

    evaluation_notes: list[str] = Field(default_factory=list)
