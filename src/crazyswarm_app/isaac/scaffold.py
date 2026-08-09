from __future__ import annotations

from crazyswarm_app.domain.models import Vector3
from crazyswarm_app.domain.simulation import VehicleParameterSchema
from crazyswarm_app.isaac.scene import IsaacSceneSpecification

QUALIFICATION = "CONFIGURED_UNQUALIFIED"


def render_minimal_usda(
    scene: IsaacSceneSpecification,
    parameters: VehicleParameterSchema,
    *,
    include_environment: bool,
) -> str:
    """Render deterministic OpenUSD scaffolding without claiming an Isaac runtime result."""

    scene.validate_parameter_source(parameters)
    vehicle = scene.vehicles[0]
    body = vehicle.body_geometry.dimensions_m
    rotor = vehicle.rotor_geometry.dimensions_m
    lines = [
        "#usda 1.0",
        "(",
        '    defaultPrim = "World"',
        "    metersPerUnit = 1",
        '    upAxis = "Z"',
        "    customLayerData = {",
        f'        string qualification = "{QUALIFICATION}"',
        '        string implementationStatus = "SCAFFOLD_NOT_RUN_IN_ISAAC"',
        f'        string sceneId = "{scene.scene_id}"',
        f'        string sceneVersion = "{scene.scene_version}"',
        f'        string sceneConfigurationSha256 = "{scene.sha256}"',
        f'        string parameterConfigurationSha256 = "{parameters.sha256}"',
        "    }",
        ")",
        "",
        'def Xform "World"',
        "{",
        '    custom string crazyswarm:qualification = "CONFIGURED_UNQUALIFIED"',
        "    custom bool crazyswarm:physicalModelAuthorized = false",
        "    custom bool crazyswarm:digitalTwinEnabled = false",
        '    def PhysicsScene "PhysicsScene"',
        "    {",
        "        vector3f physics:gravityDirection = (0, 0, -1)",
        f"        float physics:gravityMagnitude = {_number(abs(scene.world.gravity_m_s2.value))}",
        "    }",
    ]
    if include_environment:
        lines.extend(_environment_lines(scene))
    lines.extend(
        _vehicle_lines(
            vehicle_id=vehicle.vehicle_id,
            ros_namespace=vehicle.ros_namespace,
            initial_position=vehicle.initial_position_m,
            initial_yaw_rad=vehicle.initial_yaw_rad,
            body_dimensions=body,
            rotor_dimensions=rotor,
            parameters=parameters,
        )
    )
    lines.extend(("}", ""))
    return "\n".join(lines)


def _vehicle_lines(
    *,
    vehicle_id: str,
    ros_namespace: str,
    initial_position: Vector3,
    initial_yaw_rad: float,
    body_dimensions: Vector3,
    rotor_dimensions: Vector3,
    parameters: VehicleParameterSchema,
) -> list[str]:
    body_z = body_dimensions.z / 2.0
    result = [
        '    def Scope "Crazyflies"',
        "    {",
        f'        def Xform "{vehicle_id}"',
        "        {",
        f'            custom string crazyswarm:qualification = "{QUALIFICATION}"',
        f'            custom string crazyswarm:rosNamespace = "{ros_namespace}"',
        f'            custom string crazyswarm:modelId = "{parameters.model_id}"',
        f'            custom string crazyswarm:modelVersion = "{parameters.model_version}"',
        '            custom string crazyswarm:sourceClass = "SIMULATED_MODEL"',
        f"            double3 xformOp:translate = {_tuple(initial_position)}",
        "            double xformOp:rotateZ = "
        f"{_number(initial_yaw_rad * 180.0 / 3.141592653589793)}",
        '            uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateZ"]',
        '            def Xform "Body" (',
        '                prepend apiSchemas = ["PhysicsRigidBodyAPI", "PhysicsMassAPI"]',
        "            )",
        "            {",
        f'                custom string crazyswarm:qualification = "{QUALIFICATION}"',
        '                custom string crazyswarm:frame = "body"',
        "                bool physics:rigidBodyEnabled = true",
        f"                float physics:mass = {_number(parameters.total_mass_kg)}",
        "                point3f physics:centerOfMass = "
        f"{_tuple(parameters.center_of_mass_body_m)}",
        "                float3 physics:diagonalInertia = "
        f"({_number(parameters.inertia.xx_kg_m2)}, "
        f"{_number(parameters.inertia.yy_kg_m2)}, "
        f"{_number(parameters.inertia.zz_kg_m2)})",
        f"                double3 xformOp:translate = (0, 0, {_number(body_z)})",
        '                uniform token[] xformOpOrder = ["xformOp:translate"]',
        '                def Cube "CollisionVisual" (',
        '                    prepend apiSchemas = ["PhysicsCollisionAPI"]',
        "                )",
        "                {",
        f'                    custom string crazyswarm:qualification = "{QUALIFICATION}"',
        "                    double size = 1",
        f"                    float3 xformOp:scale = {_tuple(body_dimensions)}",
        '                    uniform token[] xformOpOrder = ["xformOp:scale"]',
        "                    bool physics:collisionEnabled = true",
        "                }",
    ]
    for rotor_parameter in parameters.rotors:
        position = rotor_parameter.position_body_m
        result.extend(
            (
                f'                def Cylinder "Rotor_{rotor_parameter.rotor_id}"',
                "                {",
                f'                    custom string crazyswarm:qualification = "{QUALIFICATION}"',
                "                    custom string crazyswarm:rotationDirection = "
                f'"{rotor_parameter.rotation_direction}"',
                '                    uniform token axis = "Z"',
                f"                    double radius = {_number(rotor_dimensions.x / 2.0)}",
                f"                    double height = {_number(rotor_dimensions.z)}",
                f"                    double3 xformOp:translate = {_tuple(position)}",
                '                    uniform token[] xformOpOrder = ["xformOp:translate"]',
                "                }",
            )
        )
    result.extend(_sensor_placeholder_lines())
    result.extend(("            }", "        }", "    }"))
    return result


def _sensor_placeholder_lines() -> list[str]:
    sensors = (
        ("Imu", "imu", (0.0, 0.0, 0.0), "+Z"),
        ("Flow", "flow", (0.0, 0.0, -0.01), "-Z"),
        ("RangeFront", "range/front", (0.0, 0.0, 0.0), "+X"),
        ("RangeBack", "range/back", (0.0, 0.0, 0.0), "-X"),
        ("RangeLeft", "range/left", (0.0, 0.0, 0.0), "+Y"),
        ("RangeRight", "range/right", (0.0, 0.0, 0.0), "-Y"),
        ("RangeUp", "range/up", (0.0, 0.0, 0.0), "+Z"),
        ("RangeDown", "range/down", (0.0, 0.0, 0.0), "-Z"),
    )
    result = [
        '                def Scope "SensorPlaceholders"',
        "                {",
        f'                    custom string crazyswarm:qualification = "{QUALIFICATION}"',
        '                    custom string crazyswarm:implementationStatus = "PLACEHOLDER_NOT_RUN"',
    ]
    for prim, signal, position, direction in sensors:
        result.extend(
            (
                f'                    def Xform "{prim}"',
                "                    {",
                f'                        custom string crazyswarm:signal = "{signal}"',
                f'                        custom string crazyswarm:direction = "{direction}"',
                "                        double3 xformOp:translate = "
                f"({_number(position[0])}, {_number(position[1])}, {_number(position[2])})",
                '                        uniform token[] xformOpOrder = ["xformOp:translate"]',
                "                    }",
            )
        )
    result.extend(("                }",))
    return result


def _environment_lines(scene: IsaacSceneSpecification) -> list[str]:
    dimensions = scene.world.dimensions_m
    thickness = scene.world.floor_thickness.value
    half_x = dimensions.x / 2.0
    half_y = dimensions.y / 2.0
    half_z = dimensions.z / 2.0
    walls = (
        (
            "WallPositiveX",
            (thickness, dimensions.y, dimensions.z),
            (half_x + thickness / 2.0, 0.0, half_z),
        ),
        (
            "WallNegativeX",
            (thickness, dimensions.y, dimensions.z),
            (-half_x - thickness / 2.0, 0.0, half_z),
        ),
        (
            "WallPositiveY",
            (dimensions.x, thickness, dimensions.z),
            (0.0, half_y + thickness / 2.0, half_z),
        ),
        (
            "WallNegativeY",
            (dimensions.x, thickness, dimensions.z),
            (0.0, -half_y - thickness / 2.0, half_z),
        ),
    )
    result = [
        '    def Scope "Environment"',
        "    {",
        f'        custom string crazyswarm:qualification = "{QUALIFICATION}"',
        '        custom string crazyswarm:implementationStatus = "PRIMITIVE_SCAFFOLD_NOT_RUN"',
        '        def Cube "Floor" (',
        '            prepend apiSchemas = ["PhysicsCollisionAPI"]',
        "        )",
        "        {",
        "            double size = 1",
        "            float3 xformOp:scale = "
        f"({_number(dimensions.x)}, {_number(dimensions.y)}, {_number(thickness)})",
        f"            double3 xformOp:translate = (0, 0, {_number(-thickness / 2.0)})",
        '            uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]',
        "            bool physics:collisionEnabled = true",
        "        }",
    ]
    for name, scale, translate in walls:
        result.extend(
            (
                f'        def Cube "{name}" (',
                '            prepend apiSchemas = ["PhysicsCollisionAPI"]',
                "        )",
                "        {",
                "            double size = 1",
                "            float3 xformOp:scale = "
                f"({_number(scale[0])}, {_number(scale[1])}, {_number(scale[2])})",
                "            double3 xformOp:translate = "
                f"({_number(translate[0])}, {_number(translate[1])}, {_number(translate[2])})",
                '            uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]',
                "            bool physics:collisionEnabled = true",
                "        }",
            )
        )
    result.extend(("    }",))
    return result


def _tuple(value: Vector3) -> str:
    return f"({_number(value.x)}, {_number(value.y)}, {_number(value.z)})"


def _number(value: float) -> str:
    return format(value, ".12g")
