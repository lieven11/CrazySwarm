"""Backend-neutral deployment, preparation, task, and fleet coordination contracts."""

from crazyswarm_app.fleet.artifacts import (
    BackendBindingProfile,
    DeploymentManifest,
    ExecutionBackend,
    FleetSessionIdentity,
    MissionArtifact,
)
from crazyswarm_app.fleet.coordinator import FleetCoordinator, FleetResult, FleetStatus
from crazyswarm_app.fleet.docks import DockManager, DockOperationState, DockReservation
from crazyswarm_app.fleet.metrics import FleetMetricsCollector, FleetMetricsReport
from crazyswarm_app.fleet.persistent import (
    CoverageCandidate,
    HandoverPhase,
    PersistentCoverageCoordinator,
    PersistentCoverageResult,
)
from crazyswarm_app.fleet.preparation import FleetPreparation
from crazyswarm_app.fleet.tasks import TaskLedger, TaskRecord, TaskState
from crazyswarm_app.fleet.zones import ZoneTaskPlan, ZoneTaskPlanner

__all__ = [
    "BackendBindingProfile",
    "CoverageCandidate",
    "DeploymentManifest",
    "DockManager",
    "DockOperationState",
    "DockReservation",
    "ExecutionBackend",
    "FleetCoordinator",
    "FleetMetricsCollector",
    "FleetMetricsReport",
    "FleetPreparation",
    "FleetResult",
    "FleetSessionIdentity",
    "FleetStatus",
    "HandoverPhase",
    "MissionArtifact",
    "PersistentCoverageCoordinator",
    "PersistentCoverageResult",
    "TaskLedger",
    "TaskRecord",
    "TaskState",
    "ZoneTaskPlan",
    "ZoneTaskPlanner",
]
