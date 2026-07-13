"""AWS SSM SimulationEnvironment component pending runtime implementation."""

from __future__ import annotations

from scripts.gar_lib.access.aws import AwsCommandChannel
from scripts.gar_lib.simulation.pending import PendingSimulationEnvironment


class AwsSsmSimulationEnvironment(PendingSimulationEnvironment):
    def __init__(self, aws: AwsCommandChannel, instance_id: str):
        super().__init__("aws_ssm", requires_runtime_artifact=True)
        self.aws = aws
        self.instance_id = instance_id
