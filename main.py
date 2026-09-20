"""Top-down Ursina viewer for the plot-planning project."""

from __future__ import annotations

import os
from math import atan2, ceil, cos, degrees, pi, sin
from pathlib import Path

from ursina import (
    Entity,
    Mesh,
    Text,
    Ursina,
    Vec3,
    camera,
    clamp,
    color,
    destroy,
    scene,
    window,
)

from core import (
    Building,
    ContextArea,
    ContextLinearObject,
    JsonProjectRepository,
    Point2D,
    PrimitiveObject,
    Rgba,
    SiteFeature,
)


PROJECT_FILE = Path(__file__).with_name("data.json")
MIN_ORTHOGRAPHIC_FOV = 35
MAX_ORTHOGRAPHIC_FOV = 95
ZOOM_STEP = 4
WINDOW_TYPE = os.environ.get("PLOT_PLANNER_WINDOW_TYPE", "onscreen")
SKIP_APP_LOOP = os.environ.get("PLOT_PLANNER_SKIP_APP_LOOP") == "1"


repository = JsonProjectRepository(PROJECT_FILE)
project = repository.load()

app = Ursina(
    title="Планировщик дачного участка",
    borderless=False,
    size=(1400, 900),
    window_type=WINDOW_TYPE,
)
window.exit_button.enabled = True
window.color = color.rgb32(221, 225, 216)


def ursina_color(value: Rgba):
    return color.rgba32(value.red, value.green, value.blue, value.alpha)


def secondary_color_of(item) -> Rgba:
    return getattr(item, "secondary_color", None) or item.color


def create_line(
    start: Point2D,
    end: Point2D,
    line_color,
    width: float,
    y: float,
    parent=scene,
) -> Entity:
    dx = end.x - start.x
    dz = end.z - start.z
    length = (dx * dx + dz * dz) ** 0.5
    angle_y = -degrees(atan2(dz, dx))
    return Entity(
        parent=parent,
        model="cube",
        position=((start.x + end.x) / 2, y, (start.z + end.z) / 2),
        rotation_y=angle_y,
        scale=(length, width, width),
        color=line_color,
    )


def add_world_label(
    text: str,
    position: Point2D,
    y: float,
    parent=scene,
    scale: float = 36.0,
    label_color=color.black,
) -> Text:
    return Text(
        parent=parent,
        text=text,
        position=(position.x, y, position.z),
        origin=(0, 0),
        scale=scale,
        color=label_color,
        billboard=True,
    )


def draw_plot() -> None:
    boundary = project.plot.boundary
    vertices = [Vec3(point.x, 0.0, point.z) for point in boundary]
    triangles = [
        (0, index, index + 1) for index in range(1, len(vertices) - 1)
    ]
    plot_mesh = Mesh(vertices=vertices, triangles=triangles, mode="triangle")
    Entity(
        model=plot_mesh,
        color=ursina_color(project.plot.fill_color),
        double_sided=True,
        y=0.0,
    )

    for start, end in zip(boundary, boundary[1:] + boundary[:1]):
        create_line(
            start,
            end,
            ursina_color(project.plot.boundary_color),
            width=0.28,
            y=0.18,
        )

    draw_hatching(boundary)
    draw_markers()
    draw_north_arrow()


def draw_context_area(item: ContextArea) -> None:
    vertices = [Vec3(point.x, -0.04, point.z) for point in item.boundary]
    triangles = [
        (0, index, index + 1) for index in range(1, len(vertices) - 1)
    ]
    Entity(
        model=Mesh(vertices=vertices, triangles=triangles, mode="triangle"),
        color=ursina_color(item.color),
        double_sided=True,
        y=item.height_m,
    )


def draw_context_line(item: ContextLinearObject) -> None:
    line_width = item.width_m
    line_y = 0.03
    if item.style in {"fence", "boundary_fence"}:
        line_width = max(0.18, item.width_m)
        line_y = 0.28
    elif item.style == "ditch":
        line_y = 0.04
    elif item.style == "ditch_dash":
        line_y = 0.06
    points = item.world_points
    for start, end in zip(points, points[1:]):
        create_line(
            start,
            end,
            ursina_color(secondary_color_of(item)),
            width=line_width,
            y=line_y,
        )


def draw_surroundings() -> None:
    for area in project.surroundings.areas:
        draw_context_area(area)
    for item in project.surroundings.linear_objects:
        draw_context_line(item)
    for building in project.surroundings.buildings:
        draw_building(building)
    for feature in project.surroundings.features:
        draw_feature(feature)
    for primitive in project.surroundings.primitives:
        draw_primitive(primitive)


def draw_hatching(boundary: tuple[Point2D, ...]) -> None:
    minimum_z = min(point.z for point in boundary)
    maximum_z = max(point.z for point in boundary)
    z = minimum_z + project.plot.hatch.spacing_m / 2

    while z < maximum_z:
        intersections = _horizontal_intersections(boundary, z)
        for left_x, right_x in zip(intersections[::2], intersections[1::2]):
            create_line(
                Point2D(left_x, z),
                Point2D(right_x, z),
                ursina_color(project.plot.hatch.color),
                width=project.plot.hatch.line_width_m,
                y=0.08,
            )
        z += project.plot.hatch.spacing_m


def _horizontal_intersections(
    boundary: tuple[Point2D, ...], z: float
) -> list[float]:
    intersections: list[float] = []
    for start, end in zip(boundary, boundary[1:] + boundary[:1]):
        crosses = (start.z <= z < end.z) or (end.z <= z < start.z)
        if not crosses or start.z == end.z:
            continue
        ratio = (z - start.z) / (end.z - start.z)
        intersections.append(start.x + ratio * (end.x - start.x))
    return sorted(intersections)


def draw_markers() -> None:
    for marker in project.plot.markers:
        if marker.role == "reference_marker":
            continue
        Entity(
            model="sphere",
            position=(marker.position.x, 0.38, marker.position.z),
            scale=0.65,
            color=color.black,
        )
        add_world_label(
            marker.id,
            Point2D(marker.position.x + 0.8, marker.position.z + 0.8),
            y=0.6,
            scale=28.0,
        )


def draw_north_arrow() -> None:
    boundary = project.plot.boundary
    north = project.plot.north_unit_vector
    start = Point2D(
        min(point.x for point in boundary) - 4.0,
        min(point.z for point in boundary) + 4.0,
    )
    end = Point2D(start.x + north.x * 8.0, start.z + north.z * 8.0)
    arrow_color = color.rgb32(255, 45, 205)
    create_line(start, end, arrow_color, width=0.35, y=0.5)
    base = Point2D(end.x - north.x * 1.5, end.z - north.z * 1.5)
    perpendicular = Point2D(-north.z, north.x)
    for side in (-1, 1):
        wing = Point2D(
            base.x + perpendicular.x * 0.8 * side,
            base.z + perpendicular.z * 0.8 * side,
        )
        create_line(end, wing, arrow_color, width=0.35, y=0.5)
    add_world_label(
        "СЕВЕР",
        Point2D(end.x + north.x, end.z + north.z),
        y=0.75,
        scale=30,
        label_color=arrow_color,
    )


def draw_building(building: Building, parent=scene) -> None:
    Entity(
        parent=parent,
        model="cube",
        position=(building.center.x, building.height_m / 2, building.center.z),
        scale=(building.footprint.width, building.height_m, building.footprint.depth),
        rotation_y=building.rotation_y,
        color=ursina_color(building.color),
        texture="white_cube",
    )
    Entity(
        parent=parent,
        model="cube",
        position=(building.center.x, building.height_m + 0.01, building.center.z),
        scale=(building.footprint.width, 0.02, building.footprint.depth),
        rotation_y=building.rotation_y,
        color=ursina_color(secondary_color_of(building)),
    )
    add_world_label(
        building.name,
        building.center,
        y=building.height_m + 0.25,
        parent=parent,
        scale=38.0,
        label_color=color.white,
    )


def draw_feature(feature: SiteFeature, parent=scene) -> None:
    model = "sphere" if feature.shape == "circle" else "cube"
    height = 0.42 if feature.kind in {"well", "septic"} else 0.10
    Entity(
        parent=parent,
        model=model,
        position=(feature.center.x, height / 2 + 0.2, feature.center.z),
        scale=(feature.size.width, height, feature.size.depth),
        rotation_y=feature.rotation_y,
        color=ursina_color(feature.color),
        texture="white_cube",
    )
    Entity(
        parent=parent,
        model="cube",
        position=(feature.center.x, height + 0.21, feature.center.z),
        scale=(feature.size.width, 0.02, feature.size.depth),
        rotation_y=feature.rotation_y,
        color=ursina_color(secondary_color_of(feature)),
    )

    if feature.kind == "garden":
        draw_garden_rows(feature, parent)

    label_position = feature.center
    label_scale = 32.0
    label_color = color.white if feature.kind != "garden" else color.black
    if feature.kind in {"gate", "wicket"}:
        boundary_z = [point.z for point in project.plot.boundary]
        plot_mid_z = (min(boundary_z) + max(boundary_z)) / 2
        is_front = feature.center.z > plot_mid_z
        offset_z = 1.15 if is_front else -1.15
        label_position = Point2D(feature.center.x, feature.center.z + offset_z)
        label_scale = 21.0
        label_color = color.black
    elif feature.kind == "driveway_existing":
        label_position = Point2D(feature.center.x, feature.center.z - 1.25)
        label_scale = 22.0
        label_color = color.black
    elif feature.kind == "gravel_fill":
        label_scale = 22.0
        label_color = color.black

    add_world_label(
        feature.name,
        label_position,
        y=0.85,
        parent=parent,
        scale=label_scale,
        label_color=label_color,
    )


def draw_garden_rows(feature: SiteFeature, parent=scene) -> None:
    row_z = feature.center.z - feature.size.depth / 2 + 1.2
    final_z = feature.center.z + feature.size.depth / 2 - 0.8
    while row_z <= final_z:
        create_line(
            Point2D(feature.center.x - feature.size.width / 2 + 0.6, row_z),
            Point2D(feature.center.x + feature.size.width / 2 - 0.6, row_z),
            color.rgba32(45, 110, 43, 220),
            width=0.14,
            y=0.38,
            parent=parent,
        )
        row_z += 2.0


def make_arc_plan_mesh(item: PrimitiveObject) -> Mesh:
    angle = item.arc_angle_deg * pi / 180
    half_angle = angle / 2
    radius = item.size.x / angle
    inner_radius = radius - item.size.y / 2
    outer_radius = radius + item.size.y / 2
    chord_offset = radius * cos(half_angle)
    segments = max(8, ceil(item.arc_angle_deg / 5))
    vertices: list[tuple[float, float, float]] = []
    for index in range(segments + 1):
        sample = -half_angle + angle * index / segments
        vertices.extend(
            (
                (
                    inner_radius * sin(sample),
                    0,
                    inner_radius * cos(sample) - chord_offset,
                ),
                (
                    outer_radius * sin(sample),
                    0,
                    outer_radius * cos(sample) - chord_offset,
                ),
            )
        )
    triangles: list[tuple[int, int, int]] = []
    for index in range(segments):
        inner = index * 2
        following = inner + 2
        triangles.extend(
            (
                (inner, following, following + 1),
                (inner, following + 1, inner + 1),
            )
        )
    return Mesh(vertices=vertices, triangles=triangles, mode="triangle", static=True)


def draw_primitive(item: PrimitiveObject, parent=scene) -> None:
    if item.shape == "arc":
        model = make_arc_plan_mesh(item)
        item_scale = (1, 1, 1)
    else:
        model = "sphere" if item.shape == "cylinder" else "cube"
        item_scale = (item.size.x, 0.35, item.size.y)
    Entity(
        parent=parent,
        model=model,
        position=(item.center.x, 0.35, item.center.z),
        scale=item_scale,
        rotation_y=item.rotation_y,
        color=ursina_color(item.color),
        texture="white_cube",
    )
    Entity(
        parent=parent,
        model=model,
        position=(item.center.x, 0.55, item.center.z),
        scale=item_scale,
        rotation_y=item.rotation_y,
        color=ursina_color(secondary_color_of(item)),
    )
    add_world_label(
        item.name,
        item.center,
        y=0.8,
        parent=parent,
        scale=30.0,
        label_color=color.white,
    )


draw_surroundings()
draw_plot()
layout_root: Entity | None = None
fixed_objects_root: Entity | None = None
layout_title = Text(
    position=(-0.78, 0.41),
    origin=(-0.5, 0.5),
    scale=1.05,
    color=color.black,
)
layout_description = Text(
    text=" ",
    position=(-0.78, 0.365),
    origin=(-0.5, 0.5),
    scale=0.75,
    color=color.dark_gray,
    wordwrap=64,
)


def show_layout(layout_id: str) -> None:
    global layout_root, fixed_objects_root
    if layout_root is not None:
        destroy(layout_root)
    if fixed_objects_root is not None:
        destroy(fixed_objects_root)

    layout = project.layout(layout_id)
    layout_root = Entity(parent=scene)
    fixed_objects_root = Entity(parent=scene)
    hidden_ids = set(layout.hidden_fixed_ids)
    for building in project.fixed_buildings:
        if building.id not in hidden_ids:
            draw_building(building, fixed_objects_root)
    for feature in project.fixed_features:
        if feature.id not in hidden_ids:
            draw_feature(feature, fixed_objects_root)
    for building in layout.buildings:
        draw_building(building, layout_root)
    for feature in layout.features:
        draw_feature(feature, layout_root)
    for item in layout.primitives:
        draw_primitive(item, layout_root)

    layout_title.text = layout.name
    layout_description.text = layout.description


layout_keys = {
    str(index): layout.id for index, layout in enumerate(project.layouts, start=1)
}


def input(key: str) -> None:
    if key in layout_keys:
        show_layout(layout_keys[key])
    elif key == "scroll up":
        camera.fov = clamp(
            camera.fov - ZOOM_STEP, MIN_ORTHOGRAPHIC_FOV, MAX_ORTHOGRAPHIC_FOV
        )
    elif key == "scroll down":
        camera.fov = clamp(
            camera.fov + ZOOM_STEP, MIN_ORTHOGRAPHIC_FOV, MAX_ORTHOGRAPHIC_FOV
        )


plot_height = max(point.z for point in project.plot.boundary) - min(
    point.z for point in project.plot.boundary
)
plot_center_z = (
    max(point.z for point in project.plot.boundary)
    + min(point.z for point in project.plot.boundary)
) / 2

camera.orthographic = True
camera.position = (0, 100, plot_center_z)
camera.rotation = (90, 0, 0)
camera.fov = max(72, plot_height + 12)

Text(
    text="СЕВЕР",
    position=(0.70, 0.41),
    origin=(0, 0.5),
    scale=1.05,
    color=color.rgb32(24, 65, 135),
)
Text(
    text="1 / 2 / 3 — вариант   |   колесо — масштаб",
    position=(-0.78, -0.41),
    origin=(-0.5, -0.5),
    scale=0.85,
    color=color.black,
)
Text(
    text=(
        f"Фасад {project.plot.dimensions.front_width_m:g} м   "
        f"Тыл {project.plot.dimensions.rear_width_m:g} м   "
        f"Боковые {project.plot.dimensions.left_side_m:g} м   "
        f"Площадь {project.plot.area_sqm / 100:.2f} сот."
    ),
    position=(-0.78, -0.365),
    origin=(-0.5, -0.5),
    scale=0.75,
    color=color.dark_gray,
)

show_layout(project.active_layout_id)
if not SKIP_APP_LOOP:
    app.run()
