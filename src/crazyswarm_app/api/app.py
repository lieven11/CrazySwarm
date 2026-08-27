from __future__ import annotations

import asyncio
import json
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager, suppress
from pathlib import Path
from typing import Any, Literal, TypeVar, cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.websockets import WebSocketDisconnect

from crazyswarm_app import __version__
from crazyswarm_app.api.models import (
    ArmRequest,
    DurationRequest,
    ExecutionAnnotationRequest,
    FaultInjectionRequest,
    FleetSessionCreateRequest,
    FleetStartRequest,
    MissionExecutionMode,
    MissionFileStartRequest,
    MissionFileUploadRequest,
    MissionPlanApprovalRequest,
    MissionStartRequest,
    MissionValidationRequest,
    ModeRequest,
    OperatorContext,
    ParameterSnapshotRequest,
    ParameterWriteRequest,
    PreflightRequest,
    ReasonRequest,
    ReplayAction,
    ReplayControlRequest,
    SelectVehicleRequest,
    SimulationClockAction,
    SimulationClockRequest,
    SimulationFleetResetRequest,
    TakeoffRequest,
)
from crazyswarm_app.api.runtime import ApplicationRuntime
from crazyswarm_app.api.security import (
    IdempotencyStore,
    LocalAuthenticator,
    mutation_fingerprint,
    operator_context,
)
from crazyswarm_app.campaign.api_models import (
    BrowserTimingEventRequest,
    CampaignRunRequest,
    ChildCaseRequest,
    ReviewDecisionRequest,
    ReviewObservationRequest,
    SetActiveCaseRequest,
    SetLifecycleStateRequest,
    SnapshotAssessmentRequest,
    SnapshotCommentRequest,
    StaticValidateCaseRequest,
)
from crazyswarm_app.campaign.catalog import CampaignCatalog
from crazyswarm_app.campaign.runtime_executor import FastSimCampaignExecutor
from crazyswarm_app.campaign.service import (
    MAX_CAMPAIGN_SNAPSHOT_BYTES,
    CampaignReviewFrame,
    CampaignReviewSourceRow,
    CampaignRunStatus,
    CampaignService,
    ReviewItem,
)
from crazyswarm_app.campaign.submissions import (
    BASELINE_SUBMISSION_ID,
    CoordinationPreparationRequest,
    MotionPreparationRequest,
    motion_preparation_limits_for_case,
    planning_submissions_for_case,
    registry_row_for_case,
    submissions_for_case,
)
from crazyswarm_app.campaign.timing import (
    BoundedTimingTrace,
    TimingStage,
    classify_timing_trace,
    timing_sample_correlation_id,
)
from crazyswarm_app.domain.commands import MoveRelativeCommand
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import (
    AuthorityClass,
    BackendRole,
    CoordinateFrame,
    OperatingMode,
    Vector3,
    VehicleCapability,
    VehicleState,
)
from crazyswarm_app.domain.simulation import (
    ADAPTER_CONTRACT_VERSION,
    CANONICAL_FRAME_CONVENTION,
    COMMAND_SEMANTICS,
    canonical_sha256,
)
from crazyswarm_app.fleet.artifacts import (
    BackendBindingProfile,
    DeploymentManifest,
    ExecutionBackend,
    FleetSessionIdentity,
    MissionArtifact,
    load_versioned_contract,
)
from crazyswarm_app.fleet.coordinator import FleetCoordinator
from crazyswarm_app.fleet.execution import ExecutionCoordinator, ExecutionStatus
from crazyswarm_app.fleet.planning import MissionDeploymentPlan, plan_mission_deployment
from crazyswarm_app.fleet.preparation import FleetPreparation
from crazyswarm_app.fleet.qualification import run_persistent_fleet_qualification
from crazyswarm_app.hardware.basic_flight_lab import (
    BasicFlightLabCatalog,
    BasicFlightLabRun,
    BasicFlightLabRunRequest,
    BasicFlightLabService,
    MotorActuationStatus,
    MotorBenchSession,
    MotorBenchStartRequest,
    MotorBenchStopRequest,
    MotorBenchUpdateRequest,
    PhysicalBasicFlightReadiness,
    PhysicalBasicFlightRunRequest,
    PhysicalFlightOperationStatus,
)
from crazyswarm_app.hardware.observation_twin import (
    ObservationTwinService,
    PhysicalCommandTarget,
    PhysicalTwinBindingRequest,
    PhysicalTwinConfirmRequest,
    PhysicalTwinStatus,
)
from crazyswarm_app.hardware.ownership import (
    PhysicalOperationAdmissionBusy,
    claim_physical_operation_admission,
)
from crazyswarm_app.missions.planning import (
    MissionPlanReceipt,
    MissionPlanStatus,
    PlanningObstacle,
    build_mission_plan,
)
from crazyswarm_app.missions.script import ScriptMission
from crazyswarm_app.observability.csv_export import (
    RUN_TELEMETRY_CSV_CONTRACT,
    mission_telemetry_csv_filename,
)
from crazyswarm_app.observability.events import EvidenceKind, TelemetryPayload
from crazyswarm_app.observability.replay import ReplayClock
from crazyswarm_app.observability.storage import IncompleteRunError
from crazyswarm_app.planning.approval import MissionPlanApproval
from crazyswarm_app.planning.release import run_planning_release_qualification
from crazyswarm_app.provenance import repository_provenance
from crazyswarm_app.safety.models import LiveModeAuthorization
from crazyswarm_app.simulation.faults import FaultWindow
from crazyswarm_app.simulation.models import DEFAULT_FIDELITY_MANIFEST
from crazyswarm_app.twin.calibration import (
    CalibrationCandidateRequest,
    CalibrationPromotionAcceptance,
)
from crazyswarm_app.twin.curriculum import TwinCurriculumResultRequest, TwinStageStatus
from crazyswarm_app.twin.models import (
    TwinIngestionBatch,
    TwinInitialState,
    TwinSessionConfig,
    TwinSourceClass,
)
from crazyswarm_app.twin.physical_handoff import (
    PhysicalTwinHandoffRequest,
    assess_physical_twin_handoff,
)
from crazyswarm_app.vehicles.crazyflie import CrazyflieVehicle
from crazyswarm_app.vehicles.providers import SoftwareBackendVehicleProvider

MutationResultT = TypeVar("MutationResultT")

LIVE_STATE_HISTORY_LIMIT = 10
CAMPAIGN_SNAPSHOT_CAPTURE_ENABLED = False
CAMPAIGN_AUTOMATIC_TWIN_RETENTION_ENABLED = False


def _motion_preparation_from_query(
    *,
    balance: int | None,
    speed_m_s: float | None,
    accuracy_m: float | None,
    smoothness: int | None,
) -> MotionPreparationRequest | None:
    if all(value is None for value in (balance, speed_m_s, accuracy_m, smoothness)):
        return None
    return MotionPreparationRequest(
        balance=50 if balance is None else balance,
        speed_m_s=speed_m_s,
        accuracy_m=accuracy_m,
        smoothness=smoothness,
    )


async def prepare_campaign_preview_off_loop(
    service: CampaignService,
    submission_id: str | None,
    planning_submission_id: str | None,
    *,
    motion_preparation_request: MotionPreparationRequest | None,
    coordination_preparation_request: CoordinationPreparationRequest | None = None,
) -> tuple[Any, Any, Any, Any]:
    """Keep bounded planning for interactive sliders off the API event loop."""

    return await service.preview_active_off_loop(
        submission_id,
        planning_submission_id,
        motion_preparation_request=motion_preparation_request,
        coordination_preparation_request=coordination_preparation_request,
    )


def retain_campaign_twin_evidence(
    runtime: ApplicationRuntime,
    service: CampaignService,
    review: ReviewItem,
    *,
    curriculum_stage_id: str | None = None,
) -> str | None:
    """Retain a successful one-drone Campaign run through the production twin path.

    Fast Sim estimator values remain explicitly ``CONFIGURED`` observations and
    simulator ground truth remains ``SIMULATED_MODEL`` prediction. Repeated API
    delivery reuses the campaign-run identity instead of creating duplicate twins.
    """

    if len(review.analysis.vehicles) != 1:
        return None
    existing = runtime.twins.session_for_campaign_run(review.run_id)
    if existing is not None:
        service.link_twin_session(review.run_id, existing.session_id)
        return existing.session_id
    case = service.catalog.get(review.case_id)
    vehicle_id = review.analysis.vehicles[0].vehicle_id
    simulation_parameters = runtime.config.simulation.vehicle_parameters()
    config = TwinSessionConfig(
        observed_vehicle_id=vehicle_id,
        simulated_vehicle_id=f"{vehicle_id}-predicted",
        mission_id=case.case_id,
        mission_version=str(case.schema_version),
        mission_source_sha256=case.case_sha256,
        physics_model_id="fast-sim-rigid-body",
        physics_model_version="1",
        physics_configuration_sha256=simulation_parameters.sha256,
        calibration_id=runtime.twins.active_calibration_id(),
        curriculum_stage_id=curriculum_stage_id,
        campaign_run_id=review.run_id,
        campaign_review_id=review.review_id,
        observed_initial_state=TwinInitialState(
            source_class=TwinSourceClass.CONFIGURED,
            source_id="fast-sim-estimator-telemetry",
            frame=CoordinateFrame.WORLD,
        ),
        simulated_initial_state=TwinInitialState(
            source_class=TwinSourceClass.SIMULATED_MODEL,
            source_id="fast-sim-ground-truth-model",
            frame=CoordinateFrame.WORLD,
        ),
        ground_truth_available=True,
    )
    record = runtime.twins.create_session(config)
    telemetry_path = (
        service.state_directory
        / "evidence"
        / review.analysis.mission_execution_id
        / "telemetry.csv"
    )
    try:
        runtime.twins.ingest_telemetry_csv(
            record.session_id,
            telemetry_path.read_bytes(),
            # The exact high-rate CSV remains the review oracle. The derived twin
            # retains the configured evidence cadence plus causal transitions.
            minimum_source_period_s=runtime.config.telemetry_period_s,
        )
    except Exception:
        runtime.twins.complete(record.session_id, failed=True)
        raise
    runtime.twins.complete(record.session_id)
    service.link_twin_session(review.run_id, record.session_id)
    return record.session_id


async def retain_campaign_twin_evidence_off_loop(
    runtime: ApplicationRuntime,
    service: CampaignService,
    review: ReviewItem,
    *,
    curriculum_stage_id: str | None = None,
) -> str | None:
    """Retain terminal twin evidence without blocking API liveness.

    CSV conversion, hash validation, append-only journal writes, and fsyncs can take
    several seconds once a campaign has produced a substantial telemetry artifact.
    They are terminal evidence work, not control-loop work, so keep them away from
    the event loop that serves health checks and live simulator telemetry.
    """

    return await asyncio.to_thread(
        retain_campaign_twin_evidence,
        runtime,
        service,
        review,
        curriculum_stage_id=curriculum_stage_id,
    )


def generate_local_token() -> str:
    return secrets.token_urlsafe(32)


def create_app(
    runtime: ApplicationRuntime,
    *,
    local_token: str,
    manage_runtime: bool = True,
    observation_twin_service: ObservationTwinService | None = None,
    physical_hardware_enabled: bool | None = None,
) -> FastAPI:
    authenticator = LocalAuthenticator(local_token)
    idempotency = IdempotencyStore()
    campaign_run_tasks: set[asyncio.Task[None]] = set()
    # Repository identity is process metadata, not a liveness dependency. Running
    # three Git subprocesses on every supervisor probe can block the API event loop
    # while terminal evidence is being flushed, which makes a healthy simulator look
    # offline and can cause the dashboard supervisor to restart it. Capture the
    # process-start snapshot once and keep /health bounded to in-memory state.
    health_provenance = repository_provenance()

    hardware_enabled = (
        observation_twin_service is not None
        if physical_hardware_enabled is None
        else physical_hardware_enabled
    )
    physical_twin = observation_twin_service or ObservationTwinService(runtime)

    async def borrow_physical_flight_vehicle(
        vehicle_id: str,
        target: PhysicalCommandTarget,
    ) -> CrazyflieVehicle:
        return await physical_twin.borrow_command_vehicle(
            vehicle_id=vehicle_id,
            selected_uri=target.selected_uri,
            telemetry_listener=physical_twin.accept_operation_sample,
        )

    basic_flight_lab = BasicFlightLabService(
        runtime,
        motor_bench_terminal_callback=physical_twin.resume,
        physical_flight_terminal_callback=physical_twin.resume,
        physical_telemetry_callback=physical_twin.accept_operation_sample,
        physical_vehicle_provider=borrow_physical_flight_vehicle,
    )

    def require_physical_hardware() -> None:
        if hardware_enabled:
            return
        raise CrazySwarmError(
            ErrorCode.INVALID_STATE,
            "physical hardware is disabled in this isolated runtime; use the "
            "operator-owned dashboard service",
        )

    @contextmanager
    def admit_physical_operation() -> Iterator[None]:
        try:
            with claim_physical_operation_admission(runtime.config.cache_directory):
                yield
        except PhysicalOperationAdmissionBusy as error:
            raise CrazySwarmError(ErrorCode.INVALID_STATE, str(error)) from error

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if manage_runtime:
            await runtime.start()
        # A direct-PWM parameter survives loss of the client process and radio
        # disconnect. Recover a persisted unconfirmed session before observation
        # can reacquire the Crazyradio and before the API reports an idle actuator.
        if hardware_enabled:
            fallback_target = None
            with suppress(CrazySwarmError):
                fallback_target = physical_twin.command_target()
            await basic_flight_lab.recover_stale_motor_output(
                fallback_target=fallback_target,
            )
            await physical_twin.start()
        try:
            yield
        finally:
            for task in tuple(campaign_run_tasks):
                task.cancel()
            if campaign_run_tasks:
                await asyncio.gather(*campaign_run_tasks, return_exceptions=True)
            await basic_flight_lab.shutdown()
            if hardware_enabled:
                await physical_twin.shutdown()
            if manage_runtime:
                await runtime.stop()

    app = FastAPI(
        title="CrazySwarm Control API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.runtime = runtime
    app.state.observation_twin_service = physical_twin
    app.state.basic_flight_lab_service = basic_flight_lab
    app.state.physical_hardware_enabled = hardware_enabled
    campaign_timing = BoundedTimingTrace("campaign-runtime-v1", retention_limit=20_000)
    app.state.campaign_timing = campaign_timing
    runtime.recorder.timing_trace = campaign_timing
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime.config.api.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["X-Local-Token", "X-Client-ID", "Idempotency-Key", "Content-Type"],
    )

    @app.middleware("http")
    async def reject_untrusted_origins(
        request: Request, call_next: Callable[[Request], Any]
    ) -> Any:
        origin = request.headers.get("origin")
        if origin is not None and origin not in runtime.config.api.allowed_origins:
            return _error_response(403, "ORIGIN_NOT_ALLOWED", "request origin is not trusted")
        return await call_next(request)

    @app.exception_handler(CrazySwarmError)
    async def crazy_swarm_error(request: Request, error: CrazySwarmError) -> JSONResponse:
        status = {
            ErrorCode.IDENTITY_MISMATCH: 404,
            ErrorCode.MODE_NOT_AUTHORIZED: 403,
            ErrorCode.INVALID_STATE: 409,
            ErrorCode.PREFLIGHT_FAILED: 409,
            ErrorCode.CAPABILITY_MISSING: 409,
        }.get(error.code, 400)
        return _error_response(
            status,
            error.code.value,
            error.message,
            request_id=request.headers.get("idempotency-key"),
            details=error.details,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return _error_response(
            422,
            "REQUEST_VALIDATION_FAILED",
            "request validation failed",
            request_id=request.headers.get("idempotency-key"),
            details={"errors": error.errors()},
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        detail = error.detail
        if isinstance(detail, dict):
            code = str(detail.get("code", "HTTP_ERROR"))
            message = str(detail.get("message", "request failed"))
            details: dict[str, Any] = {
                key: value for key, value in detail.items() if key not in {"code", "message"}
            }
        else:
            code = "HTTP_ERROR"
            message = str(detail)
            details = {}
        return _error_response(
            error.status_code,
            code,
            message,
            request_id=request.headers.get("idempotency-key"),
            details=details,
        )

    async def require_auth(x_local_token: str | None = Header(None, alias="X-Local-Token")) -> None:
        if not authenticator.valid(x_local_token):
            raise HTTPException(
                status_code=401,
                detail={"code": "LOCAL_AUTH_REQUIRED", "message": "valid local token required"},
            )

    router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_auth)])

    def campaign_service() -> CampaignService:
        service = getattr(app.state, "campaign_service", None)
        if service is None:
            repository = Path(__file__).resolve().parents[3]
            service = CampaignService(
                catalog=CampaignCatalog(
                    repository / "missions" / "campaigns" / "sim" / "cases",
                    additional_roots=(
                        repository / "missions" / "campaigns" / "real" / "authorized_cases",
                    ),
                    policy=runtime.supervisor.policy,
                ),
                state_directory=runtime.config.cache_directory / "campaign",
                executor=getattr(
                    app.state,
                    "campaign_executor",
                    FastSimCampaignExecutor(runtime),
                ),
            )
            app.state.campaign_service = service
        return service

    async def mutate(
        request: Request,
        context: OperatorContext,
        *,
        action: str,
        vehicle_id: str,
        operation: Callable[[], Awaitable[MutationResultT]],
    ) -> MutationResultT:
        fingerprint = await mutation_fingerprint(request)

        async def audited_operation() -> MutationResultT:
            runtime.bridge.operator_action(
                vehicle_id=vehicle_id,
                client_id=context.client_id,
                request_id=context.request_id,
                action=action,
            )
            return await operation()

        response, _ = await idempotency.execute(context, fingerprint, audited_operation)
        return cast(MutationResultT, response)

    async def schedule_mission(
        mission_id: str,
        vehicle_id: str,
        context: OperatorContext,
        *,
        parameters: dict[str, Any] | None = None,
        preset: str | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        _require_vehicle(runtime, vehicle_id)
        session = runtime.supervisor.session(vehicle_id)
        if session.lease is not None and session.lease.owner_id == context.client_id:
            if session.state is not VehicleState.READY:
                raise CrazySwarmError(
                    ErrorCode.INVALID_STATE,
                    "manual control must be landed and ready before mission start",
                )
            await runtime.supervisor.release_control(vehicle_id, context.client_id)
        runtime.missions.validate_parameters(
            mission_id,
            parameters,
            preset=preset,
            overrides=overrides,
        )
        run_id = f"run-{uuid.uuid4().hex}"
        task = asyncio.create_task(
            runtime.runner.run(
                mission_id,
                vehicle_id,
                parameters=parameters,
                preset=preset,
                overrides=overrides,
                mission_run_id=run_id,
            )
        )
        runtime.track_mission_task(run_id, task)
        return {"mission_run_id": run_id, "status": "SCHEDULED"}

    @router.get("/schema")
    async def schema() -> dict[str, Any]:
        return app.openapi()

    @router.get("/physical-twin/status", response_model=PhysicalTwinStatus)
    async def physical_twin_status() -> PhysicalTwinStatus:
        return physical_twin.status()

    @router.get("/physical-twin/lab/catalog", response_model=BasicFlightLabCatalog)
    async def physical_twin_lab_catalog() -> BasicFlightLabCatalog:
        return basic_flight_lab.catalog()

    @router.post("/physical-twin/lab/runs", response_model=BasicFlightLabRun)
    async def run_physical_twin_lab_rehearsal(
        body: BasicFlightLabRunRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> BasicFlightLabRun:
        async def operation() -> BasicFlightLabRun:
            try:
                return await basic_flight_lab.run(body)
            except ValueError as error:
                raise CrazySwarmError(ErrorCode.INVALID_COMMAND, str(error)) from error

        return await mutate(
            request,
            context,
            action="run_basic_flight_fast_sim_rehearsal",
            vehicle_id="twin-lab-fast-sim",
            operation=operation,
        )

    @router.post("/physical-twin/lab/physical-runs", response_model=BasicFlightLabRun)
    async def run_physical_twin_lab_motion(
        body: PhysicalBasicFlightRunRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> BasicFlightLabRun:
        require_physical_hardware()
        async def operation() -> BasicFlightLabRun:
            target = physical_twin.command_target()
            await physical_twin.suspend(
                reason="Physical mission owns the radio",
                owner=context.client_id,
                retain_connection=True,
            )
            try:
                return await basic_flight_lab.run_physical(
                    body,
                    target=target,
                    operator_id=context.client_id,
                )
            except RuntimeError as error:
                raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, str(error)) from error
            finally:
                with suppress(Exception):
                    await physical_twin.resume()

        return await mutate(
            request,
            context,
            action="run_basic_flight_contained_physical",
            vehicle_id="configured-physical-twin",
            operation=operation,
        )

    @router.get(
        "/physical-twin/lab/physical-flight",
        response_model=PhysicalFlightOperationStatus,
    )
    async def physical_flight_status() -> PhysicalFlightOperationStatus:
        twin_status = physical_twin.status()
        observed = twin_status.observed
        fallback_target = None
        with suppress(CrazySwarmError):
            candidate = physical_twin.command_target()
            if candidate.observed_identity_sha256 is not None:
                fallback_target = candidate
        return await basic_flight_lab.reconcile_physical_flight_stop(
            observation_current=observed is not None and observed.freshness == "CURRENT",
            armed=None if observed is None else observed.armed,
            flying=None if observed is None else observed.flying,
            auto_arming=physical_twin.supervisor_auto_arming(),
            fallback_target=fallback_target,
        )

    @router.post(
        "/physical-twin/lab/physical-flight/start",
        response_model=PhysicalFlightOperationStatus,
    )
    async def start_physical_flight(
        body: PhysicalBasicFlightRunRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> PhysicalFlightOperationStatus:
        require_physical_hardware()

        async def operation() -> PhysicalFlightOperationStatus:
            with admit_physical_operation():
                twin_status = physical_twin.status()
                observed = twin_status.observed
                actuation = await basic_flight_lab.reconcile_motor_reboot_required(
                    observation_current=(
                        twin_status.state.value == "PAIRED"
                        and observed is not None
                        and observed.freshness == "CURRENT"
                    ),
                    faults=() if observed is None else observed.faults,
                )
                if actuation.stop_required:
                    raise CrazySwarmError(
                        ErrorCode.PREFLIGHT_FAILED,
                        "Play is blocked until direct motor output is confirmed stopped",
                    )
                if actuation.reboot_required:
                    raise CrazySwarmError(
                        ErrorCode.PREFLIGHT_FAILED,
                        "Power cycle the Crazyflie before starting another physical action",
                    )
                if (
                    twin_status.state.value != "PAIRED"
                    or observed is None
                    or observed.freshness != "CURRENT"
                    or observed.armed is None
                    or observed.flying is not False
                ):
                    raise CrazySwarmError(
                        ErrorCode.PREFLIGHT_FAILED,
                        "Play is blocked until fresh supervisor telemetry confirms the "
                        "paired physical drone is not flying and reports a known arm state",
                    )
                target = physical_twin.command_target()
                await physical_twin.suspend(
                    reason="Physical mission owns the radio",
                    owner=context.client_id,
                    retain_connection=True,
                )
                try:
                    return await basic_flight_lab.start_physical_flight(
                        body,
                        target=target,
                        operator_id=context.client_id,
                    )
                except RuntimeError as error:
                    with suppress(Exception):
                        await physical_twin.resume()
                    raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, str(error)) from error
                except Exception:
                    with suppress(Exception):
                        await physical_twin.resume()
                    raise

        return await mutate(
            request,
            context,
            action="start_basic_flight_contained_physical",
            vehicle_id="configured-physical-twin",
            operation=operation,
        )

    @router.post(
        "/physical-twin/lab/physical-flight/flip",
        response_model=PhysicalFlightOperationStatus,
    )
    async def trigger_acrobatics_flip(
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> PhysicalFlightOperationStatus:
        require_physical_hardware()

        async def operation() -> PhysicalFlightOperationStatus:
            with admit_physical_operation():
                try:
                    return await basic_flight_lab.request_acrobatics_flip()
                except RuntimeError as error:
                    raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, str(error)) from error

        return await mutate(
            request,
            context,
            action="trigger_cushioned_acrobatics_flip",
            vehicle_id="configured-physical-twin",
            operation=operation,
        )

    @router.post(
        "/physical-twin/lab/physical-flight/abort",
        response_model=PhysicalFlightOperationStatus,
    )
    async def abort_physical_flight(
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> PhysicalFlightOperationStatus:
        require_physical_hardware()

        async def operation() -> PhysicalFlightOperationStatus:
            with admit_physical_operation():
                await physical_twin.suspend(
                    reason="Abort and land owns the radio",
                    owner=context.client_id,
                )
                try:
                    status = await basic_flight_lab.request_physical_flight_abort(
                        reason="operator requested abort and land",
                    )
                    if not status.stop_required:
                        with suppress(Exception):
                            await physical_twin.resume()
                    return status
                except Exception:
                    with suppress(Exception):
                        await physical_twin.resume()
                    raise

        return await mutate(
            request,
            context,
            action="abort_basic_flight_contained_physical",
            vehicle_id="configured-physical-twin",
            operation=operation,
        )

    @router.post(
        "/physical-twin/lab/physical-readiness",
        response_model=PhysicalBasicFlightReadiness,
    )
    async def assess_physical_twin_lab_readiness(
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> PhysicalBasicFlightReadiness:
        require_physical_hardware()
        async def operation() -> PhysicalBasicFlightReadiness:
            with admit_physical_operation():
                target = physical_twin.command_target()
                await physical_twin.suspend(
                    reason="Readiness check owns the radio",
                    owner=context.client_id,
                )
                try:
                    return await basic_flight_lab.assess_physical_readiness(target=target)
                finally:
                    with suppress(Exception):
                        await physical_twin.resume()

        return await mutate(
            request,
            context,
            action="assess_basic_flight_physical_readiness",
            vehicle_id="configured-physical-twin",
            operation=operation,
        )

    @router.post(
        "/physical-twin/lab/motor-bench/start",
        response_model=MotorBenchSession,
    )
    async def start_physical_motor_bench(
        body: MotorBenchStartRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> MotorBenchSession:
        require_physical_hardware()
        async def operation() -> MotorBenchSession:
            with admit_physical_operation():
                target = physical_twin.command_target()
                await physical_twin.suspend(
                    reason="Motor bench owns the radio",
                    owner=context.client_id,
                )
                try:
                    return await basic_flight_lab.start_motor_bench(
                        body,
                        target=target,
                        operator_id=context.client_id,
                    )
                except RuntimeError as error:
                    with suppress(Exception):
                        await physical_twin.resume()
                    raise CrazySwarmError(ErrorCode.PREFLIGHT_FAILED, str(error)) from error
                except Exception:
                    with suppress(Exception):
                        await physical_twin.resume()
                    raise

        return await mutate(
            request,
            context,
            action="start_props_off_motor_bench",
            vehicle_id="configured-physical-twin",
            operation=operation,
        )

    @router.get(
        "/physical-twin/lab/motor-actuation",
        response_model=MotorActuationStatus,
    )
    async def physical_motor_actuation_status() -> MotorActuationStatus:
        twin_status = physical_twin.status()
        observed = twin_status.observed
        return await basic_flight_lab.reconcile_motor_reboot_required(
            observation_current=(
                twin_status.state.value == "PAIRED"
                and observed is not None
                and observed.freshness == "CURRENT"
            ),
            faults=() if observed is None else observed.faults,
        )

    @router.post(
        "/physical-twin/lab/motor-actuation/stop",
        response_model=MotorActuationStatus,
    )
    async def stop_all_physical_motor_output(
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> MotorActuationStatus:
        require_physical_hardware()
        async def operation() -> MotorActuationStatus:
            with admit_physical_operation():
                fallback_target = None
                with suppress(CrazySwarmError):
                    fallback_target = physical_twin.command_target()
                await physical_twin.suspend(
                    reason="Motor stop owns the radio",
                    owner=context.client_id,
                )
                try:
                    return await basic_flight_lab.stop_all_motor_output(
                        fallback_target=fallback_target,
                    )
                finally:
                    with suppress(Exception):
                        await physical_twin.resume()

        return await mutate(
            request,
            context,
            action="stop_all_direct_motor_output",
            vehicle_id="configured-physical-twin",
            operation=operation,
        )

    @router.post(
        "/physical-twin/lab/motor-bench/output",
        response_model=MotorBenchSession,
    )
    async def update_physical_motor_bench(
        body: MotorBenchUpdateRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> MotorBenchSession:
        require_physical_hardware()
        async def operation() -> MotorBenchSession:
            with admit_physical_operation():
                try:
                    return await basic_flight_lab.update_motor_bench(body)
                except RuntimeError as error:
                    raise CrazySwarmError(ErrorCode.INVALID_STATE, str(error)) from error

        return await mutate(
            request,
            context,
            action="update_props_off_motor_bench",
            vehicle_id="configured-physical-twin",
            operation=operation,
        )

    @router.post(
        "/physical-twin/lab/motor-bench/stop",
        response_model=MotorBenchSession,
    )
    async def stop_physical_motor_bench(
        body: MotorBenchStopRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> MotorBenchSession:
        require_physical_hardware()
        async def operation() -> MotorBenchSession:
            with admit_physical_operation():
                try:
                    return await basic_flight_lab.stop_motor_bench(body)
                except RuntimeError as error:
                    raise CrazySwarmError(ErrorCode.INVALID_STATE, str(error)) from error
                finally:
                    with suppress(Exception):
                        await physical_twin.resume()

        return await mutate(
            request,
            context,
            action="stop_props_off_motor_bench",
            vehicle_id="configured-physical-twin",
            operation=operation,
        )

    @router.get("/physical-twin/live")
    async def physical_twin_live() -> StreamingResponse:
        async def events() -> AsyncIterator[str]:
            async for frame in physical_twin.live_stream():
                payload = json.dumps(
                    frame.model_dump(mode="json"),
                    separators=(",", ":"),
                )
                yield (f"id: {frame.live_sequence}\nevent: physical-twin\ndata: {payload}\n\n")

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    @router.put("/physical-twin/binding", response_model=PhysicalTwinStatus)
    async def configure_physical_twin(
        body: PhysicalTwinBindingRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> PhysicalTwinStatus:
        async def operation() -> PhysicalTwinStatus:
            return await physical_twin.configure(body)

        return await mutate(
            request,
            context,
            action="configure_physical_twin_binding",
            vehicle_id="physical-twin-observer",
            operation=operation,
        )

    @router.post("/physical-twin/connect", response_model=PhysicalTwinStatus)
    async def connect_physical_twin(
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> PhysicalTwinStatus:
        require_physical_hardware()
        async def operation() -> PhysicalTwinStatus:
            return await physical_twin.connect()

        return await mutate(
            request,
            context,
            action="connect_physical_twin_observer",
            vehicle_id="physical-twin-observer",
            operation=operation,
        )

    @router.post("/physical-twin/confirm", response_model=PhysicalTwinStatus)
    async def confirm_physical_twin(
        body: PhysicalTwinConfirmRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> PhysicalTwinStatus:
        require_physical_hardware()
        async def operation() -> PhysicalTwinStatus:
            return await physical_twin.confirm(body)

        return await mutate(
            request,
            context,
            action="confirm_physical_twin_identity",
            vehicle_id="physical-twin-observer",
            operation=operation,
        )

    @router.post("/physical-twin/disconnect", response_model=PhysicalTwinStatus)
    async def disconnect_physical_twin(
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> PhysicalTwinStatus:
        async def operation() -> PhysicalTwinStatus:
            return await physical_twin.disconnect()

        return await mutate(
            request,
            context,
            action="disconnect_physical_twin_observer",
            vehicle_id="physical-twin-observer",
            operation=operation,
        )

    @router.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "mode": runtime.supervisor.mode,
            "local_only": True,
            "physical_hardware_runtime": (
                "OPERATOR_OWNED" if hardware_enabled else "DISABLED"
            ),
            **health_provenance.as_dict(),
            "recorder": {
                "persisted_events": runtime.recorder.persisted_events,
                "shutdown_dropped_events": runtime.recorder.shutdown_dropped_events,
                "last_error": runtime.recorder.last_error,
                "bus": runtime.bus.stats.model_dump(mode="json"),
            },
        }

    @router.get("/state")
    async def application_state() -> dict[str, Any]:
        visible_vehicle_ids = runtime.active_vehicle_ids or set(runtime.vehicles)
        session_ids = _live_state_session_ids(runtime)
        return {
            "schema_version": 2,
            "mode": runtime.supervisor.mode,
            "selected_vehicle_id": runtime.selected_vehicle_id,
            "configured_flight_volume": runtime.supervisor.policy.flight_volume.model_dump(
                mode="json"
            ),
            "visible_obstacles": [
                obstacle.model_dump(mode="json") for obstacle in runtime.visible_obstacles()
            ],
            "safety_policy": {
                "minimum_takeoff_battery_percent": (
                    runtime.supervisor.policy.minimum_takeoff_battery_percent
                ),
                "critical_battery_percent": runtime.supervisor.policy.critical_battery_percent,
            },
            "vehicles": [
                _vehicle_view(runtime, vehicle_id) for vehicle_id in sorted(visible_vehicle_ids)
            ],
            "mission_runs": [
                _mission_run_state_summary(item) for item in _live_state_mission_runs(runtime)
            ],
            "fleet_sessions": [
                _fleet_session_view(runtime, session_id, compact=True) for session_id in session_ids
            ],
            "execution_sessions": [
                runtime.executions[session_id].state_summary
                for session_id in session_ids
                if session_id in runtime.executions
            ],
        }

    @router.get("/capabilities")
    async def capabilities() -> dict[str, Any]:
        return {
            "modes": [item.value for item in OperatingMode],
            "missions": [item.model_dump(mode="json") for item in runtime.missions.list_metadata()],
            "simulation": any(
                vehicle.backend_profile.authority is AuthorityClass.SIMULATION
                for vehicle in runtime.vehicles.values()
            ),
            "replay": True,
            "real_adapter": any(
                vehicle.backend_profile.authority is AuthorityClass.PHYSICAL
                for vehicle in runtime.vehicles.values()
            ),
        }

    @router.get("/campaign/cases")
    async def campaign_cases() -> dict[str, Any]:
        service = campaign_service()
        cases = service.catalog.cases()
        semantic_audits = {item.case_id: item for item in service.catalog.semantic_audits()}
        submission_matrix = {case.case_id: submissions_for_case(case) for case in cases}
        comparison_cases = {
            submission.submission_id: tuple(
                sorted(
                    candidate_case_id
                    for candidate_case_id, candidate_submissions in submission_matrix.items()
                    if any(
                        candidate.submission_id == submission.submission_id
                        for candidate in candidate_submissions
                    )
                )
            )
            for submissions in submission_matrix.values()
            for submission in submissions
        }
        return {
            "major_missions": service.catalog.major_mission_curriculum().model_dump(mode="json"),
            "two_drone_missions": service.catalog.two_drone_mission_curriculum().model_dump(
                mode="json"
            ),
            "cases": [
                {
                    **case.model_dump(mode="json"),
                    "case_sha256": case.case_sha256,
                    "execution_semantics_sha256": case.execution_semantics_sha256,
                    "semantic_audit": semantic_audits[case.case_id].model_dump(mode="json"),
                    "lifecycle": service.state.lifecycle[case.case_id].state,
                    "variation_relationship": {
                        "family": case.family,
                        "case_id": case.case_id,
                        "variation_name": case.variation_name,
                        "relationship": "IMMUTABLE_CASE_VARIATION",
                        "legacy_named_variations": list(case.named_variations),
                    },
                    "motion_preparation_limits": motion_preparation_limits_for_case(
                        case
                    ).model_dump(mode="json"),
                    "submission_registry": registry_row_for_case(case).model_dump(mode="json"),
                    "submissions": [
                        submission.model_dump(mode="json")
                        | {
                            "submission_sha256": submission.profile_sha256,
                            "semantic_fingerprint_sha256": (submission.semantic_fingerprint_sha256),
                            "missing_prerequisites": list(
                                service.missing_submission_prerequisites(case, submission)
                            ),
                            "run_eligible": (
                                (
                                    submission.status.value == "EXECUTABLE"
                                    or (
                                        case.environment.value == "SIMULATION"
                                        and submission.submission_id == BASELINE_SUBMISSION_ID
                                    )
                                )
                                and not service.missing_submission_prerequisites(case, submission)
                            ),
                            "comparison_case_ids": list(comparison_cases[submission.submission_id]),
                        }
                        for submission in submission_matrix[case.case_id]
                    ],
                    "planning_submissions": [
                        submission.model_dump(mode="json")
                        | {
                            "planning_submission_sha256": (submission.planning_submission_sha256),
                            "semantic_fingerprint_sha256": (submission.semantic_fingerprint_sha256),
                        }
                        for submission in planning_submissions_for_case(case)
                    ],
                }
                for case in cases
            ],
            "hierarchy": service.catalog.hierarchy(),
        }

    @router.get("/campaign/state")
    async def campaign_state() -> dict[str, Any]:
        return campaign_service().state.model_dump(mode="json")

    @router.get("/campaign/qualification")
    async def campaign_qualification() -> dict[str, Any]:
        return _campaign_qualification_payload()

    @router.get("/campaign/qualification/export")
    async def export_campaign_qualification() -> JSONResponse:
        return JSONResponse(
            _campaign_qualification_payload(),
            headers={
                "Content-Disposition": (
                    'attachment; filename="campaign-static-qualification-v2.json"'
                )
            },
        )

    @router.get("/campaign/qualification/constraint-directed")
    async def campaign_constraint_directed_qualification() -> JSONResponse:
        return JSONResponse(
            content=_qualification_payload(
                Path("missions/campaigns/sim/qualification/constraint-directed-planning-v1.json")
            ),
            headers={
                "Content-Disposition": (
                    'attachment; filename="constraint-directed-planning-v1.json"'
                )
            },
        )

    @router.get("/campaign/qualification/selective-submissions")
    async def campaign_selective_submission_qualification() -> JSONResponse:
        return JSONResponse(
            content=_qualification_payload(
                Path("missions/campaigns/sim/qualification/selective-submission-registry-v1.json")
            )
        )

    @router.post("/campaign/cases/static-validate")
    async def campaign_static_validate(
        body: StaticValidateCaseRequest,
        context: OperatorContext = Depends(operator_context),
    ) -> dict[str, Any]:
        return (
            campaign_service()
            .static_validate(
                body.case_id,
                actor_id=context.client_id,
            )
            .model_dump(mode="json")
        )

    @router.post("/campaign/active")
    async def campaign_set_active(
        body: SetActiveCaseRequest,
        context: OperatorContext = Depends(operator_context),
    ) -> dict[str, Any]:
        try:
            lock = campaign_service().set_active(
                body.case_id,
                actor_id=context.client_id,
                reason=body.reason,
            )
        except KeyError as error:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "campaign case not found",
                details={"case_id": body.case_id},
            ) from error
        except PermissionError as error:
            raise CrazySwarmError(
                ErrorCode.MODE_NOT_AUTHORIZED,
                str(error),
                details={"case_id": body.case_id},
            ) from error
        except ValueError as error:
            raise CrazySwarmError(
                ErrorCode.INVALID_STATE,
                str(error),
                details={"case_id": body.case_id},
            ) from error
        return lock.model_dump(mode="json")

    @router.post("/campaign/cases/in-review")
    async def campaign_move_to_review(
        body: SetActiveCaseRequest,
        context: OperatorContext = Depends(operator_context),
    ) -> dict[str, Any]:
        return (
            campaign_service()
            .move_to_review(
                body.case_id,
                actor_id=context.client_id,
                reason=body.reason,
            )
            .model_dump(mode="json")
        )

    @router.post("/campaign/cases/lifecycle")
    async def campaign_set_lifecycle(
        body: SetLifecycleStateRequest,
        context: OperatorContext = Depends(operator_context),
    ) -> dict[str, Any]:
        return (
            campaign_service()
            .set_lifecycle_state(
                body.case_id,
                body.state,
                actor_id=context.client_id,
                reason=body.reason,
            )
            .model_dump(mode="json")
        )

    @router.post("/campaign/cases/completed")
    async def campaign_complete_case(
        body: SetActiveCaseRequest,
        context: OperatorContext = Depends(operator_context),
    ) -> dict[str, Any]:
        return (
            campaign_service()
            .complete_case(
                body.case_id,
                actor_id=context.client_id,
                reason=body.reason,
            )
            .model_dump(mode="json")
        )

    @router.get("/campaign/active/preview")
    async def campaign_preview_active(
        submission_id: str | None = None,
        planning_submission_id: str | None = None,
        balance: int | None = Query(default=None, ge=0, le=100),
        speed_m_s: float | None = Query(default=None, gt=0.0, le=2.0),
        accuracy_m: float | None = Query(default=None, gt=0.0, le=100.0),
        smoothness: int | None = Query(default=None, ge=0, le=100),
        launch_gap_s: float | None = Query(default=None, ge=0.0, le=60.0),
    ) -> dict[str, Any]:
        service = campaign_service()
        motion_preparation = _motion_preparation_from_query(
            balance=balance,
            speed_m_s=speed_m_s,
            accuracy_m=accuracy_m,
            smoothness=smoothness,
        )
        try:
            package, plan, schedule, trajectories = await prepare_campaign_preview_off_loop(
                service,
                submission_id,
                planning_submission_id,
                motion_preparation_request=motion_preparation,
                coordination_preparation_request=(
                    CoordinationPreparationRequest(launch_gap_s=launch_gap_s)
                    if launch_gap_s is not None
                    else None
                ),
            )
        except ValueError as error:
            raise CrazySwarmError(
                ErrorCode.INVALID_STATE,
                str(error),
            ) from error
        return {
            "resolved_package": package.model_dump(mode="json"),
            "plan": plan.model_dump(mode="json"),
            "schedule": schedule.model_dump(mode="json"),
            "trajectories": trajectories.model_dump(mode="json"),
        }

    @router.get("/campaign/active/package")
    async def campaign_download_active_package(
        submission_id: str | None = None,
        planning_submission_id: str | None = None,
        balance: int | None = Query(default=None, ge=0, le=100),
        speed_m_s: float | None = Query(default=None, gt=0.0, le=2.0),
        accuracy_m: float | None = Query(default=None, gt=0.0, le=100.0),
        smoothness: int | None = Query(default=None, ge=0, le=100),
        launch_gap_s: float | None = Query(default=None, ge=0.0, le=60.0),
    ) -> JSONResponse:
        package = campaign_service().resolved_active_package(
            submission_id,
            planning_submission_id,
            motion_preparation_request=_motion_preparation_from_query(
                balance=balance,
                speed_m_s=speed_m_s,
                accuracy_m=accuracy_m,
                smoothness=smoothness,
            ),
            coordination_preparation_request=(
                CoordinationPreparationRequest(launch_gap_s=launch_gap_s)
                if launch_gap_s is not None
                else None
            ),
        )
        return JSONResponse(
            content=package.model_dump(mode="json"),
            headers={
                "Content-Disposition": (
                    'attachment; filename="resolved-campaign-planning-package-v1.json"'
                )
            },
        )

    @router.post("/campaign/active/child")
    async def campaign_create_child(body: ChildCaseRequest) -> dict[str, Any]:
        child = campaign_service().create_child(
            child_case_id=body.child_case_id,
            updates=body.updates,
        )
        return {**child.model_dump(mode="json"), "case_sha256": child.case_sha256}

    @router.post("/campaign/runs", status_code=202)
    async def campaign_run(
        body: CampaignRunRequest,
        context: OperatorContext = Depends(operator_context),
    ) -> dict[str, Any]:
        service = campaign_service()
        existing_run_id = service.state.idempotency.get(context.request_id)
        if existing_run_id is None:

            async def execute_campaign() -> None:
                try:
                    review = await service.run_active(
                        body.mode,
                        idempotency_key=context.request_id,
                        submission_id=body.submission_id,
                        planning_submission_id=body.planning_submission_id,
                        comparison_context_id=body.comparison_context_id,
                        planning_capability_request=body.planning_capability_request,
                        execution_capability_request=body.execution_capability_request,
                        motion_preparation_request=body.motion_preparation,
                        coordination_preparation_request=body.coordination_preparation,
                    )
                    # Ordinary campaign review keeps its exact CSV and can derive a
                    # twin on demand. Automatic all-channel expansion is temporarily
                    # disabled while the explicit twin curriculum remains available.
                    if CAMPAIGN_AUTOMATIC_TWIN_RETENTION_ENABLED:
                        await retain_campaign_twin_evidence_off_loop(
                            runtime,
                            service,
                            review,
                        )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # CampaignService persists the authoritative FAILED record.
                    # The workspace polling endpoint exposes that reason to the UI.
                    return

            task = asyncio.create_task(
                execute_campaign(),
                name=f"campaign-api-{context.request_id}",
            )
            campaign_run_tasks.add(task)
            task.add_done_callback(campaign_run_tasks.discard)
            # run_active persists QUEUED before its first executor wait. Yielding
            # once lets this request return the durable run identity immediately.
            await asyncio.sleep(0)
            existing_run_id = service.state.idempotency.get(context.request_id)

        if existing_run_id is None:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "CAMPAIGN_EXECUTION_FAILED",
                    "message": "campaign run could not be queued",
                },
            )
        record = next(item for item in service.state.runs if item.run_id == existing_run_id)
        return {
            "accepted": True,
            "run_id": record.run_id,
            "mode": record.mode.value,
            "status": record.status.value,
        }

    @router.post("/campaign/runs/{run_id}/cancel")
    async def campaign_cancel_run(run_id: str) -> dict[str, Any]:
        return {"run_id": run_id, "cancellation_requested": campaign_service().cancel(run_id)}

    @router.delete("/campaign/runs/{run_id}")
    async def campaign_delete_run(
        run_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> dict[str, Any]:
        async def operation() -> dict[str, Any]:
            service = campaign_service()
            try:
                run = service.validate_run_deletion(run_id)
            except KeyError as error:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    "campaign run not found",
                    details={"run_id": run_id},
                ) from error
            except PermissionError as error:
                raise CrazySwarmError(
                    ErrorCode.INVALID_STATE,
                    str(error),
                    details={"run_id": run_id},
                ) from error
            except ValueError as error:
                raise CrazySwarmError(
                    ErrorCode.INVALID_STATE,
                    str(error),
                    details={"run_id": run_id},
                ) from error

            if run.mission_execution_id is not None:
                try:
                    await asyncio.to_thread(
                        runtime.store.delete_run_file_mission,
                        run.mission_execution_id,
                    )
                except KeyError:
                    # The run-file archive may already have been removed from the
                    # general Run Files UI. Campaign state can still be cleaned up.
                    pass
                except IncompleteRunError as error:
                    raise CrazySwarmError(
                        ErrorCode.INVALID_STATE,
                        "cannot delete a campaign run while its CSV is being recorded",
                        details={"run_id": run_id},
                    ) from error

            deleted = service.delete_run(run_id)
            return {
                "run_id": deleted.run_id,
                "mission_execution_id": deleted.mission_execution_id,
                "deleted": True,
            }

        return await mutate(
            request,
            context,
            action="delete_campaign_run",
            vehicle_id=run_id,
            operation=operation,
        )

    @router.post("/campaign/runs/{run_id}/snapshots", status_code=201)
    async def campaign_capture_snapshot(
        run_id: str,
        request: Request,
        width_px: int = Query(..., ge=1, le=4096),
        height_px: int = Query(..., ge=1, le=4096),
        source_timestamp_s: float | None = Query(default=None, ge=0.0),
        source_clock_id: str | None = Query(default=None, min_length=1, max_length=96),
        source_clock_epoch: int | None = Query(default=None, ge=0),
        source_sequence: int | None = Query(default=None, ge=0),
        correlation_id: str | None = Query(default=None, min_length=1, max_length=96),
        estimate_source_timestamp_s: float | None = Query(default=None, ge=0.0),
        truth_source_timestamp_s: float | None = Query(default=None, ge=0.0),
        desired_source_timestamp_s: float | None = Query(default=None, ge=0.0),
        playback_buffer_age_s: float | None = Query(default=None, ge=0.0),
        source_rows_json: str | None = Query(default=None, min_length=2, max_length=2048),
        same_time_truth_estimate_error_m: float | None = Query(default=None, ge=0.0),
        buffer_induced_estimate_displacement_m: float | None = Query(default=None, ge=0.0),
        interpolation_state: Literal["EXACT", "INTERPOLATED", "FROZEN", "UNAVAILABLE"]
        | None = Query(default=None),
        context: OperatorContext = Depends(operator_context),
    ) -> dict[str, Any]:
        if not CAMPAIGN_SNAPSHOT_CAPTURE_ENABLED:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "CAMPAIGN_SNAPSHOT_CAPTURE_DISABLED",
                    "message": "campaign screenshot capture is temporarily disabled",
                },
            )
        declared_size = request.headers.get("content-length")
        if declared_size is not None and int(declared_size) > MAX_CAMPAIGN_SNAPSHOT_BYTES:
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                f"campaign snapshots must be at most {MAX_CAMPAIGN_SNAPSHOT_BYTES} bytes",
                details={"run_id": run_id},
            )
        content = await request.body()
        content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        frame_values = (
            source_timestamp_s,
            source_clock_id,
            source_clock_epoch,
            source_sequence,
            correlation_id,
            estimate_source_timestamp_s,
            playback_buffer_age_s,
            source_rows_json,
            interpolation_state,
        )
        if any(value is not None for value in frame_values) and not all(
            value is not None for value in frame_values
        ):
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "campaign snapshot review-frame identity is incomplete",
                details={"run_id": run_id},
            )
        source_rows: tuple[CampaignReviewSourceRow, ...] = ()
        if source_rows_json is not None:
            try:
                raw_source_rows = json.loads(source_rows_json)
                if not isinstance(raw_source_rows, list):
                    raise TypeError("source rows must be a list")
                source_rows = tuple(
                    CampaignReviewSourceRow.model_validate(item) for item in raw_source_rows
                )
            except (TypeError, ValueError) as error:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    "campaign snapshot source-row identity is invalid",
                    details={"run_id": run_id},
                ) from error
        review_frame = (
            CampaignReviewFrame(
                source_timestamp_s=source_timestamp_s,
                source_clock_id=source_clock_id,
                source_clock_epoch=source_clock_epoch,
                source_sequence=source_sequence,
                correlation_id=correlation_id,
                estimate_source_timestamp_s=estimate_source_timestamp_s,
                truth_source_timestamp_s=truth_source_timestamp_s,
                desired_source_timestamp_s=desired_source_timestamp_s,
                playback_buffer_age_s=playback_buffer_age_s,
                source_rows=source_rows,
                same_time_truth_estimate_error_m=same_time_truth_estimate_error_m,
                buffer_induced_estimate_displacement_m=(buffer_induced_estimate_displacement_m),
                interpolation_state=interpolation_state,
            )
            if all(value is not None for value in frame_values)
            else None
        )

        async def operation() -> dict[str, Any]:
            try:
                snapshot = campaign_service().add_snapshot(
                    run_id,
                    content=content,
                    content_type=content_type,
                    width_px=width_px,
                    height_px=height_px,
                    review_frame=review_frame,
                )
            except KeyError as error:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    "campaign run not found",
                    details={"run_id": run_id},
                ) from error
            except ValueError as error:
                raise CrazySwarmError(
                    ErrorCode.INVALID_STATE,
                    str(error),
                    details={"run_id": run_id},
                ) from error
            return snapshot.model_dump(mode="json")

        return await mutate(
            request,
            context,
            action="capture_campaign_snapshot",
            vehicle_id=run_id,
            operation=operation,
        )

    @router.get("/campaign/snapshots/{snapshot_id}/image")
    async def campaign_snapshot_image(snapshot_id: str) -> FileResponse:
        try:
            path, snapshot = campaign_service().snapshot_image_path(snapshot_id)
        except (KeyError, FileNotFoundError) as error:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "CAMPAIGN_SNAPSHOT_NOT_FOUND",
                    "message": "campaign snapshot image is no longer available",
                },
            ) from error
        return FileResponse(
            path,
            media_type=snapshot.content_type,
            headers={
                "Cache-Control": "private, max-age=31536000, immutable",
                "ETag": f'"{snapshot.sha256}"',
            },
        )

    @router.post("/campaign/snapshots/{snapshot_id}/comment")
    async def campaign_snapshot_comment(
        snapshot_id: str,
        body: SnapshotCommentRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> dict[str, Any]:
        async def operation() -> dict[str, Any]:
            try:
                snapshot = campaign_service().set_snapshot_comment(snapshot_id, body.note)
            except KeyError as error:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    "campaign snapshot not found",
                    details={"snapshot_id": snapshot_id},
                ) from error
            except ValueError as error:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    str(error),
                    details={"snapshot_id": snapshot_id},
                ) from error
            return snapshot.model_dump(mode="json")

        return await mutate(
            request,
            context,
            action="comment_campaign_snapshot",
            vehicle_id=snapshot_id,
            operation=operation,
        )

    @router.post("/campaign/snapshots/{snapshot_id}/assessment")
    async def campaign_snapshot_assessment(
        snapshot_id: str,
        body: SnapshotAssessmentRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> dict[str, Any]:
        async def operation() -> dict[str, Any]:
            try:
                snapshot = campaign_service().set_snapshot_assessment(
                    snapshot_id,
                    assessment=body.assessment,
                    disposition=body.disposition,
                    confidence=body.confidence,
                    evidence_refs=body.evidence_refs,
                )
            except KeyError as error:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    "campaign snapshot not found",
                    details={"snapshot_id": snapshot_id},
                ) from error
            except ValueError as error:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    str(error),
                    details={"snapshot_id": snapshot_id},
                ) from error
            return snapshot.model_dump(mode="json")

        return await mutate(
            request,
            context,
            action="assess_campaign_snapshot",
            vehicle_id=snapshot_id,
            operation=operation,
        )

    @router.post("/campaign/reviews/{review_id}/observations")
    async def campaign_review_observation(
        review_id: str,
        body: ReviewObservationRequest,
        context: OperatorContext = Depends(operator_context),
    ) -> dict[str, Any]:
        return (
            campaign_service()
            .add_observation(review_id, body.note, actor_id=context.client_id)
            .model_dump(mode="json")
        )

    @router.post("/campaign/reviews/{review_id}/decision")
    async def campaign_review_decision(
        review_id: str,
        body: ReviewDecisionRequest,
        context: OperatorContext = Depends(operator_context),
    ) -> dict[str, Any]:
        return (
            campaign_service()
            .decide_review(
                review_id,
                operator_id=context.client_id,
                decision=body.decision,
                reason=body.reason,
                note=body.note,
            )
            .model_dump(mode="json")
        )

    @router.get("/campaign/recommendation")
    async def campaign_recommendation() -> dict[str, Any]:
        return campaign_service().recommend_next().model_dump(mode="json")

    @router.post("/campaign/active/promote")
    async def campaign_promote_active(
        body: ReasonRequest,
        context: OperatorContext = Depends(operator_context),
    ) -> dict[str, Any]:
        return (
            campaign_service()
            .promote_active(
                operator_id=context.client_id,
                reason=body.reason,
            )
            .model_dump(mode="json")
        )

    @router.get("/campaign/wp25-matrix")
    async def campaign_wp25_matrix() -> dict[str, Any]:
        return campaign_service().materialize_wp25_matrix()

    @router.get("/campaign/timing")
    async def campaign_timing_snapshot() -> dict[str, Any]:
        snapshot = campaign_timing.snapshot()
        return {
            "trace": snapshot.model_dump(mode="json"),
            "classification": classify_timing_trace(snapshot).model_dump(mode="json"),
        }

    @router.post("/campaign/timing/browser")
    async def campaign_browser_timing(body: BrowserTimingEventRequest) -> dict[str, Any]:
        if body.stage not in {
            TimingStage.BROWSER_RECEIPT,
            TimingStage.RENDER_FRAME,
            TimingStage.PLAYBACK_BUFFER,
        }:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_TIMING_STAGE",
                    "message": "browser diagnostics may report only browser-owned stages",
                },
            )
        event = campaign_timing.record(**body.model_dump())
        return event.model_dump(mode="json")

    @router.get("/fleet/sessions")
    async def fleet_sessions() -> list[dict[str, Any]]:
        return [
            _fleet_session_view(runtime, session_id)
            for session_id in sorted(runtime.fleet_preparations)
        ]

    @router.get("/fleet/templates/two-drone")
    async def two_drone_fleet_templates() -> dict[str, Any]:
        fleet_config = Path(__file__).resolve().parents[3] / "config" / "fleet"
        deployment = load_versioned_contract(
            fleet_config / "two-drone-deployment-v1.yaml", DeploymentManifest
        )
        bindings = [
            load_versioned_contract(path, BackendBindingProfile)
            for path in (
                fleet_config / "fast-sim-two-drone-binding-v1.yaml",
                fleet_config / "mock-isaac-two-drone-binding-v1.yaml",
            )
        ]
        return {
            "deployment": deployment.model_dump(mode="json"),
            "bindings": [item.model_dump(mode="json") for item in bindings],
        }

    @router.get("/fleet/qualification")
    async def fleet_qualification() -> dict[str, Any]:
        root = Path(__file__).resolve().parents[3]
        return run_persistent_fleet_qualification(root).model_dump(mode="json")

    @router.get("/fleet/qualification/export")
    async def export_fleet_qualification() -> JSONResponse:
        root = Path(__file__).resolve().parents[3]
        report = run_persistent_fleet_qualification(root)
        return JSONResponse(
            content=report.model_dump(mode="json"),
            headers={
                "Content-Disposition": (
                    'attachment; filename="persistent-fleet-software-qualification-v1.json"'
                )
            },
        )

    @router.get("/planning/qualification")
    async def planning_qualification() -> dict[str, Any]:
        return run_planning_release_qualification().model_dump(mode="json")

    @router.get("/planning/qualification/export")
    async def export_planning_qualification() -> JSONResponse:
        report = run_planning_release_qualification()
        return JSONResponse(
            content=report.model_dump(mode="json"),
            headers={
                "Content-Disposition": (
                    'attachment; filename="planning-fast-sim-qualification-v1.json"'
                )
            },
        )

    @router.post("/fleet/sessions")
    async def create_fleet_session(
        body: FleetSessionCreateRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            if body.execution_session_id in runtime.fleet_preparations:
                existing = runtime.fleet_preparations[body.execution_session_id]
                if (
                    existing.deployment.sha256 == body.deployment.sha256
                    and existing.binding.sha256 == body.binding.sha256
                ):
                    return _fleet_session_view(runtime, body.execution_session_id)
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH,
                    "fleet session ID already identifies different artifacts",
                )
            if body.fleet_run_id in runtime.fleet_coordinators:
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH,
                    "fleet run ID is already in use",
                )
            task_missions = {item.mission_id for item in body.deployment.tasks}
            if body.mission_id not in task_missions or len(task_missions) != 1:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    "this fleet session requires one shared mission artifact",
                    details={"task_mission_ids": sorted(task_missions)},
                )
            metadata = runtime.missions.metadata(body.mission_id)
            if metadata.source_sha256 is None:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    "fleet mission requires a source-addressed mission artifact",
                )
            mission = MissionArtifact(
                mission_id=metadata.mission_id,
                mission_version=metadata.mission_version,
                source_sha256=metadata.source_sha256,
            )
            preparation = FleetPreparation(
                execution_session_id=body.execution_session_id,
                deployment=body.deployment,
                binding=body.binding,
                supervisor=runtime.supervisor,
            )
            preparation.discover(tuple(runtime.vehicles.values()))
            identity = FleetSessionIdentity.create(
                fleet_session_id=body.execution_session_id,
                fleet_run_id=body.fleet_run_id,
                backend=body.binding.backend,
                mission=mission,
                deployment=body.deployment,
                binding=body.binding,
                model_id="operator-fleet-foundation",
                scenario_id=runtime.scenario.scenario_id,
                initial_state={
                    member.vehicle_id: member.home.model_dump(mode="json")
                    for member in body.deployment.fleet
                },
            )
            coordinator = FleetCoordinator(
                identity=identity,
                deployment=body.deployment,
                preparation=preparation,
                supervisor=runtime.supervisor,
                mission_runner=runtime.runner,
            )
            runtime.fleet_preparations[body.execution_session_id] = preparation
            runtime.fleet_coordinators[body.fleet_run_id] = coordinator
            return _fleet_session_view(runtime, body.execution_session_id)

        return await mutate(
            request,
            context,
            action="create_fleet_session",
            vehicle_id=body.deployment.deployment_id,
            operation=operation,
        )

    @router.get("/fleet/sessions/{session_id}")
    async def fleet_session(session_id: str) -> dict[str, Any]:
        return _fleet_session_view(runtime, session_id)

    @router.post("/fleet/sessions/{session_id}/connect")
    async def connect_fleet(
        session_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            preparation = _fleet_preparation(runtime, session_id)
            await preparation.connect_all()
            return _fleet_session_view(runtime, session_id)

        return await mutate(
            request,
            context,
            action="connect_fleet",
            vehicle_id=session_id,
            operation=operation,
        )

    @router.post("/fleet/sessions/{session_id}/observe")
    async def observe_fleet(
        session_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            preparation = _fleet_preparation(runtime, session_id)
            if preparation.record.observation_started_at_monotonic_s is None:
                await preparation.start_observation()
            else:
                await preparation.refresh_observations()
            return _fleet_session_view(runtime, session_id)

        return await mutate(
            request,
            context,
            action="observe_fleet",
            vehicle_id=session_id,
            operation=operation,
        )

    @router.post("/fleet/sessions/{session_id}/preflight")
    async def preflight_fleet(
        session_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            preparation = _fleet_preparation(runtime, session_id)
            await preparation.run_preflight()
            return _fleet_session_view(runtime, session_id)

        return await mutate(
            request,
            context,
            action="preflight_fleet",
            vehicle_id=session_id,
            operation=operation,
        )

    @router.post("/fleet/sessions/{session_id}/prepare")
    async def prepare_fleet(
        session_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            preparation = _fleet_preparation(runtime, session_id)
            await preparation.connect_all()
            await preparation.start_observation()
            await preparation.run_preflight()
            return _fleet_session_view(runtime, session_id)

        return await mutate(
            request,
            context,
            action="prepare_fleet",
            vehicle_id=session_id,
            operation=operation,
        )

    @router.post("/fleet/sessions/{session_id}/vehicles/{vehicle_id}/retry")
    async def retry_fleet_vehicle(
        session_id: str,
        vehicle_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            preparation = _fleet_preparation(runtime, session_id)
            await preparation.retry_vehicle(vehicle_id)
            return _fleet_session_view(runtime, session_id)

        return await mutate(
            request,
            context,
            action="retry_fleet_vehicle",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    @router.post("/fleet/sessions/{session_id}/disconnect")
    async def disconnect_fleet(
        session_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            preparation = _fleet_preparation(runtime, session_id)
            await preparation.disconnect_all_safe()
            return _fleet_session_view(runtime, session_id)

        return await mutate(
            request,
            context,
            action="disconnect_fleet",
            vehicle_id=session_id,
            operation=operation,
        )

    @router.post("/fleet/runs/{fleet_run_id}/start")
    async def start_fleet_run(
        fleet_run_id: str,
        body: FleetStartRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, str]:
            coordinator = _fleet_coordinator(runtime, fleet_run_id)
            coordinator.preparation.require_ready()
            active = runtime.fleet_tasks.get(fleet_run_id)
            if active is not None and not active.done():
                return {"fleet_run_id": fleet_run_id, "status": "RUNNING"}

            async def execute() -> None:
                result = await coordinator.run(body.assignments)
                # A terminal fleet result is a durability boundary: do not expose it
                # while the recorder is still materializing member run files and the
                # grouped evaluation on the same store queried by operators.
                await runtime.recorder.flush()
                runtime.fleet_results[fleet_run_id] = result

            task = asyncio.create_task(execute(), name=f"fleet-run-{fleet_run_id}")
            runtime.track_fleet_task(fleet_run_id, task)
            return {"fleet_run_id": fleet_run_id, "status": "SCHEDULED"}

        return await mutate(
            request,
            context,
            action="start_fleet_run",
            vehicle_id=fleet_run_id,
            operation=operation,
        )

    @router.get("/fleet/runs/{fleet_run_id}")
    async def fleet_run(fleet_run_id: str) -> dict[str, Any]:
        coordinator = _fleet_coordinator(runtime, fleet_run_id)
        result = runtime.fleet_results.get(fleet_run_id)
        return {
            "fleet_run_id": fleet_run_id,
            "status": (
                result.status.value
                if result is not None
                else "RUNNING"
                if fleet_run_id in runtime.fleet_tasks
                else "READY"
            ),
            "result": result.model_dump(mode="json") if result is not None else None,
            "tasks": [item.model_dump(mode="json") for item in coordinator.tasks.records()],
        }

    @router.get("/fleet/runs/{fleet_run_id}/replay")
    async def replay_fleet_run(
        fleet_run_id: str,
        sequence: int | None = Query(default=None, ge=1),
    ) -> dict[str, Any]:
        coordinator = _fleet_coordinator(runtime, fleet_run_id)
        result = runtime.fleet_results.get(fleet_run_id)
        tasks = result.tasks if result is not None else coordinator.tasks.records()
        fleet_events = result.events if result is not None else ()
        events = [
            {
                "source": "FLEET",
                "timestamp_monotonic_s": item.timestamp_monotonic_s,
                **item.model_dump(mode="json"),
            }
            for item in fleet_events
        ]
        for task in tasks:
            events.extend(
                {
                    "source": "TASK",
                    "timestamp_monotonic_s": item.timestamp_monotonic_s,
                    **item.model_dump(mode="json"),
                }
                for item in task.events
            )
        events.sort(
            key=lambda item: (
                float(item["timestamp_monotonic_s"]),
                str(item["source"]),
                int(item["sequence"]),
            )
        )
        index = len(events) if sequence is None else min(sequence, len(events))
        return {
            "fleet_run_id": fleet_run_id,
            "command_authority": False,
            "source_class": "REPLAYED",
            "index": index,
            "event_count": len(events),
            "event": events[index - 1] if index else None,
            "events": events[:index],
            "tasks": [item.model_dump(mode="json") for item in tasks],
        }

    @router.post("/fleet/runs/{fleet_run_id}/vehicles/{vehicle_id}/abort")
    async def abort_fleet_vehicle(
        fleet_run_id: str,
        vehicle_id: str,
        body: ReasonRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, str]:
            coordinator = _fleet_coordinator(runtime, fleet_run_id)
            await coordinator.abort_vehicle(vehicle_id, reason=body.reason)
            return {"vehicle_id": vehicle_id, "status": "ABORT_REQUESTED"}

        return await mutate(
            request,
            context,
            action="abort_fleet_vehicle",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    @router.post("/mode")
    async def set_mode(
        body: ModeRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, str]:
            authorization = None
            if body.mode in {OperatingMode.LIVE, OperatingMode.SHADOW}:
                authorization = LiveModeAuthorization(
                    vehicle_id=runtime.selected_vehicle_id,
                    operator_id=context.client_id,
                    mode=body.mode,
                    confirmed=body.confirmed,
                    authorized_at_monotonic_s=time.monotonic(),
                )
            runtime.supervisor.set_mode(body.mode, authorization=authorization)
            return {"mode": runtime.supervisor.mode.value}

        return await mutate(
            request,
            context,
            action="set_mode",
            vehicle_id=runtime.selected_vehicle_id,
            operation=operation,
        )

    @router.get("/vehicles")
    async def vehicles() -> list[dict[str, Any]]:
        return [_vehicle_view(runtime, vehicle_id) for vehicle_id in runtime.vehicles]

    @router.get("/vehicles/discover")
    async def discover_vehicles() -> dict[str, Any]:
        return {
            "source": "configured-simulation",
            "automatic_connection": False,
            "vehicles": [_vehicle_view(runtime, vehicle_id) for vehicle_id in runtime.vehicles],
        }

    @router.get("/vehicles/{vehicle_id}")
    async def vehicle(vehicle_id: str) -> dict[str, Any]:
        _require_vehicle(runtime, vehicle_id)
        return _vehicle_view(runtime, vehicle_id)

    @router.post("/vehicles/select")
    async def select_vehicle(
        body: SelectVehicleRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, str]:
            _require_vehicle(runtime, body.vehicle_id)
            if body.vehicle_id == runtime.selected_vehicle_id:
                return {"selected_vehicle_id": body.vehicle_id}
            current = runtime.supervisor.session(runtime.selected_vehicle_id)
            target = runtime.supervisor.session(body.vehicle_id)
            switchable_states = {VehicleState.DISCONNECTED, VehicleState.READY}
            if current.state not in switchable_states or target.state not in switchable_states:
                raise CrazySwarmError(
                    ErrorCode.MODE_NOT_AUTHORIZED,
                    "vehicle selection is locked while a vehicle is active",
                )
            if current.lease is not None:
                raise CrazySwarmError(
                    ErrorCode.MODE_NOT_AUTHORIZED,
                    "release command authority before changing vehicle",
                )
            runtime.selected_vehicle_id = body.vehicle_id
            return {"selected_vehicle_id": body.vehicle_id}

        return await mutate(
            request,
            context,
            action="select_vehicle",
            vehicle_id=body.vehicle_id,
            operation=operation,
        )

    @router.post("/vehicles/{vehicle_id}/connect")
    async def connect_vehicle(
        vehicle_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            telemetry = await runtime.supervisor.connect(vehicle_id)
            return telemetry.model_dump(mode="json")

        return await mutate(
            request, context, action="connect", vehicle_id=vehicle_id, operation=operation
        )

    @router.post("/vehicles/{vehicle_id}/disconnect")
    async def disconnect_vehicle(
        vehicle_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, str]:
            await runtime.supervisor.disconnect(vehicle_id, context.client_id)
            return {"state": VehicleState.DISCONNECTED.value}

        return await mutate(
            request,
            context,
            action="disconnect",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    @router.post("/vehicles/{vehicle_id}/control/claim")
    async def claim_control(
        vehicle_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            runtime.supervisor.claim_control(vehicle_id, context.client_id)
            return runtime.supervisor.session(vehicle_id).lease.model_dump(mode="json")  # type: ignore[union-attr]

        return await mutate(
            request,
            context,
            action="claim_control",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    @router.post("/vehicles/{vehicle_id}/control/renew")
    async def renew_control(
        vehicle_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            runtime.supervisor.renew_control(vehicle_id, context.client_id)
            return runtime.supervisor.session(vehicle_id).lease.model_dump(mode="json")  # type: ignore[union-attr]

        return await mutate(
            request,
            context,
            action="renew_control",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    @router.post("/vehicles/{vehicle_id}/control/release")
    async def release_control(
        vehicle_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, bool]:
            await runtime.supervisor.release_control(vehicle_id, context.client_id)
            return {"released": True}

        return await mutate(
            request,
            context,
            action="release_control",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    @router.post("/vehicles/{vehicle_id}/preflight")
    async def preflight(
        vehicle_id: str,
        body: PreflightRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            required = frozenset({VehicleCapability.ARMING})
            if body.mission_id is not None:
                required |= runtime.missions.get(body.mission_id).required_capabilities
            report = await runtime.supervisor.preflight(
                vehicle_id,
                context.client_id,
                required_capabilities=required,
            )
            return report.model_dump(mode="json")

        return await mutate(
            request,
            context,
            action="preflight",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    @router.post("/vehicles/{vehicle_id}/arm")
    async def arm(
        vehicle_id: str,
        body: ArmRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            result = await runtime.supervisor.arm(vehicle_id, context.client_id, body.report_id)
            return result.model_dump(mode="json")

        return await mutate(
            request, context, action="arm", vehicle_id=vehicle_id, operation=operation
        )

    @router.post("/vehicles/{vehicle_id}/disarm")
    async def disarm(
        vehicle_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            result = await runtime.supervisor.disarm(vehicle_id, context.client_id)
            return result.model_dump(mode="json")

        return await mutate(
            request, context, action="disarm", vehicle_id=vehicle_id, operation=operation
        )

    @router.post("/vehicles/{vehicle_id}/takeoff")
    async def takeoff(
        vehicle_id: str,
        body: TakeoffRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            result = await runtime.supervisor.takeoff(
                vehicle_id,
                context.client_id,
                height_m=body.height_m,
                duration_s=body.duration_s,
            )
            return result.model_dump(mode="json")

        return await mutate(
            request, context, action="takeoff", vehicle_id=vehicle_id, operation=operation
        )

    @router.post("/vehicles/{vehicle_id}/hover")
    async def hover(
        vehicle_id: str,
        body: DurationRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            result = await runtime.supervisor.hover(vehicle_id, context.client_id, body.duration_s)
            return result.model_dump(mode="json")

        return await mutate(
            request, context, action="hover", vehicle_id=vehicle_id, operation=operation
        )

    @router.post("/vehicles/{vehicle_id}/move-relative")
    async def move_relative(
        vehicle_id: str,
        body: MoveRelativeCommand,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            result = await runtime.supervisor.move_relative(vehicle_id, context.client_id, body)
            return result.model_dump(mode="json")

        return await mutate(
            request,
            context,
            action="move_relative",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    @router.post("/vehicles/{vehicle_id}/stop-and-hold")
    async def stop_and_hold(
        vehicle_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            result = await runtime.supervisor.stop_and_hold(vehicle_id, context.client_id)
            return result.model_dump(mode="json")

        return await mutate(
            request,
            context,
            action="stop_and_hold",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    @router.post("/vehicles/{vehicle_id}/land")
    async def land(
        vehicle_id: str,
        body: DurationRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            result = await runtime.supervisor.land(
                vehicle_id, context.client_id, duration_s=body.duration_s
            )
            return result.model_dump(mode="json")

        return await mutate(
            request, context, action="land", vehicle_id=vehicle_id, operation=operation
        )

    @router.post("/vehicles/{vehicle_id}/abort")
    async def abort(
        vehicle_id: str,
        body: ReasonRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            result = await runtime.supervisor.abort_and_land(
                vehicle_id, context.client_id, reason=body.reason
            )
            return result.model_dump(mode="json")

        return await mutate(
            request, context, action="abort", vehicle_id=vehicle_id, operation=operation
        )

    @router.post("/vehicles/{vehicle_id}/emergency-stop")
    async def emergency_stop(
        vehicle_id: str,
        body: ReasonRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            session = runtime.supervisor.session(vehicle_id)
            owner_id = context.client_id
            mission_run_id: str | None = None
            if session.lease is not None and session.lease.owner_id.startswith("mission:run-"):
                candidate = session.lease.owner_id.removeprefix("mission:")
                task = runtime.mission_tasks.get(candidate)
                if task is not None and not task.done():
                    owner_id = session.lease.owner_id
                    mission_run_id = candidate
            result = await runtime.supervisor.emergency_stop(
                vehicle_id, owner_id, reason=body.reason
            )
            if mission_run_id is not None:
                await runtime.runner.cancel(mission_run_id)
            return result.model_dump(mode="json")

        return await mutate(
            request,
            context,
            action="emergency_stop",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    @router.get("/vehicles/{vehicle_id}/parameters")
    async def parameters(vehicle_id: str) -> dict[str, Any]:
        selected = _require_vehicle(runtime, vehicle_id)
        supported = VehicleCapability.PARAMETER_ACCESS in selected.capabilities.features
        values = (
            [item.model_dump(mode="json") for item in runtime.parameters.list(vehicle_id)]
            if supported
            else []
        )
        return {"vehicle_id": vehicle_id, "supported": supported, "values": values}

    @router.post("/vehicles/{vehicle_id}/parameters/write")
    async def write_parameter(
        vehicle_id: str,
        body: ParameterWriteRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            session = runtime.supervisor.session(vehicle_id)
            value = runtime.parameters.write(
                vehicle_id,
                body.name,
                body.value,
                state=session.state,
                armed=(session.telemetry is not None and session.telemetry.telemetry.armed),
            )
            return value.model_dump(mode="json")

        return await mutate(
            request,
            context,
            action="write_parameter",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    @router.post("/vehicles/{vehicle_id}/parameters/snapshot")
    async def snapshot_parameters(
        vehicle_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            return runtime.parameters.snapshot(vehicle_id).model_dump(mode="json")

        return await mutate(
            request,
            context,
            action="snapshot_parameters",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    @router.get("/vehicles/{vehicle_id}/parameters/snapshots/{snapshot_id}/diff")
    async def diff_parameters(vehicle_id: str, snapshot_id: str) -> dict[str, Any]:
        return {
            "snapshot_id": snapshot_id,
            "changes": runtime.parameters.diff(vehicle_id, snapshot_id),
        }

    @router.post("/vehicles/{vehicle_id}/parameters/restore")
    async def restore_parameters(
        vehicle_id: str,
        body: ParameterSnapshotRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            session = runtime.supervisor.session(vehicle_id)
            values = runtime.parameters.restore(
                vehicle_id,
                body.snapshot_id,
                state=session.state,
                armed=(session.telemetry is not None and session.telemetry.telemetry.armed),
            )
            return {
                "snapshot_id": body.snapshot_id,
                "values": [item.model_dump(mode="json") for item in values],
            }

        return await mutate(
            request,
            context,
            action="restore_parameters",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    @router.get("/vehicles/{vehicle_id}/telemetry/catalog")
    async def telemetry_catalog(vehicle_id: str) -> dict[str, Any]:
        _require_vehicle(runtime, vehicle_id)
        session = runtime.supervisor.session(vehicle_id)
        run = runtime.latest_mission_for_vehicle(vehicle_id)
        if run is None or session.telemetry is None:
            return {"vehicle_id": vehicle_id, "run_id": None, "fields": []}
        envelope = session.telemetry.model_dump(mode="json")
        fields = _simulated_field_provenance(envelope)
        return {
            "vehicle_id": vehicle_id,
            "run_id": run.mission_run_id,
            "fields": [{"name": name, **metadata} for name, metadata in fields.items()],
        }

    @router.get("/audit")
    async def audit(vehicle_id: str | None = None, limit: int = Query(100, ge=1, le=1000)) -> Any:
        events = runtime.supervisor.events
        if vehicle_id is not None:
            events = [event for event in events if event.vehicle_id == vehicle_id]
        return [event.model_dump(mode="json") for event in events[-limit:]]

    @router.get("/missions")
    async def missions() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in runtime.missions.list_metadata()]

    @router.get("/mission-files")
    async def mission_files() -> list[dict[str, Any]]:
        return [
            item.model_dump(mode="json")
            for item in runtime.missions.list_metadata()
            if item.source_kind == "UPLOADED_PYTHON"
        ]

    @router.get("/mission-files/archive")
    async def archived_mission_files() -> list[dict[str, Any]]:
        return [
            {
                "mission_id": item.mission_id,
                "name": item.name,
                "filename": item.filename,
                "source_sha256": item.source_sha256,
                "archived": True,
            }
            for item in runtime.mission_files.list_archive()
        ]

    @router.post("/mission-files")
    async def upload_mission_file(
        body: MissionFileUploadRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            record = runtime.mission_files.add(
                filename=body.filename,
                name=body.name,
                source=body.source,
            )
            return runtime.missions.metadata(record.mission_id).model_dump(mode="json")

        return await mutate(
            request,
            context,
            action="upload_mission_file",
            vehicle_id=runtime.selected_vehicle_id,
            operation=operation,
        )

    @router.get("/mission-files/{mission_id}/preview")
    async def preview_mission_file(mission_id: str) -> dict[str, Any]:
        definition = runtime.missions.get(mission_id)
        if not isinstance(definition, ScriptMission):
            raise CrazySwarmError(
                ErrorCode.INVALID_COMMAND,
                "mission preview requires an uploaded Python mission",
            )
        record = definition.record
        deployment_plan, mission_plan = await _compile_uploaded_mission_plan(
            runtime,
            definition,
            runtime.selected_vehicle_id,
        )
        previews = [
            {
                "role_id": role.role_id,
                "vehicle_id": role.vehicle_id,
                "display_name": deployment_plan.deployment.member(role.vehicle_id).display_name,
                "initial_role": role.initial_role.value,
                "home_m": role.home_m.model_dump(mode="json"),
                "start_m": role.start_m.model_dump(mode="json"),
                "battery_percent": role.observed_battery_percent,
                "minimum_battery_percent": role.minimum_battery_percent,
                "existing_vehicle": role.existing_vehicle,
                "backend_role": (
                    runtime.vehicles[role.vehicle_id].backend_profile.role.value
                    if role.vehicle_id in runtime.vehicles
                    else {
                        ExecutionBackend.FAST_SIM: BackendRole.FAST_SIM.value,
                        ExecutionBackend.MOCK_ISAAC: BackendRole.ISAAC_SIM.value,
                    }[deployment_plan.binding.backend]
                ),
                "vehicle_state": (
                    runtime.supervisor.session(role.vehicle_id).state.value
                    if role.existing_vehicle
                    else None
                ),
                "planned_commands": [
                    command.model_dump(mode="json") for command in role.planned_commands
                ],
                "preview_fidelity": role.preview_fidelity.value,
            }
            for role in mission_plan.roles
        ]
        return {
            "mission_id": mission_id,
            "source_sha256": record.source_sha256,
            "vehicles": previews,
            "plan": mission_plan.model_dump(mode="json"),
            "plan_sha256": mission_plan.sha256,
            "approval_required": mission_plan.status is not MissionPlanStatus.BLOCKED,
        }

    @router.post("/mission-files/{mission_id}/approve")
    async def approve_mission_file_plan(
        mission_id: str,
        body: MissionPlanApprovalRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        requested_vehicle_id = body.vehicle_id or runtime.selected_vehicle_id

        async def operation() -> dict[str, Any]:
            definition = runtime.missions.get(mission_id)
            if not isinstance(definition, ScriptMission):
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    "mission approval requires an uploaded Python mission",
                )
            _, mission_plan = await _compile_uploaded_mission_plan(
                runtime,
                definition,
                requested_vehicle_id,
            )
            if mission_plan.status is MissionPlanStatus.BLOCKED:
                raise CrazySwarmError(
                    ErrorCode.PREFLIGHT_FAILED,
                    "blocked mission plans cannot be approved",
                    details=_mission_plan_details(mission_plan),
                )
            if body.expected_plan_sha256 != mission_plan.sha256:
                raise CrazySwarmError(
                    ErrorCode.PREFLIGHT_FAILED,
                    "mission plan changed before approval",
                    details={
                        **_mission_plan_details(mission_plan),
                        "expected_plan_sha256": body.expected_plan_sha256,
                    },
                )
            required_acknowledgements = frozenset(
                finding.code for finding in mission_plan.findings if finding.requires_confirmation
            )
            missing = sorted(required_acknowledgements - body.acknowledged_finding_codes)
            if missing:
                raise CrazySwarmError(
                    ErrorCode.PREFLIGHT_FAILED,
                    "confirmable mission-plan findings require acknowledgement",
                    details={
                        **_mission_plan_details(mission_plan),
                        "missing_acknowledgements": missing,
                    },
                )
            approval = MissionPlanApproval.create(
                mission_plan,
                operator_client_id=context.client_id,
                acknowledged_finding_codes=body.acknowledged_finding_codes,
                now_monotonic_s=time.monotonic(),
            )
            runtime.plan_approvals[approval.approval_id] = approval
            return approval.model_dump(mode="json")

        return await mutate(
            request,
            context,
            action="approve_mission_plan",
            vehicle_id=requested_vehicle_id,
            operation=operation,
        )

    @router.post("/mission-files/{mission_id}/start")
    async def start_mission_file(
        mission_id: str,
        body: MissionFileStartRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        requested_vehicle_id = body.vehicle_id or runtime.selected_vehicle_id

        async def operation() -> dict[str, str | int]:
            definition = runtime.missions.get(mission_id)
            if definition.source_kind != "UPLOADED_PYTHON":
                raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission is not an uploaded file")
            if not isinstance(definition, ScriptMission):
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    "uploaded mission does not expose a mission package",
                )
            vehicle = _require_vehicle(runtime, requested_vehicle_id)
            if body.execution_mode is MissionExecutionMode.TWIN:
                raise CrazySwarmError(
                    ErrorCode.MODE_NOT_AUTHORIZED,
                    "digital twin requires a qualified real vehicle adapter",
                )
            if vehicle.backend_profile.authority is not AuthorityClass.SIMULATION:
                raise CrazySwarmError(
                    ErrorCode.MODE_NOT_AUTHORIZED,
                    "simulation mode requires a simulator vehicle",
                )
            active = [
                execution.execution_run_id
                for execution in runtime.executions.values()
                if not execution.terminal
            ]
            if active:
                raise CrazySwarmError(
                    ErrorCode.INVALID_STATE,
                    "another uploaded mission deployment is active",
                    details={"execution_run_ids": sorted(active)},
                )
            await runtime.cleanup_completed_execution_vehicles()
            runtime.supervisor.set_mode(OperatingMode.SIM)
            plan, mission_plan = await _compile_uploaded_mission_plan(
                runtime,
                definition,
                requested_vehicle_id,
            )
            plan_details = _mission_plan_details(mission_plan)
            if mission_plan.status is MissionPlanStatus.BLOCKED:
                raise CrazySwarmError(
                    ErrorCode.PREFLIGHT_FAILED,
                    "mission planner rejected the mission before provisioning",
                    details=plan_details,
                )
            approval = _require_current_plan_approval(
                runtime,
                mission_plan,
                approval_id=body.approval_id,
                expected_plan_sha256=body.expected_plan_sha256,
                operator_client_id=context.client_id,
            )
            if (
                mission_plan.status is MissionPlanStatus.REQUIRES_CONFIRMATION
                and not body.confirm_low_battery_risk
            ):
                raise CrazySwarmError(
                    ErrorCode.PREFLIGHT_FAILED,
                    "mission planner requires explicit simulation risk confirmation",
                    details=plan_details,
                )
            provider = SoftwareBackendVehicleProvider(runtime.scenario)
            provisioned = provider.provision(
                plan.deployment,
                plan.binding,
                existing=runtime.vehicles,
            )
            session_id = f"execution-{uuid.uuid4().hex}"
            run_id = f"run-{uuid.uuid4().hex}"
            runtime.attach_execution_vehicles(session_id, provisioned)
            preparation = FleetPreparation(
                execution_session_id=session_id,
                deployment=plan.deployment,
                binding=plan.binding,
                supervisor=runtime.supervisor,
            )
            preparation.discover(provisioned.vehicles)
            mission = MissionArtifact(
                mission_id=definition.mission_id,
                mission_version=definition.mission_version,
                source_sha256=definition.record.source_sha256,
            )
            fleet_coordinator: FleetCoordinator | None = None
            if len(plan.deployment.fleet) > 1:
                static_independent_trajectory_authority = all(
                    task.task_type == "MISSION_ROLE" for task in plan.deployment.tasks
                ) or (
                    mission_plan.deconfliction is not None
                    and mission_plan.deconfliction.status.value in {"NOT_REQUIRED", "RESOLVED"}
                    and len(mission_plan.execution_programs) == len(plan.deployment.tasks)
                )
                identity = FleetSessionIdentity.create(
                    fleet_session_id=session_id,
                    fleet_run_id=run_id,
                    backend=plan.binding.backend,
                    mission=mission,
                    deployment=plan.deployment,
                    binding=plan.binding,
                    model_id="mission-derived-execution",
                    scenario_id=runtime.scenario.scenario_id,
                    initial_state={
                        member.vehicle_id: member.home.model_dump(mode="json")
                        for member in plan.deployment.fleet
                    },
                )
                fleet_coordinator = FleetCoordinator(
                    identity=identity,
                    deployment=plan.deployment,
                    preparation=preparation,
                    supervisor=runtime.supervisor,
                    mission_runner=runtime.runner,
                    policy_decision=mission_plan.planning.fleet_policy_decision,
                    planning_bundle=mission_plan.planning,
                    accepted_plan_id=(
                        mission_plan.plan_id if static_independent_trajectory_authority else None
                    ),
                    accepted_plan_sha256=(
                        mission_plan.sha256 if static_independent_trajectory_authority else None
                    ),
                    accepted_execution_programs=(
                        {program.role_id: program for program in mission_plan.execution_programs}
                        if static_independent_trajectory_authority
                        else None
                    ),
                    deconfliction_plan=mission_plan.deconfliction,
                )
                runtime.fleet_coordinators[run_id] = fleet_coordinator
            execution = ExecutionCoordinator(
                execution_session_id=session_id,
                execution_run_id=run_id,
                mission_id=mission_id,
                mission_source_sha256=definition.record.source_sha256,
                deployment=plan.deployment,
                binding=plan.binding,
                mission_plan=mission_plan,
                assignments=plan.assignments,
                preparation=preparation,
                mission_runner=runtime.runner,
                fleet_coordinator=fleet_coordinator,
                allow_simulation_low_battery=body.confirm_low_battery_risk,
            )
            runtime.fleet_preparations[session_id] = preparation
            runtime.executions[session_id] = execution
            runtime.execution_run_sessions[run_id] = session_id
            runtime.plan_approvals.pop(approval.approval_id, None)
            await asyncio.to_thread(
                runtime.store.upsert_execution_context,
                run_id,
                execution.evidence_context,
            )

            async def execute() -> object:
                record = await execution.run()
                if execution.fleet_result is not None:
                    runtime.fleet_results[run_id] = execution.fleet_result
                await runtime.recorder.flush()
                await asyncio.to_thread(
                    runtime.store.upsert_execution_context,
                    run_id,
                    execution.evidence_context,
                )
                with suppress(KeyError):
                    await asyncio.to_thread(
                        runtime.store.materialize_mission_execution,
                        run_id,
                    )
                return record

            task = asyncio.create_task(execute(), name=f"execution-{run_id}")
            runtime.track_mission_task(run_id, task)
            return {
                "mission_run_id": run_id,
                "execution_session_id": session_id,
                "status": "SCHEDULED",
                "member_count": len(plan.deployment.fleet),
                "mission_plan_id": mission_plan.plan_id,
            }

        return await mutate(
            request,
            context,
            action=(
                "start_mission_file_low_battery_override"
                if body.confirm_low_battery_risk
                else "start_mission_file"
            ),
            vehicle_id=requested_vehicle_id,
            operation=operation,
        )

    @router.delete("/mission-files/{mission_id}")
    async def archive_mission_file(
        mission_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            definition = runtime.missions.get(mission_id)
            if definition.source_kind != "UPLOADED_PYTHON":
                raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission is not an uploaded file")
            active = [
                run.mission_run_id
                for run in runtime.runner.list_runs()
                if run.mission_id == mission_id and run.result is None
            ]
            active.extend(
                execution.execution_run_id
                for execution in runtime.executions.values()
                if execution.mission_id == mission_id and not execution.terminal
            )
            if active:
                raise CrazySwarmError(
                    ErrorCode.INVALID_STATE,
                    "cannot archive an active mission artifact",
                    details={"mission_run_ids": active},
                )
            record = runtime.mission_files.archive(mission_id)
            return {
                "mission_id": record.mission_id,
                "source_sha256": record.source_sha256,
                "archived": True,
            }

        return await mutate(
            request,
            context,
            action="archive_mission_file",
            vehicle_id=runtime.selected_vehicle_id,
            operation=operation,
        )

    @router.get("/missions/{mission_id}")
    async def mission(mission_id: str) -> dict[str, Any]:
        return runtime.missions.metadata(mission_id).model_dump(mode="json")

    @router.post("/missions/{mission_id}/validate")
    async def validate_mission(
        mission_id: str,
        body: MissionValidationRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            validated = runtime.missions.validate_parameters(
                mission_id,
                body.parameters,
                preset=body.preset,
                overrides=body.overrides,
            )
            return {"valid": True, "parameters": validated.model_dump(mode="json")}

        return await mutate(
            request,
            context,
            action="validate_mission",
            vehicle_id=runtime.selected_vehicle_id,
            operation=operation,
        )

    @router.post("/missions/{mission_id}/preflight")
    async def mission_preflight(
        mission_id: str,
        body: MissionStartRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            runtime.missions.validate_parameters(
                mission_id,
                body.parameters,
                preset=body.preset,
                overrides=body.overrides,
            )
            mission_definition = runtime.missions.get(mission_id)
            report = await runtime.supervisor.preflight(
                body.vehicle_id,
                context.client_id,
                required_capabilities=mission_definition.required_capabilities
                | frozenset({VehicleCapability.ARMING}),
            )
            return report.model_dump(mode="json")

        return await mutate(
            request,
            context,
            action="mission_preflight",
            vehicle_id=body.vehicle_id,
            operation=operation,
        )

    @router.post("/missions/{mission_id}/start")
    async def start_mission(
        mission_id: str,
        body: MissionStartRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, str]:
            return await schedule_mission(
                mission_id,
                body.vehicle_id,
                context,
                parameters=body.parameters,
                preset=body.preset,
                overrides=body.overrides,
            )

        return await mutate(
            request,
            context,
            action="start_mission",
            vehicle_id=body.vehicle_id,
            operation=operation,
        )

    @router.post("/mission-runs/{run_id}/cancel")
    async def cancel_mission(
        run_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            session_id = runtime.execution_run_sessions.get(run_id)
            if session_id is not None:
                execution = runtime.executions[session_id]
                before = execution.record.status
                record = await execution.cancel()
                task = runtime.mission_tasks.get(run_id)
                if (
                    task is not None
                    and not task.done()
                    and before
                    in {
                        ExecutionStatus.SCHEDULED,
                        ExecutionStatus.PREPARING,
                        ExecutionStatus.READY,
                    }
                ):
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                return record.model_dump(mode="json")
            await asyncio.sleep(0)
            snapshot = await runtime.runner.cancel(run_id)
            return snapshot.model_dump(mode="json")

        vehicle_id = _mission_vehicle(runtime, run_id)
        return await mutate(
            request,
            context,
            action="cancel_mission",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    @router.get("/mission-runs/{run_id}")
    async def mission_status(run_id: str) -> dict[str, Any]:
        try:
            snapshot = runtime.runner.get_run(run_id)
            if snapshot.result is not None:
                # A terminal status is also the durability boundary exposed to the
                # UI: once it is visible, its manifest and CSV must already exist.
                task = runtime.mission_tasks.get(run_id)
                if task is not None and task is not asyncio.current_task():
                    await asyncio.shield(task)
                await runtime.recorder.flush()
            return snapshot.model_dump(mode="json")
        except CrazySwarmError:
            session_id = runtime.execution_run_sessions.get(run_id)
            if session_id is not None:
                record = runtime.executions[session_id].record
                if record.result is not None:
                    await runtime.recorder.flush()
                    task = runtime.mission_tasks.get(run_id)
                    if task is not None and task is not asyncio.current_task():
                        await asyncio.shield(task)
                    record = runtime.executions[session_id].record
                return {
                    "mission_run_id": run_id,
                    "execution_session_id": session_id,
                    "phase": record.status.value,
                    "result": record.result,
                    "execution": record.model_dump(mode="json"),
                }
            task = runtime.mission_tasks.get(run_id)
            if task is not None and not task.done():
                return {"mission_run_id": run_id, "phase": "SCHEDULED"}
            raise

    @router.get("/simulation/world")
    async def simulation_world() -> dict[str, Any]:
        return runtime.scenario.model_dump(mode="json")

    @router.get("/simulation/fidelity")
    async def simulation_fidelity() -> dict[str, Any]:
        return DEFAULT_FIDELITY_MANIFEST.model_dump(mode="json")

    @router.get("/simulation/contracts")
    async def simulation_contracts() -> dict[str, Any]:
        vehicle = _require_vehicle(runtime, runtime.selected_vehicle_id)
        return {
            "contract_version": ADAPTER_CONTRACT_VERSION,
            "frames": CANONICAL_FRAME_CONVENTION.model_dump(mode="json"),
            "vehicle_parameters": runtime.config.simulation.vehicle_parameters().model_dump(
                mode="json"
            ),
            "vehicle_parameters_sha256": runtime.config.simulation.vehicle_parameters().sha256,
            "signals": [
                item.model_dump(mode="json")
                for item in runtime.config.simulation.signal_specifications()
            ],
            "commands": [item.model_dump(mode="json") for item in COMMAND_SEMANTICS],
            "adapter": vehicle.contract_manifest.model_dump(mode="json"),
        }

    @router.get("/twins")
    async def twin_sessions() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in runtime.twins.list_sessions()]

    @router.post("/twins")
    async def create_twin_session(
        body: TwinSessionConfig,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            if body.test_only:
                raise CrazySwarmError(
                    ErrorCode.MODE_NOT_AUTHORIZED,
                    "test twin sessions are not available on operator routes",
                )
            observed = _require_vehicle(runtime, body.observed_vehicle_id)
            simulated = _require_vehicle(runtime, body.simulated_vehicle_id)
            sim_truth_session = (
                observed.backend_profile.authority is AuthorityClass.SIMULATION
                and body.observed_initial_state.source_class is TwinSourceClass.CONFIGURED
                and body.ground_truth_available
            )
            if (
                observed.backend_profile.authority is not AuthorityClass.PHYSICAL
                and not sim_truth_session
            ):
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    "observed twin side requires a real adapter or explicit Sim truth",
                )
            if simulated.backend_profile.authority is not AuthorityClass.SIMULATION:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    "the predicted twin side requires a simulator adapter",
                )
            return runtime.twins.create_session(body).model_dump(mode="json")

        return await mutate(
            request,
            context,
            action="create_twin_session",
            vehicle_id=body.observed_vehicle_id,
            operation=operation,
        )

    @router.get("/twins/calibrations/candidates")
    async def twin_calibration_candidates() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in runtime.twins.calibration_candidates()]

    @router.get("/twins/calibrations/reports")
    async def twin_calibration_reports() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in runtime.twins.calibration_reports()]

    @router.get("/twins/calibrations/active")
    async def active_twin_calibration() -> dict[str, str | None]:
        return {"calibration_id": runtime.twins.active_calibration_id()}

    @router.post("/twins/calibrations/candidates")
    async def create_twin_calibration_candidate(
        body: CalibrationCandidateRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            return runtime.twins.create_calibration_candidate(body).model_dump(mode="json")

        return await mutate(
            request,
            context,
            action="create_twin_calibration_candidate",
            vehicle_id=runtime.selected_vehicle_id,
            operation=operation,
        )

    @router.post("/twins/calibrations/{calibration_id}/promote")
    async def promote_twin_calibration(
        calibration_id: str,
        body: CalibrationPromotionAcceptance,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            return runtime.twins.promote_calibration(
                calibration_id,
                body,
            ).model_dump(mode="json")

        return await mutate(
            request,
            context,
            action="promote_twin_calibration",
            vehicle_id=runtime.selected_vehicle_id,
            operation=operation,
        )

    @router.get("/twins/curriculum")
    async def twin_curriculum() -> dict[str, Any]:
        return runtime.twins.curriculum().model_dump(mode="json")

    @router.post("/twins/curriculum/{stage_id}/runs", status_code=202)
    async def run_twin_curriculum_stage(
        stage_id: str,
        body: CampaignRunRequest,
        context: OperatorContext = Depends(operator_context),
    ) -> dict[str, Any]:
        stage = runtime.twins.curriculum_stage(stage_id)
        if stage.environment != "FAST_SIM":
            raise CrazySwarmError(
                ErrorCode.MODE_NOT_AUTHORIZED,
                "real-adapter curriculum execution remains literal NOT_RUN",
            )
        service = campaign_service()
        stage_request_id = f"twin-stage-{canonical_sha256([stage_id, context.request_id])[:24]}"
        existing_run_id = service.state.idempotency.get(stage_request_id)
        if existing_run_id is None:
            if stage.status is not TwinStageStatus.READY:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    "twin curriculum stage prerequisites are not ready",
                )

            async def execute_stage() -> None:
                try:
                    service.set_active(
                        stage.case_id,
                        actor_id=context.client_id,
                        reason=f"Run ready digital-twin curriculum stage {stage.stage_id}",
                    )
                    review = await service.run_active(
                        body.mode,
                        idempotency_key=stage_request_id,
                        submission_id=body.submission_id,
                        planning_submission_id=body.planning_submission_id,
                        comparison_context_id=body.comparison_context_id,
                        planning_capability_request=body.planning_capability_request,
                        execution_capability_request=body.execution_capability_request,
                        motion_preparation_request=body.motion_preparation,
                        coordination_preparation_request=body.coordination_preparation,
                    )
                    session_id = await retain_campaign_twin_evidence_off_loop(
                        runtime,
                        service,
                        review,
                        curriculum_stage_id=stage.stage_id,
                    )
                    if session_id is None:
                        return
                    runtime.twins.record_curriculum_result(
                        stage.stage_id,
                        TwinCurriculumResultRequest(
                            session_id=session_id,
                            status=(
                                TwinStageStatus.PASSED
                                if review.status is CampaignRunStatus.SUCCEEDED
                                else TwinStageStatus.FAILED
                            ),
                            result_sha256=canonical_sha256(
                                [stage.stage_id, review.review_sha256, session_id]
                            ),
                        ),
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    return

            task = asyncio.create_task(
                execute_stage(),
                name=f"twin-curriculum-{stage.stage_id}-{context.request_id}",
            )
            campaign_run_tasks.add(task)
            task.add_done_callback(campaign_run_tasks.discard)
            await asyncio.sleep(0)
            existing_run_id = service.state.idempotency.get(stage_request_id)
        if existing_run_id is None:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "TWIN_CURRICULUM_EXECUTION_FAILED",
                    "message": "twin curriculum run could not be queued",
                },
            )
        return {
            "accepted": True,
            "stage_id": stage.stage_id,
            "case_id": stage.case_id,
            "run_id": existing_run_id,
        }

    @router.post("/twins/physical-handoff/assess")
    async def physical_twin_handoff_assessment(
        body: PhysicalTwinHandoffRequest,
    ) -> dict[str, Any]:
        return assess_physical_twin_handoff(body).model_dump(mode="json")

    @router.post("/twins/curriculum/{stage_id}/results")
    async def record_twin_curriculum_result(
        stage_id: str,
        body: TwinCurriculumResultRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            return runtime.twins.record_curriculum_result(
                stage_id,
                body,
            ).model_dump(mode="json")

        return await mutate(
            request,
            context,
            action="record_twin_curriculum_result",
            vehicle_id=runtime.twins.session(body.session_id).observed_vehicle_id,
            operation=operation,
        )

    @router.get("/twins/{session_id}")
    async def twin_session(session_id: str) -> dict[str, Any]:
        return runtime.twins.session(session_id).model_dump(mode="json")

    @router.get("/twins/{session_id}/report")
    async def twin_report(session_id: str) -> dict[str, Any]:
        return runtime.twins.report(session_id).model_dump(mode="json")

    @router.get("/twins/{session_id}/timeline")
    async def twin_timeline(
        session_id: str,
        channels: str = "",
        after_source_s: float | None = None,
        limit: int = 4096,
    ) -> dict[str, Any]:
        channel_ids = tuple(value for value in channels.split(",") if value)
        return runtime.twins.timeline(
            session_id,
            channel_ids=channel_ids,
            after_source_s=after_source_s,
            limit=limit,
        ).model_dump(mode="json")

    @router.post("/twins/{session_id}/samples")
    async def ingest_twin_samples(
        session_id: str,
        body: TwinIngestionBatch,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            if body.session_id != session_id:
                raise CrazySwarmError(
                    ErrorCode.IDENTITY_MISMATCH,
                    "twin batch route and payload identities differ",
                )
            return runtime.twins.ingest(body).model_dump(mode="json")

        return await mutate(
            request,
            context,
            action="ingest_twin_samples",
            vehicle_id=runtime.twins.session(session_id).observed_vehicle_id,
            operation=operation,
        )

    @router.post("/simulation/fleet/reset-poses")
    async def reset_simulation_fleet(
        body: SimulationFleetResetRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            active_tasks = [
                *runtime.mission_tasks.values(),
                *runtime.fleet_tasks.values(),
            ]
            campaign_is_active = any(
                run.status in {CampaignRunStatus.QUEUED, CampaignRunStatus.RUNNING}
                for run in campaign_service().state.runs
            )
            if campaign_is_active or any(not task.done() for task in active_tasks):
                raise CrazySwarmError(
                    ErrorCode.INVALID_STATE,
                    "stop the active mission before resetting the simulation fleet",
                )
            target_ids = set(body.vehicle_ids)
            current_ids = runtime.active_vehicle_ids or set(runtime.vehicles)
            affected_ids = current_ids | target_ids
            for affected_id in sorted(affected_ids):
                vehicle = _require_vehicle(runtime, affected_id)
                if vehicle.backend_profile.role is not BackendRole.FAST_SIM:
                    raise CrazySwarmError(
                        ErrorCode.CAPABILITY_MISSING,
                        "simulation fleet reset requires Fast Sim vehicles",
                        details={"vehicle_id": affected_id},
                    )

            for affected_id in sorted(affected_ids):
                controls = runtime.vehicles[affected_id].simulation_controls
                if controls is None:
                    raise CrazySwarmError(
                        ErrorCode.CAPABILITY_MISSING,
                        "simulation pose controls are unavailable",
                        details={"vehicle_id": affected_id},
                    )
                await controls.reset_pose()
                await runtime.supervisor.reconcile_terminal_adapter_state(affected_id)
                if runtime.supervisor.session(affected_id).state is not VehicleState.DISCONNECTED:
                    await runtime.supervisor.disconnect(affected_id)

            runtime.active_vehicle_ids = target_ids
            if runtime.selected_vehicle_id not in target_ids:
                runtime.selected_vehicle_id = sorted(target_ids)[0]
            return {
                "vehicle_ids": sorted(target_ids),
                "reset_scope": ["active_fleet", "pose", "motion", "estimator_state"],
            }

        return await mutate(
            request,
            context,
            action="reset_simulation_fleet_poses",
            vehicle_id=sorted(body.vehicle_ids)[0],
            operation=operation,
        )

    @router.post("/simulation/vehicles/{vehicle_id}/clock")
    async def simulation_clock(
        vehicle_id: str,
        body: SimulationClockRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            vehicle = _require_vehicle(runtime, vehicle_id)
            controls = vehicle.simulation_controls
            if controls is None:
                raise CrazySwarmError(
                    ErrorCode.CAPABILITY_MISSING,
                    "simulation clock controls are unavailable",
                )
            session = runtime.supervisor.session(vehicle_id)
            state = session.state
            recovery_telemetry = None
            if (
                body.action is SimulationClockAction.RECHARGE
                and state is not VehicleState.DISCONNECTED
            ):
                recovery_snapshot = await vehicle.snapshot()
                if recovery_snapshot.vehicle_id != vehicle_id:
                    raise CrazySwarmError(
                        ErrorCode.IDENTITY_MISMATCH,
                        "simulation recharge snapshot identity mismatch",
                    )
                recovery_telemetry = recovery_snapshot.telemetry
            safe_recharge_recovery = (
                body.action is SimulationClockAction.RECHARGE
                and state
                in {
                    VehicleState.READY,
                    VehicleState.LANDING,
                    VehicleState.ABORTING,
                    VehicleState.FAULT,
                    VehicleState.EMERGENCY,
                }
                and recovery_telemetry is not None
                and recovery_telemetry.armed is False
                and recovery_telemetry.flying is False
            )
            if state is not VehicleState.DISCONNECTED and not safe_recharge_recovery:
                raise CrazySwarmError(
                    ErrorCode.INVALID_STATE,
                    "simulation clock controls require a disconnected vehicle",
                )
            if body.action is SimulationClockAction.PAUSE:
                controls.clock.pause()
            elif body.action is SimulationClockAction.RESUME:
                controls.clock.resume()
            elif body.action is SimulationClockAction.STEP:
                if not controls.clock.paused:
                    raise CrazySwarmError(
                        ErrorCode.INVALID_STATE,
                        "simulation single-step requires a paused clock",
                    )
                await controls.clock.single_step()
            elif body.action is SimulationClockAction.RESET:
                controls.reset()
            elif body.action is SimulationClockAction.RESET_POSE:
                await controls.reset_pose()
            elif body.action is SimulationClockAction.RECHARGE:
                await controls.set_battery_level(
                    100.0 if body.battery_percent is None else body.battery_percent
                )
            if safe_recharge_recovery:
                await runtime.supervisor.disconnect(vehicle_id)
            elif body.action in {
                SimulationClockAction.RESET,
                SimulationClockAction.RESET_POSE,
                SimulationClockAction.RECHARGE,
            }:
                runtime.supervisor.receive_telemetry(await controls.snapshot())
            result: dict[str, Any] = {
                "now_s": controls.clock.now_s,
                "paused": controls.clock.paused,
                "speed": controls.clock.speed,
            }
            if body.action is SimulationClockAction.RESET:
                result.update(
                    battery_percent=controls.battery_percent,
                    reset_scope=["clock", "pose", "battery", "model_state"],
                )
            elif body.action is SimulationClockAction.RESET_POSE:
                result.update(
                    position_m=controls.true_position_m.model_dump(mode="json"),
                    reset_scope=["pose", "motion", "estimator_state"],
                )
            elif body.action is SimulationClockAction.RECHARGE:
                result.update(
                    battery_percent=controls.battery_percent,
                    reset_scope=["battery"],
                )
            return result

        return await mutate(
            request,
            context,
            action=f"simulation_clock_{body.action.value}",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    @router.post("/simulation/vehicles/{vehicle_id}/faults")
    async def inject_fault(
        vehicle_id: str,
        body: FaultInjectionRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            vehicle = _require_vehicle(runtime, vehicle_id)
            controls = vehicle.simulation_controls
            if controls is None:
                raise CrazySwarmError(
                    ErrorCode.CAPABILITY_MISSING,
                    "simulation fault injection is unavailable",
                )
            controls.faults.inject(
                FaultWindow(fault=body.fault, start_s=body.start_s, end_s=body.end_s)
            )
            return {"faults": [item.model_dump(mode="json") for item in controls.faults.windows]}

        return await mutate(
            request,
            context,
            action="inject_simulation_fault",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    @router.get("/runs")
    async def runs(vehicle_id: str | None = None, limit: int = Query(100, ge=1, le=1000)) -> Any:
        rows = await asyncio.to_thread(
            runtime.store.list_runs,
            vehicle_id=vehicle_id,
            limit=limit,
        )
        return [_run_view(row) for row in rows]

    @router.get("/run-files")
    async def run_files(limit: int = Query(100, ge=1, le=1000)) -> Any:
        manifests = await asyncio.to_thread(
            runtime.store.list_run_file_missions,
            limit=limit,
        )
        return [_run_file_mission_view(manifest) for manifest in manifests]

    @router.delete("/run-files/{mission_execution_id}")
    async def delete_run_file_mission(
        mission_execution_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            try:
                return await asyncio.to_thread(
                    runtime.store.delete_run_file_mission,
                    mission_execution_id,
                )
            except IncompleteRunError as error:
                raise CrazySwarmError(
                    ErrorCode.INVALID_STATE,
                    "cannot delete a mission run file while it is being recorded",
                    details={"mission_execution_id": mission_execution_id},
                ) from error
            except KeyError as error:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    "mission run file not found",
                    details={"mission_execution_id": mission_execution_id},
                ) from error

        return await mutate(
            request,
            context,
            action="delete_run_file_mission",
            vehicle_id=mission_execution_id,
            operation=operation,
        )

    @router.get("/run-files/{mission_execution_id}/runs/{run_id}/telemetry.csv")
    async def persisted_telemetry_csv_export(
        mission_execution_id: str,
        run_id: str,
    ) -> FileResponse:
        try:
            artifact = await asyncio.to_thread(
                runtime.store.get_persisted_run_file,
                mission_execution_id,
                run_id,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "RUN_FILE_NOT_FOUND",
                    "message": f"persisted run file not found: {mission_execution_id}/{run_id}",
                },
            ) from error
        except IncompleteRunError as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "RUN_INCOMPLETE",
                    "message": f"run is still being recorded: {run_id}",
                },
            ) from error
        return FileResponse(
            artifact["path"],
            media_type="text/csv",
            filename=str(artifact["filename"]),
            headers={
                "ETag": f'"{artifact["sha256"]}"',
                "X-CrazySwarm-CSV-Schema": RUN_TELEMETRY_CSV_CONTRACT,
                "X-CrazySwarm-Row-Count": str(artifact["telemetry_row_count"]),
                "X-CrazySwarm-Content-SHA256": str(artifact["sha256"]),
            },
        )

    @router.get("/run-files/{mission_execution_id}/telemetry.csv")
    async def persisted_mission_telemetry_csv_export(
        mission_execution_id: str,
    ) -> FileResponse:
        try:
            artifact = await asyncio.to_thread(
                runtime.store.get_persisted_mission_file,
                mission_execution_id,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "MISSION_RUN_FILE_NOT_FOUND",
                    "message": f"persisted mission file not found: {mission_execution_id}",
                },
            ) from error
        return FileResponse(
            artifact["path"],
            media_type="text/csv",
            filename=str(artifact["filename"]),
            headers={
                "ETag": f'"{artifact["sha256"]}"',
                "X-CrazySwarm-CSV-Schema": RUN_TELEMETRY_CSV_CONTRACT,
                "X-CrazySwarm-Row-Count": str(artifact["telemetry_row_count"]),
                "X-CrazySwarm-Content-SHA256": str(artifact["sha256"]),
            },
        )

    @router.get("/run-files/{mission_execution_id}/evaluation")
    async def mission_execution_evaluation(mission_execution_id: str) -> dict[str, Any]:
        try:
            report = await asyncio.to_thread(
                runtime.store.evaluate_mission_execution,
                mission_execution_id,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "MISSION_EXECUTION_NOT_FOUND",
                    "message": f"mission execution not found: {mission_execution_id}",
                },
            ) from error
        return report.model_dump(mode="json")

    @router.get("/run-files/{mission_execution_id}/evaluation.json")
    async def persisted_mission_execution_evaluation(
        mission_execution_id: str,
    ) -> FileResponse:
        try:
            artifact = await asyncio.to_thread(
                runtime.store.get_persisted_execution_evaluation,
                mission_execution_id,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "MISSION_EXECUTION_EVALUATION_NOT_FOUND",
                    "message": f"mission evaluation not found: {mission_execution_id}",
                },
            ) from error
        return FileResponse(
            artifact["path"],
            media_type="application/json",
            filename=str(artifact["filename"]),
            headers={
                "ETag": f'"{artifact["sha256"]}"',
                "X-CrazySwarm-Content-SHA256": str(artifact["sha256"]),
                "X-CrazySwarm-Report-SHA256": str(artifact["report_sha256"]),
            },
        )

    @router.get("/run-files/{mission_execution_id}/execution-bundle.json")
    async def persisted_mission_execution_bundle(
        mission_execution_id: str,
    ) -> FileResponse:
        try:
            artifact = await asyncio.to_thread(
                runtime.store.get_persisted_execution_bundle,
                mission_execution_id,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "MISSION_EXECUTION_BUNDLE_NOT_FOUND",
                    "message": f"mission execution bundle not found: {mission_execution_id}",
                },
            ) from error
        return FileResponse(
            artifact["path"],
            media_type="application/json",
            filename=str(artifact["filename"]),
            headers={
                "ETag": f'"{artifact["sha256"]}"',
                "X-CrazySwarm-Content-SHA256": str(artifact["sha256"]),
                "X-CrazySwarm-Bundle-SHA256": str(artifact["bundle_sha256"]),
            },
        )

    @router.post("/run-files/{mission_execution_id}/annotations")
    async def annotate_mission_execution(
        mission_execution_id: str,
        body: ExecutionAnnotationRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            try:
                annotation = await asyncio.to_thread(
                    runtime.store.add_execution_annotation,
                    mission_execution_id,
                    annotation_id=f"annotation-{uuid.uuid4().hex}",
                    author_id=context.client_id,
                    note=body.note,
                )
            except KeyError as error:
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    f"mission execution not found: {mission_execution_id}",
                ) from error
            report = await asyncio.to_thread(
                runtime.store.evaluate_mission_execution,
                mission_execution_id,
            )
            return {
                "annotation": annotation,
                "evaluation": report.model_dump(mode="json"),
            }

        return await mutate(
            request,
            context,
            action="annotate_mission_execution",
            vehicle_id=mission_execution_id,
            operation=operation,
        )

    @router.get("/runs/{run_id}/events")
    async def run_events(
        run_id: str,
        kind: EvidenceKind | None = None,
        sensor: str | None = None,
        start_s: float | None = None,
        end_s: float | None = None,
        limit: int = Query(10_000, ge=1, le=50_000),
    ) -> list[dict[str, Any]]:
        events = await asyncio.to_thread(
            runtime.store.query_events,
            run_id=run_id,
            kind=kind,
            sensor=sensor,
            start_s=start_s,
            end_s=end_s,
            limit=limit,
        )
        return [event.model_dump(mode="json") for event in events]

    @router.get(
        "/runs/{run_id}/telemetry.csv",
        response_class=Response,
        responses={
            200: {
                "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
                "description": "Deterministic run telemetry CSV",
            }
        },
    )
    async def telemetry_csv_export(run_id: str) -> Response:
        try:
            artifact = await asyncio.to_thread(
                runtime.store.get_persisted_run_file_for_run,
                run_id,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail={"code": "RUN_NOT_FOUND", "message": f"run not found: {run_id}"},
            ) from error
        except IncompleteRunError as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "RUN_INCOMPLETE",
                    "message": f"run is still being recorded: {run_id}",
                },
            ) from error
        return FileResponse(
            artifact["path"],
            media_type="text/csv",
            filename=str(artifact["filename"]),
            headers={
                "ETag": f'"{artifact["sha256"]}"',
                "X-CrazySwarm-CSV-Schema": RUN_TELEMETRY_CSV_CONTRACT,
                "X-CrazySwarm-Row-Count": str(artifact["telemetry_row_count"]),
                "X-CrazySwarm-Content-SHA256": str(artifact["sha256"]),
            },
        )

    @router.get("/runs/{run_id}/diagnostic")
    async def diagnostic_export(run_id: str) -> FileResponse:
        destination = runtime.config.cache_directory / "exports" / f"{run_id}.zip"
        await asyncio.to_thread(runtime.store.export_bundle, run_id, destination)
        return FileResponse(destination, media_type="application/zip", filename=f"{run_id}.zip")

    @router.post("/replay/{run_id}/open")
    async def open_replay(
        run_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            events = await asyncio.to_thread(runtime.store.query_events, run_id=run_id)
            if not events:
                raise CrazySwarmError(ErrorCode.INVALID_COMMAND, f"run has no events: {run_id}")
            runtime.replays[run_id] = ReplayClock(events)
            return _replay_view(runtime.replays[run_id])

        run = await asyncio.to_thread(runtime.store.get_run, run_id)
        vehicle_id = str(run["vehicle_id"])
        return await mutate(
            request,
            context,
            action="open_replay",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    @router.post("/replay/{run_id}/control")
    async def control_replay(
        run_id: str,
        body: ReplayControlRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            try:
                clock = runtime.replays[run_id]
            except KeyError as error:
                raise CrazySwarmError(
                    ErrorCode.INVALID_STATE, "replay must be opened first"
                ) from error
            stepped = None
            if body.action is ReplayAction.PAUSE:
                clock.pause()
            elif body.action is ReplayAction.RESUME:
                clock.resume()
            elif body.action is ReplayAction.SEEK:
                clock.seek(_required_replay_value(body))
            elif body.action is ReplayAction.SPEED:
                clock.set_speed(_required_replay_value(body))
            elif body.action is ReplayAction.STEP:
                event = clock.step()
                stepped = None if event is None else event.model_dump(mode="json")
            return {**_replay_view(clock), "event": stepped}

        vehicle_id = str(runtime.store.get_run(run_id)["vehicle_id"])
        return await mutate(
            request,
            context,
            action=f"replay_{body.action.value}",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    app.include_router(router)

    @app.websocket("/api/v1/ws/events")
    async def event_socket(
        websocket: WebSocket,
        token: str = Query(...),
        client_id: str = Query(...),
        rate_hz: float = Query(20.0, gt=0.0, le=60.0),
    ) -> None:
        origin = websocket.headers.get("origin")
        if not authenticator.valid(token):
            await websocket.close(code=4401, reason="local authentication required")
            return
        if origin is not None and origin not in runtime.config.api.allowed_origins:
            await websocket.close(code=4403, reason="origin not allowed")
            return
        await websocket.accept()
        subscription = runtime.bus.subscribe(
            buffer_size=256,
            max_telemetry_rate_hz=rate_hz,
        )
        try:
            await websocket.send_json(
                {
                    "type": "connected",
                    "client_id": client_id,
                    "rate_hz": rate_hz,
                    "mode": runtime.supervisor.mode.value,
                }
            )
            async for event in subscription:
                if event.kind is EvidenceKind.TELEMETRY and event.run_id.startswith("system-"):
                    # Supervisor telemetry remains available internally for safety. The public
                    # observer feed only exposes simulated samples tied to an explicit mission.
                    continue
                clock_id = event.source
                clock_epoch = 0
                if isinstance(event.payload, TelemetryPayload):
                    clock_id = event.payload.telemetry.source_clock_id
                    clock_epoch = event.payload.telemetry.source_clock_epoch
                timing_correlation_id = (
                    timing_sample_correlation_id(
                        clock_id,
                        clock_epoch,
                        event.payload.telemetry.sequence,
                    )
                    if isinstance(event.payload, TelemetryPayload)
                    else event.event_id
                )
                campaign_timing.record(
                    correlation_id=timing_correlation_id,
                    stage=TimingStage.WEBSOCKET_ENQUEUE,
                    source_timestamp_s=event.source_timestamp_s,
                    source_clock_id=clock_id,
                    source_clock_epoch=clock_epoch,
                    observed_monotonic_s=time.monotonic(),
                    dropped_samples=subscription.dropped_events,
                )
                await websocket.send_json(
                    {
                        "type": "event",
                        "data": event.model_dump(mode="json"),
                        "timing_correlation_id": timing_correlation_id,
                        "dropped_events": subscription.dropped_events,
                    }
                )
                campaign_timing.record(
                    correlation_id=timing_correlation_id,
                    stage=TimingStage.WEBSOCKET_DELIVERY,
                    source_timestamp_s=event.source_timestamp_s,
                    source_clock_id=clock_id,
                    source_clock_epoch=clock_epoch,
                    observed_monotonic_s=time.monotonic(),
                    dropped_samples=subscription.dropped_events,
                )
        except WebSocketDisconnect:
            pass
        finally:
            subscription.close()

    return app


async def _compile_uploaded_mission_plan(
    runtime: ApplicationRuntime,
    definition: ScriptMission,
    vehicle_id: str,
) -> tuple[MissionDeploymentPlan, MissionPlanReceipt]:
    vehicle = _require_vehicle(runtime, vehicle_id)
    backend = {
        BackendRole.FAST_SIM: ExecutionBackend.FAST_SIM,
        BackendRole.ISAAC_SIM: ExecutionBackend.MOCK_ISAAC,
    }.get(vehicle.backend_profile.role)
    if backend is None:
        raise CrazySwarmError(
            ErrorCode.MODE_NOT_AUTHORIZED,
            "mission planning currently requires a software simulation backend",
        )
    implicit_home = next(
        (spawn.position_m for spawn in runtime.scenario.vehicles if spawn.vehicle_id == vehicle_id),
        Vector3(),
    )
    volume = runtime.supervisor.policy.flight_volume
    deployment_plan = plan_mission_deployment(
        definition.record,
        required_capabilities=definition.required_capabilities,
        backend=backend,
        implicit_vehicle_id=vehicle_id,
        implicit_display_name=vehicle.identity.display_name,
        implicit_home=implicit_home,
        implicit_backend_identifier=getattr(vehicle, "backend_namespace", None),
        world_minimum_m=volume.minimum_m,
        world_maximum_m=volume.maximum_m,
    )
    starts, batteries, existing_vehicle_ids = await _mission_planning_observations(
        runtime,
        deployment_plan.deployment,
    )
    mission_plan = await build_mission_plan(
        definition.record,
        deployment_plan.deployment,
        deployment_plan.assignments,
        runtime.supervisor.policy,
        start_positions=starts,
        observed_batteries=batteries,
        existing_vehicle_ids=existing_vehicle_ids,
        obstacles=_mission_planning_obstacles(runtime),
    )
    return deployment_plan, mission_plan


def _mission_plan_details(mission_plan: MissionPlanReceipt) -> dict[str, Any]:
    return {
        "mission_plan_id": mission_plan.plan_id,
        "mission_plan_sha256": mission_plan.sha256,
        "safety_case_sha256": mission_plan.planning.safety_case.safety_case_sha256,
        "status": mission_plan.status.value,
        "findings": [item.model_dump(mode="json") for item in mission_plan.findings],
    }


def _require_current_plan_approval(
    runtime: ApplicationRuntime,
    mission_plan: MissionPlanReceipt,
    *,
    approval_id: str | None,
    expected_plan_sha256: str | None,
    operator_client_id: str,
) -> MissionPlanApproval:
    if approval_id is None or expected_plan_sha256 is None:
        raise CrazySwarmError(
            ErrorCode.PREFLIGHT_FAILED,
            "Play requires approval of the exact current mission plan",
            details=_mission_plan_details(mission_plan),
        )
    if expected_plan_sha256 != mission_plan.sha256:
        raise CrazySwarmError(
            ErrorCode.PREFLIGHT_FAILED,
            "approved mission plan hash is stale",
            details={
                **_mission_plan_details(mission_plan),
                "expected_plan_sha256": expected_plan_sha256,
            },
        )
    approval = runtime.plan_approvals.get(approval_id)
    if approval is None:
        raise CrazySwarmError(
            ErrorCode.PREFLIGHT_FAILED,
            "mission plan approval is unknown or already consumed",
            details=_mission_plan_details(mission_plan),
        )
    mismatch_reasons = approval.mismatch_reasons(
        mission_plan,
        operator_client_id=operator_client_id,
        now_monotonic_s=time.monotonic(),
    )
    if mismatch_reasons:
        raise CrazySwarmError(
            ErrorCode.PREFLIGHT_FAILED,
            "mission plan approval is stale",
            details={
                **_mission_plan_details(mission_plan),
                "approval_id": approval_id,
                "mismatch_reasons": list(mismatch_reasons),
            },
        )
    return approval


async def _mission_planning_observations(
    runtime: ApplicationRuntime,
    deployment: DeploymentManifest,
) -> tuple[dict[str, Vector3], dict[str, float], frozenset[str]]:
    starts: dict[str, Vector3] = {}
    batteries: dict[str, float] = {}
    existing_vehicle_ids: set[str] = set()
    for member in deployment.fleet:
        vehicle = runtime.vehicles.get(member.vehicle_id)
        if vehicle is None:
            starts[member.vehicle_id] = member.home
            continue
        existing_vehicle_ids.add(member.vehicle_id)
        snapshot = await vehicle.snapshot()
        if snapshot.telemetry.position_m is not None:
            starts[member.vehicle_id] = snapshot.telemetry.position_m
        if snapshot.telemetry.battery_percent is not None:
            batteries[member.vehicle_id] = snapshot.telemetry.battery_percent
    return starts, batteries, frozenset(existing_vehicle_ids)


def _mission_planning_obstacles(
    runtime: ApplicationRuntime,
) -> tuple[PlanningObstacle, ...]:
    return tuple(
        PlanningObstacle(
            obstacle_id=obstacle.obstacle_id,
            minimum_m=obstacle.minimum_m,
            maximum_m=obstacle.maximum_m,
        )
        for obstacle in runtime.scenario.world.obstacles
    )


def _require_vehicle(runtime: ApplicationRuntime, vehicle_id: str) -> Any:
    try:
        return runtime.vehicles[vehicle_id]
    except KeyError as error:
        raise CrazySwarmError(
            ErrorCode.IDENTITY_MISMATCH, f"unknown vehicle: {vehicle_id}"
        ) from error


def _vehicle_view(runtime: ApplicationRuntime, vehicle_id: str) -> dict[str, Any]:
    vehicle = _require_vehicle(runtime, vehicle_id)
    session = runtime.supervisor.session(vehicle_id)
    run = runtime.latest_mission_for_vehicle(vehicle_id)
    telemetry = None
    field_provenance: dict[str, Any] = {}
    observation_status = "NOT_STARTED"
    observation_run_id: str | None = None
    if run is not None and session.telemetry is not None:
        telemetry = session.telemetry.model_dump(mode="json")
        # These internal fields describe the simulated command transport. Publishing them under
        # radio-like names would falsely imply that a Crazyradio measurement exists.
        payload = telemetry.get("telemetry", {})
        if isinstance(payload, dict):
            payload.pop("link_quality_percent", None)
            payload.pop("link_latency_ms", None)
            payload.pop("packet_loss_percent", None)
        field_provenance = _simulated_field_provenance(telemetry)
        observation_status = "ACTIVE" if run.result is None else "COMPLETED_SNAPSHOT"
        observation_run_id = run.mission_run_id
    elif session.telemetry is not None:
        for fleet_session_id, preparation in runtime.fleet_preparations.items():
            try:
                lifecycle = preparation.vehicle(vehicle_id)
            except CrazySwarmError:
                continue
            if lifecycle.latest_telemetry is not None and lifecycle.observation.value in {
                "CURRENT",
                "STALE",
            }:
                telemetry = lifecycle.latest_telemetry.model_dump(mode="json")
                field_provenance = _simulated_field_provenance(telemetry)
                observation_status = lifecycle.observation.value
                observation_run_id = fleet_session_id
                break
        if telemetry is None and vehicle.backend_profile.authority is AuthorityClass.SIMULATION:
            # An idle simulator snapshot is safe to expose as modeled state even though no
            # mission observation has started. Keep NOT_STARTED/run_id=None so it cannot be
            # mistaken for mission evidence.
            telemetry = session.telemetry.model_dump(mode="json")
            payload = telemetry.get("telemetry", {})
            if isinstance(payload, dict):
                payload.pop("link_quality_percent", None)
                payload.pop("link_latency_ms", None)
                payload.pop("packet_loss_percent", None)
            field_provenance = _simulated_field_provenance(telemetry)
    if telemetry is not None:
        source_clock_id = str(telemetry.get("source_clock_id", vehicle_id))
        source_clock_epoch = int(telemetry.get("source_clock_epoch", 0))
        sequence = int(telemetry.get("sequence", 0))
        telemetry["timing_correlation_id"] = timing_sample_correlation_id(
            source_clock_id,
            source_clock_epoch,
            sequence,
        )
    return {
        "identity": vehicle.identity.model_dump(mode="json"),
        "backend": vehicle.backend_profile.model_dump(mode="json"),
        "capabilities": vehicle.capabilities.model_dump(mode="json"),
        "state": session.state.value,
        "selected": runtime.selected_vehicle_id == vehicle_id,
        "telemetry": telemetry,
        "observation": {
            "status": observation_status,
            "source_class": (
                "SIMULATED_MODEL"
                if telemetry is not None
                and vehicle.backend_profile.authority is AuthorityClass.SIMULATION
                else ("MEASURED_REAL" if telemetry is not None else "UNAVAILABLE")
            ),
            "run_id": observation_run_id,
            "fidelity_manifest_id": DEFAULT_FIDELITY_MANIFEST.manifest_id,
            "physical_radio_available": False,
            "fields": field_provenance,
        },
        "control_lease": None if session.lease is None else session.lease.model_dump(mode="json"),
        "control_state": {
            "armed": None if session.telemetry is None else session.telemetry.telemetry.armed,
            "flying": None if session.telemetry is None else session.telemetry.telemetry.flying,
        },
    }


def _simulated_field_provenance(envelope: dict[str, Any]) -> dict[str, dict[str, Any]]:
    telemetry = envelope.get("telemetry")
    if not isinstance(telemetry, dict):
        return {}
    timestamp_s = envelope.get("source_timestamp_s")

    def record(unit: str, frame: str, *, valid: bool = True) -> dict[str, Any]:
        motors = telemetry.get("motors")
        model_version = str(motors.get("model_version")) if isinstance(motors, dict) else "1.0.0"
        return {
            "source_class": "SIMULATED_MODEL",
            "source": "crazyflie-6dof",
            "model": DEFAULT_FIDELITY_MANIFEST.model,
            "model_version": model_version,
            "fidelity_manifest_id": DEFAULT_FIDELITY_MANIFEST.manifest_id,
            "unit": unit,
            "frame": frame,
            "source_timestamp_s": timestamp_s,
            "valid": valid,
        }

    fields: dict[str, dict[str, Any]] = {}
    declared = {
        "position_m": ("m", str(telemetry.get("frame", "home"))),
        "ground_truth_position_m": ("m", "world"),
        "velocity_m_s": ("m/s", str(telemetry.get("frame", "home"))),
        "attitude": ("rad", "body"),
        "localization_quality_percent": ("percent", "home"),
        "battery_percent": ("percent", "vehicle"),
        "battery_voltage_v": ("V", "vehicle"),
        "battery_current_a": ("A", "vehicle"),
        "imu": ("m/s^2,rad/s", "body"),
        "flow": ("m,m/s", "body"),
        "ranges": ("m", "sensor"),
        "motors": ("percent,N,A", "body"),
        "transport": ("percent,ms", "transport"),
    }
    for name, (unit, frame) in declared.items():
        if telemetry.get(name) is not None:
            fields[name] = record(unit, frame)
    return fields


def _mission_vehicle(runtime: ApplicationRuntime, run_id: str) -> str:
    session_id = runtime.execution_run_sessions.get(run_id)
    if session_id is not None:
        assignments = runtime.executions[session_id].assignments
        if assignments:
            return next(iter(assignments.values()))
    try:
        return runtime.runner.get_run(run_id).vehicle_id
    except CrazySwarmError:
        return runtime.selected_vehicle_id


def _fleet_preparation(runtime: ApplicationRuntime, session_id: str) -> FleetPreparation:
    try:
        return runtime.fleet_preparations[session_id]
    except KeyError as error:
        raise CrazySwarmError(
            ErrorCode.IDENTITY_MISMATCH,
            f"unknown fleet execution session: {session_id}",
        ) from error


def _fleet_coordinator(runtime: ApplicationRuntime, fleet_run_id: str) -> FleetCoordinator:
    try:
        return runtime.fleet_coordinators[fleet_run_id]
    except KeyError as error:
        raise CrazySwarmError(
            ErrorCode.IDENTITY_MISMATCH,
            f"unknown fleet run: {fleet_run_id}",
        ) from error


def _fleet_session_view(
    runtime: ApplicationRuntime,
    session_id: str,
    *,
    compact: bool = False,
) -> dict[str, Any]:
    preparation = _fleet_preparation(runtime, session_id)
    coordinator = next(
        (
            item
            for item in runtime.fleet_coordinators.values()
            if item.identity.fleet_session_id == session_id
        ),
        None,
    )
    fleet_run_id = coordinator.identity.fleet_run_id if coordinator is not None else None
    result = runtime.fleet_results.get(fleet_run_id) if fleet_run_id is not None else None
    active = fleet_run_id is not None and fleet_run_id in runtime.fleet_tasks
    execution = runtime.executions.get(session_id)
    execution_record = execution.record if execution is not None and not compact else None
    execution_summary = execution.state_summary if execution is not None else None
    if execution_summary is not None:
        fleet_run_id = str(execution_summary["execution_run_id"])
    elif execution_record is not None:
        fleet_run_id = execution_record.execution_run_id
    if compact:
        result_summary = (
            {
                "status": result.status.value,
                "reason_code": result.reason_code,
                "message": result.message,
            }
            if result is not None
            else None
        )
        return {
            "session": preparation.state_summary,
            "deployment": preparation.deployment.model_dump(mode="json"),
            "binding": {
                "binding_id": preparation.binding.binding_id,
                "backend": preparation.binding.backend.value,
                "sha256": preparation.binding.sha256,
            },
            "fleet_run_id": fleet_run_id,
            "fleet_run_status": (
                str(execution_summary["status"])
                if execution_summary is not None
                else result.status.value
                if result is not None
                else "RUNNING"
                if active
                else "READY"
            ),
            "tasks": (
                [_task_state_summary(item) for item in coordinator.tasks.records()]
                if coordinator is not None
                else []
            ),
            "coordination": (coordinator.operator_summary() if coordinator is not None else None),
            "result": result_summary,
            "execution": execution_summary,
        }
    return {
        "session": preparation.record.model_dump(mode="json"),
        "deployment": preparation.deployment.model_dump(mode="json"),
        "binding": {
            "binding_id": preparation.binding.binding_id,
            "backend": preparation.binding.backend.value,
            "sha256": preparation.binding.sha256,
        },
        "fleet_run_id": fleet_run_id,
        "fleet_run_status": (
            execution_record.status.value
            if execution_record is not None
            else result.status.value
            if result is not None
            else "RUNNING"
            if active
            else "READY"
        ),
        "tasks": (
            [item.model_dump(mode="json") for item in coordinator.tasks.records()]
            if coordinator is not None
            else []
        ),
        "coordination": coordinator.operator_summary() if coordinator is not None else None,
        "result": result.model_dump(mode="json") if result is not None else None,
        "execution": (
            execution_record.model_dump(mode="json") if execution_record is not None else None
        ),
    }


def _live_state_session_ids(runtime: ApplicationRuntime) -> tuple[str, ...]:
    records = [
        (session_id, preparation.created_at_monotonic_s)
        for session_id, preparation in runtime.fleet_preparations.items()
    ]
    records.sort(key=lambda item: (item[1], item[0]))
    recent = records[-LIVE_STATE_HISTORY_LIMIT:]
    active_ids = {
        session_id for session_id, execution in runtime.executions.items() if not execution.terminal
    }
    selected = {session_id for session_id, _ in recent} | active_ids
    return tuple(session_id for session_id, _ in records if session_id in selected)


def _live_state_mission_runs(runtime: ApplicationRuntime) -> tuple[Any, ...]:
    runs = sorted(
        runtime.runner.list_runs(),
        key=lambda item: (item.started_at_monotonic_s, item.mission_run_id),
    )
    recent = runs[-LIVE_STATE_HISTORY_LIMIT:]
    active_ids = {item.mission_run_id for item in runs if item.result is None}
    selected = {item.mission_run_id for item in recent} | active_ids
    return tuple(item for item in runs if item.mission_run_id in selected)


def _mission_run_state_summary(item: Any) -> dict[str, Any]:
    result = item.result
    return {
        "mission_run_id": item.mission_run_id,
        "mission_id": item.mission_id,
        "vehicle_id": item.vehicle_id,
        "phase": item.phase.value,
        "parameters": item.parameters,
        "started_at_monotonic_s": item.started_at_monotonic_s,
        "cancellation_requested": item.cancellation_requested,
        "result": (
            {
                "status": result.status.value,
                "reason_code": result.reason_code,
                "message": result.message,
            }
            if result is not None
            else None
        ),
    }


def _task_state_summary(record: Any) -> dict[str, Any]:
    return {
        "definition": record.definition.model_dump(mode="json"),
        "state": record.state.value,
        "owner_vehicle_id": record.owner_vehicle_id,
        "lease_generation": record.lease_generation,
        "progress_percent": record.progress_percent,
        "attempts": record.attempts,
        "decision": record.decision.value if record.decision is not None else None,
        "terminal_reason": record.terminal_reason,
        "child_mission_run_id": record.child_mission_run_id,
    }


def _run_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in {"snapshot_json", "result_json", "telemetry_row_count"}
    } | {
        "snapshot": _json_or_none(row.get("snapshot_json")),
        "result": _json_or_none(row.get("result_json")),
        "artifacts": [_telemetry_csv_artifact_view(row)],
    }


def _run_file_mission_view(manifest: dict[str, Any]) -> dict[str, Any]:
    execution_id = str(manifest["mission_execution_id"])
    raw_artifact = manifest.get("artifact")
    artifact = raw_artifact if isinstance(raw_artifact, dict) else {}
    filename = artifact.get("filename")
    raw_evaluation = manifest.get("evaluation")
    evaluation = raw_evaluation if isinstance(raw_evaluation, dict) else {}
    raw_bundle = manifest.get("bundle")
    bundle = raw_bundle if isinstance(raw_bundle, dict) else {}
    return {key: value for key, value in manifest.items() if not key.startswith("_")} | {
        "artifact": {
            **artifact,
            "available": isinstance(filename, str) and bool(filename),
            "download_url": (
                f"/api/v1/run-files/{quote(execution_id, safe='')}/telemetry.csv"
                if isinstance(filename, str) and filename
                else None
            ),
        },
        "evaluation": {
            **evaluation,
            "available": bool(evaluation.get("filename")),
            "download_url": (
                f"/api/v1/run-files/{quote(execution_id, safe='')}/evaluation.json"
                if evaluation.get("filename")
                else None
            ),
        },
        "bundle": {
            **bundle,
            "available": bool(bundle.get("filename")),
            "download_url": (
                f"/api/v1/run-files/{quote(execution_id, safe='')}/execution-bundle.json"
                if bundle.get("filename")
                else None
            ),
        },
    }


def _telemetry_csv_artifact_view(row: dict[str, Any]) -> dict[str, Any]:
    execution_id = str(row.get("mission_execution_id") or row["run_id"])
    available = row.get("status") is not None
    return {
        "kind": "TELEMETRY_CSV",
        "filename": mission_telemetry_csv_filename(row),
        "media_type": "text/csv",
        "schema_version": RUN_TELEMETRY_CSV_CONTRACT,
        "download_url": (f"/api/v1/run-files/{quote(execution_id, safe='')}/telemetry.csv"),
        "available": available,
        "unavailable_reason": None if available else "RUN_INCOMPLETE",
        "row_count": int(row.get("telemetry_row_count", 0)),
    }


def _json_or_none(value: object) -> Any:
    if value is None:
        return None
    import json

    return json.loads(str(value))


def _campaign_qualification_payload() -> dict[str, Any]:
    return _qualification_payload(
        Path("missions/campaigns/sim/qualification/catalog-static-qualification-v2.json")
    )


def _qualification_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise HTTPException(status_code=404, detail="campaign qualification is unavailable")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HTTPException(status_code=500, detail="campaign qualification is invalid")
    return value


def _replay_view(clock: ReplayClock) -> dict[str, Any]:
    return {
        "index": clock.index,
        "event_count": len(clock.events),
        "now_s": clock.now_s,
        "paused": clock.paused,
        "speed": clock.speed,
    }


def _required_replay_value(body: ReplayControlRequest) -> float:
    if body.value is None:
        raise CrazySwarmError(
            ErrorCode.INVALID_COMMAND,
            f"replay action {body.action.value} requires value",
        )
    return body.value


def _error_response(
    status: int,
    code: str,
    message: str,
    *,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
                "details": details or {},
            }
        },
    )
