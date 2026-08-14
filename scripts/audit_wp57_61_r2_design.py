#!/usr/bin/env python3
"""Audit the final corrective design overlay for WP-57 through WP-61.

The first revised design remains immutable.  This audit binds that exact payload,
prototypes the complete WP-61F holdout relation, recomputes retained evaluation
identities, and mechanically closes existing and intended-new production boundaries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from itertools import pairwise
from pathlib import Path
from typing import Any

BASE_DESIGN_SHA256 = (
    "2096bac6a01dd437ff5f909bc63bd3b012b30927b7d270aa3f9c4644049f8c6f"
)
BASE_AUDIT_SCRIPT_SHA256 = (
    "f2b1df6c4017dd3856ddfaf7f35e5b88baa87da8d2bfdc8bd1689417bd98efa8"
)
BASE_AUDIT_FILE_SHA256 = (
    "5ee24c1382553e3168caa86825208c5c1cf116c3e6e412bcf3f2f4e7d95c0ada"
)
BASE_AUDIT_PAYLOAD_SHA256 = (
    "65f7243a5c7bf944570e6758a84dccc060882af8459c310fedb9356136bbea40"
)
WORKFLOW_SHA256 = (
    "e268966870c6f6cf7f3cc835507d3082ce56368e08f335167322027af7777544"
)

BEGIN = "<!-- WP57-61-DESIGN-PAYLOAD-BEGIN -->"
END = "<!-- WP57-61-DESIGN-PAYLOAD-END -->"

EXISTING_BOUNDARIES: dict[str, tuple[str, str]] = {
    "src/crazyswarm_app/campaign/models.py": (
        "31c3b5067972298b9dbd4a4dc026ff3b48de96685b253a9b22d48293eb71fdf0",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/campaign/trajectory.py": (
        "39b320d3a93064a751203b104ac64d4f013369e5b97df8e9b1b90d911c07dc08",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/campaign/analyzer.py": (
        "c2e62b8411dc9f9938208e75adb3d5be7663263e57d0c9cb7ab4cda4c07c540a",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/campaign/replanning.py": (
        "8a80ff02979979affe6dc1cee9d4d0550430473d36de0a3fb5d1abffe0f054e9",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/campaign/execution_head.py": (
        "a6510c17f13a0f6d8b82ef450c2442b3271b32046932d6c6a7de245dba43e5bc",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/campaign/runtime_executor.py": (
        "eff68869fcc5943adbc5d3b1e258f5304f213417121d9207f312b7d2bd5a3e38",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/campaign/service.py": (
        "3a9e3047ba587b0545413fb0b3564a0d774b54fd157e394fc9817e074bc23a00",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/campaign/catalog.py": (
        "2111911ac0c36602cb660e1e01dc61f6fae10e691c7c4795a1270e577e974b2c",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/campaign/api_models.py": (
        "06a8620e2c08512ab5e8b0d9d060bd29dc51fd0e358400a9dee0f6482165c39f",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/campaign/planner.py": (
        "4bed265f082def6902b6c08b86302285dfc93d45b4c46877e5fb5419866ce23c",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/campaign/submissions.py": (
        "9b31d64b04037420b7c8e68420d2db44d4d09d9b8e3fcec1903c4dfee150f919",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/campaign/execution.py": (
        "d6d7b335dbe97633badab7245a5cd21862c0eb5c52e9f981f4a1192afb997f16",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/campaign/scenario.py": (
        "c7e3ddeee88b235551ba2c31c639ef73da0edddfc46eb94cd5a83c24d96ef221",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/campaign/geometry.py": (
        "f011ece2306fb5a2505818eb7dac8771a21bb72a6dffc62a8f3bcb9c30d21802",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/missions/base.py": (
        "887e02db596015f4e27ac4d75476408d31c760c997860101b9243ef7ca371702",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/domain/trajectory.py": (
        "32c235cd9b6b2212e030a7c25f4e1d7692988a0ca0f0a416abcf447abae6f446",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/domain/telemetry.py": (
        "741a4aa9cc4a405588960eece156b82e85348bf124e61fcb16f66ebb97376f99",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/simulation/physics.py": (
        "d9c37b60d72a5d035bc07d8ad3ecfee3ed1f390aab61336de8807f1d9fe72ea1",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/simulation/world.py": (
        "5a9c4df5b8b00a4e63835bcede4b695e3cca760d4fed7965eaa95aa781d13c5d",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/simulation/sensors.py": (
        "b49dd4a9a594b25201b89c3e45300e8299a8d9fe9cd667a087f1e989bc7fcba6",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/simulation/vehicle.py": (
        "c40f660b35e12b5cc01c5aa76d02f9afc2b7fc28c9b1eb6948963518f16c71e3",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/observability/storage.py": (
        "aa3e3abc76751e4f840145500c50dc419867a0120de53dfe3c9d0223a50dc689",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/observability/replay.py": (
        "496bb5cab3c7ad68ebe082b22ab6c1aa2abcc78be07ea3f1b55af778aec845bb",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/observability/evaluation.py": (
        "f94e6ad3da7a1024e316615c1ce565f19a67223f1fe3517e480dd397513b7f46",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/observability/csv_export.py": (
        "07702a86a9adb529dbdc3f309d15d5e8a256b6f89bf2a133460b090de7563126",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/twin/models.py": (
        "4f5de2f3fbd8f4f769cfab34963ecb7e424e36543e0998559f99081b5c37d3d1",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/twin/coordinator.py": (
        "219894404160f2c726f402b3f92151b9c6702f906d3ea2c5f84ea004b9df6cbf",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/api/app.py": (
        "7015952b033fcecaa1e36a9777ecc6c1373549fd96c3e4cc0a610a8e6d79a718",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/api/models.py": (
        "ae78fa0502d73b28625e01df41364b9517237838b574ec28daf714eda151026e",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/api/runtime.py": (
        "b257d952d3ac15bed827c862c7e9891ab005f31a18ca438474cc8c8e93064072",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/dashboard.py": (
        "950f53e55caebf4c8e3f77b840a2f3f6cb079c01a044b981bdf299afaad53149",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/vehicles/providers.py": (
        "1996e53bd87f97a7da6c1ebf946dfb27c1268247853572d927cfc6dd95786c0b",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/vehicles/crazyflie.py": (
        "e7ea1b9080c00c7ac4622fd440ecff373f62f8b8afed3750a639a299545ee5f0",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/hardware/models.py": (
        "cb101bcc2056db0a6d013f30eee790c46c16f8d467aa534919b2cfc11d6eaf5c",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/qualification/physical.py": (
        "7a7ee3d4730533fa7674b5a5d30d6b9fd8a3781db8e9470bf42097f0385634cc",
        "IMPLEMENTATION_OWNED",
    ),
    "src/crazyswarm_app/safety/supervisor.py": (
        "bad9b04a5cc87bb9372840f016fe405815f1368f47332cdc94377f64458ed68b",
        "RELIED_UPON_UNCHANGED",
    ),
    "ui/app/components/CampaignLab.tsx": (
        "3f0f39d058f79b3f088166c054c99bc5f79fb514d62691564429ca95a6613c11",
        "IMPLEMENTATION_OWNED",
    ),
    "ui/app/page.tsx": (
        "df5abbd859b591ac2644eb9acd82d5191c377c3f351cd75310b3538f4801f752",
        "IMPLEMENTATION_OWNED",
    ),
    "ui/app/components/ControlCenter.tsx": (
        "9904f9462ac05f2924df48e54875089434a36814bbfb10d030baeb68ccaaa0fb",
        "IMPLEMENTATION_OWNED",
    ),
    "ui/app/components/TelemetryDock.tsx": (
        "8597b063d755bcc1a26f7617ed3b9abc57430fcf717165b87814eb31cde5baf7",
        "IMPLEMENTATION_OWNED",
    ),
    "ui/app/components/RoomScene.tsx": (
        "63c65e5b852cef9e7913426cec4c7a52b439066374e86bb9da1524429b3a8d05",
        "IMPLEMENTATION_OWNED",
    ),
    "ui/app/lib/api.ts": (
        "7feb12cade8a83f426c1b2017a45ec4d33c28d1a8d0fac366de426ba1d7be29d",
        "IMPLEMENTATION_OWNED",
    ),
    "ui/app/lib/api.generated.ts": (
        "b290012068ba02d70c9dacb7cf22ac90112471b2fe59495c7481c326cd72a576",
        "GENERATED_POSTIMAGE",
    ),
    "ui/app/lib/models.ts": (
        "be9c09ea870a4bcb00320b54bdc2a2b4dad46a8dc92490b38e28e28d2d3c3622",
        "IMPLEMENTATION_OWNED",
    ),
    "ui/app/lib/campaign-telemetry.ts": (
        "10a71f64d8081cc9d902709baf9a6cb75834cc7a29b3ced085c2ab2601249204",
        "IMPLEMENTATION_OWNED",
    ),
    "ui/app/globals.css": (
        "38e9e8d533591aa08d3458e69fcb2845b07fec472ea66536a23984a32a99ccb1",
        "IMPLEMENTATION_OWNED",
    ),
    "scripts/campaign_case_specs.py": (
        "5c02700b2638af8ae57223d6ee24418e592a56913ac6588a4ca24f3228d48af9",
        "IMPLEMENTATION_OWNED",
    ),
    "scripts/generate_campaign_catalog.py": (
        "715afda601bb517482cc868b5ae91b0e8a61e434702f31049fc3f39c2c5167a0",
        "IMPLEMENTATION_OWNED",
    ),
    "config/qualification/reality-physical-plan-v1.json": (
        "04e950f5d2dea29a909bdc6639290b42caa6f95f1a9311737415bf7c742d12b1",
        "IMPLEMENTATION_OWNED",
    ),
    "scripts/audit_wp57_61_design.py": (
        BASE_AUDIT_SCRIPT_SHA256,
        "DESIGN_EVIDENCE_IMMUTABLE",
    ),
    "missions/campaigns/sim/qualification/wp57-61-predraft-1d-evidence-v1.json": (
        BASE_AUDIT_FILE_SHA256,
        "DESIGN_EVIDENCE_IMMUTABLE",
    ),
}

EXISTING_BOUNDARIES.update(
    {
        (
            "missions/campaigns/real/authorized_cases/basic-flight-and-route-following/"
            "real-mirrors-v1.yaml"
        ): (
            "6f9ec6548eee3f109f4f39d4a82deeed2ec1b0f4622e9f56db5b067199abf1bd",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        (
            "missions/campaigns/real/authorized_cases/constraints-and-optimization/"
            "real-mirrors-v1.yaml"
        ): (
            "c48f0d369aecbdd83e00bdd817dc7e530cc238fc5c8b8a7364e2714cb4e5fe33",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        (
            "missions/campaigns/real/authorized_cases/coordination-and-allocation/"
            "real-mirrors-v1.yaml"
        ): (
            "7a65556a4264639685fd3e61b7dfa337987330fb8b1af62f4ddcb20fd9c05928",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        (
            "missions/campaigns/real/authorized_cases/geometric-conflict-resolution/"
            "real-mirrors-v1.yaml"
        ): (
            "50df48eb71852fc5899f2d87207f586864439e46708e8e4239737fddd806b241",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/campaigns/sim/cases/basic-flight-and-route-following/1d-cases-v1.yaml": (
            "964aa81d6a112103365bc8842b2cf55d1ea9a5713ad521bc543920363e0ab617",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/campaigns/sim/cases/constraints-and-optimization/1d-cases-v1.yaml": (
            "5a7083ab682a170f2019c21015b02cb68fcd4f176abeb75cf869fb03f4f35769",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/campaigns/sim/cases/constraints-and-optimization/2d-cases-v1.yaml": (
            "a4235c6f8253cb6f81329c769d712032f9961ea3e6a7aa5f8b4e08b765724abd",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/campaigns/sim/cases/constraints-and-optimization/3d-cases-v1.yaml": (
            "48675d50499927d9717b0a6221e470f32b414ccbce3195330d49567cc9a5388c",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/campaigns/sim/cases/coordination-and-allocation/2d-cases-v1.yaml": (
            "dd8b48613c58e0a360b8dd4fc5212922eec9fe38ee984317c8a6e6f248426bed",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/campaigns/sim/cases/coordination-and-allocation/3d-cases-v1.yaml": (
            "a0c5bd3df40c2e0cb621a4d09d1c2f9c185e6dc6519419d5cd92113afc59f787",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/campaigns/sim/cases/failure-recovery-and-replanning/1d-cases-v1.yaml": (
            "e9e99f6f00ace10d19cf18afca0a3160434ed806d5cf66ce854c979f0627e3ad",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/campaigns/sim/cases/failure-recovery-and-replanning/2d-cases-v1.yaml": (
            "6d0464c7eefd5d7beba27da2432f9bfab8dc808ae1350f77c6a912d659bc3cac",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/campaigns/sim/cases/failure-recovery-and-replanning/3d-cases-v1.yaml": (
            "3a1cf2e3db5bbeaf683d38c528a2c0664f21f71022cb84ae5609a41ace2b1579",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/campaigns/sim/cases/geometric-conflict-resolution/2d-cases-v1.yaml": (
            "2d05a0020eb8f88e95cfaf3eeffc30c98eb041bd15ae9c0dd094ba43adfdbe78",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/campaigns/sim/cases/geometric-conflict-resolution/3d-cases-v1.yaml": (
            "76a2c1d439bcbcc3f02b28e574722cd9e671d4e425ab8d8f77244426036cf6d5",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/campaigns/sim/profiles/default-development-preset-v1.yaml": (
            "c19fb67fcef5ecf3dd77f9e9e7801d0620d36a756d561352c65d50eef04d222b",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/library/one_drone/abort_and_land_goal_fallback/mission.py": (
            "872eec2ca8b99f470ad411e70861d25942416822c21c4b31b940d2d77a1512b8",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/library/one_drone/altitude_transition/mission.py": (
            "90aaf259918bd70eccce591328188e45da7ce2080b3d4876199483148d121f49",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/library/one_drone/blocked_replan/mission.py": (
            "962ace48336c4c8b37c1e1db13fe8f6a9d84c730729e1944a641c492764bc8df",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/library/one_drone/boundary_constrained_route/mission.py": (
            "dddafa6ee20c14b7a0c19d6660f7e00a81da2902a8f5a329fa668a862ee241ea",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/library/one_drone/continuous_waypoint_sequence/mission.py": (
            "717ff1e9d13f5820b0cbc7186b316b52957e270316b56f2a1fdab3d50c53b052",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/library/one_drone/curved_route/mission.py": (
            "150f7f3252d98b07c14f339e8c5c57ef8dd207385a8f288b1d7c56228edb3ff6",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/library/one_drone/duplicate_stale_goal_update/mission.py": (
            "0de771779dc4cee65b2fe8ea6523ff347d3fd69fed5a5303fb064fbb6bf7e0c8",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/library/one_drone/failure_recovery/mission.py": (
            "f798558abfa984f5f4740553ce921cd9912ea6e0634aeb4974db719042a1aa36",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/library/one_drone/mid_route_goal_replacement/mission.py": (
            "a7ff9470e495643d3842ea6a2d09bd078848091ebb2bdb695db046135df87439",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/library/one_drone/move_return/mission.py": (
            "bef326184c05e1c42004220efd437839e69367330b752d5d71d8028ed701a26c",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/library/one_drone/moving_target/mission.py": (
            "a4631b4f01fbbca9938cf085bc669992d46889df0a77535ed5300983b41edc47",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/library/one_drone/operator_approval_goal_replacement/mission.py": (
            "d43669e81d77521ff8bd519d4db1ff2a9bd82c7ae699ad294b48288e90b59cae",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/library/one_drone/planar_shape_loop/mission.py": (
            "735247c51f5761e83c5390dd74078160b53d1ce744942fbf80ab26b8c850f905",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/library/one_drone/planning_budget_expiry/mission.py": (
            "dd7ccf83b3c9c74cbf6a76b29205a2b99c07d048809491800d3cefd827447136",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/library/one_drone/point_to_point_relocation/mission.py": (
            "7e053c63f802c7b1b7a8a93ea2ec964970c346095dba6a304e5419e10c97fb3e",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/library/one_drone/static_multi_goal_sequence/mission.py": (
            "aff1470e1b8a6947e9806cf2f45a692b1a8ce18bb4702e0117cd2b38a4816edb",
            "GENERATED_RECONCILIATION_OWNED",
        ),
        "missions/library/one_drone/takeoff_hover_land/mission.py": (
            "5ad804d0b78b5afd3fdfcf72bf006cdf69774664f04a8e14aa355d746e5dbe65",
            "GENERATED_RECONCILIATION_OWNED",
        ),
    }
)

INTENDED_NEW_BOUNDARIES = (
    "src/crazyswarm_app/campaign/route_horizon.py",
    "src/crazyswarm_app/campaign/perception.py",
    "src/crazyswarm_app/campaign/physical_truth.py",
    "src/crazyswarm_app/twin/storage.py",
    "src/crazyswarm_app/twin/ingestion.py",
    "src/crazyswarm_app/twin/calibration.py",
    "tests/campaign/test_motion_quality_contract.py",
    "tests/campaign/test_whole_route_motion.py",
    "tests/campaign/test_wp58_baseline_oracle.py",
    "tests/campaign/test_route_horizon.py",
    "tests/campaign/test_whole_route_smoother.py",
    "tests/campaign/test_adaptive_motion_cutover.py",
    "tests/campaign/test_motion_production_qualification.py",
    "tests/campaign/test_dynamic_perception_replanning.py",
    "tests/campaign/test_perception_contract.py",
    "tests/simulation/test_dynamic_obstacle_sensor.py",
    "tests/campaign/test_one_drone_execution_head.py",
    "tests/campaign/test_changed_world_safety_monitor.py",
    "tests/campaign/test_reality_mission_e2e.py",
    "tests/simulation/test_motor_physical_truth.py",
    "tests/twin/test_twin_pipeline_e2e.py",
    "tests/twin/test_storage.py",
    "tests/twin/test_ingestion.py",
    "tests/twin/test_replay.py",
    "tests/twin/test_curriculum.py",
    "tests/twin/test_calibration.py",
    "tests/twin/test_physical_handoff.py",
    "tests/api/test_twin.py",
    "ui/tests/campaign-motion-quality.test.tsx",
    "ui/tests/campaign-replan-timeline.test.tsx",
    "ui/tests/motor-truth.test.tsx",
    "ui/tests/twin-session.test.tsx",
    "missions/campaigns/sim/qualification/wp61-ui-inspection-v1.json",
)

CLAIM_AND_TRANSIT_GROUPS = {
    "motion_contract_and_whole_route": (
        "src/crazyswarm_app/campaign/models.py",
        "src/crazyswarm_app/missions/base.py",
        "src/crazyswarm_app/campaign/submissions.py",
        "src/crazyswarm_app/campaign/planner.py",
        "src/crazyswarm_app/campaign/trajectory.py",
        "src/crazyswarm_app/campaign/runtime_executor.py",
        "src/crazyswarm_app/campaign/analyzer.py",
    ),
    "perception_replanning_and_command": (
        "src/crazyswarm_app/simulation/world.py",
        "src/crazyswarm_app/simulation/sensors.py",
        "src/crazyswarm_app/campaign/scenario.py",
        "src/crazyswarm_app/campaign/execution_head.py",
        "src/crazyswarm_app/campaign/replanning.py",
        "src/crazyswarm_app/campaign/execution.py",
        "src/crazyswarm_app/safety/supervisor.py",
    ),
    "physical_truth_and_evidence_export": (
        "src/crazyswarm_app/simulation/physics.py",
        "src/crazyswarm_app/simulation/vehicle.py",
        "src/crazyswarm_app/domain/telemetry.py",
        "src/crazyswarm_app/observability/storage.py",
        "src/crazyswarm_app/observability/csv_export.py",
        "src/crazyswarm_app/observability/evaluation.py",
    ),
    "twin_persistence_and_api": (
        "src/crazyswarm_app/twin/models.py",
        "src/crazyswarm_app/twin/coordinator.py",
        "src/crazyswarm_app/api/app.py",
        "src/crazyswarm_app/api/models.py",
        "src/crazyswarm_app/api/runtime.py",
    ),
    "served_operator_ui": (
        "src/crazyswarm_app/dashboard.py",
        "ui/app/components/CampaignLab.tsx",
        "ui/app/components/ControlCenter.tsx",
        "ui/app/components/TelemetryDock.tsx",
        "ui/app/components/RoomScene.tsx",
        "ui/app/lib/api.ts",
        "ui/app/lib/api.generated.ts",
        "ui/app/lib/models.ts",
        "ui/app/lib/campaign-telemetry.ts",
        "ui/app/globals.css",
    ),
    "physical_handoff": (
        "src/crazyswarm_app/vehicles/providers.py",
        "src/crazyswarm_app/vehicles/crazyflie.py",
        "src/crazyswarm_app/hardware/models.py",
        "src/crazyswarm_app/qualification/physical.py",
        "config/qualification/reality-physical-plan-v1.json",
    ),
    "catalog_generation": (
        "src/crazyswarm_app/campaign/catalog.py",
        "src/crazyswarm_app/campaign/service.py",
        "scripts/campaign_case_specs.py",
        "scripts/generate_campaign_catalog.py",
    ),
}

EXPECTED_CLAIM_ROWS = (
    "WP-57 parent",
    "WP-58 parent",
    "WP-58A",
    "WP-58B",
    "WP-58C",
    "WP-58D",
    "WP-58E",
    "WP-59 parent",
    "WP-59A",
    "WP-59B",
    "WP-59C",
    "WP-59D",
    "WP-59E",
    "WP-60 parent",
    "WP-61 parent",
    "WP-61A",
    "WP-61B",
    "WP-61C",
    "WP-61D",
    "WP-61E",
    "WP-61F",
    "WP-61G",
)

CLAIM_OWNER_BINDINGS = {
    "WP-57 parent": (
        "src/crazyswarm_app/campaign/models.py",
        "src/crazyswarm_app/campaign/analyzer.py",
        "src/crazyswarm_app/observability/evaluation.py",
        "src/crazyswarm_app/campaign/catalog.py",
        "ui/app/components/CampaignLab.tsx",
        "ui/app/lib/campaign-telemetry.ts",
        "tests/campaign/test_motion_quality_contract.py",
        "ui/tests/campaign-motion-quality.test.tsx",
    ),
    "WP-58 parent": (
        "src/crazyswarm_app/campaign/trajectory.py",
        "src/crazyswarm_app/campaign/runtime_executor.py",
        "tests/campaign/test_whole_route_motion.py",
    ),
    "WP-58A": (
        "scripts/audit_wp57_61_design.py",
        "missions/campaigns/sim/qualification/wp57-61-predraft-1d-evidence-v1.json",
        "tests/campaign/test_wp58_baseline_oracle.py",
    ),
    "WP-58B": (
        "src/crazyswarm_app/campaign/submissions.py",
        "src/crazyswarm_app/campaign/trajectory.py",
        "src/crazyswarm_app/campaign/route_horizon.py",
        "tests/campaign/test_route_horizon.py",
    ),
    "WP-58C": (
        "src/crazyswarm_app/campaign/route_horizon.py",
        "src/crazyswarm_app/campaign/trajectory.py",
        "src/crazyswarm_app/campaign/planner.py",
        "tests/campaign/test_whole_route_smoother.py",
    ),
    "WP-58D": (
        "src/crazyswarm_app/campaign/scenario.py",
        "src/crazyswarm_app/campaign/execution_head.py",
        "tests/campaign/test_adaptive_motion_cutover.py",
    ),
    "WP-58E": (
        "src/crazyswarm_app/campaign/service.py",
        "src/crazyswarm_app/campaign/runtime_executor.py",
        "src/crazyswarm_app/observability/storage.py",
        "src/crazyswarm_app/observability/replay.py",
        "src/crazyswarm_app/api/app.py",
        "ui/app/components/CampaignLab.tsx",
        "tests/campaign/test_motion_production_qualification.py",
        "ui/tests/campaign-motion-quality.test.tsx",
    ),
    "WP-59 parent": (
        "src/crazyswarm_app/campaign/api_models.py",
        "src/crazyswarm_app/api/app.py",
        "src/crazyswarm_app/campaign/service.py",
        "src/crazyswarm_app/campaign/runtime_executor.py",
        "src/crazyswarm_app/campaign/execution_head.py",
        "src/crazyswarm_app/safety/supervisor.py",
        "tests/campaign/test_dynamic_perception_replanning.py",
    ),
    "WP-59A": (
        "src/crazyswarm_app/campaign/perception.py",
        "src/crazyswarm_app/campaign/models.py",
        "src/crazyswarm_app/campaign/scenario.py",
        "tests/campaign/test_perception_contract.py",
    ),
    "WP-59B": (
        "src/crazyswarm_app/simulation/world.py",
        "src/crazyswarm_app/simulation/sensors.py",
        "src/crazyswarm_app/campaign/perception.py",
        "tests/simulation/test_dynamic_obstacle_sensor.py",
    ),
    "WP-59C": (
        "src/crazyswarm_app/campaign/execution_head.py",
        "src/crazyswarm_app/campaign/replanning.py",
        "src/crazyswarm_app/missions/base.py",
        "tests/campaign/test_one_drone_execution_head.py",
    ),
    "WP-59D": (
        "src/crazyswarm_app/campaign/replanning.py",
        "src/crazyswarm_app/campaign/geometry.py",
        "src/crazyswarm_app/campaign/planner.py",
        "tests/campaign/test_changed_world_safety_monitor.py",
    ),
    "WP-59E": (
        "scripts/campaign_case_specs.py",
        "scripts/generate_campaign_catalog.py",
        "src/crazyswarm_app/campaign/service.py",
        "src/crazyswarm_app/campaign/runtime_executor.py",
        "src/crazyswarm_app/observability/storage.py",
        "ui/app/components/CampaignLab.tsx",
        "tests/campaign/test_reality_mission_e2e.py",
        "ui/tests/campaign-replan-timeline.test.tsx",
    ),
    "WP-60 parent": (
        "src/crazyswarm_app/campaign/physical_truth.py",
        "src/crazyswarm_app/simulation/physics.py",
        "src/crazyswarm_app/observability/csv_export.py",
        "ui/app/components/TelemetryDock.tsx",
        "tests/simulation/test_motor_physical_truth.py",
        "ui/tests/motor-truth.test.tsx",
    ),
    "WP-61 parent": (
        "src/crazyswarm_app/twin/models.py",
        "src/crazyswarm_app/twin/coordinator.py",
        "src/crazyswarm_app/api/app.py",
        "ui/app/components/ControlCenter.tsx",
        "tests/twin/test_twin_pipeline_e2e.py",
    ),
    "WP-61A": (
        "src/crazyswarm_app/twin/storage.py",
        "src/crazyswarm_app/twin/models.py",
        "src/crazyswarm_app/twin/coordinator.py",
        "tests/twin/test_storage.py",
    ),
    "WP-61B": (
        "src/crazyswarm_app/twin/ingestion.py",
        "src/crazyswarm_app/domain/telemetry.py",
        "src/crazyswarm_app/api/app.py",
        "tests/twin/test_ingestion.py",
        "tests/api/test_twin.py",
    ),
    "WP-61C": (
        "src/crazyswarm_app/twin/coordinator.py",
        "src/crazyswarm_app/twin/storage.py",
        "src/crazyswarm_app/observability/replay.py",
        "tests/twin/test_replay.py",
    ),
    "WP-61D": (
        "src/crazyswarm_app/api/app.py",
        "src/crazyswarm_app/dashboard.py",
        "ui/app/page.tsx",
        "ui/app/components/ControlCenter.tsx",
        "ui/app/components/CampaignLab.tsx",
        "tests/api/test_twin.py",
        "ui/tests/twin-session.test.tsx",
        "missions/campaigns/sim/qualification/wp61-ui-inspection-v1.json",
    ),
    "WP-61E": (
        "scripts/campaign_case_specs.py",
        "scripts/generate_campaign_catalog.py",
        "src/crazyswarm_app/campaign/service.py",
        "src/crazyswarm_app/twin/ingestion.py",
        "tests/twin/test_curriculum.py",
    ),
    "WP-61F": (
        "src/crazyswarm_app/twin/calibration.py",
        "src/crazyswarm_app/twin/storage.py",
        "src/crazyswarm_app/api/app.py",
        "tests/twin/test_calibration.py",
    ),
    "WP-61G": (
        "src/crazyswarm_app/vehicles/providers.py",
        "src/crazyswarm_app/vehicles/crazyflie.py",
        "src/crazyswarm_app/hardware/models.py",
        "src/crazyswarm_app/qualification/physical.py",
        "config/qualification/reality-physical-plan-v1.json",
        "tests/twin/test_physical_handoff.py",
    ),
}

PUBLIC_TRANSIT_PROBES = {
    "src/crazyswarm_app/api/app.py": (
        '@router.post("/campaign/runs"',
        "CampaignRunRequest",
        "service.run_active",
        '@router.post("/twins"',
    ),
    "src/crazyswarm_app/campaign/api_models.py": ("class CampaignRunRequest",),
    "src/crazyswarm_app/campaign/service.py": ("self.executor", "run_active"),
    "src/crazyswarm_app/campaign/runtime_executor.py": (
        "CampaignExecutionHead",
        "export_mission_telemetry_csv",
    ),
    "src/crazyswarm_app/campaign/execution_head.py": ("MissionContext",),
    "src/crazyswarm_app/missions/base.py": ("execute_replanned_trajectory",),
    "src/crazyswarm_app/observability/storage.py": ("csv_export",),
    "src/crazyswarm_app/observability/csv_export.py": (
        "motor_{motor_id}_requested_thrust_n",
    ),
    "src/crazyswarm_app/dashboard.py": ("current", "release"),
    "ui/app/page.tsx": ("ControlCenter",),
    "src/crazyswarm_app/twin/coordinator.py": ("class TwinCoordinator",),
    "scripts/generate_campaign_catalog.py": ('root / "library"', "authorized_cases"),
}

ONE_DRONE_MISSION_FAMILIES = (
    "abort_and_land_goal_fallback",
    "altitude_transition",
    "blocked_replan",
    "boundary_constrained_route",
    "continuous_waypoint_sequence",
    "curved_route",
    "duplicate_stale_goal_update",
    "failure_recovery",
    "mid_route_goal_replacement",
    "move_return",
    "moving_target",
    "operator_approval_goal_replacement",
    "planar_shape_loop",
    "planning_budget_expiry",
    "point_to_point_relocation",
    "static_multi_goal_sequence",
    "takeoff_hover_land",
)

EXPECTED_GENERATED_OUTPUTS = {
    "one_drone_missions": tuple(
        f"missions/library/one_drone/{family}/mission.py"
        for family in ONE_DRONE_MISSION_FAMILIES
    ),
    "campaign_case_manifests": (
        "missions/campaigns/sim/cases/basic-flight-and-route-following/1d-cases-v1.yaml",
        "missions/campaigns/sim/cases/constraints-and-optimization/1d-cases-v1.yaml",
        "missions/campaigns/sim/cases/constraints-and-optimization/2d-cases-v1.yaml",
        "missions/campaigns/sim/cases/constraints-and-optimization/3d-cases-v1.yaml",
        "missions/campaigns/sim/cases/coordination-and-allocation/2d-cases-v1.yaml",
        "missions/campaigns/sim/cases/coordination-and-allocation/3d-cases-v1.yaml",
        "missions/campaigns/sim/cases/failure-recovery-and-replanning/1d-cases-v1.yaml",
        "missions/campaigns/sim/cases/failure-recovery-and-replanning/2d-cases-v1.yaml",
        "missions/campaigns/sim/cases/failure-recovery-and-replanning/3d-cases-v1.yaml",
        "missions/campaigns/sim/cases/geometric-conflict-resolution/2d-cases-v1.yaml",
        "missions/campaigns/sim/cases/geometric-conflict-resolution/3d-cases-v1.yaml",
    ),
    "real_mirrors": (
        "missions/campaigns/real/authorized_cases/basic-flight-and-route-following/real-mirrors-v1.yaml",
        "missions/campaigns/real/authorized_cases/constraints-and-optimization/real-mirrors-v1.yaml",
        "missions/campaigns/real/authorized_cases/coordination-and-allocation/real-mirrors-v1.yaml",
        "missions/campaigns/real/authorized_cases/geometric-conflict-resolution/real-mirrors-v1.yaml",
    ),
    "development_preset": (
        "missions/campaigns/sim/profiles/default-development-preset-v1.yaml",
    ),
}

GENERATED_OUTPUT_GLOBS = {
    "one_drone_missions": "missions/library/one_drone/*/mission.py",
    "campaign_case_manifests": "missions/campaigns/sim/cases/**/*-cases-v1.yaml",
    "real_mirrors": "missions/campaigns/real/authorized_cases/**/real-mirrors-v1.yaml",
    "development_preset": "missions/campaigns/sim/profiles/*.yaml",
}

BASELINE = {
    "straight": {
        "position_rmse_m": (0.080, 0.080, 0.080),
        "altitude_rmse_m": (0.040, 0.040, 0.040),
        "velocity_rmse_m_s": (0.100, 0.100, 0.100),
    },
    "curve": {
        "position_rmse_m": (0.070, 0.070, 0.070),
        "altitude_rmse_m": (0.035, 0.035, 0.035),
        "velocity_rmse_m_s": (0.090, 0.090, 0.090),
    },
}

CANDIDATES = {
    "pass": {
        "straight": {
            "position_rmse_m": (0.068, 0.068, 0.068),
            "altitude_rmse_m": (0.041, 0.041, 0.041),
            "velocity_rmse_m_s": (0.102, 0.102, 0.102),
        },
        "curve": {
            "position_rmse_m": (0.060, 0.060, 0.060),
            "altitude_rmse_m": (0.036, 0.036, 0.036),
            "velocity_rmse_m_s": (0.092, 0.092, 0.092),
        },
    },
    "fail_primary_and_guards": {
        "straight": {
            "position_rmse_m": (0.074, 0.074, 0.074),
            "altitude_rmse_m": (0.043, 0.043, 0.043),
            "velocity_rmse_m_s": (0.106, 0.106, 0.106),
        },
        "curve": {
            "position_rmse_m": (0.066, 0.066, 0.066),
            "altitude_rmse_m": (0.038, 0.038, 0.038),
            "velocity_rmse_m_s": (0.096, 0.096, 0.096),
        },
    },
    "fail_nonrepeatable": {
        "straight": {
            "position_rmse_m": (0.068, 0.068, 0.068000000002),
            "altitude_rmse_m": (0.041, 0.041, 0.041),
            "velocity_rmse_m_s": (0.102, 0.102, 0.102),
        },
        "curve": {
            "position_rmse_m": (0.060, 0.060, 0.060),
            "altitude_rmse_m": (0.036, 0.036, 0.036),
            "velocity_rmse_m_s": (0.092, 0.092, 0.092),
        },
    },
}

MOTION_SAFETY_GUARD_REGISTRY: dict[str, dict[str, Any]] = {
    "speed_compliance_fraction": {
        "relation": "MINIMUM_AND_MAXIMUM_REGRESSION",
        "hard_threshold": 0.95,
        "maximum_regression_fraction": 0.05,
    },
    "speed_ripple_m_s": {
        "relation": "MAXIMUM_AND_MAXIMUM_REGRESSION",
        "hard_threshold": 0.05,
        "maximum_regression_fraction": 0.05,
    },
    "acceleration_p95_m_s2": {
        "relation": "MAXIMUM_AND_MAXIMUM_REGRESSION",
        "hard_threshold": 1.0,
        "maximum_regression_fraction": 0.05,
    },
    "jerk_p95_m_s3": {
        "relation": "MAXIMUM_AND_MAXIMUM_REGRESSION",
        "hard_threshold": 8.0,
        "maximum_regression_fraction": 0.05,
    },
    "angular_rate_p95_rad_s": {
        "relation": "MAXIMUM_AND_MAXIMUM_REGRESSION",
        "hard_threshold": 0.40,
        "maximum_regression_fraction": 0.05,
    },
    "motor_spread_p95_percent": {
        "relation": "MAXIMUM_AND_MAXIMUM_REGRESSION",
        "hard_threshold": 0.50,
        "maximum_regression_fraction": 0.10,
    },
    "tracking_rms_m": {
        "relation": "MAXIMUM_AND_MAXIMUM_REGRESSION",
        "hard_threshold": 0.05,
        "maximum_regression_fraction": 0.05,
    },
    "path_tube_max_error_m": {
        "relation": "MAXIMUM_AND_MAXIMUM_REGRESSION",
        "hard_threshold": 0.05,
        "maximum_regression_fraction": 0.05,
    },
    "motor_saturation_fraction": {
        "relation": "MAXIMUM_AND_MAXIMUM_REGRESSION",
        "hard_threshold": 0.02,
        "maximum_regression_fraction": 0.05,
    },
    "duration_s": {
        "relation": "MAXIMUM_AND_MAXIMUM_REGRESSION",
        "hard_threshold": 17.5,
        "maximum_regression_fraction": 0.05,
    },
    "terminal_secondary_peak_m_s": {
        "relation": "MAXIMUM_AND_MAXIMUM_REGRESSION",
        "hard_threshold": 0.02,
        "maximum_regression_fraction": 0.05,
    },
    "terminal_reversal_count": {
        "relation": "MAXIMUM_EXACT",
        "hard_threshold": 0,
    },
    "minimum_clearance_m": {
        "relation": "MINIMUM_AND_MAXIMUM_REGRESSION",
        "hard_threshold": 0.15,
        "maximum_regression_fraction": 0.05,
    },
    "collision_count": {
        "relation": "MAXIMUM_EXACT",
        "hard_threshold": 0,
    },
    "supervisor_safety_gate_passed": {
        "relation": "BOOLEAN_TRUE",
        "hard_threshold": True,
    },
}

BASELINE_MOTION_SAFETY = {
    "straight": {
        "speed_compliance_fraction": 0.970,
        "speed_ripple_m_s": 0.040,
        "acceleration_p95_m_s2": 0.600,
        "jerk_p95_m_s3": 4.000,
        "angular_rate_p95_rad_s": 0.250,
        "motor_spread_p95_percent": 0.250,
        "tracking_rms_m": 0.035,
        "path_tube_max_error_m": 0.040,
        "motor_saturation_fraction": 0.005,
        "duration_s": 10.000,
        "terminal_secondary_peak_m_s": 0.010,
        "terminal_reversal_count": 0,
        "minimum_clearance_m": 0.200,
        "collision_count": 0,
        "supervisor_safety_gate_passed": True,
    },
    "curve": {
        "speed_compliance_fraction": 0.965,
        "speed_ripple_m_s": 0.042,
        "acceleration_p95_m_s2": 0.640,
        "jerk_p95_m_s3": 4.200,
        "angular_rate_p95_rad_s": 0.270,
        "motor_spread_p95_percent": 0.270,
        "tracking_rms_m": 0.036,
        "path_tube_max_error_m": 0.041,
        "motor_saturation_fraction": 0.006,
        "duration_s": 11.000,
        "terminal_secondary_peak_m_s": 0.011,
        "terminal_reversal_count": 0,
        "minimum_clearance_m": 0.190,
        "collision_count": 0,
        "supervisor_safety_gate_passed": True,
    },
}

PASS_MOTION_SAFETY = {
    "straight": {
        "speed_compliance_fraction": 0.960,
        "speed_ripple_m_s": 0.041,
        "acceleration_p95_m_s2": 0.620,
        "jerk_p95_m_s3": 4.100,
        "angular_rate_p95_rad_s": 0.260,
        "motor_spread_p95_percent": 0.260,
        "tracking_rms_m": 0.036,
        "path_tube_max_error_m": 0.041,
        "motor_saturation_fraction": 0.005,
        "duration_s": 10.200,
        "terminal_secondary_peak_m_s": 0.0104,
        "terminal_reversal_count": 0,
        "minimum_clearance_m": 0.195,
        "collision_count": 0,
        "supervisor_safety_gate_passed": True,
    },
    "curve": {
        "speed_compliance_fraction": 0.955,
        "speed_ripple_m_s": 0.043,
        "acceleration_p95_m_s2": 0.660,
        "jerk_p95_m_s3": 4.300,
        "angular_rate_p95_rad_s": 0.280,
        "motor_spread_p95_percent": 0.280,
        "tracking_rms_m": 0.037,
        "path_tube_max_error_m": 0.042,
        "motor_saturation_fraction": 0.006,
        "duration_s": 11.200,
        "terminal_secondary_peak_m_s": 0.0114,
        "terminal_reversal_count": 0,
        "minimum_clearance_m": 0.185,
        "collision_count": 0,
        "supervisor_safety_gate_passed": True,
    },
}

ISOLATED_MOTION_SAFETY_FAILURE_VALUES = {
    "speed_compliance_fraction": 0.94,
    "speed_ripple_m_s": 0.052,
    "acceleration_p95_m_s2": 0.700,
    "jerk_p95_m_s3": 4.400,
    "angular_rate_p95_rad_s": 0.280,
    "motor_spread_p95_percent": 0.280,
    "tracking_rms_m": 0.038,
    "path_tube_max_error_m": 0.052,
    "motor_saturation_fraction": 0.030,
    "duration_s": 10.600,
    "terminal_secondary_peak_m_s": 0.021,
    "terminal_reversal_count": 1,
    "minimum_clearance_m": 0.140,
    "collision_count": 1,
    "supervisor_safety_gate_passed": False,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _mean(values: tuple[float, ...] | list[float]) -> float:
    return sum(values) / len(values)


def _extract_base_design(active_path: Path) -> tuple[str, int]:
    text = active_path.read_text(encoding="utf-8")
    start = text.index(BEGIN)
    end = text.index(END, start) + len(END)
    payload = text[start:end].encode()
    return hashlib.sha256(payload).hexdigest(), len(payload)


def _guard_result(
    guard_id: str,
    baseline_values: list[float | int | bool],
    candidate_values: list[float | int | bool],
) -> dict[str, Any]:
    contract = MOTION_SAFETY_GUARD_REGISTRY[guard_id]
    relation = contract["relation"]
    threshold = contract["hard_threshold"]
    if relation == "BOOLEAN_TRUE":
        passed = all(value is True for value in candidate_values)
        baseline_mean: float | bool = all(value is True for value in baseline_values)
        candidate_mean: float | bool = all(value is True for value in candidate_values)
        regression = None
    else:
        numeric_baseline = [float(value) for value in baseline_values]
        numeric_candidate = [float(value) for value in candidate_values]
        baseline_mean = _mean(numeric_baseline)
        candidate_mean = _mean(numeric_candidate)
        maximum_regression = contract.get("maximum_regression_fraction")
        if relation == "MAXIMUM_EXACT":
            regression = None
            passed = max(numeric_candidate) <= float(threshold)
        elif relation == "MAXIMUM_AND_MAXIMUM_REGRESSION":
            regression = candidate_mean / baseline_mean - 1.0
            passed = max(numeric_candidate) <= float(threshold) and regression <= float(
                maximum_regression
            )
        elif relation == "MINIMUM_AND_MAXIMUM_REGRESSION":
            regression = 1.0 - candidate_mean / baseline_mean
            passed = min(numeric_candidate) >= float(threshold) and regression <= float(
                maximum_regression
            )
        else:  # pragma: no cover - frozen registry is exhaustively checked below
            raise ValueError(f"unknown motion/safety guard relation: {relation}")
    return {
        "guard_id": guard_id,
        "relation": relation,
        "hard_threshold": threshold,
        "maximum_regression_fraction": contract.get("maximum_regression_fraction"),
        "baseline_mean": baseline_mean,
        "candidate_mean": candidate_mean,
        "regression_fraction": regression,
        "passed": passed,
    }


def _guard_repeat_outputs(values: dict[str, float | int | bool]) -> dict[str, tuple[Any, ...]]:
    return {guard_id: (value, value, value) for guard_id, value in values.items()}


def _isolated_guard_candidate(guard_id: str) -> dict[str, dict[str, float | int | bool]]:
    candidate = {
        geometry: dict(values) for geometry, values in PASS_MOTION_SAFETY.items()
    }
    candidate["straight"][guard_id] = ISOLATED_MOTION_SAFETY_FAILURE_VALUES[guard_id]
    return candidate


def _calibration_scenario(
    name: str,
    candidate: dict[str, Any],
    *,
    motion_safety_candidate: dict[str, dict[str, float | int | bool]] | None = None,
    isolated_guard_id: str | None = None,
) -> dict[str, Any]:
    motion_safety_candidate = motion_safety_candidate or PASS_MOTION_SAFETY
    geometries: dict[str, Any] = {}
    all_baseline_position: list[float] = []
    all_candidate_position: list[float] = []
    secondary_aggregate: dict[str, dict[str, list[float]]] = {
        metric: {"baseline": [], "candidate": []}
        for metric in ("altitude_rmse_m", "velocity_rmse_m_s")
    }
    motion_guard_aggregate: dict[str, dict[str, list[float | int | bool]]] = {
        guard_id: {"baseline": [], "candidate": []}
        for guard_id in MOTION_SAFETY_GUARD_REGISTRY
    }
    repeatable = True
    for geometry in ("straight", "curve"):
        baseline = BASELINE[geometry]
        subject = candidate[geometry]
        baseline_motion = _guard_repeat_outputs(BASELINE_MOTION_SAFETY[geometry])
        candidate_motion = _guard_repeat_outputs(motion_safety_candidate[geometry])
        baseline_outputs = {**baseline, **baseline_motion}
        candidate_outputs = {**subject, **candidate_motion}
        repeat_vectors = [
            {metric: candidate_outputs[metric][index] for metric in sorted(candidate_outputs)}
            for index in range(3)
        ]
        repeat_hashes = [_canonical_sha256(vector) for vector in repeat_vectors]
        spans = {
            metric: float(max(values)) - float(min(values))
            for metric, values in candidate_outputs.items()
        }
        geometry_repeatable = (
            len(set(repeat_hashes)) == 1 and max(spans.values()) <= 1e-12
        )
        repeatable = repeatable and geometry_repeatable
        baseline_position = _mean(baseline["position_rmse_m"])
        candidate_position = _mean(subject["position_rmse_m"])
        all_baseline_position.extend(baseline["position_rmse_m"])
        all_candidate_position.extend(subject["position_rmse_m"])
        guard_results: dict[str, Any] = {}
        for metric in ("altitude_rmse_m", "velocity_rmse_m_s"):
            baseline_mean = _mean(baseline[metric])
            candidate_mean = _mean(subject[metric])
            regression = candidate_mean / baseline_mean - 1.0
            guard_results[metric] = {
                "baseline_mean": baseline_mean,
                "candidate_mean": candidate_mean,
                "regression_fraction": regression,
                "threshold_max": 0.05,
                "passed": regression <= 0.05,
            }
            secondary_aggregate[metric]["baseline"].extend(baseline[metric])
            secondary_aggregate[metric]["candidate"].extend(subject[metric])
        motion_results = {}
        for guard_id in MOTION_SAFETY_GUARD_REGISTRY:
            baseline_values = list(baseline_motion[guard_id])
            candidate_values = list(candidate_motion[guard_id])
            motion_results[guard_id] = _guard_result(
                guard_id, baseline_values, candidate_values
            )
            motion_guard_aggregate[guard_id]["baseline"].extend(baseline_values)
            motion_guard_aggregate[guard_id]["candidate"].extend(candidate_values)
        geometries[geometry] = {
            "baseline_repeat_outputs": baseline_outputs,
            "candidate_repeat_outputs": candidate_outputs,
            "candidate_repeat_vectors": repeat_vectors,
            "candidate_repeat_hashes": repeat_hashes,
            "max_absolute_repeat_spread_by_metric": spans,
            "repeatability_tolerance": 1e-12,
            "repeatable": geometry_repeatable,
            "position_no_worse": candidate_position <= baseline_position,
            "residual_secondary_guards": guard_results,
            "motion_safety_guards": motion_results,
        }

    baseline_position = _mean(all_baseline_position)
    candidate_position = _mean(all_candidate_position)
    improvement_absolute = baseline_position - candidate_position
    improvement_fraction = improvement_absolute / baseline_position
    aggregate_residual_guards: dict[str, Any] = {}
    for metric, values in secondary_aggregate.items():
        baseline_mean = _mean(values["baseline"])
        candidate_mean = _mean(values["candidate"])
        regression = candidate_mean / baseline_mean - 1.0
        aggregate_residual_guards[metric] = {
            "baseline_mean": baseline_mean,
            "candidate_mean": candidate_mean,
            "regression_fraction": regression,
            "threshold_max": 0.05,
            "passed": regression <= 0.05,
        }
    primary_passed = (
        improvement_absolute >= 0.005
        and improvement_fraction >= 0.10
        and all(item["position_no_worse"] for item in geometries.values())
    )
    residual_guards_passed = all(
        guard["passed"]
        for item in geometries.values()
        for guard in item["residual_secondary_guards"].values()
    ) and all(guard["passed"] for guard in aggregate_residual_guards.values())
    aggregate_motion_guards = {
        guard_id: _guard_result(
            guard_id,
            values["baseline"],
            values["candidate"],
        )
        for guard_id, values in motion_guard_aggregate.items()
    }
    motion_safety_guards_passed = all(
        guard["passed"]
        for item in geometries.values()
        for guard in item["motion_safety_guards"].values()
    ) and all(guard["passed"] for guard in aggregate_motion_guards.values())
    changed_guard_ids = sorted(
        guard_id
        for guard_id in MOTION_SAFETY_GUARD_REGISTRY
        if any(
            motion_safety_candidate[geometry][guard_id]
            != PASS_MOTION_SAFETY[geometry][guard_id]
            for geometry in ("straight", "curve")
        )
    )
    isolated_change_passed = (
        changed_guard_ids == [isolated_guard_id] if isolated_guard_id is not None else True
    )
    verdict = (
        primary_passed
        and residual_guards_passed
        and motion_safety_guards_passed
        and repeatable
        and isolated_change_passed
    )
    return {
        "scenario": name,
        "three_whole_holdout_replays_per_geometry": True,
        "aggregation": "arithmetic mean over six whole-session replay outputs",
        "repeat_identity": "canonical metric-vector SHA-256 equality",
        "repeat_numeric_tolerance": 1e-12,
        "geometries": geometries,
        "aggregate": {
            "position_baseline_mean_m": baseline_position,
            "position_candidate_mean_m": candidate_position,
            "position_improvement_absolute_m": improvement_absolute,
            "position_improvement_fraction": improvement_fraction,
            "position_threshold_absolute_min_m": 0.005,
            "position_threshold_fraction_min": 0.10,
            "primary_passed": primary_passed,
            "residual_secondary_guards": aggregate_residual_guards,
            "residual_secondary_guards_passed": residual_guards_passed,
            "motion_safety_guards": aggregate_motion_guards,
            "motion_safety_guards_passed": motion_safety_guards_passed,
            "repeatable": repeatable,
        },
        "isolated_guard_id": isolated_guard_id,
        "changed_motion_safety_guard_ids": changed_guard_ids,
        "isolated_change_passed": isolated_change_passed,
        "promotion_oracle_passed": verdict,
    }


def _point_aabb_distance(
    point: tuple[float, float, float],
    minimum: tuple[float, float, float],
    maximum: tuple[float, float, float],
) -> float:
    squared = 0.0
    for value, low, high in zip(point, minimum, maximum, strict=True):
        delta = low - value if value < low else value - high if value > high else 0.0
        squared += delta * delta
    return math.sqrt(squared)


def _path_clearance(
    points: tuple[tuple[float, float, float], ...],
    obstacle_minimum: tuple[float, float, float],
    obstacle_maximum: tuple[float, float, float],
) -> float:
    distances: list[float] = []
    for before, after in pairwise(points):
        for index in range(1001):
            fraction = index / 1000.0
            point = tuple(
                before[axis] + (after[axis] - before[axis]) * fraction
                for axis in range(3)
            )
            distances.append(_point_aabb_distance(point, obstacle_minimum, obstacle_maximum))
    return min(distances)


def _path_length(points: tuple[tuple[float, float, float], ...]) -> float:
    return sum(
        math.sqrt(sum((after[axis] - before[axis]) ** 2 for axis in range(3)))
        for before, after in pairwise(points)
    )


def _wp59_reaction_safety_oracle() -> dict[str, Any]:
    obstacle_minimum = (1.00, -0.25, 0.20)
    obstacle_maximum = (1.40, 0.25, 1.60)
    clearance_required_m = 0.15
    start = (0.00, 0.00, 1.00)
    nominal_state = (0.40, 0.00, 1.00)
    goal = (2.40, 0.00, 1.00)
    direct = (nominal_state, goal)
    detour = (nominal_state, (0.84, 0.41, 1.00), (1.56, 0.41, 1.00), goal)
    insufficient_detour = (
        nominal_state,
        (0.86, 0.39, 1.00),
        (1.54, 0.39, 1.00),
        goal,
    )
    latencies = {
        "sensor_capture_s": 0.08,
        "transport_s": 0.04,
        "perception_processing_s": 0.03,
        "queue_s": 0.02,
        "planning_s": 0.20,
        "acknowledgement_s": 0.04,
        "commit_s": 0.03,
        "cutover_guard_s": 0.10,
    }
    total_reaction_s = sum(latencies.values())
    prediction_horizon_s = 1.50
    nominal_truth_s = 2.00
    nominal_capture_s = nominal_truth_s + latencies["sensor_capture_s"]
    nominal_receive_s = nominal_capture_s + latencies["transport_s"]
    nominal_processing_complete_s = nominal_receive_s + latencies[
        "perception_processing_s"
    ]
    nominal_cutover_s = nominal_truth_s + total_reaction_s
    nominal_effective_s = 3.20
    observation_payload = {
        "mission_id": "1d.reality_obstacle_replan.canonical_nominal",
        "run_id": "prototype-run",
        "vehicle_id": "drone-1",
        "sensor_id": "sim-depth-front",
        "sensor_configuration_sha256": "1" * 64,
        "world_revision": 2,
        "sequence": 1,
        "truth_event_source_s": nominal_truth_s,
        "source_timestamp_s": nominal_capture_s,
        "received_timestamp_s": nominal_receive_s,
        "confidence": 0.98,
        "region_id": "appearing-wall-1",
        "region_minimum_m": obstacle_minimum,
        "region_maximum_m": obstacle_maximum,
    }
    observation_raw_sha256 = _canonical_sha256(observation_payload)
    initial_plan_payload = {
        "start_m": start,
        "goal_m": goal,
        "flight_volume_minimum_m": (-1.0, -1.0, 0.0),
        "flight_volume_maximum_m": (3.0, 1.0, 2.0),
        "initially_perceived_solids": (),
    }
    initial_plan_sha256 = _canonical_sha256(initial_plan_payload)
    truth_world_sha256 = _canonical_sha256(
        {"revision": 2, "solids": (("appearing-wall-1", obstacle_minimum, obstacle_maximum),)}
    )
    perceived_world_sha256 = _canonical_sha256(
        {
            "revision": 2,
            "source_observation_sha256": observation_raw_sha256,
            "solids": (("appearing-wall-1", obstacle_minimum, obstacle_maximum),),
        }
    )
    direct_clearance = _path_clearance(direct, obstacle_minimum, obstacle_maximum)
    detour_clearance = _path_clearance(detour, obstacle_minimum, obstacle_maximum)
    insufficient_clearance = _path_clearance(
        insufficient_detour, obstacle_minimum, obstacle_maximum
    )
    supervisor_reaction_s = sum(
        latencies[key]
        for key in ("sensor_capture_s", "transport_s", "perception_processing_s", "queue_s")
    )
    nominal_speed_m_s = 0.30
    maximum_braking_m_s2 = 0.80
    hold_drift_m = 0.08
    position_uncertainty_m = 0.03
    nominal_reaction_distance = nominal_speed_m_s * supervisor_reaction_s
    nominal_braking_distance = nominal_speed_m_s**2 / (2.0 * maximum_braking_m_s2)
    nominal_stopping_envelope = (
        nominal_reaction_distance
        + nominal_braking_distance
        + hold_drift_m
        + position_uncertainty_m
    )
    expanded_obstacle_front_x = obstacle_minimum[0] - clearance_required_m
    nominal_available_stopping_distance = expanded_obstacle_front_x - nominal_state[0]
    nominal_safe_until_s = nominal_processing_complete_s + (
        nominal_available_stopping_distance - position_uncertainty_m
    ) / nominal_speed_m_s
    nominal_certificate_payload = {
        "accepted_trajectory_sha256": "2" * 64,
        "observation_sha256": observation_raw_sha256,
        "perceived_world_sha256": perceived_world_sha256,
        "world_revision": 2,
        "vehicle_state": {
            "source_timestamp_s": nominal_capture_s,
            "position_m": nominal_state,
            "velocity_m_s": (nominal_speed_m_s, 0.0, 0.0),
        },
        "safe_until_source_s": nominal_safe_until_s,
        "stopping_envelope_m": nominal_stopping_envelope,
        "fallback_command": "STOP_AND_HOLD",
    }
    nominal_certificate_sha256 = _canonical_sha256(nominal_certificate_payload)

    late_truth_s = 3.00
    late_effective_s = 3.30
    late_state = (0.74, 0.00, 1.00)
    late_speed_m_s = 0.10
    late_reaction_distance = late_speed_m_s * supervisor_reaction_s
    late_braking_distance = late_speed_m_s**2 / (2.0 * maximum_braking_m_s2)
    late_stopping_envelope = (
        late_reaction_distance
        + late_braking_distance
        + hold_drift_m
        + position_uncertainty_m
    )
    late_available_stopping_distance = expanded_obstacle_front_x - late_state[0]
    brake_peak = (
        late_state[0] + late_reaction_distance + late_braking_distance,
        0.0,
        1.0,
    )
    accepted_landing = (0.30, 0.00, 0.05)
    abort_path = (late_state, brake_peak, (0.30, 0.00, 1.00), accepted_landing)
    abort_clearance = _path_clearance(abort_path, obstacle_minimum, obstacle_maximum)
    late_abort_payload = {
        "accepted_landing_region_id": "base-landing",
        "path_m": abort_path,
        "minimum_clearance_m": abort_clearance,
        "required_clearance_m": clearance_required_m,
        "command": "ABORT_AND_LAND",
    }
    late_abort_sha256 = _canonical_sha256(late_abort_payload)
    nominal_checks = {
        "future_truth_excluded_from_initial_plan": (
            "appearing-wall-1"
            not in json.dumps(initial_plan_payload, sort_keys=True)
        ),
        "observation_latency_is_realistic": math.isclose(
            nominal_capture_s - nominal_truth_s, 0.08, abs_tol=1e-12
        ),
        "observation_fresh": nominal_receive_s - nominal_capture_s <= 0.25,
        "prediction_horizon_covers_reaction": prediction_horizon_s >= total_reaction_s,
        "reaction_finishes_before_effect": nominal_cutover_s <= nominal_effective_s,
        "direct_path_is_blocked": direct_clearance < clearance_required_m,
        "detour_clearance_passed": detour_clearance >= clearance_required_m,
        "detour_is_nontrivial": _path_length(detour) > _path_length(direct) + 0.05,
        "safe_prefix_covers_cutover": nominal_safe_until_s >= nominal_cutover_s,
        "hold_is_certified": (
            nominal_available_stopping_distance >= nominal_stopping_envelope
        ),
    }
    late_checks = {
        "reaction_horizon_blocks_replacement": (
            late_effective_s - late_truth_s < total_reaction_s
        ),
        "stop_and_hold_not_certified": (
            late_available_stopping_distance < late_stopping_envelope
        ),
        "accepted_abort_route_certified": abort_clearance >= clearance_required_m,
    }
    perturbations = {
        "zero_latency_future_leak": {
            "changed": {"sensor_capture_s": 0.0},
            "accepted": False,
            "reason": "sensor observation cannot precede the frozen 0.08 s capture latency",
        },
        "stale_observation": {
            "changed": {"receive_minus_source_s": 0.26},
            "accepted": False,
            "reason": "observation exceeds the 0.25 s freshness limit",
        },
        "tampered_raw_hash": {
            "changed": {"raw_sha256_matches": False},
            "accepted": False,
            "reason": "perceived-world revision requires the exact persisted raw hash",
        },
        "wrong_world_revision": {
            "changed": {"certificate_world_revision": 1},
            "accepted": False,
            "reason": "certificate revision differs from perceived-world revision 2",
        },
        "insufficient_detour_clearance": {
            "changed": {"minimum_clearance_m": insufficient_clearance},
            "accepted": insufficient_clearance >= clearance_required_m,
            "reason": "route is below the 0.15 m clearance",
        },
        "reaction_lead_short_by_0_01_s": {
            "changed": {"available_lead_s": total_reaction_s - 0.01},
            "accepted": total_reaction_s - 0.01 >= total_reaction_s,
            "reason": "complete sensed-to-cutover budget does not fit",
        },
        "missing_safe_prefix_certificate": {
            "changed": {"certificate_present": False},
            "accepted": False,
            "reason": "caller safety booleans are not replacement authority",
        },
        "unsafe_hold_and_uncertified_abort": {
            "changed": {"hold_certified": False, "abort_certified": False},
            "accepted": False,
            "reason": "must request UNQUALIFIED_EMERGENCY_FALLBACK with zero replacement dispatch",
        },
    }
    return {
        "fixture_id": "wp59-sensed-world-reaction-safety-v1",
        "world_geometry": {
            "flight_volume_minimum_m": (-1.0, -1.0, 0.0),
            "flight_volume_maximum_m": (3.0, 1.0, 2.0),
            "start_m": start,
            "goal_m": goal,
            "obstacle_minimum_m": obstacle_minimum,
            "obstacle_maximum_m": obstacle_maximum,
            "required_clearance_m": clearance_required_m,
        },
        "latency_budget": {
            **latencies,
            "total_reaction_s": total_reaction_s,
            "prediction_horizon_s": prediction_horizon_s,
        },
        "world_lineage": {
            "initial_plan_sha256": initial_plan_sha256,
            "truth_world_sha256": truth_world_sha256,
            "observation_raw_sha256": observation_raw_sha256,
            "perceived_world_sha256": perceived_world_sha256,
        },
        "nominal_detour": {
            "truth_event_source_s": nominal_truth_s,
            "sensor_source_s": nominal_capture_s,
            "received_source_s": nominal_receive_s,
            "processing_complete_source_s": nominal_processing_complete_s,
            "effective_source_s": nominal_effective_s,
            "cutover_source_s": nominal_cutover_s,
            "vehicle_state_position_m": nominal_state,
            "vehicle_velocity_m_s": (nominal_speed_m_s, 0.0, 0.0),
            "direct_path_m": direct,
            "direct_clearance_m": direct_clearance,
            "detour_path_m": detour,
            "detour_clearance_m": detour_clearance,
            "direct_path_length_m": _path_length(direct),
            "detour_path_length_m": _path_length(detour),
            "safe_prefix_certificate": {
                **nominal_certificate_payload,
                "certificate_sha256": nominal_certificate_sha256,
            },
            "checks": nominal_checks,
            "accepted": all(nominal_checks.values()),
        },
        "certified_hold": {
            "planner_result": "INFEASIBLE",
            "stopping_envelope_m": nominal_stopping_envelope,
            "available_stopping_distance_m": nominal_available_stopping_distance,
            "command": "STOP_AND_HOLD",
            "certificate_sha256": nominal_certificate_sha256,
            "certified": nominal_checks["hold_is_certified"],
        },
        "late_certified_abort": {
            "truth_event_source_s": late_truth_s,
            "effective_source_s": late_effective_s,
            "available_event_lead_s": late_effective_s - late_truth_s,
            "vehicle_state_position_m": late_state,
            "vehicle_velocity_m_s": (late_speed_m_s, 0.0, 0.0),
            "stopping_envelope_m": late_stopping_envelope,
            "available_stopping_distance_m": late_available_stopping_distance,
            "abort_route": late_abort_payload,
            "abort_certificate_sha256": late_abort_sha256,
            "checks": late_checks,
            "command": "ABORT_AND_LAND",
            "certified": all(late_checks.values()),
        },
        "perturbations": perturbations,
        "all_perturbations_rejected": all(
            item["accepted"] is False for item in perturbations.values()
        ),
        "passed": (
            all(nominal_checks.values())
            and all(late_checks.values())
            and all(item["accepted"] is False for item in perturbations.values())
        ),
    }


def _evaluation_identity_audit(workspace: Path) -> dict[str, Any]:
    checked: list[dict[str, Any]] = []
    for path in sorted((workspace / "evidence").glob("*/evaluation.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        recorded = report.pop("report_sha256", None)
        recomputed = _canonical_sha256(report)
        checked.append(
            {
                "path": str(path),
                "recorded_report_sha256": recorded,
                "recomputed_report_sha256": recomputed,
                "passed": recorded == recomputed,
            }
        )
    return {
        "checked_count": len(checked),
        "reports": checked,
        "all_passed": bool(checked) and all(item["passed"] for item in checked),
    }


def _claim_matrix_audit(active_path: Path, manifest_paths: set[str]) -> dict[str, Any]:
    text = active_path.read_text(encoding="utf-8")
    start = text.index(BEGIN)
    end = text.index(END, start) + len(END)
    base_payload = text[start:end]
    observed_rows = tuple(
        match.group(1)
        for match in re.finditer(
            r"^\| (WP-(?:57|58|59|60|61)(?:[A-G])?(?: parent)?) \|",
            base_payload,
            flags=re.MULTILINE,
        )
    )
    binding_keys = tuple(CLAIM_OWNER_BINDINGS)
    owner_rows = {
        claim: {
            "paths": paths,
            "missing_from_manifest": sorted(set(paths) - manifest_paths),
            "passed": set(paths) <= manifest_paths,
        }
        for claim, paths in CLAIM_OWNER_BINDINGS.items()
    }
    return {
        "expected_rows": EXPECTED_CLAIM_ROWS,
        "observed_rows": observed_rows,
        "binding_keys": binding_keys,
        "row_set_exact": observed_rows == EXPECTED_CLAIM_ROWS,
        "binding_set_exact": binding_keys == EXPECTED_CLAIM_ROWS,
        "owners_by_claim": owner_rows,
        "passed": (
            observed_rows == EXPECTED_CLAIM_ROWS
            and binding_keys == EXPECTED_CLAIM_ROWS
            and all(item["passed"] for item in owner_rows.values())
        ),
    }


def _public_transit_audit(root: Path, manifest_paths: set[str]) -> dict[str, Any]:
    rows = {}
    for relative_path, tokens in PUBLIC_TRANSIT_PROBES.items():
        text = (root / relative_path).read_text(encoding="utf-8")
        missing_tokens = tuple(token for token in tokens if token not in text)
        rows[relative_path] = {
            "required_tokens": tokens,
            "missing_tokens": missing_tokens,
            "in_manifest": relative_path in manifest_paths,
            "passed": not missing_tokens and relative_path in manifest_paths,
        }
    return {"nodes": rows, "passed": all(item["passed"] for item in rows.values())}


def _generated_output_audit(root: Path, manifest_paths: set[str]) -> dict[str, Any]:
    rows = {}
    for group, pattern in GENERATED_OUTPUT_GLOBS.items():
        discovered = tuple(
            sorted(str(path.relative_to(root)) for path in root.glob(pattern) if path.is_file())
        )
        expected = tuple(sorted(EXPECTED_GENERATED_OUTPUTS[group]))
        rows[group] = {
            "glob": pattern,
            "expected_paths": expected,
            "discovered_paths": discovered,
            "missing_from_manifest": sorted(set(discovered) - manifest_paths),
            "set_exact": discovered == expected,
            "passed": discovered == expected and set(discovered) <= manifest_paths,
        }
    return {"groups": rows, "passed": all(item["passed"] for item in rows.values())}


def build_audit(root: Path, workspace: Path) -> dict[str, Any]:
    active_path = root / "docs/work-packages/ACTIVE.md"
    base_design_sha256, base_design_bytes = _extract_base_design(active_path)
    base_audit_path = (
        root
        / "missions/campaigns/sim/qualification/"
        "wp57-61-predraft-1d-evidence-v1.json"
    )
    base_audit = json.loads(base_audit_path.read_text(encoding="utf-8"))
    boundary_rows = []
    for relative_path, (expected_sha256, classification) in sorted(
        EXISTING_BOUNDARIES.items()
    ):
        path = root / relative_path
        actual = _sha256(path) if path.is_file() else None
        boundary_rows.append(
            {
                "path": relative_path,
                "classification": classification,
                "expected_sha256": expected_sha256,
                "actual_sha256": actual,
                "passed": actual == expected_sha256,
            }
        )
    intended_new_rows = [
        {
            "path": relative_path,
            "classification": "INTENDED_NEW_ABSENT_AT_DESIGN_FREEZE",
            "absent": not (root / relative_path).exists(),
        }
        for relative_path in INTENDED_NEW_BOUNDARIES
    ]
    manifest_paths = set(EXISTING_BOUNDARIES) | set(INTENDED_NEW_BOUNDARIES)
    group_rows = {
        group: {
            "paths": paths,
            "missing_from_manifest": sorted(set(paths) - manifest_paths),
            "passed": set(paths) <= manifest_paths,
        }
        for group, paths in CLAIM_AND_TRANSIT_GROUPS.items()
    }
    calibration = {
        name: _calibration_scenario(name, candidate)
        for name, candidate in CANDIDATES.items()
    }
    isolated_motion_safety_failures = {
        guard_id: _calibration_scenario(
            f"fail_motion_safety_guard.{guard_id}",
            CANDIDATES["pass"],
            motion_safety_candidate=_isolated_guard_candidate(guard_id),
            isolated_guard_id=guard_id,
        )
        for guard_id in MOTION_SAFETY_GUARD_REGISTRY
    }
    claim_matrix = _claim_matrix_audit(active_path, manifest_paths)
    public_transit = _public_transit_audit(root, manifest_paths)
    generated_outputs = _generated_output_audit(root, manifest_paths)
    reaction_safety = _wp59_reaction_safety_oracle()
    identities = {
        "base_design": {
            "expected_sha256": BASE_DESIGN_SHA256,
            "actual_sha256": base_design_sha256,
            "byte_count": base_design_bytes,
            "passed": base_design_sha256 == BASE_DESIGN_SHA256,
        },
        "base_audit_script": {
            "expected_sha256": BASE_AUDIT_SCRIPT_SHA256,
            "actual_sha256": _sha256(root / "scripts/audit_wp57_61_design.py"),
        },
        "base_audit_file": {
            "expected_sha256": BASE_AUDIT_FILE_SHA256,
            "actual_sha256": _sha256(base_audit_path),
        },
        "base_audit_payload": {
            "expected_sha256": BASE_AUDIT_PAYLOAD_SHA256,
            "actual_sha256": base_audit.get("payload_sha256"),
        },
        "workflow": {
            "expected_sha256": WORKFLOW_SHA256,
            "actual_sha256": _sha256(
                root / "docs/project/WORKFLOW_AND_REQUIREMENTS.md"
            ),
        },
    }
    for item in identities.values():
        item.setdefault("passed", item["actual_sha256"] == item["expected_sha256"])
    evaluation_identities = _evaluation_identity_audit(workspace)
    checks = {
        "all_frozen_identities_passed": all(
            item["passed"] for item in identities.values()
        ),
        "all_existing_boundary_preimages_passed": all(
            item["passed"] for item in boundary_rows
        ),
        "all_intended_new_boundaries_absent": all(
            item["absent"] for item in intended_new_rows
        ),
        "all_claim_and_transit_groups_closed": all(
            item["passed"] for item in group_rows.values()
        ),
        "claim_matrix_owner_set_closed": claim_matrix["passed"],
        "public_transit_nodes_closed": public_transit["passed"],
        "generated_output_sets_closed": generated_outputs["passed"],
        "wp59_reaction_safety_prototype_passed": reaction_safety["passed"],
        "calibration_pass_vector_accepted": calibration["pass"][
            "promotion_oracle_passed"
        ],
        "calibration_primary_guard_fail_vector_rejected": not calibration[
            "fail_primary_and_guards"
        ]["promotion_oracle_passed"],
        "calibration_nonrepeatable_vector_rejected": not calibration[
            "fail_nonrepeatable"
        ]["promotion_oracle_passed"],
        "every_motion_safety_guard_has_one_isolated_rejection": (
            set(isolated_motion_safety_failures) == set(MOTION_SAFETY_GUARD_REGISTRY)
            and all(
                not item["promotion_oracle_passed"]
                and item["changed_motion_safety_guard_ids"] == [guard_id]
                and item["isolated_change_passed"]
                and item["aggregate"]["primary_passed"]
                and item["aggregate"]["residual_secondary_guards_passed"]
                and item["aggregate"]["repeatable"]
                for guard_id, item in isolated_motion_safety_failures.items()
            )
        ),
        "evaluation_report_identities_recomputed": evaluation_identities[
            "all_passed"
        ],
    }
    payload: dict[str, Any] = {
        "schema_version": 1,
        "purpose": "WP-57 through WP-61 final design-cycle corrective audit",
        "requirements_applied": ("REQ-WFL-046", "REQ-WFL-047", "REQ-WFL-048"),
        "frozen_identities": identities,
        "wp59_reaction_safety_oracle": reaction_safety,
        "calibration_oracle": {
            **calibration,
            "motion_safety_guard_registry": MOTION_SAFETY_GUARD_REGISTRY,
            "isolated_motion_safety_guard_failures": isolated_motion_safety_failures,
        },
        "affected_boundary_closure": {
            "existing_boundaries": boundary_rows,
            "intended_new_boundaries": intended_new_rows,
            "claim_and_transit_groups": group_rows,
            "claim_matrix": claim_matrix,
            "public_transit": public_transit,
            "generated_outputs": generated_outputs,
        },
        "evaluation_identity_audit": evaluation_identities,
        "checks": checks,
        "passed": all(checks.values()),
    }
    payload["payload_sha256"] = _canonical_sha256(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--workspace", type=Path, default=Path(".cache/crazyswarm/campaign")
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", type=Path)
    arguments = parser.parse_args()
    audit = build_audit(arguments.root, arguments.workspace)
    rendered = json.dumps(audit, indent=2, sort_keys=True) + "\n"
    if arguments.check is not None:
        if arguments.check.read_text(encoding="utf-8") != rendered:
            raise SystemExit("retained WP-57 through WP-61 R2 design audit is stale")
    elif arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    print(
        json.dumps(
            {
                "passed": audit["passed"],
                "payload_sha256": audit["payload_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0 if audit["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
