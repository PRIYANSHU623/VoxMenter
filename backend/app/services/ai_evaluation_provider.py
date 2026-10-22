
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.schemas.evaluation import EvaluationResult, QuestionType
from app.services.evaluation_prompt import (
    EVALUATION_SYSTEM_PROMPT,
    build_evaluation_prompt,
)
from app.schemas.evaluation import (
    EvaluationResult,
    FillerAnalysis,
    QuestionType,
)

from app.services.filler_analysis import analyze_fillers

load_dotenv()


def evaluate_with_gemini(
    question: str,
    transcript: str,
    question_type: QuestionType = "general",
) -> EvaluationResult:
    """Evaluate an interview answer using Gemini structured output."""

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing from the backend .env")

    if not question.strip():
        raise ValueError("Interview question cannot be empty")

    if not transcript.strip():
        raise ValueError("Transcript cannot be empty")

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    client = genai.Client(api_key=api_key)

    prompt = build_evaluation_prompt(
        question=question,
        transcript=transcript,
        question_type=question_type,
    )

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=EVALUATION_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=EvaluationResult,
            temperature=0.2,
        ),
    )

    # Validate the returned JSON against our existing Pydantic schema.
    if not response.text:
        raise RuntimeError("Gemini returned an empty evaluation response")

    result = EvaluationResult.model_validate_json(response.text)

    # Use Python's exact counts instead of Gemini's estimates.
    filler_data = analyze_fillers(transcript)
    result = result.model_copy(
        update={"filler_analysis": FillerAnalysis(**filler_data)}
    )

    return result


# Later: optional OpenAI implementation.
# Install with: python -m pip install openai
# Add OPENAI_API_KEY to .env and select a model that supports
# Structured Outputs.
#
# from openai import OpenAI
#
# def evaluate_with_openai(
#     question: str,
#     transcript: str,
#     question_type: QuestionType = "general",
# ) -> EvaluationResult:
#     api_key = os.getenv("OPENAI_API_KEY")
#     if not api_key:
#         raise RuntimeError("OPENAI_API_KEY is missing")
#
#     client = OpenAI(api_key=api_key)
#     prompt = build_evaluation_prompt(
#         question=question,
#         transcript=transcript,
#         question_type=question_type,
#     )
#
#     completion = client.chat.completions.parse(
#         model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
#         messages=[
#             {"role": "system", "content": EVALUATION_SYSTEM_PROMPT},
#             {"role": "user", "content": prompt},
#         ],
#         response_format=EvaluationResult,
#     )
#
#     result = completion.choices[0].message.parsed
#     if result is None:
#         raise RuntimeError("OpenAI returned no parsed evaluation")
#
#     return result
