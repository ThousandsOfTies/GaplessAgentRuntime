from __future__ import annotations

import inspect
import pkgutil
from pathlib import Path

import scripts.gar_lib.environments.registry as registry_pkg
from scripts.gar_lib.environments.base import DevEnvironment


class ProviderDiscoveryError(RuntimeError):
    pass


CATEGORY_METADATA = {
    "codespace": {
        "name": "開発環境",
        "order": 10,
    },
    "simulator": {
        "name": "シミュレート環境",
        "order": 20,
    },
    "target": {
        "name": "実機環境",
        "order": 30,
    },
}


def discover_environment_providers() -> list[type[DevEnvironment]]:
    providers: list[type[DevEnvironment]] = []
    provider_ids: dict[str, type[DevEnvironment]] = {}

    for module_info in pkgutil.walk_packages(
        registry_pkg.__path__,
        prefix=f"{registry_pkg.__name__}.",
    ):
        if not _is_provider_module(module_info.name):
            continue

        module = __import__(module_info.name, fromlist=[""])
        category_id = _category_id_for_module(module.__name__)
        category = CATEGORY_METADATA.get(category_id, {})

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is DevEnvironment:
                continue
            if not issubclass(obj, DevEnvironment):
                continue
            if obj.__module__ != module.__name__:
                continue

            _validate_provider(obj)
            existing = provider_ids.get(obj.provider_id)
            if existing is not None:
                raise ProviderDiscoveryError(
                    "duplicate provider_id "
                    f"{obj.provider_id!r}: {existing.__name__}, {obj.__name__}"
            )
            provider_ids[obj.provider_id] = obj
            obj.category_id = category_id
            obj.category_name = category.get("name", category_id)
            obj.category_order = category.get("order", 100)
            providers.append(obj)

    return sorted(
        providers,
        key=lambda cls: (
            cls.category_order,
            cls.display_order,
            cls.display_name.lower(),
        ),
    )


def _validate_provider(provider: type[DevEnvironment]) -> None:
    for attr in ("provider_id", "display_name", "description"):
        value = getattr(provider, attr, None)
        if not isinstance(value, str) or not value.strip():
            raise ProviderDiscoveryError(
                f"{provider.__name__} must define non-empty {attr}"
            )

    required_commands = getattr(provider, "required_commands", None)
    if not isinstance(required_commands, tuple):
        raise ProviderDiscoveryError(
            f"{provider.__name__}.required_commands must be a tuple[str, ...]"
        )
    if not all(isinstance(command, str) for command in required_commands):
        raise ProviderDiscoveryError(
            f"{provider.__name__}.required_commands must contain strings only"
        )

def _is_provider_module(module_name: str) -> bool:
    relative = module_name.removeprefix(f"{registry_pkg.__name__}.")
    parts = relative.split(".")
    if len(parts) != 2:
        return False
    return not any(part.startswith("_") for part in parts)


def _category_id_for_module(module_name: str) -> str:
    relative = module_name.removeprefix(f"{registry_pkg.__name__}.")
    return Path(relative.replace(".", "/")).parts[0]
