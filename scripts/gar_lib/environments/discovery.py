from __future__ import annotations

from scripts.gar_lib.environments.registry import ENVIRONMENT_OPTIONS
from scripts.gar_lib.environments.setup_option import EnvironmentSetupOption


class EnvironmentDiscoveryError(RuntimeError):
    pass


def discover_environments() -> list[type[EnvironmentSetupOption]]:
    """Validate and return the explicitly registered setup choices."""

    environment_ids: dict[str, type[EnvironmentSetupOption]] = {}
    for environment in ENVIRONMENT_OPTIONS:
        _validate_environment(environment)
        existing = environment_ids.get(environment.environment_id)
        if existing is not None:
            raise EnvironmentDiscoveryError(
                "duplicate environment_id "
                f"{environment.environment_id!r}: {existing.__name__}, {environment.__name__}"
            )
        environment_ids[environment.environment_id] = environment

    return sorted(
        ENVIRONMENT_OPTIONS,
        key=lambda cls: (
            cls.category_order,
            cls.setup_priority(),
            cls.display_name.lower(),
        ),
    )


def _validate_environment(environment: type[EnvironmentSetupOption]) -> None:
    for attr in ("environment_id", "display_name", "description"):
        value = getattr(environment, attr, None)
        if not isinstance(value, str) or not value.strip():
            raise EnvironmentDiscoveryError(f"{environment.__name__} must define non-empty {attr}")

    required_commands = getattr(environment, "required_commands", None)
    if not isinstance(required_commands, tuple):
        raise EnvironmentDiscoveryError(f"{environment.__name__}.required_commands must be a tuple[str, ...]")
    if not all(isinstance(command, str) for command in required_commands):
        raise EnvironmentDiscoveryError(f"{environment.__name__}.required_commands must contain strings only")
