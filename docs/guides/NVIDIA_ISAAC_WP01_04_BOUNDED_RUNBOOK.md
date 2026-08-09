# NVIDIA Isaac WP01–WP04 bounded runbook

> Navigation: [documentation index](../README.md)

Status: `DEFER_RESOURCE_LIMIT_FROM_REPORTED_PRECHECK`. This is not measured Victus
evidence and not a live Isaac result. Fast Sim remains the default backend.

## Current decision

The Isaac Sim 6.0.1 official minimum captured on 2026-08-07 is Windows 11 or
Ubuntu 22.04/24.04, four physical CPU cores, 32 GiB RAM, 50 GiB free SSD storage,
an RTX 4080, 16 GiB VRAM, and the tested Windows driver 595.97. NVIDIA requires
the official compatibility checker for the final host decision.

The repository's reported candidate is an HP Victus with an i5-13500H, 16 GiB
RAM, RTX 4050 Laptop GPU, and expected 6 GiB VRAM. RAM and VRAM are below the
official minimum. The generated precheck therefore records:

```text
decision=DEFER_RESOURCE_LIMIT
compatible=false
headless_gateway_authorized=false
isaac_runtime_version=NOT_PINNED_RESOURCE_GATE_NOT_GO
```

No Isaac runtime, NVIDIA driver, ROS distribution, compatibility-checker package,
asset pack, or cloud resource was installed or changed from this Mac session.

Official sources:

- [Isaac Sim 6.0.1 requirements](https://docs.isaacsim.omniverse.nvidia.com/6.0.1/installation/requirements.html)
- [Isaac Sim 6.0.1 workstation and compatibility-checker instructions](https://docs.isaacsim.omniverse.nvidia.com/6.0.1/installation/install_workstation.html)
- [Isaac Sim ROS 2 support](https://docs.isaacsim.omniverse.nvidia.com/6.0.1/installation/install_ros.html)

## WP01 measured-host procedure

Run the inventory directly on the Victus in PowerShell from a checked-out copy of
this repository. It is read-only unless an already-present compatibility-checker
path is supplied; in that case it also runs that checker and saves its log.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/collect_isaac_windows_host.ps1 `
  -OutputPath evidence/isaac/victus-host-inventory.json
```

If the official checker is already present:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/collect_isaac_windows_host.ps1 `
  -OutputPath evidence/isaac/victus-host-inventory.json `
  -CompatibilityChecker C:\isaacsim\isaac-sim.compatibility_check.bat
```

An exit code of zero records `REVIEW_REQUIRED`, not success. After inspecting the
saved checker log and confirming that every official required check is green, rerun
the same command with `-ConfirmAllOfficialChecksGreen`; only that reviewed record
can contain `PASSED`.

Evaluate the captured inventory from the project environment:

```bash
.venv/bin/python scripts/evaluate_isaac_host.py \
  --inventory evidence/isaac/victus-host-inventory.json \
  --requirements config/isaac/official-requirements-6.0.1-v1.json \
  --output evidence/isaac/victus-host-profile.json
```

The evaluator exits zero only for measured host evidence in which every declared
minimum passes and the official checker reports `PASSED`. Missing measurements,
reported-only values, and an unrun checker cannot produce `GO_MINIMAL_EXPERIMENT`.

## Installation rule

Do not install the full runtime while the decision is `DEFER_RESOURCE_LIMIT` or
`WAITING_FOR_MEASURED_HOST_AND_CHECKER`. If a future measured profile reaches
`GO_MINIMAL_EXPERIMENT`, create a reviewed installation manifest that pins the
exact Isaac package/build and checksum, driver, Isaac Python, supported ROS 2
distribution, middleware, gateway protocol, repository commit, and minimal
extension set before downloading the full runtime. Never use `latest`.

The allowed install excludes cameras, RTX lidar, Replicator, Isaac Lab, Isaac ROS,
large asset packs, and unrelated extensions. License acceptance, driver mutation,
large downloads, and any cloud spend require their own recorded authorization.

## WP03/WP04 scaffolding

Regenerate the deterministic one-vehicle OpenUSD files with:

```bash
.venv/bin/python scripts/generate_isaac_scaffolding.py
```

The outputs are:

- `assets/isaac/crazyflie-primitive-empty-scene-v1.usda`: one primitive `cf01`,
  four declared rotors, rigid-body/mass properties, and frame/sensor placeholders.
- `assets/isaac/crazyflie-primitive-minimal-room-v1.usda`: the same vehicle plus
  primitive floor and walls from the canonical room configuration.
- `assets/isaac/scaffold-manifest-v1.json`: content hashes and the explicit
  `CONFIGURED_UNQUALIFIED`/`NOT_RUN` classification.

Both generated stages pass the Mac's native `usdchecker`. The project Python
environment does not contain `pxr`, and parser validation is not proof that Isaac
can simulate, stabilize, or render the model. Physics/Isaac behavior remains part
of the future bounded live test.

## Bounded verification and stop gate

The local contract suite verifies one-vehicle commands, telemetry, fixed stepping,
clock reset, authenticated start, clean stop, process loss, unknown command outcome,
and restart behavior against the deterministic mock gateway:

```bash
.venv/bin/pytest -q tests/isaac \
  'tests/vehicles/test_adapter_conformance.py::test_shared_flight_adapter_conformance[isaac-gateway]' \
  tests/vehicles/test_adapter_conformance.py::test_gateway_process_loss_is_structured_and_never_retried_as_success \
  tests/vehicles/test_adapter_conformance.py::test_gateway_delay_duplicate_disconnect_and_restart_are_explicit \
  tests/vehicles/test_adapter_conformance.py::test_acknowledgement_loss_is_unknown_outcome_and_never_auto_retried
```

The live test remains skipped until a measured compatible host, pinned runtime,
authenticated TLS gateway, and explicit launch variables exist. A future bounded
live run stops after one primitive vehicle proves ready/step/command/telemetry/
stop/crash/restart. It must not start WP05, multi-drone Isaac missions, tuning,
physical-model qualification, or digital-twin work.

Continuation beyond this point requires Reality WP04 exact-aircraft bench data,
Reality WP05 reviewed contained-flight data, and the Reality WP06 decision
`GO_ISAAC_PHYSICAL_MODEL` for the named model/sensor subset.
