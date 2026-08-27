from __future__ import annotations

import fcntl
import json
import os
import socket
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

HARDWARE_ENABLED_ENV = "CRAZYSWARM_PHYSICAL_HARDWARE_ENABLED"
HARDWARE_OWNER_ENV = "CRAZYSWARM_HARDWARE_OWNER"
HARDWARE_LOCK_PATH_ENV = "CRAZYSWARM_HARDWARE_LOCK_PATH"
PHYSICAL_OPERATION_GATE_FILENAME = "physical-operation-admission.lock"


def default_hardware_lock_path() -> Path:
    """Return one per-user lease shared by every checkout and worktree."""

    override = os.environ.get(HARDWARE_LOCK_PATH_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".cache" / "crazyswarm" / "hardware-runtime.lock"


@dataclass(frozen=True, slots=True)
class HardwareRuntimeOwner:
    owner: str
    pid: int
    hostname: str
    checkout: str
    acquired_at_utc: str

    @classmethod
    def from_mapping(cls, value: object) -> HardwareRuntimeOwner | None:
        if not isinstance(value, dict):
            return None
        try:
            return cls(
                owner=str(value["owner"]),
                pid=int(value["pid"]),
                hostname=str(value["hostname"]),
                checkout=str(value["checkout"]),
                acquired_at_utc=str(value["acquired_at_utc"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


class HardwareRuntimeBusy(RuntimeError):
    def __init__(self, owner: HardwareRuntimeOwner | None) -> None:
        detail = "another process"
        if owner is not None:
            detail = f"{owner.owner} (pid {owner.pid}, checkout {owner.checkout})"
        super().__init__(
            "Crazyradio hardware runtime is already owned by "
            f"{detail}; use an isolated simulation runtime or stop the owner explicitly"
        )
        self.owner = owner


class PhysicalOperationAdmissionBusy(RuntimeError):
    """Raised when deployment and a physical-operation admission overlap."""

    def __init__(self, *, deployment: bool) -> None:
        message = (
            "operator dashboard deployment is in progress; physical actions are temporarily blocked"
            if not deployment
            else "a physical action is being admitted; dashboard deployment is temporarily blocked"
        )
        super().__init__(message)
        self.deployment = deployment


class HardwareRuntimeLease:
    """Process-lifetime, crash-releasing ownership of the physical Crazyradio runtime."""

    def __init__(
        self,
        owner: str,
        *,
        path: Path | None = None,
        checkout: Path | None = None,
    ) -> None:
        normalized = owner.strip()
        if not normalized:
            raise ValueError("hardware runtime owner must not be empty")
        self.owner = normalized
        self.path = (path or default_hardware_lock_path()).expanduser().resolve()
        self.checkout = (checkout or Path.cwd()).resolve()
        self._file: IO[str] | None = None

    def acquire(self) -> HardwareRuntimeOwner:
        if self._file is not None:
            raise RuntimeError("hardware runtime lease is already acquired")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            handle.seek(0)
            owner = _decode_owner(handle.read())
            handle.close()
            raise HardwareRuntimeBusy(owner) from error
        owner = HardwareRuntimeOwner(
            owner=self.owner,
            pid=os.getpid(),
            hostname=socket.gethostname(),
            checkout=str(self.checkout),
            acquired_at_utc=datetime.now(UTC).isoformat(),
        )
        handle.seek(0)
        handle.truncate()
        json.dump(asdict(owner), handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        self._file = handle
        return owner

    def release(self) -> None:
        handle = self._file
        if handle is None:
            return
        try:
            handle.seek(0)
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._file = None

    def __enter__(self) -> HardwareRuntimeLease:
        self.acquire()
        return self

    def __exit__(self, *_error: object) -> None:
        self.release()


_ACTIVE_LEASE: HardwareRuntimeLease | None = None


@contextmanager
def claim_hardware_runtime(
    owner: str,
    *,
    path: Path | None = None,
    checkout: Path | None = None,
) -> Iterator[HardwareRuntimeOwner]:
    global _ACTIVE_LEASE
    if _ACTIVE_LEASE is not None:
        raise RuntimeError("this process already owns the hardware runtime")
    lease = HardwareRuntimeLease(owner, path=path, checkout=checkout)
    acquired = lease.acquire()
    _ACTIVE_LEASE = lease
    previous_enabled = os.environ.get(HARDWARE_ENABLED_ENV)
    previous_owner = os.environ.get(HARDWARE_OWNER_ENV)
    os.environ[HARDWARE_ENABLED_ENV] = "1"
    os.environ[HARDWARE_OWNER_ENV] = owner
    try:
        yield acquired
    finally:
        if previous_enabled is None:
            os.environ.pop(HARDWARE_ENABLED_ENV, None)
        else:
            os.environ[HARDWARE_ENABLED_ENV] = previous_enabled
        if previous_owner is None:
            os.environ.pop(HARDWARE_OWNER_ENV, None)
        else:
            os.environ[HARDWARE_OWNER_ENV] = previous_owner
        _ACTIVE_LEASE = None
        lease.release()


def hardware_runtime_owned() -> bool:
    return _ACTIVE_LEASE is not None and os.environ.get(HARDWARE_ENABLED_ENV) == "1"


def require_hardware_runtime() -> None:
    if hardware_runtime_owned():
        return
    raise RuntimeError(
        "physical Crazyradio access is disabled in this process; use the operator-owned "
        "dashboard service instead of starting hardware from a coding task"
    )


def physical_operation_gate_path(cache_directory: Path) -> Path:
    return cache_directory.expanduser().resolve() / PHYSICAL_OPERATION_GATE_FILENAME


@contextmanager
def claim_physical_operation_admission(cache_directory: Path) -> Iterator[None]:
    """Hold shared admission while one API request makes physical work durable.

    Deployment takes the exclusive side of this gate before checking live actuation
    and flight state. A physical start that entered first therefore becomes visible
    to that check; a deployment that entered first blocks the start before the
    observer releases the radio.
    """

    with _claim_physical_operation_gate(cache_directory, exclusive=False):
        yield


@contextmanager
def claim_hardware_deployment(cache_directory: Path) -> Iterator[None]:
    """Exclude new physical-operation admissions for one dashboard replacement."""

    with _claim_physical_operation_gate(cache_directory, exclusive=True):
        yield


@contextmanager
def _claim_physical_operation_gate(
    cache_directory: Path,
    *,
    exclusive: bool,
) -> Iterator[None]:
    path = physical_operation_gate_path(cache_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    try:
        try:
            fcntl.flock(handle.fileno(), operation | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise PhysicalOperationAdmissionBusy(deployment=exclusive) from error
        yield
    finally:
        with suppress(OSError):
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def read_hardware_runtime_owner(path: Path | None = None) -> HardwareRuntimeOwner | None:
    target = (path or default_hardware_lock_path()).expanduser().resolve()
    try:
        handle = target.open("a+", encoding="utf-8")
    except OSError:
        return None
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.seek(0)
            return _decode_owner(handle.read())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return None
    finally:
        handle.close()


def _decode_owner(raw: str) -> HardwareRuntimeOwner | None:
    try:
        return HardwareRuntimeOwner.from_mapping(json.loads(raw))
    except json.JSONDecodeError:
        return None
