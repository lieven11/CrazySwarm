#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs/project/requirements"
INDEX = CATALOG / "README.md"
COMPATIBILITY = ROOT / "docs/project/WORKFLOW_AND_REQUIREMENTS.md"
AGENTS = ROOT / "AGENTS.md"

DEFINITION = re.compile(r"^\| `(REQ-([A-Z]+)-(\d{3}))` \|")
MARKDOWN_LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")
INDEX_OWNER_ROW = re.compile(
    r"^\| (?P<label>(?:`REQ-[^`]+`(?:, )?)+) \| "
    r"\[[^]]+\]\((?P<owner>[^)]+)\) \| (?P<count>\d+) \|$"
)
INDEX_TOTAL_ROW = re.compile(r"^\| \*\*Total\*\* \|  \| \*\*(?P<count>\d+)\*\* \|$")

EXPECTED_COUNTS = {
    "EVI": 14,
    "GEO": 11,
    "MIS": 10,
    "MOT": 17,
    "PLN": 13,
    "REU": 6,
    "RPL": 13,
    "UI": 2,
    "WFL": 54,
    "XFR": 10,
}

EXPECTED_OWNERS = {
    "EVI": "EVIDENCE_AND_REVIEW.md",
    "GEO": "PLANNING_AND_GEOMETRY.md",
    "MIS": "MISSION_AND_CURRICULUM.md",
    "MOT": "MOTION_AND_CONTROL.md",
    "PLN": "PLANNING_AND_GEOMETRY.md",
    "REU": "MISSION_AND_CURRICULUM.md",
    "RPL": "REPLANNING_AND_RUNTIME.md",
    "UI": "UI_AND_CATALOG.md",
    "XFR": "FIDELITY_AND_TRANSFER.md",
}

EXPECTED_INDEX_ROWS = {
    ("`REQ-MIS-*`, `REQ-REU-*`", "MISSION_AND_CURRICULUM.md", 16),
    ("`REQ-MOT-*`", "MOTION_AND_CONTROL.md", 17),
    ("`REQ-PLN-*`, `REQ-GEO-*`", "PLANNING_AND_GEOMETRY.md", 24),
    ("`REQ-RPL-*`", "REPLANNING_AND_RUNTIME.md", 13),
    ("`REQ-XFR-*`", "FIDELITY_AND_TRANSFER.md", 10),
    ("`REQ-EVI-*`", "EVIDENCE_AND_REVIEW.md", 14),
    ("`REQ-UI-*`", "UI_AND_CATALOG.md", 2),
    ("`REQ-WFL-001..012`", "workflow/ITERATION_AND_TUNING.md", 12),
    ("`REQ-WFL-013..027`", "workflow/WORK_PACKET_GATES.md", 15),
    ("`REQ-WFL-028..041`", "workflow/PREFREEZE_AND_ORACLES.md", 14),
    ("`REQ-WFL-042..054`", "workflow/COST_SCOPE_AND_HANDOFF.md", 13),
}


def workflow_owner(number: int) -> str:
    if number <= 12:
        return "workflow/ITERATION_AND_TUNING.md"
    if number <= 27:
        return "workflow/WORK_PACKET_GATES.md"
    if number <= 41:
        return "workflow/PREFREEZE_AND_ORACLES.md"
    return "workflow/COST_SCOPE_AND_HANDOFF.md"


def expected_ids() -> set[str]:
    return {
        f"REQ-{prefix}-{number:03d}"
        for prefix, count in EXPECTED_COUNTS.items()
        for number in range(1, count + 1)
    }


def collect_definitions() -> tuple[dict[str, Path], list[str]]:
    owners: dict[str, Path] = {}
    errors: list[str] = []
    for path in sorted(CATALOG.rglob("*.md")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = DEFINITION.match(line)
            if match is None:
                continue
            requirement_id = match.group(1)
            if requirement_id in owners:
                errors.append(
                    f"duplicate {requirement_id}: {owners[requirement_id].relative_to(ROOT)} "
                    f"and {path.relative_to(ROOT)}:{line_number}"
                )
            owners[requirement_id] = path
    return owners, errors


def check_links(path: Path) -> list[str]:
    errors: list[str] = []
    for target in MARKDOWN_LINK.findall(path.read_text(encoding="utf-8")):
        target_path = target.split("#", 1)[0]
        if not target_path or "://" in target_path:
            continue
        resolved = (path.parent / target_path).resolve()
        if not resolved.exists():
            errors.append(f"broken link in {path.relative_to(ROOT)}: {target}")
    return errors


def check_index_summary(definition_count: int) -> list[str]:
    errors: list[str] = []
    rows: set[tuple[str, str, int]] = set()
    total: int | None = None
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        if match := INDEX_OWNER_ROW.match(line):
            rows.add((match["label"], match["owner"], int(match["count"])))
        elif match := INDEX_TOTAL_ROW.match(line):
            total = int(match["count"])
    if rows != EXPECTED_INDEX_ROWS:
        errors.append(
            "requirement index ownership rows differ: "
            f"actual={sorted(rows)} expected={sorted(EXPECTED_INDEX_ROWS)}"
        )
    displayed_sum = sum(row[2] for row in rows)
    if displayed_sum != definition_count:
        errors.append(
            f"requirement index row sum differs: displayed={displayed_sum} "
            f"definitions={definition_count}"
        )
    if total != definition_count:
        errors.append(
            f"requirement index total differs: displayed={total} definitions={definition_count}"
        )
    return errors


def validate() -> dict[str, object]:
    owners, errors = collect_definitions()
    expected = expected_ids()
    actual = set(owners)
    for requirement_id in sorted(expected - actual):
        errors.append(f"missing requirement: {requirement_id}")
    for requirement_id in sorted(actual - expected):
        errors.append(f"unexpected requirement: {requirement_id}")

    counts: dict[str, int] = defaultdict(int)
    for requirement_id, path in owners.items():
        _, prefix, number_text = requirement_id.split("-")
        counts[prefix] += 1
        expected_owner = (
            workflow_owner(int(number_text)) if prefix == "WFL" else EXPECTED_OWNERS.get(prefix)
        )
        if expected_owner is None:
            errors.append(f"no owner mapping for {requirement_id}")
            continue
        actual_owner = path.relative_to(CATALOG).as_posix()
        if actual_owner != expected_owner:
            errors.append(
                f"wrong owner for {requirement_id}: {actual_owner}; expected {expected_owner}"
            )

    if dict(sorted(counts.items())) != EXPECTED_COUNTS:
        errors.append(
            f"prefix counts differ: actual={dict(sorted(counts.items()))}, "
            f"expected={EXPECTED_COUNTS}"
        )
    errors.extend(check_index_summary(len(owners)))

    nonnormative_paths = [
        COMPATIBILITY,
        ROOT / "docs/project/REQUIREMENTS_CHANGELOG.md",
        *sorted((ROOT / "docs/project/decisions").glob("*.md")),
        *sorted((ROOT / "docs/project/retrospectives").glob("*.md")),
    ]
    for path in nonnormative_paths:
        text = path.read_text(encoding="utf-8")
        if any(DEFINITION.match(line) for line in text.splitlines()):
            errors.append(
                f"non-normative document contains requirement definitions: {path.relative_to(ROOT)}"
            )

    routed_docs = [
        *sorted(CATALOG.rglob("*.md")),
        *nonnormative_paths,
        ROOT / "docs/guides/RUN_ANALYSIS_PROTOCOL.md",
        ROOT / "docs/system/README.md",
        ROOT / "docs/README.md",
    ]
    for path in routed_docs:
        errors.extend(check_links(path))
    agents_text = AGENTS.read_text(encoding="utf-8")
    for required_path in (
        "docs/project/requirements/README.md",
        "docs/project/requirements/workflow/WORK_PACKET_GATES.md",
        "docs/project/requirements/workflow/COST_SCOPE_AND_HANDOFF.md",
        "docs/project/requirements/workflow/PREFREEZE_AND_ORACLES.md",
        "docs/guides/RUN_ANALYSIS_PROTOCOL.md",
    ):
        if required_path not in agents_text:
            errors.append(f"AGENTS.md does not route to {required_path}")

    return {
        "valid": not errors,
        "definition_count": len(owners),
        "prefix_counts": dict(sorted(counts.items())),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the routed requirement catalog")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args()
    result = validate()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result["valid"]:
        print(f"requirement catalog valid: {result['definition_count']} unique definitions")
    else:
        print("requirement catalog invalid")
        for error in result["errors"]:
            print(f"- {error}")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
