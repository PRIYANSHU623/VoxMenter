"""Tests for the daily discovery service.

Each test uses its own in-memory database and fake providers, so nothing real
is called and no search credits or AI tokens are spent.
"""

import json
from datetime import date, timedelta

import pytest

from app.core import question_discovery_config as config
from app.models import (
    CategoryCooldown,
    Question,
    QuestionGenerationRun,
    QuestionSource,
)
from app.services.question_dedup import exact_key
from app.services.question_discovery_service import (
    STATUS_ALREADY_DONE,
    _difficulty_from_query,
    _open_run,
    _rotate,
    run_daily_discovery,
)
from app.services.question_generation_provider import GenerationProviderError
from app.services.question_search_provider import SearchProviderError
from app.services.run_budget import RunBudget
from tests.fakes import FakeGenerator, FakeSearch

# Genuinely different questions, so none of them counts as a near-duplicate.
PY = [
    "How does Python manage memory?",
    "What are Python decorators used for?",
    "How do Python generators save memory?",
    "Explain how the Python GIL affects threads",
    "What does a context manager do in Python?",
    "How are exceptions handled in Python?",
    "What is the difference between deep and shallow copy?",
]
HR = [
    "Tell me about a time you resolved a conflict with a teammate.",
    "How do you handle tight deadlines?",
    "Why do you want to work at this company?",
    "What is your biggest professional weakness?",
]
LIST_TUPLE = "What is the difference between a list and a tuple in Python?"
LIST_TUPLE_REWORDED = "Difference between tuple and list in Python"


@pytest.fixture(autouse=True)
def pin_config(monkeypatch):
    """Tests must not depend on whatever is set in backend/.env."""
    monkeypatch.setattr(config, "MIN_QUESTION_LENGTH", 15)
    monkeypatch.setattr(config, "MAX_QUESTION_LENGTH", 255)
    monkeypatch.setattr(
        config, "ALLOWED_DIFFICULTIES", ("Beginner", "Intermediate", "Advanced")
    )
    monkeypatch.setattr(config, "DEFAULT_DIFFICULTY", "Beginner")
    monkeypatch.setattr(config, "DEDUP_JACCARD_THRESHOLD", 0.8)
    monkeypatch.setattr(config, "DEDUP_SEQUENCE_THRESHOLD", 0.9)
    monkeypatch.setattr(config, "RUN_LOCK_TTL_SECONDS", 3600)


def make_budget(**overrides):
    values = dict(
        max_search_requests=20,
        max_ai_calls=20,
        max_tokens=10**6,
        max_search_per_category=1,
        max_ai_per_category=1,
    )
    values.update(overrides)
    return RunBudget(**values)


def run(db, now, categories, search=None, gen=None, **options):
    options.setdefault("budget", make_budget())
    options.setdefault("questions_per_category", 3)
    options.setdefault("cooldown_days", 3)
    return run_daily_discovery(
        db,
        search_provider=search,
        generator=gen,
        categories=categories,
        now=now,
        **options,
    )


def add_question(db, title, category="python", is_active=True):
    question = Question(
        title=title, category=category, difficulty="Beginner", is_active=is_active
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return question


def run_rows(db, category):
    return (
        db.query(QuestionGenerationRun)
        .filter(QuestionGenerationRun.category == category)
        .order_by(QuestionGenerationRun.run_date, QuestionGenerationRun.id)
        .all()
    )


def titles(db):
    return [row.title for row in db.query(Question).order_by(Question.id)]


# ======================= inserting questions =======================
def test_web_questions_are_saved_with_their_source_details(db, now):
    search = FakeSearch([PY[:2]])

    result = run(db, now, ["python"], search, questions_per_category=2).results[0]

    assert result.status == "completed"
    assert (result.inserted_web, result.inserted_ai) == (2, 0)

    questions = db.query(Question).order_by(Question.id).all()
    assert [q.title for q in questions] == PY[:2]
    query = search.calls[0][1]
    for question in questions:
        assert question.is_active is True
        assert question.category == "python"
        assert question.difficulty == _difficulty_from_query(query)

    sources = db.query(QuestionSource).order_by(QuestionSource.id).all()
    assert len(sources) == 2
    for index, (source, question) in enumerate(zip(sources, questions)):
        assert source.question_id == question.id
        assert source.origin == "web"
        assert source.provider == "tavily"
        assert source.model_name is None
        assert source.source_url == f"https://site.example/{index}"
        assert source.source_domain == "site.example"
        assert source.source_title == "Page"
        assert source.search_query == query
        assert source.attribution
        assert source.exact_key == exact_key(question.title)


def test_ai_questions_are_labeled_and_have_no_source_url(db, now):
    gen = FakeGenerator(
        [[(PY[0], "Advanced", "Covers the allocator and garbage collector."), PY[1]]]
    )

    result = run(db, now, ["python"], None, gen, questions_per_category=2).results[0]

    assert result.status == "completed"
    assert (result.inserted_web, result.inserted_ai) == (0, 2)
    assert (result.ai_calls, result.tokens_used) == (1, 500)

    first, second = db.query(Question).order_by(Question.id).all()
    assert (first.difficulty, second.difficulty) == ("Advanced", "Intermediate")
    assert first.description == "Covers the allocator and garbage collector."
    assert second.description is None

    for source in db.query(QuestionSource).all():
        assert source.origin == "ai_generated"
        assert source.provider == "gemini"
        assert source.model_name == "fake-model"
        assert source.source_url is None
        assert source.source_domain is None
        assert source.attribution.startswith("AI-generated")


def test_an_unknown_ai_difficulty_falls_back_to_the_default(db, now):
    gen = FakeGenerator([[PY[0]]], difficulty="Expert")

    run(db, now, ["python"], None, gen, questions_per_category=1)

    assert db.query(Question).one().difficulty == "Beginner"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("advanced Python interview questions decorators generators", "Advanced"),
        ("HR interview questions for freshers", "Beginner"),
        ("basic SQL interview questions", "Beginner"),
        ("Python interview questions and answers", "Beginner"),
    ],
)
def test_difficulty_of_web_questions_comes_from_the_search_query(query, expected):
    assert _difficulty_from_query(query) == expected


def test_questions_the_ai_rejected_are_counted_as_invalid(db, now):
    gen = FakeGenerator([[PY[0]]], rejected_per_call=2)

    result = run(db, now, ["python"], None, gen, questions_per_category=1).results[0]

    assert result.status == "completed"
    assert result.invalid_skipped == 2


# ======================= duplicates =======================
def test_duplicates_and_invalid_questions_are_skipped(db, now):
    add_question(db, LIST_TUPLE)
    search = FakeSearch(
        [
            [
                LIST_TUPLE,  # same as a stored question
                LIST_TUPLE_REWORDED,  # same meaning as a stored question
                PY[0],  # new
                PY[0].lower(),  # repeats the previous candidate in this batch
                "What is X?",  # shorter than the minimum length
                PY[1],  # new
            ]
        ]
    )

    result = run(db, now, ["python"], search, questions_per_category=5).results[0]

    assert result.inserted_total == 2
    assert result.duplicates_skipped == 3
    assert result.invalid_skipped == 1
    assert result.status == "exhausted"  # fewer than the target were available
    assert titles(db) == [LIST_TUPLE, PY[0], PY[1]]


def test_a_deactivated_question_is_never_added_again(db, now):
    add_question(db, LIST_TUPLE, is_active=False)
    search = FakeSearch([[LIST_TUPLE]])

    result = run(db, now, ["python"], search).results[0]

    assert result.duplicates_skipped == 1
    assert db.query(Question).count() == 1


def test_a_question_stored_in_another_category_is_a_duplicate(db, now):
    add_question(db, "Tell me about yourself.", category="hr")
    search = FakeSearch([["Tell me about yourself."]])

    result = run(db, now, ["python"], search).results[0]

    assert result.duplicates_skipped == 1
    assert db.query(Question).count() == 1


def test_the_ai_is_given_recent_questions_of_the_same_category_only(db, now):
    add_question(db, PY[5])
    add_question(db, PY[6])
    add_question(db, HR[0], category="hr")
    gen = FakeGenerator()

    run(db, now, ["python"], None, gen)

    assert set(gen.calls[0].avoid) == {PY[5], PY[6]}


@pytest.mark.parametrize(
    ("target", "asked"),
    [(1, 4), (2, 5), (7, 10), (14, 15), (20, 15)],
)
def test_the_ai_is_asked_for_a_few_extra_questions_up_to_a_maximum(
    db, now, target, asked
):
    gen = FakeGenerator()

    run(db, now, ["python"], None, gen, questions_per_category=target)

    assert gen.calls[0].count == asked


def test_ai_calls_stop_when_nothing_new_comes_back(db, now):
    add_question(db, PY[0])
    gen = FakeGenerator([[PY[0]], [PY[1]]])

    result = run(
        db,
        now,
        ["python"],
        None,
        gen,
        questions_per_category=2,
        budget=make_budget(max_ai_per_category=3),
    ).results[0]

    assert result.status == "exhausted"
    assert len(gen.calls) == 1
    assert len(gen.batches) == 1  # the second batch was never requested


def test_a_second_ai_call_tops_up_the_missing_questions(db, now):
    gen = FakeGenerator([[PY[0]], [PY[1]]])

    result = run(
        db,
        now,
        ["python"],
        None,
        gen,
        questions_per_category=2,
        budget=make_budget(max_ai_per_category=2),
    ).results[0]

    assert result.status == "completed"
    assert [call.count for call in gen.calls] == [5, 4]
    assert result.inserted_ai == 2


# ======================= daily limits =======================
def test_a_category_stops_at_its_daily_target(db, now):
    search = FakeSearch([PY[:5]])
    gen = FakeGenerator([[PY[5]]])

    result = run(db, now, ["python"], search, gen, questions_per_category=3).results[0]

    assert result.status == "completed"
    assert result.inserted_web == 3
    assert titles(db) == PY[:3]
    assert gen.calls == []  # the AI was not needed

    cooldown = db.get(CategoryCooldown, "python")
    assert cooldown.last_status == "completed"
    assert cooldown.last_inserted == 3
    assert cooldown.paused_until is None
    assert cooldown.consecutive_shortfalls == 0


def test_a_finished_category_is_not_processed_again_the_same_day(db, now):
    run(db, now, ["python"], FakeSearch([PY[:3]]))
    search, gen = FakeSearch([PY[3:6]]), FakeGenerator([[PY[6]]])

    result = run(db, now, ["python"], search, gen).results[0]

    assert result.status == STATUS_ALREADY_DONE
    assert search.calls == []
    assert gen.calls == []
    assert db.query(Question).count() == 3
    assert len(run_rows(db, "python")) == 1


def test_an_interrupted_run_is_topped_up_without_exceeding_the_daily_target(db, now):
    # First run: only the search runs. The AI is blocked by the run limit.
    first = run(
        db,
        now,
        ["python"],
        FakeSearch([PY[:2]]),
        FakeGenerator([[PY[2]]]),
        budget=make_budget(max_ai_calls=0),
    ).results[0]
    assert first.status == "limit_reached"
    assert first.inserted_web == 2

    # Second run, same day: only the missing question is requested.
    gen = FakeGenerator([[PY[2]]])
    second = run(db, now, ["python"], FakeSearch(), gen).results[0]

    assert second.status == "completed"
    assert second.inserted_ai == 1
    assert gen.calls[0].count == 4  # 1 missing + 3 extra, not the full target
    assert db.query(Question).count() == 3

    rows = run_rows(db, "python")
    assert len(rows) == 1
    assert (rows[0].status, rows[0].inserted_web, rows[0].inserted_ai) == ("completed", 2, 1)


def test_the_next_day_starts_a_new_daily_run(db, now):
    run(db, now, ["python"], FakeSearch([PY[:3]]))

    result = run(
        db, now + timedelta(days=1), ["python"], FakeSearch([PY[3:6]])
    ).results[0]

    assert result.status == "completed"
    assert db.query(Question).count() == 6
    rows = run_rows(db, "python")
    assert [row.run_date for row in rows] == [now.date(), now.date() + timedelta(days=1)]


# ======================= request, AI and token limits =======================
def test_the_search_cap_per_category_limits_the_number_of_searches(db, now):
    search = FakeSearch([[PY[0]], [PY[1]], [PY[2]]])

    result = run(
        db,
        now,
        ["python"],
        search,
        questions_per_category=5,
        budget=make_budget(max_search_per_category=2),
    ).results[0]

    assert len(search.calls) == 2
    assert search.calls[0][1] != search.calls[1][1]  # a different query each time
    assert result.inserted_web == 2
    assert result.status == "exhausted"


def test_searching_stops_once_the_target_is_met(db, now):
    search = FakeSearch([PY[:3], [PY[3]]])

    run(
        db,
        now,
        ["python"],
        search,
        budget=make_budget(max_search_per_category=2),
    )

    assert len(search.calls) == 1


def test_the_run_wide_search_limit_stops_a_category_without_a_cooldown(db, now):
    search = FakeSearch([[PY[0]], [PY[1]]])

    result = run(
        db,
        now,
        ["python"],
        search,
        budget=make_budget(max_search_requests=1, max_search_per_category=2),
    ).results[0]

    assert result.status == "limit_reached"
    assert len(search.calls) == 1
    assert db.get(CategoryCooldown, "python").paused_until is None


def test_the_run_wide_ai_call_limit_is_shared_by_all_categories(db, now):
    gen = FakeGenerator([[PY[0]], [HR[0]]])

    report = run(
        db,
        now,
        ["python", "hr"],
        None,
        gen,
        questions_per_category=1,
        budget=make_budget(max_ai_calls=1),
    )

    assert sorted(r.status for r in report.results) == ["completed", "limit_reached"]
    assert len(gen.calls) == 1
    limited = next(r for r in report.results if r.status == "limit_reached")
    cooldown = db.get(CategoryCooldown, limited.category)
    assert cooldown.last_status == "limit_reached"
    assert cooldown.paused_until is None  # a shared limit is not the category's fault


def test_the_token_budget_stops_later_categories(db, now):
    gen = FakeGenerator([[PY[0]], [HR[0]]], tokens=600)

    report = run(
        db,
        now,
        ["python", "hr"],
        None,
        gen,
        questions_per_category=1,
        budget=make_budget(max_tokens=500),
    )

    assert sorted(r.status for r in report.results) == ["completed", "limit_reached"]
    assert len(gen.calls) == 1
    completed = next(r for r in report.results if r.status == "completed")
    assert completed.tokens_used == 600


def test_usage_is_recorded_on_the_daily_run_row(db, now):
    search = FakeSearch([[PY[0]]])
    gen = FakeGenerator([[PY[1]]])

    report = run(db, now, ["python"], search, gen)

    result = report.results[0]
    assert (result.search_requests, result.ai_calls, result.tokens_used) == (1, 1, 500)

    row = run_rows(db, "python")[0]
    assert row.run_id == report.run_id
    assert row.target == 3
    assert (row.inserted_web, row.inserted_ai) == (1, 1)
    assert (row.search_requests, row.ai_calls, row.tokens_used) == (1, 1, 500)
    assert row.status == "exhausted"
    assert row.finished_at is not None


# ======================= cooldowns =======================
def test_an_exhausted_category_pauses_then_resumes_automatically(db, now):
    expected = [
        (0, "exhausted", 2),
        (1, "skipped_cooldown", 0),
        (2, "skipped_cooldown", 0),
        (3, "exhausted", 2),
    ]
    for offset, status, provider_calls in expected:
        search, gen = FakeSearch(), FakeGenerator()
        result = run(
            db, now + timedelta(days=offset), ["python"], search, gen
        ).results[0]

        assert result.status == status, f"day +{offset}"
        assert len(search.calls) + len(gen.calls) == provider_calls, f"day +{offset}"
        if offset == 0:
            cooldown = db.get(CategoryCooldown, "python")
            assert cooldown.paused_until.date() == date(2026, 10, 27)
            assert cooldown.paused_until.hour == 0
            assert cooldown.consecutive_shortfalls == 1

    cooldown = db.get(CategoryCooldown, "python")
    assert cooldown.paused_until.date() == date(2026, 10, 30)
    assert cooldown.consecutive_shortfalls == 2

    rows = run_rows(db, "python")
    assert [row.status for row in rows] == [
        "exhausted",
        "skipped_cooldown",
        "skipped_cooldown",
        "exhausted",
    ]
    assert "2026-10-27" in rows[1].error_message


@pytest.mark.parametrize(
    ("paused_until_offset", "should_run"),
    [
        (timedelta(hours=-1), True),  # already expired
        (timedelta(0), True),  # expires at exactly this moment
        (timedelta(seconds=1), False),  # still paused
    ],
    ids=["expired", "expires-now", "still-paused"],
)
def test_the_cooldown_boundary(db, now, paused_until_offset, should_run):
    db.add(
        CategoryCooldown(
            category="python",
            paused_until=now + paused_until_offset,
            consecutive_shortfalls=2,
        )
    )
    db.commit()
    search = FakeSearch([PY[:3]])

    result = run(db, now, ["python"], search).results[0]
    cooldown = db.get(CategoryCooldown, "python")

    if should_run:
        assert result.status == "completed"
        assert cooldown.paused_until is None
        assert cooldown.consecutive_shortfalls == 0  # a good day resets the streak
    else:
        assert result.status == "skipped_cooldown"
        assert search.calls == []
        assert cooldown.consecutive_shortfalls == 2


def test_an_admin_can_bypass_an_active_cooldown(db, now):
    db.add(CategoryCooldown(category="python", paused_until=now + timedelta(days=1)))
    db.commit()
    search = FakeSearch([PY[:3]])

    result = run(db, now, ["python"], search, ignore_cooldown=True).results[0]

    assert result.status == "completed"
    assert len(search.calls) == 1
    assert db.get(CategoryCooldown, "python").paused_until is None


def test_clearing_a_cooldown_lets_a_skipped_category_run_the_same_day(db, now):
    db.add(CategoryCooldown(category="python", paused_until=now + timedelta(days=1)))
    db.commit()
    assert run(db, now, ["python"], FakeSearch([PY[:3]])).results[0].status == "skipped_cooldown"

    cooldown = db.get(CategoryCooldown, "python")
    cooldown.paused_until = None
    db.commit()

    result = run(db, now, ["python"], FakeSearch([PY[:3]])).results[0]

    assert result.status == "completed"
    rows = run_rows(db, "python")
    assert len(rows) == 1
    assert rows[0].status == "completed"


# ======================= provider failures =======================
def test_a_failing_provider_keeps_valid_questions_and_starts_no_cooldown(db, now):
    search = FakeSearch(
        error=SearchProviderError(
            "Tavily is temporarily unavailable (HTTP 500).",
            retryable=True,
            status_code=500,
        )
    )
    gen = FakeGenerator([[PY[0], PY[1]]])

    result = run(db, now, ["python"], search, gen, questions_per_category=3).results[0]

    assert result.status == "failed"
    assert result.inserted_ai == 2
    assert "temporarily unavailable" in result.message
    assert titles(db) == [PY[0], PY[1]]
    cooldown = db.get(CategoryCooldown, "python")
    assert cooldown.paused_until is None
    assert cooldown.consecutive_shortfalls == 0
    assert "temporarily unavailable" in run_rows(db, "python")[0].error_message


def test_the_day_is_completed_even_if_the_search_provider_failed(db, now):
    search = FakeSearch(error=SearchProviderError("Search is down.", retryable=True, status_code=503))
    gen = FakeGenerator([PY[:3]])

    result = run(db, now, ["python"], search, gen).results[0]

    assert result.status == "completed"
    assert "Search:" in run_rows(db, "python")[0].error_message


def test_a_rejected_search_key_disables_search_for_the_rest_of_the_job(db, now):
    search = FakeSearch(
        error=SearchProviderError("Tavily rejected the API key.", status_code=401)
    )
    gen = FakeGenerator([[PY[0]], [HR[0]]])

    report = run(db, now, ["python", "hr"], search, gen, questions_per_category=1)

    assert len(search.calls) == 1  # the second category never tried
    assert [r.status for r in report.results] == ["completed", "completed"]
    for category in ("python", "hr"):
        assert "Tavily rejected the API key" in run_rows(db, category)[0].error_message


def test_other_search_errors_do_not_disable_search(db, now):
    search = FakeSearch(
        error=SearchProviderError("Tavily is temporarily unavailable.", retryable=True, status_code=500)
    )

    report = run(db, now, ["python", "hr"], search)

    assert len(search.calls) == 2
    assert [r.status for r in report.results] == ["failed", "failed"]


def test_a_rejected_gemini_key_disables_the_ai_for_the_rest_of_the_job(db, now):
    gen = FakeGenerator(
        error=GenerationProviderError("Gemini rejected the API key.", status_code=401)
    )

    report = run(db, now, ["python", "hr"], None, gen)

    assert len(gen.calls) == 1
    assert [r.status for r in report.results] == ["failed", "failed"]
    for result in report.results:
        assert "Gemini rejected the API key" in result.message


def test_an_unexpected_error_in_one_category_does_not_stop_the_others(db, now):
    gen = FakeGenerator(
        [[HR[0]]], errors_by_category={"python": RuntimeError("secret boom")}
    )

    report = run(db, now, ["python", "hr"], None, gen, questions_per_category=1)

    by_category = {r.category: r for r in report.results}
    assert by_category["python"].status == "failed"
    assert by_category["python"].message == "Unexpected error. See the server logs."
    assert "boom" not in run_rows(db, "python")[0].error_message
    assert by_category["hr"].status == "completed"
    assert titles(db) == [HR[0]]


def test_without_any_provider_the_run_fails_clearly_and_starts_no_cooldown(db, now):
    result = run(db, now, ["python"], None, None).results[0]

    assert result.status == "failed"
    assert "No question source is available" in result.message
    assert db.get(CategoryCooldown, "python").paused_until is None


# ======================= concurrent runs =======================
def test_another_worker_that_is_still_running_blocks_the_category(db, now):
    db.add(
        QuestionGenerationRun(
            run_id="other-worker",
            run_date=now.date(),
            category="python",
            status="running",
            target=3,
            started_at=now - timedelta(minutes=30),
        )
    )
    db.commit()
    search = FakeSearch([PY[:3]])

    result = run(db, now, ["python"], search).results[0]

    assert result.status == STATUS_ALREADY_DONE
    assert search.calls == []
    row = run_rows(db, "python")[0]
    assert (row.run_id, row.status) == ("other-worker", "running")


def test_a_crashed_run_is_taken_over_after_the_lock_expires(db, now):
    db.add(
        QuestionGenerationRun(
            run_id="crashed-worker",
            run_date=now.date(),
            category="python",
            status="running",
            target=3,
            started_at=now - timedelta(hours=2),
        )
    )
    db.commit()

    result = run(db, now, ["python"], FakeSearch([PY[:3]])).results[0]

    assert result.status == "completed"
    row = run_rows(db, "python")[0]
    assert row.run_id != "crashed-worker"
    assert row.status == "completed"
    assert len(run_rows(db, "python")) == 1


def test_a_stale_row_can_only_be_claimed_by_one_worker(db, now):
    db.add(
        QuestionGenerationRun(
            run_id="old",
            run_date=now.date(),
            category="python",
            status="running",
            target=3,
            started_at=now - timedelta(hours=2),
        )
    )
    db.commit()

    first = _open_run(db, "run-a", "python", 3, now)
    second = _open_run(db, "run-b", "python", 3, now)

    assert first is not None and first.run_id == "run-a"
    assert second is None
    assert run_rows(db, "python")[0].run_id == "run-a"


def test_losing_the_race_to_create_the_daily_row_is_handled(db, now, monkeypatch):
    db.add(
        QuestionGenerationRun(
            run_id="other-worker",
            run_date=now.date(),
            category="python",
            status="running",
            target=3,
            started_at=now,
        )
    )
    db.commit()

    # Make this worker believe that no row exists yet, so it tries to create
    # one and hits the unique (day, category) constraint.
    class NoRows:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return None

    real_query = db.query
    hidden = {"done": False}

    def query(*entities, **kwargs):
        if entities and entities[0] is QuestionGenerationRun and not hidden["done"]:
            hidden["done"] = True
            return NoRows()
        return real_query(*entities, **kwargs)

    monkeypatch.setattr(db, "query", query)
    search = FakeSearch([PY[:3]])

    result = run(db, now, ["python"], search).results[0]

    assert result.status == STATUS_ALREADY_DONE
    assert search.calls == []
    rows = run_rows(db, "python")
    assert len(rows) == 1
    assert rows[0].run_id == "other-worker"


def test_losing_the_race_to_save_the_same_question_is_handled(db, now):
    # Another run already saved PY[0] under a different stored title, so the
    # title check cannot see it. The unique exact_key must catch it.
    other = add_question(
        db, "A completely unrelated stored question about networking?", category="general"
    )
    db.add(
        QuestionSource(
            question_id=other.id,
            origin="ai_generated",
            provider="gemini",
            exact_key=exact_key(PY[0]),
        )
    )
    db.commit()

    result = run(
        db, now, ["python"], FakeSearch([[PY[0], PY[1]]]), questions_per_category=2
    ).results[0]

    assert result.inserted_total == 1
    assert result.duplicates_skipped == 1
    assert PY[0] not in titles(db)  # the half-saved question was rolled back
    assert PY[1] in titles(db)
    row = run_rows(db, "python")[0]
    assert (row.inserted_web, row.duplicates_skipped) == (1, 1)


# ======================= input checks, ordering and the report =======================
def test_unknown_categories_are_rejected(db, now):
    with pytest.raises(ValueError, match="Unknown categories: cooking"):
        run(db, now, ["python", "cooking"])


def test_at_least_one_category_is_required(db, now):
    with pytest.raises(ValueError, match="At least one category"):
        run(db, now, [])


@pytest.mark.parametrize("option", ["questions_per_category", "cooldown_days"])
def test_targets_and_cooldowns_must_be_positive(db, now, option):
    with pytest.raises(ValueError):
        run(db, now, ["python"], **{option: 0})


def test_repeated_category_names_run_once(db, now):
    report = run(db, now, ["python", "python"], FakeSearch([PY[:3]]))

    assert [r.category for r in report.results] == ["python"]


def test_category_order_rotates_daily():
    items = ["a", "b", "c"]
    start = date(2026, 10, 24)

    firsts = {_rotate(items, start + timedelta(days=n))[0] for n in range(3)}

    assert firsts == set(items)
    assert sorted(_rotate(items, start)) == items


def test_a_small_run_budget_does_not_always_starve_the_same_category(db, now):
    def order_for(day, batches):
        report = run(db, day, ["python", "hr"], FakeSearch(batches), questions_per_category=1)
        return [r.category for r in report.results]

    first = order_for(now, [[PY[0]], [HR[0]]])
    second = order_for(now + timedelta(days=1), [[PY[1]], [HR[1]]])

    assert sorted(first) == sorted(second) == ["hr", "python"]
    assert first != second


def test_the_report_summarises_the_whole_run(db, now):
    report = run(
        db,
        now,
        ["python", "hr"],
        FakeSearch([PY[:3], HR[:3]]),
        run_id="fixed-run-id",
    )

    assert report.run_id == "fixed-run-id"
    assert report.total_inserted == 6

    data = json.loads(json.dumps(report.as_dict()))  # must be JSON-serialisable
    assert data["run_id"] == "fixed-run-id"
    assert data["total_inserted"] == 6
    assert {c["category"] for c in data["categories"]} == {"python", "hr"}
    assert all(c["inserted_total"] == 3 for c in data["categories"])

    for category in ("python", "hr"):
        assert run_rows(db, category)[0].run_id == "fixed-run-id"