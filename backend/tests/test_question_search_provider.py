import json
import logging
from datetime import date

import httpx
import pytest

from app.core import question_discovery_config as config
from app.services.question_search_provider import (
    MAX_QUESTIONS_PER_RESULT,
    SEARCH_QUERIES,
    TAVILY_SEARCH_URL,
    SearchProviderError,
    TavilySearchProvider,
    clean_question_text,
    extract_questions,
    parse_results,
    query_for,
)
from app.services.run_budget import (
    SEARCH_CATEGORY_LIMIT,
    SEARCH_RUN_LIMIT,
    BudgetExceeded,
    RunBudget,
)

API_KEY = "tvly-secret-key"
GOOD_QUESTION = "What is the difference between a list and a tuple in Python?"

PAYLOAD = {
    "results": [
        {
            "title": "Top 50 Python Interview Questions",
            "url": "https://www.example.com/python-questions",
            "content": (
                "1. What is the difference between a list and a tuple in Python? [...] "
                "2. How does Python manage memory? [...] "
                "Subscribe to our newsletter today! Are you ready to ace your interview?"
            ),
        },
        {"title": "No URL", "url": "", "content": "What is a decorator in Python?"},
        {
            "title": "Duplicate page",
            "url": "https://other.dev/py",
            "content": (
                "Q3: What is the difference between a list and a tuple in Python? "
                "Python is a popular language. Explain GIL?"
            ),
        },
    ]
}


def make_provider(outcomes, *, max_retries=2, backoff_seconds=0):
    requests, sleeps = [], []

    def handler(request):
        requests.append(request)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = TavilySearchProvider(
        API_KEY,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        client=client,
        sleep=sleeps.append,
    )
    return provider, requests, sleeps


def budget(**overrides):
    values = dict(
        max_search_requests=10,
        max_ai_calls=0,
        max_tokens=1,
        max_search_per_category=5,
        max_ai_per_category=0,
    )
    values.update(overrides)
    return RunBudget(**values)


# ---------- cleaning ----------
@pytest.mark.parametrize(
    "text",
    [
        "What is the difference between a process and a thread?",
        "How do you download files concurrently in Python?",
        "Where would you place your database index?",
        "What is the discount factor in reinforcement learning?",
    ],
)
def test_normal_questions_are_accepted(text):
    assert clean_question_text(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "what is a closure in JavaScript?",
        "Why?",
        "Are you ready to ace your next interview?",
        "Subscribe to our newsletter for more questions?",
        "Visit https://example.com for more questions?",
        "What is this [...] thing about in Python?",
        "What is a closure? What is a decorator?",
        "Explain how database indexes work",
        "",
    ],
)
def test_unusable_text_is_rejected(text):
    assert clean_question_text(text) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1. What is a closure in Python?", "What is a closure in Python?"),
        ("Q3) What is a closure in Python?", "What is a closure in Python?"),
        ("- **What is a closure in Python?**", "What is a closure in Python?"),
        ("* [What is a closure in Python?](https://x.dev/c)", "What is a closure in Python?"),
        ('  "What is a closure in Python?"  ', "What is a closure in Python?"),
        ("What   is a\nclosure in Python?", "What is a closure in Python?"),
    ],
)
def test_numbering_markdown_and_whitespace_are_removed(raw, expected):
    assert clean_question_text(raw) == expected


def test_ai_questions_may_be_instructions_and_may_use_promo_words():
    assert (
        clean_question_text("Explain how database indexes work", require_question_mark=False)
        == "Explain how database indexes work"
    )

    pubsub = "What is the role of subscribe in a pub/sub system?"
    assert clean_question_text(pubsub) is None
    assert clean_question_text(pubsub, check_promo=False) == pubsub


def test_length_limits_come_from_the_config(monkeypatch):
    assert clean_question_text(GOOD_QUESTION) == GOOD_QUESTION

    monkeypatch.setattr(config, "MAX_QUESTION_LENGTH", 30)

    assert clean_question_text(GOOD_QUESTION) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Can you explain why a service stalls even though the handler is marked async?", True),
        ("Can you design a URL shortener?", True),
        ("Do you prefer working alone or in a team?", True),
        ("Where would you place your database index?", True),
        ("Can you reason about where the bottleneck actually is?", False),
        ("Can you choose between async, threads, and processes based on workload?", False),
        ("Can you design for cancellation, timeout budgets, and bounded concurrency?", False),
        ("Subscribe to our newsletter for more interview questions?", False),
    ],
)
def test_rhetorical_blog_questions_are_filtered_out(text, expected):
    assert bool(extract_questions(text)) is expected


def test_extract_questions_splits_snippets_and_removes_duplicates():
    snippet = (
        f"1. {GOOD_QUESTION} [...] "
        "2. How does Python manage memory? [...] "
        "Subscribe to our newsletter today! "
        f"3. {GOOD_QUESTION}"
    )

    assert extract_questions(snippet) == [GOOD_QUESTION, "How does Python manage memory?"]


def test_extract_questions_handles_empty_input():
    assert extract_questions("") == []
    assert extract_questions(None) == []


# ---------- parsing results ----------
def test_parse_results_keeps_attribution_for_every_question():
    found = parse_results(PAYLOAD, "python interview questions")

    assert [c.text for c in found] == [GOOD_QUESTION, "How does Python manage memory?"]
    first = found[0]
    assert first.source_url == "https://www.example.com/python-questions"
    assert first.source_domain == "example.com"
    assert first.source_title == "Top 50 Python Interview Questions"
    assert first.search_query == "python interview questions"
    assert first.provider == "tavily"
    assert "example.com" in first.attribution
    assert "Top 50 Python Interview Questions" in first.attribution


def test_parse_results_skips_malformed_and_unsafe_results():
    data = {
        "results": [
            "not a dict",
            {"title": "No URL", "url": "", "content": GOOD_QUESTION},
            {"title": "No content", "url": "https://a.example/x"},
            {"title": "Bad content", "url": "https://a.example/y", "content": 5},
            {"title": "FTP", "url": "ftp://files.example/q", "content": GOOD_QUESTION},
            {"title": "No host", "url": "http:///path", "content": GOOD_QUESTION},
            {"title": "Too long", "url": "https://a.example/" + "x" * 2100, "content": GOOD_QUESTION},
            {"title": "  Good   page ", "url": "https://WWW.Good.Example/q", "content": GOOD_QUESTION},
        ]
    }

    found = parse_results(data, "query")

    assert len(found) == 1
    assert found[0].source_domain == "good.example"
    assert found[0].source_title == "Good page"
    assert found[0].source_url == "https://WWW.Good.Example/q"


def test_a_question_found_on_two_pages_keeps_the_first_source():
    data = {
        "results": [
            {"title": "A", "url": "https://a.example/q", "content": GOOD_QUESTION},
            {"title": "B", "url": "https://b.example/q", "content": GOOD_QUESTION},
        ]
    }

    found = parse_results(data, "query")

    assert len(found) == 1
    assert found[0].source_domain == "a.example"


def test_at_most_five_questions_are_taken_from_one_result():
    content = " ".join(
        f"What is the purpose of feature number {i} in Python?" for i in range(8)
    )
    data = {"results": [{"title": "T", "url": "https://a.example/q", "content": content}]}

    found = parse_results(data, "query")

    assert MAX_QUESTIONS_PER_RESULT == 5
    assert len(found) == 5


def test_a_missing_title_is_allowed():
    data = {"results": [{"url": "https://a.example/q", "content": GOOD_QUESTION}]}

    found = parse_results(data, "query")

    assert found[0].source_title is None
    assert "a.example" in found[0].attribution


# ---------- queries ----------
def test_every_supported_category_has_search_queries():
    for category in config.SUPPORTED_CATEGORIES:
        assert len(SEARCH_QUERIES[category]) >= 2


def test_queries_rotate_by_day_and_attempt():
    day = date(2026, 10, 23)
    other_day = date(2026, 10, 24)

    assert query_for("python", 0, day) in SEARCH_QUERIES["python"]
    assert query_for("python", 0, day) == query_for("python", 0, day)
    assert query_for("python", 0, day) != query_for("python", 1, day)
    assert query_for("python", 0, day) != query_for("python", 0, other_day)


def test_unknown_category_has_no_query():
    with pytest.raises(ValueError):
        query_for("cooking")


# ---------- the request ----------
def test_the_request_uses_the_documented_format():
    provider, requests, _ = make_provider([httpx.Response(200, json=PAYLOAD)])

    found = provider.search_questions("python", "python interview questions", budget())

    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == TAVILY_SEARCH_URL
    assert request.headers["authorization"] == f"Bearer {API_KEY}"
    assert json.loads(request.content) == {
        "query": "python interview questions",
        "search_depth": "basic",
        "max_results": 10,
        "include_answer": False,
        "include_raw_content": False,
    }
    assert len(found) == 2


# ---------- retries and failures ----------
def test_a_server_error_is_retried_with_growing_delays():
    provider, requests, sleeps = make_provider(
        [httpx.Response(500), httpx.Response(500), httpx.Response(200, json=PAYLOAD)],
        backoff_seconds=2,
    )
    run_budget = budget()

    found = provider.search_questions("python", "q", run_budget)

    assert len(found) == 2
    assert len(requests) == 3
    assert run_budget.search_requests == 3  # every attempt is counted
    assert sleeps == [2, 4]


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503])
def test_retryable_statuses_give_up_after_the_retry_limit(status):
    provider, requests, _ = make_provider([httpx.Response(status) for _ in range(3)])
    run_budget = budget()

    with pytest.raises(SearchProviderError) as error:
        provider.search_questions("python", "q", run_budget)

    assert error.value.retryable is True
    assert error.value.status_code == status
    assert len(requests) == 3
    assert run_budget.search_requests == 3


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_errors_are_not_retried(status):
    provider, requests, sleeps = make_provider([httpx.Response(status)])

    with pytest.raises(SearchProviderError) as error:
        provider.search_questions("python", "q", budget())

    assert error.value.retryable is False
    assert error.value.status_code == status
    assert error.value.is_auth_error is (status in (401, 403))
    assert len(requests) == 1
    assert sleeps == []


def test_retry_after_is_respected_but_capped():
    provider, _, sleeps = make_provider(
        [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json=PAYLOAD)],
        backoff_seconds=2,
    )
    provider.search_questions("python", "q", budget())
    assert sleeps == [7.0]

    provider, _, sleeps = make_provider(
        [httpx.Response(429, headers={"Retry-After": "999"}), httpx.Response(200, json=PAYLOAD)],
        backoff_seconds=2,
    )
    provider.search_questions("python", "q", budget())
    assert sleeps == [30]


@pytest.mark.parametrize("header", ["soon", "-5"])
def test_an_invalid_retry_after_falls_back_to_the_normal_delay(header):
    provider, _, sleeps = make_provider(
        [httpx.Response(429, headers={"Retry-After": header}), httpx.Response(200, json=PAYLOAD)],
        backoff_seconds=2,
    )

    provider.search_questions("python", "q", budget())

    assert sleeps == [2]


@pytest.mark.parametrize(
    ("exception", "message"),
    [
        (httpx.ReadTimeout("slow"), "timed out"),
        (httpx.ConnectError("refused"), "Could not reach Tavily"),
    ],
)
def test_network_failures_are_retried_then_reported(exception, message):
    provider, requests, _ = make_provider([exception] * 3)

    with pytest.raises(SearchProviderError, match=message) as error:
        provider.search_questions("python", "q", budget())

    assert error.value.retryable is True
    assert len(requests) == 3


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"results": "nope"}),
    ],
)
def test_invalid_success_responses_are_reported_without_retrying(response):
    provider, requests, _ = make_provider([response])

    with pytest.raises(SearchProviderError) as error:
        provider.search_questions("python", "q", budget())

    assert error.value.retryable is False
    assert len(requests) == 1


def test_with_zero_retries_only_one_attempt_is_made():
    provider, requests, _ = make_provider([httpx.Response(500)], max_retries=0)

    with pytest.raises(SearchProviderError):
        provider.search_questions("python", "q", budget())

    assert len(requests) == 1


def test_the_api_key_never_appears_in_errors_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    provider, _, _ = make_provider([httpx.Response(401)])
    with pytest.raises(SearchProviderError) as auth_error:
        provider.search_questions("python", "q", budget())

    provider, _, _ = make_provider([httpx.Response(500)] * 3)
    with pytest.raises(SearchProviderError) as server_error:
        provider.search_questions("python", "q", budget())

    assert API_KEY not in str(auth_error.value)
    assert API_KEY not in str(server_error.value)
    assert API_KEY not in caplog.text


# ---------- limits ----------
def test_nothing_is_sent_when_the_run_limit_is_zero():
    provider, requests, _ = make_provider([httpx.Response(200, json=PAYLOAD)])

    with pytest.raises(BudgetExceeded) as error:
        provider.search_questions("python", "q", budget(max_search_requests=0))

    assert error.value.reason == SEARCH_RUN_LIMIT
    assert requests == []


def test_retries_are_limited_by_the_category_cap():
    provider, requests, _ = make_provider([httpx.Response(500)] * 3)

    with pytest.raises(BudgetExceeded) as error:
        provider.search_questions("python", "q", budget(max_search_per_category=2))

    assert error.value.reason == SEARCH_CATEGORY_LIMIT
    assert len(requests) == 2


def test_a_failed_attempt_still_costs_a_request():
    provider, _, _ = make_provider([httpx.Response(401)])
    run_budget = budget()

    with pytest.raises(SearchProviderError):
        provider.search_questions("python", "q", run_budget)

    assert run_budget.search_requests == 1


# ---------- construction ----------
def test_an_api_key_is_required():
    with pytest.raises(ValueError):
        TavilySearchProvider("")


def test_negative_retries_are_rejected():
    with pytest.raises(ValueError):
        TavilySearchProvider(API_KEY, max_retries=-1)


def test_from_settings_returns_none_when_search_is_disabled(monkeypatch):
    monkeypatch.setattr(config, "SEARCH_ENABLED", False)

    assert TavilySearchProvider.from_settings() is None


def test_from_settings_rejects_unsupported_providers(monkeypatch):
    monkeypatch.setattr(config, "SEARCH_ENABLED", True)
    monkeypatch.setattr(config, "SEARCH_PROVIDER", "brave")

    with pytest.raises(RuntimeError, match="Unsupported"):
        TavilySearchProvider.from_settings()


def test_from_settings_builds_a_provider_from_the_config(monkeypatch):
    monkeypatch.setattr(config, "SEARCH_ENABLED", True)
    monkeypatch.setattr(config, "SEARCH_PROVIDER", "tavily")
    monkeypatch.setattr(config, "SEARCH_API_KEY", "tvly-test")
    monkeypatch.setattr(config, "MAX_PROVIDER_RETRIES", 1)
    monkeypatch.setattr(config, "RETRY_BACKOFF_SECONDS", 5)

    provider = TavilySearchProvider.from_settings()
    try:
        assert provider.max_retries == 1
        assert provider.backoff_seconds == 5
    finally:
        provider.close()


def test_close_only_closes_a_client_the_provider_created():
    owned = TavilySearchProvider(API_KEY)
    owned.close()
    assert owned._client.is_closed

    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    shared = TavilySearchProvider(API_KEY, client=client)
    shared.close()
    assert not client.is_closed
    client.close()