
from unittest.mock import patch

from app.services.ai_evaluation_provider import evaluate_with_gemini


def test_gemini_provider_validation():
    with patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
        try:
            evaluate_with_gemini(
                question="What is a Python dictionary?",
                transcript="A dictionary stores key-value pairs.",
                question_type="python",
            )
        except RuntimeError as exc:
            assert "GEMINI_API_KEY" in str(exc)
        else:
            raise AssertionError("Missing API key should raise an error")

    print("Gemini provider validation test passed!")


if __name__ == "__main__":
    test_gemini_provider_validation()
