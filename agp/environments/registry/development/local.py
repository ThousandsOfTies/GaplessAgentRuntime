from __future__ import annotations

from agp.environments.base import DevEnvironment


class LocalEnvironment(DevEnvironment):
    provider_id = "local"
    display_name = "Local"
    description = "このマシン上のローカル環境を使います"
    display_order = 90
    required_commands = ()
