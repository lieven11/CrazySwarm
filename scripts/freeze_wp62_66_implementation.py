#!/usr/bin/env python3
"""Freeze the exact WP-62 through WP-66 implementation review payload."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(
    "missions/campaigns/sim/qualification/"
    "wp62-66-implementation-manifest-v1.json"
)
ACTIVE = Path("docs/work-packages/ACTIVE.md")
SECTION_BEGIN = "<!-- WP62-66-IMPLEMENTATION-PAYLOAD-BEGIN -->"
SECTION_END = "<!-- WP62-66-IMPLEMENTATION-PAYLOAD-END -->"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(*arguments: str) -> bytes:
    return subprocess.run(
        ("git", *arguments),
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


def _changed_paths() -> tuple[tuple[str, str], ...]:
    records = _git(
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=no",
    ).split(b"\0")
    output: list[tuple[str, str]] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        status = record[:2].decode("ascii")
        path = record[3:].decode("utf-8")
        if "R" in status or "C" in status:
            if index >= len(records) or not records[index]:
                raise RuntimeError("git status rename/copy record is incomplete")
            path = records[index].decode("utf-8")
            index += 1
        if path == OUTPUT.as_posix():
            continue
        output.append((status, path))
    output.extend(
        ("??", path.decode("utf-8"))
        for path in _git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
        if path
        and path.decode("utf-8") != OUTPUT.as_posix()
    )
    return tuple(sorted(output, key=lambda item: item[1]))


def _git_preimage(path: str) -> bytes | None:
    result = subprocess.run(
        ("git", "show", f"HEAD:{path}"),
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    return result.stdout if result.returncode == 0 else None


def _section_bytes() -> bytes:
    text = (ROOT / ACTIVE).read_text()
    if text.count(SECTION_BEGIN) != 1 or text.count(SECTION_END) != 1:
        raise RuntimeError("implementation payload delimiters must occur exactly once")
    start = text.index(SECTION_BEGIN)
    end = text.index(SECTION_END, start) + len(SECTION_END)
    return text[start:end].encode()


def _entry(status: str, path: str) -> dict[str, Any]:
    preimage = _git_preimage(path)
    disk_path = ROOT / path
    postimage = disk_path.read_bytes() if disk_path.is_file() else None
    if preimage is None and postimage is None:
        raise RuntimeError(f"changed path has neither preimage nor postimage: {path}")
    change_kind = (
        "NEW"
        if preimage is None
        else "DELETED"
        if postimage is None
        else "MODIFIED"
    )
    return {
        "path": path,
        "git_status": status,
        "change_kind": change_kind,
        "preimage_sha256": _sha256(preimage) if preimage is not None else None,
        "postimage_sha256": _sha256(postimage) if postimage is not None else None,
        "postimage_size_bytes": len(postimage) if postimage is not None else None,
    }


def build_payload() -> dict[str, Any]:
    files = tuple(
        _entry(status, path)
        for status, path in _changed_paths()
        if path != ACTIVE.as_posix()
    )
    section = _section_bytes()
    payload: dict[str, Any] = {
        "schema_version": 1,
        "manifest_id": "wp62-66-implementation-manifest-v1",
        "review_unit": "WP-62-through-WP-66",
        "base_commit": _git("rev-parse", "HEAD").decode().strip(),
        "accepted_design_payload_sha256s": {
            "base": "52570fcfcef8c7e5d62f79eb8c111522c236fe2a590500bcf086092bbc5e43c6",
            "r2": "4201ea8a858e1d91b3f5877bdfacbd4716b5fa59b42cac9ac9d796cf38477806",
            "r3": "5c24eb560133232cf5fb9e7a5105a727083f78854f07cba85c86c2d5ee6c3b5d",
            "r4": "34d6640165a86a86ad741fbc16202f4f4ec22fe6a06f18de701bec6900a99a1b",
        },
        "files": files,
        "delimited_sections": (
            {
                "path": ACTIVE.as_posix(),
                "begin_marker": SECTION_BEGIN,
                "end_marker": SECTION_END,
                "preimage_sha256": None,
                "postimage_sha256": _sha256(section),
                "postimage_size_bytes": len(section),
            },
        ),
        "envelope_exclusions": (
            {
                "path": OUTPUT.as_posix(),
                "reason": (
                    "This generated manifest is the identity envelope and cannot "
                    "self-hash; its file SHA-256 is recorded in the review handoff."
                ),
            },
        ),
        "declared_checks": (
            "scripts/qualify_wp62_66_runtime.py: PASS",
            "packet-focused backend suite: 170 PASS",
            "broader compatibility suite: 172 PASS; 2 documented out-of-scope "
            "legacy failures",
            "focused Ruff: PASS",
            "targeted Mypy: PASS",
            "UI ESLint/TypeScript/13-file 133-test Vitest/build/3 rendered HTML: PASS",
            "served 1280x720 UI and automated narrow/reduced-motion coverage: PASS",
        ),
        "known_external_failures": (
            "Legacy 3d.simultaneous_center_conflict.joint_schedule_v2 with 20/40 s "
            "ground waits aborts Gamma for STALE_FLEET_OBSERVATION in both modes; "
            "multi-role runtime is outside the frozen 1D review unit.",
            "Synthetic 2d.head_on_conflict.runtime_object_replan expects dispatch "
            "where the protected response/certification boundary fails closed; "
            "WP-66 explicitly does not qualify a second dynamic mission.",
        ),
        "claim_boundary": (
            "Production-entry deterministic Fast Sim, accelerated and observed "
            "realtime as declared per packet, plus locally served UI. No hardware, "
            "physical-flight, Live Isaac, or aerodynamic-fidelity claim."
        ),
    }
    payload["payload_sha256"] = _sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )
    return payload


def main() -> None:
    payload = build_payload()
    output = ROOT / OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    print(
        json.dumps(
            {
                "file_count": len(payload["files"]),
                "payload_sha256": payload["payload_sha256"],
                "output": OUTPUT.as_posix(),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
