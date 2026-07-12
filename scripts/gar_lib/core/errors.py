"""Errors raised by the new GAR domain and orchestration layers."""


class GarDomainError(RuntimeError):
    """A user-actionable failure without CLI rendering or exit-code policy."""


class AccessConnectionError(GarDomainError):
    """A channel could not reach or authenticate with its endpoint."""

    def __init__(
        self,
        *,
        channel: str,
        endpoint: str,
        reason: str,
        returncode: int,
    ):
        self.channel = channel
        self.endpoint = endpoint
        self.reason = reason
        self.returncode = returncode
        super().__init__(f"{channel} connection failed: {endpoint} ({reason}, exit {returncode})")
