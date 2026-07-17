"""Concrete build environments."""

from scripts.gar_lib.build.base import (
    BuildEnvironment,
    BuildEnvironmentResolver,
    BuildSpec,
    ProductBuildSpecResolver,
)
from scripts.gar_lib.build.codespaces import CodespacesBuildEnvironment
from scripts.gar_lib.build.local import LocalBuildEnvironment
from scripts.gar_lib.build.resolver import ConfigBuildEnvironmentResolver

__all__ = [
    "BuildEnvironment",
    "BuildEnvironmentResolver",
    "BuildSpec",
    "CodespacesBuildEnvironment",
    "ConfigBuildEnvironmentResolver",
    "LocalBuildEnvironment",
    "ProductBuildSpecResolver",
]
