
from app.services.ai_evaluation_provider import evaluate_with_gemini
from app.services.evaluation_service import calculate_evaluation_scores

result = evaluate_with_gemini(
    question="What is the time complexity of binary search, and why?",
    transcript=(
        "Binary search has O(log n) time complexity  um because "
        "it divides the search  umm uh space in half at each step."
    ),
    question_type="dsa",
)

print("Evaluation:")
print(result.model_dump_json(indent=2))

scores = calculate_evaluation_scores(result)
print("\nCalculated scores:")
print(scores)
