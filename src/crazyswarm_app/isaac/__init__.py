"""Isaac gateway contracts that remain importable without Isaac or ROS installed."""

from crazyswarm_app.isaac.protocol import GATEWAY_PROTOCOL_VERSION
from crazyswarm_app.isaac.scene import IsaacSceneSpecification, load_isaac_scene

__all__ = ["GATEWAY_PROTOCOL_VERSION", "IsaacSceneSpecification", "load_isaac_scene"]
