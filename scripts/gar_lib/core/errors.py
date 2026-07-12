"""Errors raised by the new GAR domain and orchestration layers."""


class GarDomainError(RuntimeError):
    """A user-actionable failure without CLI rendering or exit-code policy."""
