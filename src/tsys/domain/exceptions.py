"""Domain exceptions. Adapters translate infra errors into these; entrypoints
decide restart/backoff (SPEC B5)."""

from __future__ import annotations


class DomainError(Exception):
    """Base for all domain-level errors."""


class RiskRejected(DomainError):
    """A proposed order violated a risk rule."""


class StaleCalendar(DomainError):
    """The economic calendar is older than its freshness window (SPEC D2.3 failsafe)."""
