"""Vehicle interfaces and adapters."""

from crazyswarm_app.vehicles.base import Vehicle
from crazyswarm_app.vehicles.crazyflie import CrazyflieVehicle
from crazyswarm_app.vehicles.isaac import IsaacSimVehicle
from crazyswarm_app.vehicles.mock_isaac import MockGatewayFault, MockIsaacSimVehicle

__all__ = [
    "CrazyflieVehicle",
    "IsaacSimVehicle",
    "MockGatewayFault",
    "MockIsaacSimVehicle",
    "Vehicle",
]
