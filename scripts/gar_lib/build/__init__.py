"""Concrete build environments."""

from scripts.gar_lib.build.base import BuildEnvironment
from scripts.gar_lib.build.codespaces import CodespacesBuildEnvironment
from scripts.gar_lib.build.local import LocalBuildEnvironment
from scripts.gar_lib.build.resolver import BuildEnvironmentResolver, ConfigBuildEnvironmentResolver
from scripts.gar_lib.build.spec import BuildSpec, ProductBuildSpecResolver

__all__ = [
    "BuildEnvironment",
    "BuildEnvironmentResolver",
    "BuildSpec",
    "CodespacesBuildEnvironment",
    "ConfigBuildEnvironmentResolver",
    "LocalBuildEnvironment",
    "ProductBuildSpecResolver",
]
