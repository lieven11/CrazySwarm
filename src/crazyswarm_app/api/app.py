from __future__ import annotations

import asyncio
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.websockets import WebSocketDisconnect

from crazyswarm_app import __version__
from crazyswarm_app.api.models import (
    ArmRequest,
    DurationRequest,
    FaultInjectionRequest,
    MissionExecutionMode,
    MissionFileStartRequest,
    MissionFileUploadRequest,
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
    TakeoffRequest,
)
from crazyswarm_app.api.runtime import ApplicationRuntime
from crazyswarm_app.api.security import (
    IdempotencyStore,
    LocalAuthenticator,
    mutation_fingerprint,
    operator_context,
)
from crazyswarm_app.domain.commands import MoveRelativeCommand
from crazyswarm_app.domain.errors import CrazySwarmError, ErrorCode
from crazyswarm_app.domain.models import OperatingMode, VehicleCapability, VehicleState
from crazyswarm_app.domain.simulation import (
    ADAPTER_CONTRACT_VERSION,
    CANONICAL_FRAME_CONVENTION,
    COMMAND_SEMANTICS,
)
from crazyswarm_app.observability.events import EvidenceKind
from crazyswarm_app.observability.replay import ReplayClock
from crazyswarm_app.safety.models import LiveModeAuthorization
from crazyswarm_app.simulation.faults import FaultWindow
from crazyswarm_app.simulation.models import DEFAULT_FIDELITY_MANIFEST
from crazyswarm_app.twin.models import TwinSessionConfig


def generate_local_token() -> str:
    return secrets.token_urlsafe(32)


def create_app(
    runtime: ApplicationRuntime,
    *,
    local_token: str,
    manage_runtime: bool = True,
) -> FastAPI:
    authenticator = LocalAuthenticator(local_token)
    idempotency = IdempotencyStore()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if manage_runtime:
            await runtime.start()
        try:
            yield
        finally:
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime.config.api.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
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

    async def mutate(
        request: Request,
        context: OperatorContext,
        *,
        action: str,
        vehicle_id: str,
        operation: Callable[[], Awaitable[Any]],
    ) -> Any:
        fingerprint = await mutation_fingerprint(request)

        async def audited_operation() -> Any:
            runtime.bridge.operator_action(
                vehicle_id=vehicle_id,
                client_id=context.client_id,
                request_id=context.request_id,
                action=action,
            )
            return await operation()

        response, _ = await idempotency.execute(context, fingerprint, audited_operation)
        return response

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

    @router.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "mode": runtime.supervisor.mode,
            "local_only": True,
            "recorder": {
                "persisted_events": runtime.recorder.persisted_events,
                "bus": runtime.bus.stats.model_dump(mode="json"),
            },
        }

    @router.get("/state")
    async def application_state() -> dict[str, Any]:
        return {
            "mode": runtime.supervisor.mode,
            "selected_vehicle_id": runtime.selected_vehicle_id,
            "configured_flight_volume": runtime.supervisor.policy.flight_volume.model_dump(
                mode="json"
            ),
            "vehicles": [_vehicle_view(runtime, vehicle_id) for vehicle_id in runtime.vehicles],
            "mission_runs": [item.model_dump(mode="json") for item in runtime.runner.list_runs()],
        }

    @router.get("/capabilities")
    async def capabilities() -> dict[str, Any]:
        return {
            "modes": [item.value for item in OperatingMode],
            "missions": [item.model_dump(mode="json") for item in runtime.missions.list_metadata()],
            "simulation": True,
            "replay": True,
            "real_adapter": False,
        }

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

    @router.post("/mission-files/{mission_id}/start")
    async def start_mission_file(
        mission_id: str,
        body: MissionFileStartRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, str]:
            definition = runtime.missions.get(mission_id)
            if definition.source_kind != "UPLOADED_PYTHON":
                raise CrazySwarmError(ErrorCode.INVALID_COMMAND, "mission is not an uploaded file")
            vehicle = _require_vehicle(runtime, body.vehicle_id)
            if body.execution_mode is MissionExecutionMode.TWIN:
                raise CrazySwarmError(
                    ErrorCode.MODE_NOT_AUTHORIZED,
                    "digital twin requires a qualified real vehicle adapter",
                )
            if vehicle.identity.adapter != "sim":
                raise CrazySwarmError(
                    ErrorCode.MODE_NOT_AUTHORIZED,
                    "simulation mode requires a simulator vehicle",
                )
            runtime.supervisor.set_mode(OperatingMode.SIM)
            return await schedule_mission(mission_id, body.vehicle_id, context)

        return await mutate(
            request,
            context,
            action="start_mission_file",
            vehicle_id=body.vehicle_id,
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
            task = runtime.mission_tasks.get(run_id)
            if task is None:
                raise CrazySwarmError(ErrorCode.INVALID_COMMAND, f"unknown mission run: {run_id}")
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
            return runtime.runner.get_run(run_id).model_dump(mode="json")
        except CrazySwarmError:
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
            if observed.identity.adapter == "sim":
                raise CrazySwarmError(
                    ErrorCode.INVALID_COMMAND,
                    "the observed twin side requires a real adapter",
                )
            if simulated.identity.adapter != "sim":
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

    @router.get("/twins/{session_id}")
    async def twin_session(session_id: str) -> dict[str, Any]:
        return runtime.twins.session(session_id).model_dump(mode="json")

    @router.get("/twins/{session_id}/report")
    async def twin_report(session_id: str) -> dict[str, Any]:
        return runtime.twins.report(session_id).model_dump(mode="json")

    @router.post("/simulation/vehicles/{vehicle_id}/clock")
    async def simulation_clock(
        vehicle_id: str,
        body: SimulationClockRequest,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            vehicle = _require_vehicle(runtime, vehicle_id)
            state = runtime.supervisor.session(vehicle_id).state
            if state is not VehicleState.DISCONNECTED:
                raise CrazySwarmError(
                    ErrorCode.INVALID_STATE,
                    "simulation clock controls require a disconnected vehicle",
                )
            if body.action is SimulationClockAction.PAUSE:
                vehicle.clock.pause()
            elif body.action is SimulationClockAction.RESUME:
                vehicle.clock.resume()
            elif body.action is SimulationClockAction.STEP:
                if not vehicle.clock.paused:
                    raise CrazySwarmError(
                        ErrorCode.INVALID_STATE,
                        "simulation single-step requires a paused clock",
                    )
                await vehicle.clock.single_step()
            elif body.action is SimulationClockAction.RESET:
                vehicle.reset()
            result: dict[str, Any] = {
                "now_s": vehicle.clock.now_s,
                "paused": vehicle.clock.paused,
                "speed": vehicle.clock.speed,
            }
            if body.action is SimulationClockAction.RESET:
                result.update(
                    battery_percent=vehicle.battery_percent,
                    reset_scope=["clock", "pose", "battery", "model_state"],
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
            vehicle.faults.inject(
                FaultWindow(fault=body.fault, start_s=body.start_s, end_s=body.end_s)
            )
            return {"faults": [item.model_dump(mode="json") for item in vehicle.faults.windows]}

        return await mutate(
            request,
            context,
            action="inject_simulation_fault",
            vehicle_id=vehicle_id,
            operation=operation,
        )

    @router.get("/runs")
    async def runs(vehicle_id: str | None = None, limit: int = Query(100, ge=1, le=1000)) -> Any:
        return [
            _run_view(row) for row in runtime.store.list_runs(vehicle_id=vehicle_id, limit=limit)
        ]

    @router.get("/runs/{run_id}/events")
    async def run_events(
        run_id: str,
        kind: EvidenceKind | None = None,
        sensor: str | None = None,
        start_s: float | None = None,
        end_s: float | None = None,
        limit: int = Query(10_000, ge=1, le=50_000),
    ) -> list[dict[str, Any]]:
        return [
            event.model_dump(mode="json")
            for event in runtime.store.query_events(
                run_id=run_id,
                kind=kind,
                sensor=sensor,
                start_s=start_s,
                end_s=end_s,
                limit=limit,
            )
        ]

    @router.get("/runs/{run_id}/diagnostic")
    async def diagnostic_export(run_id: str) -> FileResponse:
        destination = runtime.config.cache_directory / "exports" / f"{run_id}.zip"
        runtime.store.export_bundle(run_id, destination)
        return FileResponse(destination, media_type="application/zip", filename=f"{run_id}.zip")

    @router.post("/replay/{run_id}/open")
    async def open_replay(
        run_id: str,
        request: Request,
        context: OperatorContext = Depends(operator_context),
    ) -> Any:
        async def operation() -> dict[str, Any]:
            events = runtime.store.query_events(run_id=run_id)
            if not events:
                raise CrazySwarmError(ErrorCode.INVALID_COMMAND, f"run has no events: {run_id}")
            runtime.replays[run_id] = ReplayClock(events)
            return _replay_view(runtime.replays[run_id])

        vehicle_id = str(runtime.store.get_run(run_id)["vehicle_id"])
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
                await websocket.send_json(
                    {
                        "type": "event",
                        "data": event.model_dump(mode="json"),
                        "dropped_events": subscription.dropped_events,
                    }
                )
        except WebSocketDisconnect:
            pass
        finally:
            subscription.close()

    return app


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
    return {
        "identity": vehicle.identity.model_dump(mode="json"),
        "capabilities": vehicle.capabilities.model_dump(mode="json"),
        "state": session.state.value,
        "selected": runtime.selected_vehicle_id == vehicle_id,
        "telemetry": telemetry,
        "observation": {
            "status": observation_status,
            "source_class": "SIMULATED_MODEL" if telemetry is not None else "UNAVAILABLE",
            "run_id": None if run is None else run.mission_run_id,
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
    try:
        return runtime.runner.get_run(run_id).vehicle_id
    except CrazySwarmError:
        return runtime.selected_vehicle_id


def _run_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in row.items() if key not in {"snapshot_json", "result_json"}
    } | {
        "snapshot": _json_or_none(row.get("snapshot_json")),
        "result": _json_or_none(row.get("result_json")),
    }


def _json_or_none(value: object) -> Any:
    if value is None:
        return None
    import json

    return json.loads(str(value))


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
