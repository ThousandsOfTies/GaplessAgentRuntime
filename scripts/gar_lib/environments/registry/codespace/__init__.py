"""Explicit registry of development environments."""

from scripts.gar_lib.environments.registry.codespace.github_codespaces import (
    GitHubCodespacesEnvironment,
)
from scripts.gar_lib.environments.registry.codespace.local_docker import (
    LocalDockerDevelopmentSetup,
)
from scripts.gar_lib.environments.registry.codespace.wslc import WslcDevelopmentSetup
from scripts.gar_lib.environments.setup_option import EnvironmentSetupOption

ENVIRONMENT_OPTIONS: tuple[type[EnvironmentSetupOption], ...] = (
    WslcDevelopmentSetup,
    LocalDockerDevelopmentSetup,
    GitHubCodespacesEnvironment,
)
