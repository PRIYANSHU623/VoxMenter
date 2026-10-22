
from typing import Literal

from app.schemas.evaluation import EvaluationResult, QuestionType


# Weights for technical and knowledge-based interview questions.
TECHNICAL_WEIGHTS = {
    "technical_correctness": 40,
    "completeness": 20,
    "clarity_structure": 15,
    "grammar": 10,
    "vocabulary": 5,
    "conciseness": 5,
    "fillers_repetition": 5,
}

# Weights for HR and behavioral interview questions.
HR_WEIGHTS = {
    "technical_correctness": 10,
    "completeness": 15,
    "clarity_structure": 20,
    "grammar": 20,
    "vocabulary": 10,
    "conciseness": 10,
    "fillers_repetition": 15,
}

TECHNICAL_QUESTION_TYPES = {
    "dsa",
    "python",
    "dbms_sql",
    "oop",
    "ai_ml",
    "project",
}


def get_weights(question_type: QuestionType) -> dict[str, int]:
    """Return the scoring weights for the question type."""
    if question_type == "hr":
        return HR_WEIGHTS.copy()

    return TECHNICAL_WEIGHTS.copy()


def calculate_evaluation_scores(
    evaluation: EvaluationResult,
) -> dict:
    """
    Calculate weighted overall, technical, and communication scores.

    Each category score supplied by the evaluator must be between
    0 and 100. The final weighted score is calculated by Python.
    """
    category_scores = evaluation.scores.model_dump()

    weights = get_weights(evaluation.question_type)

    total_weight = sum(weights.values())
    if total_weight != 100:
        raise ValueError("Evaluation weights must add up to 100")

    overall_score = sum(
        category_scores[category]["score"] * weight
        for category, weight in weights.items()
    ) / total_weight

    # Technical performance is measured separately from English.
    technical_score = (
        category_scores["technical_correctness"]["score"] * 40
        + category_scores["completeness"]["score"] * 20
    ) / 60

    # Communication score combines the five communication categories.
    communication_categories = [
        "clarity_structure",
        "grammar",
        "vocabulary",
        "conciseness",
        "fillers_repetition",
    ]

    communication_weight = sum(
        weights[category] for category in communication_categories
    )

    communication_score = sum(
        category_scores[category]["score"] * weights[category]
        for category in communication_categories
    ) / communication_weight

    return {
        "overall_score": round(overall_score, 2),
        "technical_score": round(technical_score, 2),
        "communication_score": round(communication_score, 2),
        "category_scores": category_scores,
        "weights": weights,
    }
