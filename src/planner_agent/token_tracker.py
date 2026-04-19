"""Daily token usage tracker with ASCII progress bar and cost estimate.

Tracks cumulative input + output tokens per day and auto-resets
at midnight.  The progress bar is appended to outgoing messages
so the user always sees their budget status and estimated spend.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_BAR_WIDTH = 20  # characters in the progress bar

# Claude 3.5 Haiku pricing (USD per million tokens)
_PRICING: dict[str, tuple[float, float]] = {
    # model prefix: (input $/MTok, output $/MTok)
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-haiku": (0.25, 1.25),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-opus-4": (15.00, 75.00),
    "claude-3-opus": (15.00, 75.00),
}
_DEFAULT_PRICING = (1.00, 5.00)  # conservative fallback


class TokenTracker:
    """Tracks daily token usage against a budget.

    Args:
        daily_budget: Maximum tokens per day.  0 disables tracking.
        timezone: IANA timezone for day-boundary detection.
        model: Claude model name for cost estimation.
    """

    def __init__(
        self,
        daily_budget: int,
        timezone: str = "UTC",
        model: str = "",
    ) -> None:
        self._daily_budget = daily_budget
        self._tz = ZoneInfo(timezone)
        self._today: date = datetime.now(self._tz).date()
        self._input_tokens: int = 0
        self._output_tokens: int = 0
        self._input_price, self._output_price = _resolve_pricing(model)

    def record(self, input_tokens: int, output_tokens: int) -> None:
        """Add token counts from an API call to today's tally.

        Resets automatically if the day has rolled over.
        """
        self._maybe_reset()
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens
        logger.debug(
            "Tokens today: %d in + %d out = %d total",
            self._input_tokens,
            self._output_tokens,
            self.used,
        )

    def progress_bar(self) -> str:
        """Return a progress bar with token count and estimated cost.

        Example::

            |████████░░░░░░░░░░░░| 40% ⚡40.0k / 100.0k (~$0.12)
        """
        self._maybe_reset()
        if self._daily_budget <= 0:
            return ""

        total = self.used
        pct = min(total / self._daily_budget, 1.0)
        filled = round(pct * _BAR_WIDTH)
        empty = _BAR_WIDTH - filled
        bar = "█" * filled + "░" * empty
        used_str = _fmt_tokens(total)
        budget_str = _fmt_tokens(self._daily_budget)
        cost = self.estimated_cost
        return f"|{bar}| {pct:.0%} ⚡{used_str} / {budget_str} (~${cost:.3f})"

    @property
    def used(self) -> int:
        """Total tokens used today (input + output)."""
        self._maybe_reset()
        return self._input_tokens + self._output_tokens

    @property
    def estimated_cost(self) -> float:
        """Estimated cost in USD based on model pricing."""
        self._maybe_reset()
        input_cost = (self._input_tokens / 1_000_000) * self._input_price
        output_cost = (self._output_tokens / 1_000_000) * self._output_price
        return input_cost + output_cost

    def _maybe_reset(self) -> None:
        """Reset the counter if a new day has started."""
        today = datetime.now(self._tz).date()
        if today != self._today:
            total = self._input_tokens + self._output_tokens
            cost = (self._input_tokens / 1_000_000) * self._input_price + \
                   (self._output_tokens / 1_000_000) * self._output_price
            logger.info(
                "New day — resetting token counter (was %d, ~$%.4f)",
                total,
                cost,
            )
            self._today = today
            self._input_tokens = 0
            self._output_tokens = 0


def _resolve_pricing(model: str) -> tuple[float, float]:
    """Match a model name to its pricing tier."""
    for prefix, prices in _PRICING.items():
        if model.startswith(prefix):
            return prices
    return _DEFAULT_PRICING


def _fmt_tokens(n: int) -> str:
    """Format a token count as a compact string (e.g. ``1.2k``, ``150k``)."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)

