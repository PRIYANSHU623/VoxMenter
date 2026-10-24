"""Web question discovery through the Tavily Search API.

Search results (title, URL, snippet) are scanned for question-shaped
sentences. Only the question text and its source details are kept, so every
question stays attributable to the page it was found on. Every request,
retries included, is charged to the RunBudget before it is sent.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.parse import urlparse

import httpx

from app.core import question_discovery_config as config
from app.services.question_dedup import exact_key
from app.services.run_budget import RunBudget

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
PROVIDER_NAME = "tavily"

MAX_QUESTIONS_PER_RESULT = 5
MAX_RETRY_AFTER_SECONDS = 30
MAX_URL_LENGTH = 2048

# Several queries per category. The one used rotates by date and attempt, so
# different days and repeated searches on the same day see different results.
SEARCH_QUERIES: dict[str, tuple[str, ...]] = {
    "dsa": (
        "data structures and algorithms interview questions",
        "coding interview questions arrays strings linked list",
        "dynamic programming interview questions",
        "binary tree and graph interview questions",
        "sorting and searching algorithm interview questions",
        "time complexity big o interview questions",
    ),
    "python": (
        "Python interview questions and answers",
        "advanced Python interview questions decorators generators",
        "Python coding interview questions",
        "Python data structures interview questions",
        "Python concurrency asyncio interview questions",
        "Python memory management GIL interview questions",
    ),
    "dbms_sql": (
        "SQL interview questions and answers",
        "DBMS interview questions normalization transactions",
        "SQL joins and indexes interview questions",
        "database ACID properties indexing interview questions",
        "SQL query optimization interview questions",
        "SQL window functions interview questions",
    ),
    "oop": (
        "object oriented programming interview questions",
        "OOP concepts inheritance polymorphism interview questions",
        "SOLID principles interview questions",
        "design patterns interview questions",
        "encapsulation and abstraction interview questions",
        "object oriented design interview questions",
    ),
    "ai_ml": (
        "machine learning interview questions",
        "deep learning interview questions",
        "NLP interview questions",
        "model evaluation overfitting interview questions",
        "data science interview questions",
        "generative AI and LLM interview questions",
    ),
    "hr": (
        "common HR interview questions",
        "behavioral interview questions",
        "tell me about a time interview questions",
        "HR interview questions for freshers",
        "leadership and teamwork interview questions",
        "strengths and weaknesses interview questions",
    ),
    "project": (
        "project based interview questions software engineer",
        "questions about your project in an interview",
        "resume project interview questions for freshers",
        "project discussion technical interview questions",
        "technical challenges in a project interview questions",
        "portfolio project interview questions developer",
    ),
    "general": (
        "software developer interview questions",
        "technical interview questions for freshers",
        "computer science fundamentals interview questions",
        "operating systems and networking interview questions",
        "git and version control interview questions",
        "software engineering interview questions",
    ),
}


def query_for(category: str, attempt: int = 0, today: date | None = None) -> str:
    variants = SEARCH_QUERIES.get(category)
    if not variants:
        raise ValueError(f"No search queries are defined for category {category!r}")
    day = today or datetime.now(timezone.utc).date()
    return variants[(day.toordinal() + attempt) % len(variants)]


# ---------- question text cleaning ----------
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_TRUNCATION = re.compile(r"\[\s*(?:\.\.\.|\u2026)\s*\]")
_LEADING_BULLET = re.compile(r"^[\s\-\*\u2022\u25aa\u25e6>#]+")
_LEADING_NUMBER = re.compile(
    r"^\s*(?:q(?:uestion)?\s*)?\d{1,3}\s*[.):]\s*", re.IGNORECASE
)
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9"\u201c(])')
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)

_PROMO_STARTS = (
    "are you looking",
    "looking for",
    "ready to",
    "want to learn",
    "need help",
    "wondering",
    "struggling",
    "did you know",
)
_PROMO_PHRASES = re.compile(
    r"\b(?:click here|subscribe|sign up|free course|enroll|our course|"
    r"ace your|land your|dream job|limited time)\b",
    re.IGNORECASE,
)

# "Can you <verb> ...?" is a normal interview prompt only for these verbs.
# Blog prose like "Can you reason about ...?" is rhetorical, so it is dropped.
_MODAL_STARTS = ("can you ", "could you ", "would you ", "will you ")
_INTERVIEW_VERBS = frozenset(
    {
        "explain", "describe", "tell", "walk", "give", "name", "define",
        "write", "implement", "differentiate", "distinguish", "compare",
        "list", "discuss", "solve", "find", "outline", "summarize",
        "elaborate", "share", "talk", "say", "justify", "show",
        "demonstrate", "identify", "mention", "recall", "think", "code",
    }
)


def _is_interview_prompt(text: str) -> bool:
    lowered = text.lower()
    for start in _MODAL_STARTS:
        if lowered.startswith(start):
            rest = lowered[len(start):].split()
            if not rest:
                return False
            verb = rest[0].strip(",.")
            if verb == "design":
                # "Can you design a URL shortener?" yes; "design for X" no.
                return len(rest) > 1 and rest[1] in {"a", "an", "the", "your"}
            return verb in _INTERVIEW_VERBS
    return True


def clean_question_text(
    text: str,
    *,
    require_question_mark: bool = True,
    check_promo: bool = True,
) -> str | None:
    """Return a tidy single question, or None if it is not usable.

    Web results must end with a question mark. AI-generated questions may be
    imperative ("Explain how ..."), so callers pass require_question_mark=False
    for those.
    """
    value = _MARKDOWN_LINK.sub(r"\1", text or "")
    value = value.replace("**", "").replace("`", "")
    value = re.sub(r"\s+", " ", value).strip()
    value = _LEADING_BULLET.sub("", value)
    value = _LEADING_NUMBER.sub("", value)
    value = value.strip(" \"'\u201c\u201d\u2018\u2019")

    if not value:
        return None
    if not config.MIN_QUESTION_LENGTH <= len(value) <= config.MAX_QUESTION_LENGTH:
        return None
    if len(value.split()) < 3:
        return None
    # A lowercase start usually means a sentence fragment.
    if not value[0].isupper():
        return None
    if _URL.search(value) or any(mark in value for mark in ("[", "]", "|", "\u2026", "...")):
        return None
    if require_question_mark and (not value.endswith("?") or "?" in value[:-1]):
        return None

        # Promo checks are for web text only. AI-generated questions legitimately
    # mention words like "subscribe" (pub/sub) or "discount" (RL).
    if check_promo:
        lowered = value.lower()
        if lowered.startswith(_PROMO_STARTS):
            return None
        if _PROMO_PHRASES.search(lowered):
            return None
    return value


def extract_questions(text: str) -> list[str]:
    """Question sentences found in a search snippet, without duplicates."""
    prepared = _TRUNCATION.sub("\n", text or "")
    found: list[str] = []
    seen: set[str] = set()

    for line in prepared.splitlines():
        for sentence in _SENTENCE_SPLIT.split(line):
            if "?" not in sentence:
                continue
            cleaned = clean_question_text(sentence.strip())
            if cleaned is None or not _is_interview_prompt(cleaned):
                continue
            key = exact_key(cleaned)
            if key in seen:
                continue
            seen.add(key)
            found.append(cleaned)
    return found


# ---------- results ----------
@dataclass(frozen=True)
class CandidateQuestion:
    text: str
    source_url: str
    source_title: str | None
    source_domain: str
    search_query: str
    provider: str
    attribution: str


def _attribution(domain: str, title: str | None) -> str:
    source = f"{domain} ({title})" if title else domain
    return (
        f"Found on {source} through web search. "
        "The wording comes from the search result snippet."
    )


def parse_results(data: dict, query: str) -> list[CandidateQuestion]:
    candidates: list[CandidateQuestion] = []
    seen: set[str] = set()

    for item in data.get("results", []):
        if not isinstance(item, dict):
            continue

        url = item.get("url")
        content = item.get("content")
        if not isinstance(url, str) or not isinstance(content, str):
            continue

        url = url.strip()
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname
        except ValueError:
            continue
        if parsed.scheme not in ("http", "https") or not hostname or len(url) > MAX_URL_LENGTH:
            continue

        domain = hostname.lower().removeprefix("www.")[:255]
        raw_title = item.get("title")
        title = (
            " ".join(raw_title.split())[:500]
            if isinstance(raw_title, str) and raw_title.strip()
            else None
        )

        taken = 0
        for text in extract_questions(content):
            key = exact_key(text)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                CandidateQuestion(
                    text=text,
                    source_url=url,
                    source_title=title,
                    source_domain=domain,
                    search_query=query,
                    provider=PROVIDER_NAME,
                    attribution=_attribution(domain, title),
                )
            )
            taken += 1
            if taken >= MAX_QUESTIONS_PER_RESULT:
                break

    return candidates


# ---------- provider ----------
class SearchProviderError(Exception):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after = retry_after

    @property
    def is_auth_error(self) -> bool:
        return self.status_code in (401, 403)


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


class TavilySearchProvider:
    name = PROVIDER_NAME

    def __init__(
        self,
        api_key: str,
        *,
        max_retries: int = 2,
        backoff_seconds: float = 2,
        timeout_seconds: float = 20.0,
        max_results: int = 10,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("A Tavily API key is required")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")

        self._api_key = api_key
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.max_results = max_results
        self._sleep = sleep
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout_seconds)

    @classmethod
    def from_settings(cls) -> "TavilySearchProvider | None":
        """Build the provider from config, or None when search is disabled."""
        if not config.SEARCH_ENABLED:
            return None
        if config.SEARCH_PROVIDER != PROVIDER_NAME:
            raise RuntimeError(
                f"Unsupported QUESTION_SEARCH_PROVIDER {config.SEARCH_PROVIDER!r}. "
                f"Only {PROVIDER_NAME!r} is supported."
            )
        return cls(
            config.SEARCH_API_KEY,
            max_retries=config.MAX_PROVIDER_RETRIES,
            backoff_seconds=config.RETRY_BACKOFF_SECONDS,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def search_questions(
        self,
        category: str,
        query: str,
        budget: RunBudget,
    ) -> list[CandidateQuestion]:
        """Search once (plus limited retries) and return candidate questions.

        Raises BudgetExceeded when a limit is reached and SearchProviderError
        when Tavily keeps failing.
        """
        attempts = self.max_retries + 1

        for attempt in range(attempts):
            budget.consume_search(category)  # every attempt is counted
            try:
                data = self._post(query)
            except SearchProviderError as error:
                logger.warning(
                    "Tavily search failed (attempt %d/%d, category %s): %s",
                    attempt + 1,
                    attempts,
                    category,
                    error,
                )
                if not error.retryable or attempt == attempts - 1:
                    raise
                delay = self.backoff_seconds * (2**attempt)
                if error.retry_after is not None:
                    delay = max(delay, min(error.retry_after, MAX_RETRY_AFTER_SECONDS))
                self._sleep(delay)
                continue
            return parse_results(data, query)

        raise SearchProviderError("Tavily search failed.")

    def _post(self, query: str) -> dict:
        try:
            response = self._client.post(
                TAVILY_SEARCH_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "search_depth": "basic",  # 1 credit per request
                    "max_results": self.max_results,
                    "include_answer": False,
                    "include_raw_content": False,
                },
            )
        except httpx.TimeoutException as exc:
            raise SearchProviderError("Tavily request timed out.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise SearchProviderError("Could not reach Tavily.", retryable=True) from exc

        status = response.status_code

        if status in (401, 403):
            raise SearchProviderError(
                "Tavily rejected the API key. Check QUESTION_SEARCH_API_KEY.",
                status_code=status,
            )
        if status == 429:
            raise SearchProviderError(
                "Tavily rate limit reached (HTTP 429).",
                retryable=True,
                status_code=status,
                retry_after=_retry_after(response),
            )
        if status == 408 or status >= 500:
            raise SearchProviderError(
                f"Tavily is temporarily unavailable (HTTP {status}).",
                retryable=True,
                status_code=status,
                retry_after=_retry_after(response),
            )
        if status >= 400:
            raise SearchProviderError(f"Tavily returned HTTP {status}.", status_code=status)

        try:
            data = response.json()
        except ValueError as exc:
            raise SearchProviderError("Tavily returned invalid JSON.") from exc

        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise SearchProviderError("Tavily returned an unexpected response format.")
        return data