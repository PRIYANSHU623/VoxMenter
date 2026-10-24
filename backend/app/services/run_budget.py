"""Shared request, AI-call and token limits for one discovery run.

One RunBudget is created per job run and passed to every provider. Providers
consume from it *before* each external call (retries included), so a failing
provider cannot loop and spend past the configured limits.

Token usage is only known after a call returns. The token budget is therefore
checked before each AI call and can be exceeded by at most one call.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

SEARCH_RUN_LIMIT = "search_run_limit"
SEARCH_CATEGORY_LIMIT = "search_category_limit"
AI_RUN_LIMIT = "ai_run_limit"
AI_CATEGORY_LIMIT = "ai_category_limit"
TOKEN_BUDGET = "token_budget"

_MESSAGES = {
    SEARCH_RUN_LIMIT: "The search request limit for this run was reached.",
    SEARCH_CATEGORY_LIMIT: "The search request limit for this category was reached.",
    AI_RUN_LIMIT: "The AI call limit for this run was reached.",
    AI_CATEGORY_LIMIT: "The AI call limit for this category was reached.",
    TOKEN_BUDGET: "The token budget for this run was reached.",
}


class BudgetExceeded(Exception):
    """Raised when a request would go past a configured limit."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(_MESSAGES.get(reason, reason))


@dataclass(frozen=True)
class Usage:
    search_requests: int
    ai_calls: int
    tokens_used: int


class RunBudget:
    def __init__(
        self,
        *,
        max_search_requests: int,
        max_ai_calls: int,
        max_tokens: int,
        max_search_per_category: int,
        max_ai_per_category: int,
    ) -> None:
        limits = {
            "max_search_requests": max_search_requests,
            "max_ai_calls": max_ai_calls,
            "max_tokens": max_tokens,
            "max_search_per_category": max_search_per_category,
            "max_ai_per_category": max_ai_per_category,
        }
        for name, value in limits.items():
            if value < 0:
                raise ValueError(f"{name} cannot be negative, got {value}")

        self.max_search_requests = max_search_requests
        self.max_ai_calls = max_ai_calls
        self.max_tokens = max_tokens
        self.max_search_per_category = max_search_per_category
        self.max_ai_per_category = max_ai_per_category

        self._lock = threading.Lock()
        self._searches: dict[str, int] = {}
        self._ai_calls: dict[str, int] = {}
        self._tokens: dict[str, int] = {}

    @classmethod
    def from_settings(cls) -> "RunBudget":
        """Build a budget from question_discovery_config."""
        from app.core import question_discovery_config as config

        return cls(
            max_search_requests=config.MAX_SEARCH_REQUESTS_PER_RUN,
            max_ai_calls=config.MAX_AI_CALLS_PER_RUN,
            max_tokens=config.MAX_TOKEN_BUDGET_PER_RUN,
            max_search_per_category=config.MAX_SEARCH_REQUESTS_PER_CATEGORY,
            max_ai_per_category=config.MAX_AI_CALLS_PER_CATEGORY,
        )

    # ---------- totals ----------
    @property
    def search_requests(self) -> int:
        return sum(self._searches.values())

    @property
    def ai_calls(self) -> int:
        return sum(self._ai_calls.values())

    @property
    def tokens_used(self) -> int:
        return sum(self._tokens.values())

    # ---------- checks ----------
    def _search_block(self, category: str) -> str | None:
        if self.search_requests >= self.max_search_requests:
            return SEARCH_RUN_LIMIT
        if self._searches.get(category, 0) >= self.max_search_per_category:
            return SEARCH_CATEGORY_LIMIT
        return None

    def _ai_block(self, category: str) -> str | None:
        if self.tokens_used >= self.max_tokens:
            return TOKEN_BUDGET
        if self.ai_calls >= self.max_ai_calls:
            return AI_RUN_LIMIT
        if self._ai_calls.get(category, 0) >= self.max_ai_per_category:
            return AI_CATEGORY_LIMIT
        return None

    def search_block_reason(self, category: str) -> str | None:
        with self._lock:
            return self._search_block(category)

    def ai_block_reason(self, category: str) -> str | None:
        with self._lock:
            return self._ai_block(category)

    def can_search(self, category: str) -> bool:
        return self.search_block_reason(category) is None

    def can_call_ai(self, category: str) -> bool:
        return self.ai_block_reason(category) is None

    # ---------- spending ----------
    def consume_search(self, category: str) -> None:
        """Count one search request, or raise BudgetExceeded."""
        with self._lock:
            reason = self._search_block(category)
            if reason is not None:
                raise BudgetExceeded(reason)
            self._searches[category] = self._searches.get(category, 0) + 1

    def consume_ai_call(self, category: str) -> None:
        """Count one AI call, or raise BudgetExceeded."""
        with self._lock:
            reason = self._ai_block(category)
            if reason is not None:
                raise BudgetExceeded(reason)
            self._ai_calls[category] = self._ai_calls.get(category, 0) + 1

    def add_tokens(self, category: str, tokens: int | None) -> None:
        """Record tokens reported by a finished AI call. None counts as 0."""
        if not tokens or tokens < 0:
            return
        with self._lock:
            self._tokens[category] = self._tokens.get(category, 0) + tokens

    # ---------- reporting ----------
    def usage(self, category: str) -> Usage:
        with self._lock:
            return Usage(
                search_requests=self._searches.get(category, 0),
                ai_calls=self._ai_calls.get(category, 0),
                tokens_used=self._tokens.get(category, 0),
            )

    def totals(self) -> Usage:
        with self._lock:
            return Usage(
                search_requests=sum(self._searches.values()),
                ai_calls=sum(self._ai_calls.values()),
                tokens_used=sum(self._tokens.values()),
            )

    @property
    def run_limits_exhausted(self) -> bool:
        """True when neither search nor AI can be used for any category."""
        with self._lock:
            no_search = sum(self._searches.values()) >= self.max_search_requests
            no_ai = (
                sum(self._ai_calls.values()) >= self.max_ai_calls
                or sum(self._tokens.values()) >= self.max_tokens
            )
            return no_search and no_ai