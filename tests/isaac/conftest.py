from __future__ import annotations

import os
from collections.abc import Mapping

import pytest


@pytest.fixture
def live_isaac_environment() -> Mapping[str, str]:
    required = (
        "CRAZYSWARM_LIVE_ISAAC_HOST",
        "CRAZYSWARM_LIVE_ISAAC_PORT",
        "CRAZYSWARM_LIVE_ISAAC_SERVER_NAME",
        "CRAZYSWARM_LIVE_ISAAC_CA_CERTIFICATE",
        "CRAZYSWARM_ISAAC_GATEWAY_TOKEN",
    )
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        pytest.skip("WAITING_FOR_COMPATIBLE_LOCAL_OR_CLOUD_HOST: " + ", ".join(missing))
    return os.environ
