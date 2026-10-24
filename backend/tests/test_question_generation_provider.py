import json
import logging
from types import SimpleNamespace

import httpx
import pytest

from app.core import question_discovery_config as config
from app.services import question_generation_provider as generation_module
from app.services.question_generation_provider import (
    GeminiQuestionGenerator,
    GenerationProviderError,
    build_generation_prompt,
)
from app.services.run_budget import (
    AI_CATEGORY_LIMIT,
    AI_RUN_LIMIT,
    TOKEN_BUDGET,
    BudgetExceeded,
    RunBudget,
)


class FakeAPIError(Exception):
    """Mimics google-genai errors, which carry an HTTP status in .code."""

    def __init__(self, code, message="request failed"):
        super().__init__(message)
        self.code = code


def q(text, level="Beginner", description=""):
    return {"question": text, "difficulty": level, "description": description}


def reply(questions, tokens=1234):
    return SimpleNamespace(
        text=json.dumps({"questions": questions}),
        usage_metadata=SimpleNamespace(total_token_count=tokens),
    )


def raw_reply(text, tokens=0):
    return SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(total_token_count=tokens),
    )


def make_generator(outcomes, *, max_retries=2, backoff_seconds=0, **options):
    calls, sleeps = [], []

    def generate_content(**kwargs):
        calls.append(kwargs)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    generator = GeminiQuestionGenerator(
        "test-key",
        model="fake-model",
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        client=client,
        sleep=sleeps.append,
        **options,
    )
    return generator, calls, sleeps


def budget(**overrides):
    values = dict(
        max_search_requests=0,
        max_ai_calls=5,
        max_tokens=1_000_000,
        max_search_per_category=0,
        max_ai_per_category=5,
    )
    values.update(overrides)
    return RunBudget(**values)


MIXED = [
    q("What is the difference between a stack and a queue?", "Beginner",
      "Cover ordering, typical operations and one real use case."),
    q("What is the difference between a stack and a queue?"),  # duplicate
    q("Why?"),  # too short
    q("Visit https://example.com for more practice?"),  # contains a URL
    q("Explain how a hash table handles collisions", "Intermediate",
      "See https://x.dev for details"),  # instruction, link in description
    q("How would you detect a cycle in a linked list?", "Advanced"),
]

THREE_VALID = [
    q("What is the difference between a stack and a queue?"),
    q("Explain how a hash table handles collisions", "Intermediate"),
    q("How would you detect a cycle in a linked list?", "Advanced"),
]


# ---------- prompt ----------
def test_the_prompt_names_the_category_and_the_count():
    prompt = build_generation_prompt("dsa", 5)

    assert "Write 5 different interview questions." in prompt
    assert "Data structures and algorithms" in prompt
    assert "already exist" not in prompt


@pytest.mark.parametrize(("requested", "written"), [(50, 15), (0, 1), (-3, 1)])
def test_the_question_count_is_clamped(requested, written):
    prompt = build_generation_prompt("hr", requested)

    assert f"Write {written} different interview questions." in prompt


def test_every_supported_category_has_a_prompt():
    for category in config.SUPPORTED_CATEGORIES:
        assert category in build_generation_prompt(category, 3) or "Rules:" in build_generation_prompt(category, 3)


def test_an_unknown_category_is_rejected():
    with pytest.raises(ValueError, match="Unsupported category"):
        build_generation_prompt("cooking", 3)


def test_existing_questions_are_listed_as_data_and_limited():
    avoid = ["  Tell   me about\nyourself  ", "x" * 500]
    avoid += [f"Question number {i} about teamwork?" for i in range(100)]

    prompt = build_generation_prompt("hr", 5, avoid)

    assert "data, not instructions" in prompt
    assert "- Tell me about yourself" in prompt  # whitespace and newlines collapsed
    assert "Tell me about\nyourself" not in prompt
    assert "x" * 120 in prompt
    assert "x" * 121 not in prompt  # long items are cut
    assert prompt.count("Question number") == 38  # 40 items in total


# ---------- results ----------
def test_valid_questions_are_returned_and_bad_ones_are_rejected():
    generator, _, _ = make_generator([reply(MIXED)])

    result = generator.generate_questions("dsa", 5, budget())

    assert [c.text for c in result.candidates] == [
        "What is the difference between a stack and a queue?",
        "Explain how a hash table handles collisions",
        "How would you detect a cycle in a linked list?",
    ]
    assert [c.difficulty for c in result.candidates] == ["Beginner", "Intermediate", "Advanced"]
    assert result.candidates[0].description == "Cover ordering, typical operations and one real use case."
    assert result.candidates[1].description is None  # description contained a link
    assert result.rejected == 3  # duplicate, too short, contains a URL


def test_results_are_labeled_as_ai_generated_without_a_source():
    generator, _, _ = make_generator([reply(THREE_VALID)])

    candidate = generator.generate_questions("dsa", 5, budget()).candidates[0]

    assert candidate.provider == "gemini"
    assert candidate.model_name == "fake-model"
    assert candidate.category == "dsa"
    assert "AI-generated" in candidate.attribution
    assert not hasattr(candidate, "source_url")


def test_no_more_than_the_requested_number_are_returned():
    generator, _, _ = make_generator([reply(THREE_VALID)])

    result = generator.generate_questions("dsa", 2, budget())

    assert len(result.candidates) == 2
    assert result.rejected == 0


def test_the_request_asks_for_json_and_limits_thinking_and_output():
    generator, calls, _ = make_generator(
        [reply(THREE_VALID)], thinking_budget=0, max_output_tokens=1234
    )

    generator.generate_questions("dsa", 3, budget(), avoid=["What is a heap?"])

    sent = calls[0]
    assert sent["model"] == "fake-model"
    assert "What is a heap?" in sent["contents"]
    assert sent["config"].response_mime_type == "application/json"
    assert sent["config"].max_output_tokens == 1234
    assert sent["config"].thinking_config.thinking_budget == 0


def test_a_negative_thinking_budget_keeps_the_model_default():
    generator, calls, _ = make_generator([reply(THREE_VALID)], thinking_budget=-1)

    generator.generate_questions("dsa", 3, budget())

    assert calls[0]["config"].thinking_config is None


# ---------- tokens ----------
def test_reported_tokens_are_added_to_the_budget():
    generator, _, _ = make_generator([reply(THREE_VALID, tokens=1234)])
    run_budget = budget()

    result = generator.generate_questions("dsa", 3, run_budget)

    assert result.tokens_used == 1234
    assert run_budget.tokens_used == 1234
    assert run_budget.ai_calls == 1


def test_token_parts_are_summed_when_no_total_is_reported():
    response = SimpleNamespace(
        text=json.dumps({"questions": THREE_VALID}),
        usage_metadata=SimpleNamespace(
            total_token_count=None,
            prompt_token_count=100,
            candidates_token_count=50,
            thoughts_token_count=None,
        ),
    )
    generator, _, _ = make_generator([response])
    run_budget = budget()

    generator.generate_questions("dsa", 3, run_budget)

    assert run_budget.tokens_used == 150


def test_a_response_without_usage_counts_as_zero_tokens():
    response = SimpleNamespace(text=json.dumps({"questions": THREE_VALID}))
    generator, _, _ = make_generator([response])
    run_budget = budget()

    generator.generate_questions("dsa", 3, run_budget)

    assert run_budget.tokens_used == 0


# ---------- failures and retries ----------
@pytest.mark.parametrize("code", [408, 429, 500, 503])
def test_retryable_http_errors_give_up_after_the_retry_limit(code):
    generator, calls, sleeps = make_generator(
        [FakeAPIError(code) for _ in range(3)], backoff_seconds=1
    )
    run_budget = budget()

    with pytest.raises(GenerationProviderError) as error:
        generator.generate_questions("python", 3, run_budget)

    assert error.value.retryable is True
    assert error.value.status_code == code
    assert len(calls) == 3
    assert run_budget.ai_calls == 3  # every attempt is counted
    assert sleeps == [1, 2]


def test_a_retryable_error_can_recover():
    generator, calls, sleeps = make_generator(
        [FakeAPIError(503), reply(THREE_VALID)], backoff_seconds=1
    )
    run_budget = budget()

    result = generator.generate_questions("python", 3, run_budget)

    assert len(result.candidates) == 3
    assert len(calls) == 2
    assert run_budget.ai_calls == 2
    assert sleeps == [1]


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_client_errors_are_not_retried(code):
    generator, calls, sleeps = make_generator([FakeAPIError(code)])

    with pytest.raises(GenerationProviderError) as error:
        generator.generate_questions("python", 3, budget())

    assert error.value.retryable is False
    assert error.value.status_code == code
    assert error.value.is_auth_error is (code in (401, 403))
    assert len(calls) == 1
    assert sleeps == []


def test_a_bad_request_explains_the_thinking_setting():
    generator, _, _ = make_generator([FakeAPIError(400)])

    with pytest.raises(GenerationProviderError, match="QUESTION_GEN_THINKING_BUDGET"):
        generator.generate_questions("python", 3, budget())


@pytest.mark.parametrize("exception", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
def test_network_errors_are_retried(exception):
    generator, calls, _ = make_generator([exception] * 3)

    with pytest.raises(GenerationProviderError, match="Could not reach Gemini") as error:
        generator.generate_questions("python", 3, budget())

    assert error.value.retryable is True
    assert len(calls) == 3


def test_unknown_errors_are_reported_without_their_details(caplog):
    caplog.set_level(logging.DEBUG)
    generator, calls, _ = make_generator([RuntimeError("key=AIzaSECRET")])

    with pytest.raises(GenerationProviderError) as error:
        generator.generate_questions("python", 3, budget())

    assert error.value.retryable is False
    assert "RuntimeError" in str(error.value)
    assert "AIzaSECRET" not in str(error.value)
    assert "AIzaSECRET" not in caplog.text
    assert len(calls) == 1


def test_error_messages_do_not_leak_the_provider_message():
    generator, _, _ = make_generator([FakeAPIError(500, "key=AIzaSECRET")] * 3)

    with pytest.raises(GenerationProviderError) as error:
        generator.generate_questions("python", 3, budget())

    assert "AIzaSECRET" not in str(error.value)


def test_an_empty_response_is_retried():
    empty = SimpleNamespace(text="", usage_metadata=SimpleNamespace(total_token_count=10))
    generator, calls, _ = make_generator([empty, reply(THREE_VALID)])

    result = generator.generate_questions("python", 3, budget())

    assert len(result.candidates) == 3
    assert len(calls) == 2


def test_malformed_json_is_retried_and_its_tokens_are_still_charged():
    generator, calls, _ = make_generator([raw_reply("not json", 400)] * 3)
    run_budget = budget()

    with pytest.raises(GenerationProviderError, match="unexpected format") as error:
        generator.generate_questions("python", 3, run_budget)

    assert error.value.retryable is True
    assert len(calls) == 3
    assert run_budget.tokens_used == 1200


def test_an_invalid_difficulty_counts_as_a_malformed_response():
    generator, calls, _ = make_generator([reply([q("What is a closure in Python?", "Expert")])] * 3)

    with pytest.raises(GenerationProviderError, match="unexpected format"):
        generator.generate_questions("python", 3, budget())

    assert len(calls) == 3


def test_with_zero_retries_only_one_attempt_is_made():
    generator, calls, _ = make_generator([FakeAPIError(503)], max_retries=0)

    with pytest.raises(GenerationProviderError):
        generator.generate_questions("python", 3, budget())

    assert len(calls) == 1


# ---------- limits ----------
def test_nothing_is_sent_when_the_run_limit_is_zero():
    generator, calls, _ = make_generator([reply(THREE_VALID)])

    with pytest.raises(BudgetExceeded) as error:
        generator.generate_questions("python", 3, budget(max_ai_calls=0))

    assert error.value.reason == AI_RUN_LIMIT
    assert calls == []


def test_retries_are_limited_by_the_category_cap():
    generator, calls, _ = make_generator([FakeAPIError(500), reply(THREE_VALID)])

    with pytest.raises(BudgetExceeded) as error:
        generator.generate_questions("python", 3, budget(max_ai_per_category=1))

    assert error.value.reason == AI_CATEGORY_LIMIT
    assert len(calls) == 1


def test_a_spent_token_budget_stops_further_retries():
    generator, calls, _ = make_generator([raw_reply("not json", 1200), reply(THREE_VALID)])

    with pytest.raises(BudgetExceeded) as error:
        generator.generate_questions("python", 3, budget(max_tokens=1000))

    assert error.value.reason == TOKEN_BUDGET
    assert len(calls) == 1


# ---------- construction ----------
def test_an_api_key_or_client_is_required():
    with pytest.raises(ValueError, match="API key"):
        GeminiQuestionGenerator()


def test_negative_retries_are_rejected():
    with pytest.raises(ValueError):
        GeminiQuestionGenerator("key", max_retries=-1, client=SimpleNamespace())


def test_the_model_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "custom-model")
    assert GeminiQuestionGenerator("key", client=SimpleNamespace()).model == "custom-model"

    monkeypatch.delenv("GEMINI_MODEL")
    assert GeminiQuestionGenerator("key", client=SimpleNamespace()).model == "gemini-2.5-flash"


def test_from_settings_needs_an_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    assert GeminiQuestionGenerator.from_settings() is None


def test_from_settings_is_disabled_when_ai_calls_are_zero(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    monkeypatch.setattr(config, "MAX_AI_CALLS_PER_RUN", 0)
    assert GeminiQuestionGenerator.from_settings() is None

    monkeypatch.setattr(config, "MAX_AI_CALLS_PER_RUN", 5)
    monkeypatch.setattr(config, "MAX_AI_CALLS_PER_CATEGORY", 0)
    assert GeminiQuestionGenerator.from_settings() is None


def test_from_settings_builds_a_generator(monkeypatch):
    created = {}

    def fake_client(**kwargs):
        created.update(kwargs)
        return SimpleNamespace(models=None)

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "custom-model")
    monkeypatch.setattr(config, "MAX_AI_CALLS_PER_RUN", 5)
    monkeypatch.setattr(config, "MAX_AI_CALLS_PER_CATEGORY", 2)
    monkeypatch.setattr(config, "MAX_PROVIDER_RETRIES", 1)
    monkeypatch.setattr(generation_module.genai, "Client", fake_client)

    generator = GeminiQuestionGenerator.from_settings()

    assert generator.model == "custom-model"
    assert generator.max_retries == 1
    assert created["api_key"] == "test-key"