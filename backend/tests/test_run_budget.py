import threading

import pytest

from app.core import question_discovery_config as config
from app.services.run_budget import (
    AI_CATEGORY_LIMIT,
    AI_RUN_LIMIT,
    SEARCH_CATEGORY_LIMIT,
    SEARCH_RUN_LIMIT,
    TOKEN_BUDGET,
    BudgetExceeded,
    RunBudget,
    Usage,
)


def make(**overrides):
    values = dict(
        max_search_requests=10,
        max_ai_calls=10,
        max_tokens=10_000,
        max_search_per_category=5,
        max_ai_per_category=5,
    )
    values.update(overrides)
    return RunBudget(**values)


def test_search_is_limited_per_category():
    budget = make(max_search_per_category=2)
    budget.consume_search("python")
    budget.consume_search("python")

    with pytest.raises(BudgetExceeded) as error:
        budget.consume_search("python")

    assert error.value.reason == SEARCH_CATEGORY_LIMIT
    budget.consume_search("hr")  # other categories are unaffected
    assert budget.usage("python").search_requests == 2
    assert budget.usage("hr").search_requests == 1


def test_search_is_limited_per_run():
    budget = make(max_search_requests=3, max_search_per_category=2)
    budget.consume_search("python")
    budget.consume_search("python")
    budget.consume_search("hr")

    with pytest.raises(BudgetExceeded) as error:
        budget.consume_search("dsa")

    assert error.value.reason == SEARCH_RUN_LIMIT
    assert budget.search_requests == 3


def test_the_run_limit_is_reported_before_the_category_limit():
    budget = make(max_search_requests=1, max_search_per_category=1)
    budget.consume_search("python")

    with pytest.raises(BudgetExceeded) as error:
        budget.consume_search("python")

    assert error.value.reason == SEARCH_RUN_LIMIT


def test_a_blocked_request_is_not_counted():
    budget = make(max_search_requests=1)
    budget.consume_search("python")

    for _ in range(3):
        with pytest.raises(BudgetExceeded):
            budget.consume_search("python")

    assert budget.search_requests == 1


def test_ai_calls_are_limited_per_category_and_per_run():
    budget = make(max_ai_calls=2, max_ai_per_category=1)
    budget.consume_ai_call("python")

    with pytest.raises(BudgetExceeded) as category_error:
        budget.consume_ai_call("python")
    assert category_error.value.reason == AI_CATEGORY_LIMIT

    budget.consume_ai_call("hr")

    with pytest.raises(BudgetExceeded) as run_error:
        budget.consume_ai_call("dsa")
    assert run_error.value.reason == AI_RUN_LIMIT
    assert budget.ai_calls == 2


def test_the_token_budget_blocks_the_next_ai_call():
    budget = make(max_tokens=1000)
    budget.consume_ai_call("python")
    budget.add_tokens("python", 1200)  # one call may overshoot the budget

    assert budget.tokens_used == 1200
    with pytest.raises(BudgetExceeded) as error:
        budget.consume_ai_call("hr")
    assert error.value.reason == TOKEN_BUDGET


def test_the_token_budget_is_reported_before_other_ai_limits():
    budget = make(max_tokens=10, max_ai_calls=1, max_ai_per_category=1)
    budget.consume_ai_call("python")
    budget.add_tokens("python", 50)

    with pytest.raises(BudgetExceeded) as error:
        budget.consume_ai_call("python")

    assert error.value.reason == TOKEN_BUDGET


@pytest.mark.parametrize("tokens", [None, 0, -5])
def test_add_tokens_ignores_missing_or_invalid_values(tokens):
    budget = make()
    budget.add_tokens("python", tokens)
    assert budget.tokens_used == 0


def test_tokens_are_tracked_per_category_and_in_total():
    budget = make()
    budget.add_tokens("python", 100)
    budget.add_tokens("python", 20)
    budget.add_tokens("hr", 50)

    assert budget.usage("python").tokens_used == 120
    assert budget.usage("hr").tokens_used == 50
    assert budget.usage("dsa").tokens_used == 0
    assert budget.totals().tokens_used == 170


def test_checking_a_limit_does_not_spend_anything():
    budget = make(max_search_requests=1, max_ai_calls=1)

    assert budget.can_search("python")
    assert budget.can_call_ai("python")
    assert budget.search_block_reason("python") is None
    assert budget.ai_block_reason("python") is None
    assert budget.totals() == Usage(0, 0, 0)

    budget.consume_search("python")
    budget.consume_ai_call("python")

    assert not budget.can_search("python")
    assert not budget.can_call_ai("hr")
    assert budget.search_block_reason("python") == SEARCH_RUN_LIMIT
    assert budget.ai_block_reason("hr") == AI_RUN_LIMIT


def test_run_limits_are_exhausted_only_when_neither_search_nor_ai_is_left():
    budget = make(max_search_requests=1, max_ai_calls=1)
    assert budget.run_limits_exhausted is False

    budget.consume_search("python")
    assert budget.run_limits_exhausted is False  # AI is still available

    budget.consume_ai_call("python")
    assert budget.run_limits_exhausted is True


def test_an_exhausted_token_budget_counts_as_no_ai_left():
    budget = make(max_search_requests=1, max_tokens=100)
    budget.consume_search("python")
    assert budget.run_limits_exhausted is False

    budget.add_tokens("python", 100)
    assert budget.run_limits_exhausted is True


def test_zero_limits_disable_everything():
    budget = make(
        max_search_requests=0,
        max_ai_calls=0,
        max_tokens=1,
        max_search_per_category=0,
        max_ai_per_category=0,
    )

    assert budget.run_limits_exhausted is True
    with pytest.raises(BudgetExceeded) as search_error:
        budget.consume_search("python")
    with pytest.raises(BudgetExceeded) as ai_error:
        budget.consume_ai_call("python")
    assert search_error.value.reason == SEARCH_RUN_LIMIT
    assert ai_error.value.reason == AI_RUN_LIMIT


@pytest.mark.parametrize(
    "name",
    [
        "max_search_requests",
        "max_ai_calls",
        "max_tokens",
        "max_search_per_category",
        "max_ai_per_category",
    ],
)
def test_negative_limits_are_rejected(name):
    with pytest.raises(ValueError, match=name):
        make(**{name: -1})


def test_from_settings_reads_the_discovery_config(monkeypatch):
    monkeypatch.setattr(config, "MAX_SEARCH_REQUESTS_PER_RUN", 4)
    monkeypatch.setattr(config, "MAX_AI_CALLS_PER_RUN", 3)
    monkeypatch.setattr(config, "MAX_TOKEN_BUDGET_PER_RUN", 999)
    monkeypatch.setattr(config, "MAX_SEARCH_REQUESTS_PER_CATEGORY", 2)
    monkeypatch.setattr(config, "MAX_AI_CALLS_PER_CATEGORY", 1)

    budget = RunBudget.from_settings()

    assert (
        budget.max_search_requests,
        budget.max_ai_calls,
        budget.max_tokens,
        budget.max_search_per_category,
        budget.max_ai_per_category,
    ) == (4, 3, 999, 2, 1)


def test_every_run_starts_with_a_fresh_budget():
    first = make(max_search_requests=1)
    first.consume_search("python")

    second = make(max_search_requests=1)

    assert second.can_search("python")
    assert second.search_requests == 0


def test_concurrent_requests_never_exceed_the_limit():
    budget = make(max_search_requests=100, max_search_per_category=1000)
    successes: list[int] = []

    def worker():
        count = 0
        for _ in range(50):
            try:
                budget.consume_search("python")
                count += 1
            except BudgetExceeded:
                pass
        successes.append(count)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(successes) == 100
    assert budget.search_requests == 100