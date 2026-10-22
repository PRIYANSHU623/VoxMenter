
from app.schemas.evaluation import (
    CategoryScore,
    EvaluationResult,
    EvaluationScores,
    FillerAnalysis,
)
from app.services.evaluation_service import (
    calculate_evaluation_scores,
)


def test_scoring():
    result = EvaluationResult(
        question_type="dsa",
        scores=EvaluationScores(
            technical_correctness=CategoryScore(
                score=80, feedback="Correct approach."
            ),
            completeness=CategoryScore(
                score=70, feedback="One edge case is missing."
            ),
            clarity_structure=CategoryScore(
                score=90, feedback="Well structured."
            ),
            grammar=CategoryScore(
                score=80, feedback="Minor errors."
            ),
            vocabulary=CategoryScore(
                score=80, feedback="Appropriate vocabulary."
            ),
            conciseness=CategoryScore(
                score=70, feedback="Some repetition."
            ),
            fillers_repetition=CategoryScore(
                score=90, feedback="Few fillers."
            ),
        ),
        strengths=["Good algorithmic approach."],
        improvements=["Explain edge cases."],
        missing_points=["Worst-case complexity."],
        technical_issues=[],
        grammar_corrections=[],
        filler_analysis=FillerAnalysis(
            counts=[{"word": "um", "count": 2}],
            repeated_phrases=[],
            filler_percentage=1.0,
            suggested_pauses=[],
        ),
        improved_answer="An improved sample answer.",
        practice_exercise="Explain the approach in 60 seconds.",
    )

    scores = calculate_evaluation_scores(result)

    print(scores)

    assert scores["overall_score"] == 79.5
    assert scores["technical_score"] == 76.67
    assert scores["communication_score"] == 83.75

if __name__ == "__main__":
    test_scoring()
    print("Evaluation scoring test passed!")
