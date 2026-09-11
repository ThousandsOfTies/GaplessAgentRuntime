"""Provider-owned preparation of a Linux Sim Host, without deploying artifacts."""

from __future__ import annotations

import shlex
from uuid import uuid4

from scripts.gar_lib.access.ssh import ScpFileChannel, SshCommandChannel
from scripts.gar_lib.core.capabilities import require_simulation_action
from scripts.gar_lib.core.config import PROJECT_ROOT
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.simulation.composition import simulation_host_for


def prepare_simulation_host(workspace: Workspace) -> None:
    require_simulation_action(workspace, "prepare")
    backend = workspace.selected_environments.simulator
    if backend == "local_docker":
        simulation_host_for(workspace).start(update_address=False, update_repository=False)
        return
    host = workspace.simulation_ssh_host
    if not host:
        raise GarDomainError("Sim HostのSSH aliasが未設定です")
    channel = SshCommandChannel(host)
    probe = channel.run('set -eu; . /etc/os-release; test "$ID" = ubuntu; sudo -n true')
    if probe.returncode:
        raise GarDomainError("sim prepareには起動済みUbuntu Sim Hostと非対話sudo権限が必要です")
    script = PROJECT_ROOT / "infra/simulation-host/ubuntu-bootstrap.sh"
    destination = f"/tmp/gar-sim-prepare-{uuid4().hex}.sh"
    copied = ScpFileChannel(host).push(script, destination)
    if copied.returncode:
        raise GarDomainError("Sim Host bootstrapの転送に失敗しました")
    path = shlex.quote(destination)
    cleanup = shlex.quote(f"rm -f -- {path}")
    result = channel.run(f"trap {cleanup} EXIT; sudo -n /bin/bash {path}")
    if result.returncode:
        raise GarDomainError(
            f"Sim Host bootstrapが失敗しました。一部の依存は導入済みの可能性があります: {result.stderr}"
        )
