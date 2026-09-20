"""Interactive 3D editor for the land-plot planning project."""

from __future__ import annotations

import os
from math import atan2, ceil, cos, degrees, floor, pi, sin
from pathlib import Path
from uuid import uuid4

from panda3d.core import Point3
from ursina import (
    AmbientLight,
    BoxCollider,
    Button,
    CheckBox,
    DirectionalLight,
    Entity,
    Mesh,
    Sky,
    Text,
    Ursina,
    Vec2,
    Vec3,
    camera,
    color,
    destroy,
    held_keys,
    invoke,
    mouse,
    scene,
    window,
)
from ursina.prefabs.draggable import Draggable
from ursina.prefabs.dropdown_menu import DropdownMenu, DropdownMenuButton
from ursina.prefabs.editor_camera import EditorCamera
from ursina.prefabs.input_field import InputField
from ursina.shaders import lit_with_shadows_shader

from core import (
    ARC_VARIANTS,
    Building,
    ContextArea,
    ContextLinearObject,
    DomainValidationError,
    FENCE_OBJECT_ID,
    JsonProjectRepository,
    NATURE_VARIANTS,
    Point2D,
    PrimitiveObject,
    ProjectEditor,
    Rgba,
    RoofSpec,
    SiteFeature,
    Size2D,
    Size3D,
    WellStructure,
)


PROJECT_FILE = Path(__file__).with_name("data.json")
WINDOW_TYPE = os.environ.get("PLOT_PLANNER_WINDOW_TYPE", "onscreen")
SKIP_APP_LOOP = os.environ.get("PLOT_PLANNER_SKIP_APP_LOOP") == "1"
UI_FONT = "/c/Windows/Fonts/arial.ttf"
TREE_PHOTO_TEXTURES = {
    "pine_photo": "assets/trees/pine-photo.png",
    "birch_photo": "assets/trees/birch-photo.png",
    "ash_photo": "assets/trees/ash-photo.png",
}
PHOTO_TREE_DEFAULT_SIZES = {
    "pine_photo": Size3D(4.0, 4.0, 8.0),
    "birch_photo": Size3D(3.5, 3.5, 8.0),
    "ash_photo": Size3D(4.0, 4.0, 7.0),
}
PALETTE_COLORS = (
    ("Чёрный", "#000000"),
    ("Серый", "#808080"),
    ("Серебро", "#C0C0C0"),
    ("Белый", "#FFFFFF"),
    ("Бордовый", "#800000"),
    ("Красный", "#FF0000"),
    ("Оранжевый", "#FF8000"),
    ("Жёлтый", "#FFFF00"),
    ("Оливковый", "#808000"),
    ("Лайм", "#00FF00"),
    ("Зелёный", "#008000"),
    ("Бирюзовый", "#008080"),
    ("Голубой", "#00FFFF"),
    ("Синий", "#0000FF"),
    ("Тёмно-синий", "#000080"),
    ("Фиолетовый", "#800080"),
)

Text.default_font = UI_FONT

repository = JsonProjectRepository(PROJECT_FILE)
editor = ProjectEditor(repository)

app = Ursina(
    title="3D-планировщик дачного участка",
    borderless=False,
    size=(1500, 900),
    window_type=WINDOW_TYPE,
)
window.exit_button.enabled = True
window.color = color.rgb32(188, 205, 220)


class CyrillicInputField(InputField):
    """InputField using a Windows font that contains Cyrillic glyphs."""

    def __init__(self, default_value: str = "", **kwargs) -> None:
        super().__init__(default_value="", **kwargs)
        self.text_field.font = UI_FONT
        self.text_field.text_entity.font = UI_FONT
        self.text_field.line_numbers.font = UI_FONT
        self.text = default_value

    def input(self, key: str) -> None:
        if key == "tab" and self.active and self.on_submit:
            self.on_submit()
        super().input(key)


class ProtectedCheckBox(CheckBox):
    """Checkbox that reports its new value after the built-in toggle."""

    def __init__(self, on_change, **kwargs) -> None:
        self._on_change = on_change
        super().__init__(**kwargs)

    def on_click(self) -> None:
        super().on_click()
        self._on_change(self.value)


def to_color(value: Rgba):
    return color.rgba32(value.red, value.green, value.blue, value.alpha)


def secondary_color_of(item) -> Rgba:
    return getattr(item, "secondary_color", None) or item.color


def make_cylinder_mesh(segments: int = 32) -> Mesh:
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, ...]] = []

    for index in range(segments):
        angle = 2 * pi * index / segments
        x = cos(angle) * 0.5
        z = sin(angle) * 0.5
        vertices.append((x, 0, z))
        vertices.append((x, 1, z))

    bottom_center = len(vertices)
    vertices.append((0, 0, 0))
    top_center = len(vertices)
    vertices.append((0, 1, 0))

    for index in range(segments):
        next_index = (index + 1) % segments
        bottom = index * 2
        top = bottom + 1
        next_bottom = next_index * 2
        next_top = next_bottom + 1
        triangles.extend(
            (
                (bottom, next_bottom, next_top),
                (bottom, next_top, top),
                (bottom_center, next_bottom, bottom),
                (top_center, top, next_top),
            )
        )

    return Mesh(vertices=vertices, triangles=triangles, mode="triangle", static=True)


CYLINDER_MESH = make_cylinder_mesh()


def make_cone_mesh(segments: int = 32) -> Mesh:
    """Closed cone normalized to unit width, depth and height."""
    vertices = [
        (cos(2 * pi * index / segments) * 0.5, 0, sin(2 * pi * index / segments) * 0.5)
        for index in range(segments)
    ]
    base_center = len(vertices)
    vertices.append((0, 0, 0))
    apex = len(vertices)
    vertices.append((0, 1, 0))
    triangles: list[tuple[int, ...]] = []
    for index in range(segments):
        following = (index + 1) % segments
        triangles.extend(
            (
                (index, following, apex),
                (base_center, following, index),
            )
        )
    return Mesh(vertices=vertices, triangles=triangles, mode="triangle", static=True)


CONE_MESH = make_cone_mesh()


def make_ring_mesh(segments: int = 32, inner_ratio: float = 0.62) -> Mesh:
    """Concrete ring with a visible hollow centre, normalized to unit height."""
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, ...]] = []
    outer_radius = 0.5
    inner_radius = outer_radius * inner_ratio

    for index in range(segments):
        angle = 2 * pi * index / segments
        cosine = cos(angle)
        sine = sin(angle)
        vertices.extend(
            (
                (cosine * outer_radius, 0, sine * outer_radius),
                (cosine * outer_radius, 1, sine * outer_radius),
                (cosine * inner_radius, 0, sine * inner_radius),
                (cosine * inner_radius, 1, sine * inner_radius),
            )
        )

    for index in range(segments):
        following = (index + 1) % segments
        outer_bottom = index * 4
        outer_top = outer_bottom + 1
        inner_bottom = outer_bottom + 2
        inner_top = outer_bottom + 3
        next_outer_bottom = following * 4
        next_outer_top = next_outer_bottom + 1
        next_inner_bottom = next_outer_bottom + 2
        next_inner_top = next_outer_bottom + 3
        triangles.extend(
            (
                (outer_bottom, next_outer_bottom, next_outer_top),
                (outer_bottom, next_outer_top, outer_top),
                (inner_bottom, next_inner_top, next_inner_bottom),
                (inner_bottom, inner_top, next_inner_top),
                (outer_top, next_outer_top, next_inner_top),
                (outer_top, next_inner_top, inner_top),
                (outer_bottom, next_inner_bottom, next_outer_bottom),
                (outer_bottom, inner_bottom, next_inner_bottom),
            )
        )

    return Mesh(vertices=vertices, triangles=triangles, mode="triangle", static=True)


RING_MESH = make_ring_mesh()


def make_arc_prism_mesh(
    length: float,
    width: float,
    height: float,
    angle_deg: float,
) -> Mesh:
    """Create a curved strip; X is centre-line length, Y width and Z height."""
    angle = angle_deg * pi / 180
    half_angle = angle / 2
    radius = length / angle
    inner_radius = radius - width / 2
    outer_radius = radius + width / 2
    chord_offset = radius * cos(half_angle)
    segments = max(8, ceil(angle_deg / 5))
    vertices: list[tuple[float, float, float]] = []
    for index in range(segments + 1):
        sample = -half_angle + angle * index / segments
        sample_sine = sin(sample)
        sample_cosine = cos(sample)
        inner_x = inner_radius * sample_sine
        inner_z = inner_radius * sample_cosine - chord_offset
        outer_x = outer_radius * sample_sine
        outer_z = outer_radius * sample_cosine - chord_offset
        vertices.extend(
            (
                (inner_x, 0, inner_z),
                (inner_x, height, inner_z),
                (outer_x, 0, outer_z),
                (outer_x, height, outer_z),
            )
        )

    triangles: list[tuple[int, int, int]] = []
    for index in range(segments):
        current = index * 4
        following = (index + 1) * 4
        triangles.extend(
            (
                (current + 1, following + 1, following + 3),
                (current + 1, following + 3, current + 3),
                (current, following + 2, following),
                (current, current + 2, following + 2),
                (current, following, following + 1),
                (current, following + 1, current + 1),
                (current + 2, current + 3, following + 3),
                (current + 2, following + 3, following + 2),
            )
        )
    final = segments * 4
    triangles.extend(
        (
            (0, 1, 3),
            (0, 3, 2),
            (final, final + 3, final + 1),
            (final, final + 2, final + 3),
        )
    )
    return Mesh(vertices=vertices, triangles=triangles, mode="triangle", static=True)


def arc_selection_size(item: PrimitiveObject) -> tuple[float, float]:
    angle = item.arc_angle_deg * pi / 180
    radius = item.size.x / angle
    outer_radius = radius + item.size.y / 2
    width = 2 * outer_radius * sin(angle / 2)
    depth = radius * (1 - cos(angle / 2)) + item.size.y
    return width, depth


def make_gable_roof_mesh(
    width: float, depth: float, height: float, ridge_axis: str
) -> Mesh:
    half_width = width / 2
    half_depth = depth / 2
    vertices = [
        (-half_width, 0, -half_depth),
        (half_width, 0, -half_depth),
        (half_width, 0, half_depth),
        (-half_width, 0, half_depth),
    ]

    if ridge_axis == "x":
        vertices.extend(((-half_width, height, 0), (half_width, height, 0)))
        triangles = [
            (0, 1, 5),
            (0, 5, 4),
            (4, 5, 2),
            (4, 2, 3),
            (0, 4, 3),
            (1, 2, 5),
        ]
    else:
        vertices.extend(((0, height, -half_depth), (0, height, half_depth)))
        triangles = [
            (0, 4, 5),
            (0, 5, 3),
            (4, 1, 2),
            (4, 2, 5),
            (0, 1, 4),
            (3, 5, 2),
        ]

    return Mesh(vertices=vertices, triangles=triangles, mode="triangle", static=True)


def make_shed_roof_mesh(width: float, depth: float, height: float) -> Mesh:
    """Wedge roof whose high front edge slopes towards the local +Z rear."""
    half_width = width / 2
    half_depth = depth / 2
    vertices = [
        (-half_width, 0, -half_depth),
        (half_width, 0, -half_depth),
        (half_width, 0, half_depth),
        (-half_width, 0, half_depth),
        (-half_width, height, -half_depth),
        (half_width, height, -half_depth),
    ]
    triangles = [
        (0, 1, 2),
        (0, 2, 3),
        (4, 5, 2),
        (4, 2, 3),
        (0, 4, 5),
        (0, 5, 1),
        (0, 3, 4),
        (1, 5, 2),
    ]
    return Mesh(vertices=vertices, triangles=triangles, mode="triangle", static=True)


def make_plot_mesh() -> Mesh:
    return make_polygon_mesh(editor.project.plot.boundary)


def make_polygon_mesh(boundary: tuple[Point2D, ...]) -> Mesh:
    vertices = [(point.x, 0, point.z) for point in boundary]
    triangles = [(0, index, index + 1) for index in range(1, len(vertices) - 1)]
    return Mesh(vertices=vertices, triangles=triangles, mode="triangle", static=True)


class SelectableGroup(Entity):
    """Stationary source object that can still be selected from the panel."""

    def __init__(
        self,
        center: Point2D,
        width: float,
        depth: float,
        height: float,
        rotation_y: float,
        parent,
    ) -> None:
        super().__init__(
            parent=parent,
            position=(center.x, 0, center.z),
            rotation_y=rotation_y,
        )
        safe_height = max(height, 0.2)
        self.collider = BoxCollider(
            self,
            center=(0, safe_height / 2, 0),
            size=(width, safe_height, depth),
        )
        self.selection_size = (width, safe_height, depth)


class MovableGroup(Draggable):
    """World-space draggable root constrained to the flat X/Y plot plane."""

    def __init__(
        self,
        center: Point2D,
        width: float,
        depth: float,
        height: float,
        rotation_y: float,
        parent,
    ) -> None:
        super().__init__(
            parent=parent,
            model=None,
            collider=None,
            position=(center.x, 0, center.z),
            rotation_y=rotation_y,
            plane_direction=(0, 1, 0),
            lock=(0, 1, 0),
            step=(0.25, 0, 0.25),
        )
        self.collider = BoxCollider(
            self,
            center=(0, max(height, 0.2) / 2, 0),
            size=(width, max(height, 0.2), depth),
        )
        self.selection_size = (width, max(height, 0.2), depth)


def add_world_label(parent, text: str, height: float) -> None:
    Text(
        parent=parent,
        text=text,
        position=(0, height + 0.45, 0),
        origin=(0, 0),
        scale=16,
        color=color.white,
        billboard=True,
    )


def create_render_root(
    center: Point2D,
    width: float,
    depth: float,
    height: float,
    rotation_y: float,
    parent,
    movable: bool,
):
    if movable:
        return MovableGroup(center, width, depth, height, rotation_y, parent)
    return SelectableGroup(center, width, depth, height, rotation_y, parent)


def render_building(building: Building, parent, editable: bool):
    movable = editable and building.movable and not building.protected
    root = create_render_root(
        building.center,
        building.footprint.width,
        building.footprint.depth,
        building.height_m,
        building.rotation_y,
        parent,
        movable,
    )

    wall_height = building.wall_height_m or building.height_m
    wall_width = building.footprint.width
    wall_depth = building.footprint.depth
    if building.roof:
        wall_width -= building.roof.overhang_m * 2
        wall_depth -= building.roof.overhang_m * 2

    Entity(
        parent=root,
        model="cube",
        position=(0, wall_height / 2, 0),
        scale=(wall_width, wall_height, wall_depth),
        color=to_color(building.color),
        texture="white_cube",
        shader=lit_with_shadows_shader,
    )

    if building.roof:
        if building.roof.shape == "gable":
            roof_mesh = make_gable_roof_mesh(
                building.footprint.width,
                building.footprint.depth,
                building.roof.height_m,
                building.roof.ridge_axis,
            )
            Entity(
                parent=root,
                model=roof_mesh,
                position=(0, wall_height, 0),
                color=to_color(secondary_color_of(building)),
                double_sided=True,
                shader=lit_with_shadows_shader,
            )
        elif building.roof.shape == "shed":
            Entity(
                parent=root,
                model=make_shed_roof_mesh(
                    building.footprint.width,
                    building.footprint.depth,
                    building.roof.height_m,
                ),
                position=(0, wall_height, 0),
                color=to_color(secondary_color_of(building)),
                double_sided=True,
                shader=lit_with_shadows_shader,
            )
        else:
            Entity(
                parent=root,
                model="cube",
                position=(0, wall_height + building.roof.height_m / 2, 0),
                scale=(
                    building.footprint.width,
                    building.roof.height_m,
                    building.footprint.depth,
                ),
                color=to_color(secondary_color_of(building)),
                shader=lit_with_shadows_shader,
            )
    else:
        Entity(
            parent=root,
            model="cube",
            position=(0, building.height_m + 0.009, 0),
            scale=(building.footprint.width, 0.018, building.footprint.depth),
            color=to_color(secondary_color_of(building)),
        )

    add_world_label(root, building.name, building.height_m)
    return root


def render_nature_feature(feature: SiteFeature, root: Entity) -> None:
    """Render a recognizable plant while keeping X/Y/Z as its editable envelope."""
    width = feature.size.width
    depth = feature.size.depth
    height = feature.height_m
    main_color = to_color(feature.color)
    upper_color = to_color(secondary_color_of(feature))
    trunk_color = color.rgb32(105, 78, 48)

    if feature.kind == "tree":
        trunk_width = min(width, depth) * 0.13
        if feature.variant in TREE_PHOTO_TEXTURES:
            texture = TREE_PHOTO_TEXTURES[feature.variant]
            for rotation, plane_width in ((0, width), (90, depth)):
                Entity(
                    parent=root,
                    model="quad",
                    texture=texture,
                    position=(0, height / 2, 0),
                    rotation_y=rotation,
                    scale=(plane_width, height),
                    color=upper_color,
                    double_sided=True,
                )
        elif feature.variant == "pine":
            Entity(
                parent=root,
                model=CYLINDER_MESH,
                scale=(trunk_width, height * 0.55, trunk_width),
                color=trunk_color,
                shader=lit_with_shadows_shader,
            )
            Entity(
                parent=root,
                model=CONE_MESH,
                position=(0, height * 0.24, 0),
                scale=(width, height * 0.76, depth),
                color=upper_color,
                double_sided=True,
                shader=lit_with_shadows_shader,
            )
            Entity(
                parent=root,
                model=CONE_MESH,
                position=(0, height * 0.47, 0),
                scale=(width * 0.68, height * 0.48, depth * 0.68),
                color=main_color,
                double_sided=True,
                shader=lit_with_shadows_shader,
            )
        else:
            is_birch = feature.variant == "birch"
            trunk = color.rgb32(226, 222, 205) if is_birch else trunk_color
            Entity(
                parent=root,
                model=CYLINDER_MESH,
                scale=(trunk_width, height * 0.73, trunk_width),
                color=trunk,
                shader=lit_with_shadows_shader,
            )
            crown_parts = (
                (0, height * 0.76, 0, 0.72, 0.47, 0.72),
                (-width * 0.20, height * 0.72, 0, 0.55, 0.38, 0.56),
                (width * 0.20, height * 0.74, depth * 0.08, 0.55, 0.40, 0.54),
            )
            for index, (x, y, z, sx, sy, sz) in enumerate(crown_parts):
                Entity(
                    parent=root,
                    model="sphere",
                    position=(x, y, z),
                    scale=(width * sx, height * sy, depth * sz),
                    color=upper_color if index == 0 else main_color,
                    shader=lit_with_shadows_shader,
                )
            if is_birch:
                for level in (0.20, 0.34, 0.48):
                    Entity(
                        parent=root,
                        model=CYLINDER_MESH,
                        position=(0, height * level, 0),
                        scale=(trunk_width * 1.03, height * 0.018, trunk_width * 1.03),
                        color=color.rgb32(42, 42, 38),
                    )
            else:
                apple_size = min(width, depth) * 0.075
                for x_ratio, y_ratio, z_ratio in (
                    (-0.27, 0.80, 0.12),
                    (0.24, 0.78, -0.16),
                    (0.04, 0.90, 0.22),
                    (-0.06, 0.67, -0.24),
                    (0.31, 0.70, 0.12),
                ):
                    Entity(
                        parent=root,
                        model="sphere",
                        position=(width * x_ratio, height * y_ratio, depth * z_ratio),
                        scale=apple_size,
                        color=color.rgb32(205, 47, 37),
                    )

    elif feature.kind == "bush":
        if feature.variant == "narrow":
            for index, (x_ratio, z_ratio, scale_ratio) in enumerate((
                (-0.22, 0.10, 0.55),
                (0, -0.12, 0.72),
                (0.22, 0.12, 0.55),
            )):
                Entity(
                    parent=root,
                    model="sphere",
                    position=(width * x_ratio, height * 0.52, depth * z_ratio),
                    scale=(width * 0.40, height * scale_ratio, depth * 0.40),
                    color=upper_color if index == 1 else main_color,
                    shader=lit_with_shadows_shader,
                )
        elif feature.variant == "wide":
            for index, (x_ratio, y_ratio, z_ratio, scale_ratio) in enumerate((
                (0, 0.47, 0, 0.70),
                (-0.28, 0.42, 0.12, 0.52),
                (0.28, 0.43, -0.10, 0.52),
                (0, 0.38, 0.30, 0.48),
            )):
                Entity(
                    parent=root,
                    model="sphere",
                    position=(width * x_ratio, height * y_ratio, depth * z_ratio),
                    scale=(width * scale_ratio, height * 0.70, depth * scale_ratio),
                    color=upper_color if index == 0 else main_color,
                    shader=lit_with_shadows_shader,
                )
        else:
            stem_width = min(width, depth) * 0.045
            berry_size = min(width, depth) * 0.07
            for index, (x_ratio, z_ratio) in enumerate(
                ((-0.30, -0.16), (-0.15, 0.15), (0, -0.05), (0.17, 0.18), (0.31, -0.12))
            ):
                stem_height = height * (0.68 + (index % 3) * 0.10)
                Entity(
                    parent=root,
                    model=CYLINDER_MESH,
                    position=(width * x_ratio, 0, depth * z_ratio),
                    scale=(stem_width, stem_height, stem_width),
                    color=color.rgb32(91, 83, 49),
                )
                Entity(
                    parent=root,
                    model="sphere",
                    position=(width * x_ratio, stem_height * 0.73, depth * z_ratio),
                    scale=(width * 0.26, height * 0.30, depth * 0.24),
                    color=main_color,
                    shader=lit_with_shadows_shader,
                )
                Entity(
                    parent=root,
                    model="sphere",
                    position=(width * (x_ratio + 0.04), stem_height * 0.61, depth * z_ratio),
                    scale=berry_size,
                    color=color.rgb32(172, 28, 65),
                )

    else:
        base_height = max(0.05, height * 0.16)
        Entity(
            parent=root,
            model="cube",
            position=(0, base_height / 2, 0),
            scale=(width, base_height, depth),
            color=color.rgb32(111, 75, 43),
            texture="white_cube",
            shader=lit_with_shadows_shader,
        )
        columns = 5
        rows = 3
        stem_width = max(0.025, min(width / columns, depth / rows) * 0.10)
        for column in range(columns):
            for row in range(rows):
                x = -width * 0.40 + width * 0.20 * column
                z = -depth * 0.32 + depth * 0.32 * row
                if feature.variant == "onion":
                    stalk_height = height * (0.55 + ((column + row) % 3) * 0.08)
                    Entity(
                        parent=root,
                        model=CYLINDER_MESH,
                        position=(x, base_height, z),
                        scale=(stem_width, stalk_height, stem_width),
                        color=upper_color if (column + row) % 2 else main_color,
                    )
                elif feature.variant == "carrot":
                    top_size = min(width / columns, depth / rows) * 0.55
                    Entity(
                        parent=root,
                        model="sphere",
                        position=(x, base_height + height * 0.28, z),
                        scale=(top_size, height * 0.48, top_size),
                        color=main_color,
                        shader=lit_with_shadows_shader,
                    )
                elif (column + row) % 2 == 0:
                    leaf_size = min(width / columns, depth / rows) * 0.62
                    Entity(
                        parent=root,
                        model="sphere",
                        position=(x, base_height + height * 0.20, z),
                        scale=(leaf_size, height * 0.28, leaf_size),
                        color=main_color,
                        shader=lit_with_shadows_shader,
                    )
                    Entity(
                        parent=root,
                        model="sphere",
                        position=(x + leaf_size * 0.18, base_height + height * 0.25, z),
                        scale=leaf_size * 0.24,
                        color=color.rgb32(207, 42, 42),
                    )


def render_feature(feature: SiteFeature, parent, editable: bool):
    movable = editable and feature.movable and not feature.protected
    render_height = feature.height_m
    if feature.kind == "septic":
        render_height = max(render_height, 0.55)
    root = create_render_root(
        feature.center,
        feature.size.width,
        feature.size.depth,
        render_height,
        feature.rotation_y,
        parent,
        movable,
    )

    if feature.kind in NATURE_VARIANTS:
        render_nature_feature(feature, root)
    elif feature.kind == "well" and feature.well_structure is not None:
        structure = feature.well_structure
        Entity(
            parent=root,
            model=RING_MESH,
            scale=(feature.size.width, structure.ring_height_m, feature.size.depth),
            color=to_color(feature.color),
            double_sided=True,
            shader=lit_with_shadows_shader,
        )
        roof_mesh = make_gable_roof_mesh(
            feature.size.width + structure.roof_overhang_m * 2,
            feature.size.depth + structure.roof_overhang_m * 2,
            structure.roof_height_m,
            structure.ridge_axis,
        )
        Entity(
            parent=root,
            model=roof_mesh,
            position=(0, structure.ring_height_m, 0),
            color=to_color(secondary_color_of(feature)),
            shader=lit_with_shadows_shader,
        )
    elif feature.shape == "circle":
        Entity(
            parent=root,
            model=CYLINDER_MESH,
            scale=(feature.size.width, render_height, feature.size.depth),
            color=to_color(feature.color),
            shader=lit_with_shadows_shader,
        )
        Entity(
            parent=root,
            model=CYLINDER_MESH,
            position=(0, render_height, 0),
            scale=(feature.size.width, 0.018, feature.size.depth),
            color=to_color(secondary_color_of(feature)),
        )
    else:
        Entity(
            parent=root,
            model="cube",
            position=(0, render_height / 2, 0),
            scale=(feature.size.width, render_height, feature.size.depth),
            color=to_color(feature.color),
            texture="white_cube",
            shader=lit_with_shadows_shader,
        )
        Entity(
            parent=root,
            model="cube",
            position=(0, render_height + 0.009, 0),
            scale=(feature.size.width, 0.018, feature.size.depth),
            color=to_color(secondary_color_of(feature)),
        )

    if feature.kind in {"well", "septic"} or feature.kind in NATURE_VARIANTS:
        add_world_label(root, feature.name, render_height)
    return root


def render_primitive(item: PrimitiveObject, parent, editable: bool):
    selection_width = item.size.x
    selection_depth = item.size.y
    if item.shape == "arc":
        selection_width, selection_depth = arc_selection_size(item)
    root = create_render_root(
        item.center,
        selection_width,
        selection_depth,
        item.size.z,
        item.rotation_y,
        parent,
        editable and item.movable and not item.protected,
    )
    if item.shape == "arc":
        Entity(
            parent=root,
            model=make_arc_prism_mesh(
                item.size.x,
                item.size.y,
                item.size.z,
                item.arc_angle_deg,
            ),
            color=to_color(item.color),
            double_sided=True,
            shader=lit_with_shadows_shader,
        )
        Entity(
            parent=root,
            model=make_arc_prism_mesh(
                item.size.x,
                item.size.y,
                0.012,
                item.arc_angle_deg,
            ),
            y=item.size.z,
            color=to_color(secondary_color_of(item)),
            double_sided=True,
        )
    elif item.shape == "cylinder":
        Entity(
            parent=root,
            model=CYLINDER_MESH,
            scale=(item.size.x, item.size.z, item.size.y),
            color=to_color(item.color),
            shader=lit_with_shadows_shader,
        )
        Entity(
            parent=root,
            model=CYLINDER_MESH,
            position=(0, item.size.z, 0),
            scale=(item.size.x, 0.012, item.size.y),
            color=to_color(secondary_color_of(item)),
        )
    else:
        Entity(
            parent=root,
            model="cube",
            position=(0, item.size.z / 2, 0),
            scale=(item.size.x, item.size.z, item.size.y),
            color=to_color(item.color),
            texture="white_cube",
            shader=lit_with_shadows_shader,
        )
        Entity(
            parent=root,
            model="cube",
            position=(0, item.size.z + 0.006, 0),
            scale=(item.size.x, 0.012, item.size.y),
            color=to_color(secondary_color_of(item)),
        )
    add_world_label(root, item.name, item.size.z)
    return root


def context_color_shade(value: Rgba, factor: float) -> Rgba:
    return Rgba(
        max(0, min(255, round(value.red * factor))),
        max(0, min(255, round(value.green * factor))),
        max(0, min(255, round(value.blue * factor))),
        value.alpha,
    )


def render_context_area(item: ContextArea, parent: Entity) -> Entity:
    return Entity(
        parent=parent,
        model=make_polygon_mesh(item.boundary),
        y=item.height_m,
        color=to_color(item.color),
        double_sided=True,
        shader=lit_with_shadows_shader,
    )


def create_context_segment(
    parent: Entity,
    start: Point2D,
    end: Point2D,
    width: float,
    height: float,
    y: float,
    segment_color,
    lateral_offset: float = 0.0,
) -> Entity:
    dx = end.x - start.x
    dz = end.z - start.z
    length = (dx * dx + dz * dz) ** 0.5
    normal_x = -dz / length
    normal_z = dx / length
    center_x = (start.x + end.x) / 2 + normal_x * lateral_offset
    center_z = (start.z + end.z) / 2 + normal_z * lateral_offset
    return Entity(
        parent=parent,
        model="cube",
        position=(center_x, y + height / 2, center_z),
        rotation_y=-degrees(atan2(dz, dx)),
        scale=(length, height, width),
        color=segment_color,
        texture="white_cube",
        shader=lit_with_shadows_shader,
    )


def polyline_normals(points: tuple[Point2D, ...]) -> tuple[tuple[float, float], ...]:
    segment_normals: list[tuple[float, float]] = []
    for start, end in zip(points, points[1:]):
        dx = end.x - start.x
        dz = end.z - start.z
        length = (dx * dx + dz * dz) ** 0.5
        segment_normals.append((-dz / length, dx / length))

    normals: list[tuple[float, float]] = []
    for index in range(len(points)):
        if index == 0:
            normals.append(segment_normals[0])
        elif index == len(points) - 1:
            normals.append(segment_normals[-1])
        else:
            x = segment_normals[index - 1][0] + segment_normals[index][0]
            z = segment_normals[index - 1][1] + segment_normals[index][1]
            length = (x * x + z * z) ** 0.5
            normals.append((x / length, z / length))
    return tuple(normals)


def offset_polyline(
    points: tuple[Point2D, ...], offset: float
) -> tuple[Point2D, ...]:
    return tuple(
        Point2D(point.x + normal_x * offset, point.z + normal_z * offset)
        for point, (normal_x, normal_z) in zip(points, polyline_normals(points))
    )


def make_polyline_ribbon(points: tuple[Point2D, ...], width: float) -> Mesh:
    vertices: list[tuple[float, float, float]] = []
    for point, (normal_x, normal_z) in zip(points, polyline_normals(points)):
        vertices.extend(
            (
                (point.x + normal_x * width / 2, 0, point.z + normal_z * width / 2),
                (point.x - normal_x * width / 2, 0, point.z - normal_z * width / 2),
            )
        )
    triangles: list[tuple[int, int, int]] = []
    for index in range(len(points) - 1):
        left = index * 2
        triangles.extend(
            (
                (left, left + 1, left + 3),
                (left, left + 3, left + 2),
            )
        )
    return Mesh(vertices=vertices, triangles=triangles, mode="triangle", static=True)


def context_local_points(item: ContextLinearObject) -> tuple[Point2D, ...]:
    center = item.center
    return tuple(
        Point2D(point.x - center.x, point.z - center.z) for point in item.points
    )


def create_context_root(
    item: ContextLinearObject, parent: Entity, editable: bool
) -> Entity:
    center = item.center
    span_x = max(point.x for point in item.points) - min(
        point.x for point in item.points
    )
    span_z = max(point.z for point in item.points) - min(
        point.z for point in item.points
    )
    width = max(item.width_m, span_x + item.width_m)
    depth = max(item.width_m, span_z + item.width_m)
    if editable and item.movable and not item.protected:
        return MovableGroup(
            center,
            width,
            depth,
            max(item.height_m, 0.12),
            item.rotation_y,
            parent,
        )
    if editable:
        return SelectableGroup(
            center,
            width,
            depth,
            max(item.height_m, 0.12),
            item.rotation_y,
            parent,
        )
    return Entity(
        parent=parent,
        position=(center.x, 0, center.z),
        rotation_y=item.rotation_y,
    )


def render_context_road(
    item: ContextLinearObject, parent: Entity, editable: bool = False
) -> Entity:
    root = create_context_root(item, parent, editable)
    points = context_local_points(item)
    road_color = to_color(secondary_color_of(item))
    edge_color = to_color(context_color_shade(item.color, 0.68))
    edge_width = min(0.18, item.width_m * 0.04)
    surface_y = item.height_m
    Entity(
        parent=root,
        model=make_polyline_ribbon(points, item.width_m),
        y=surface_y,
        color=road_color,
        double_sided=True,
    )
    edge_offset = item.width_m / 2 - edge_width / 2
    for side in (-1, 1):
        Entity(
            parent=root,
            model=make_polyline_ribbon(
                offset_polyline(points, edge_offset * side), edge_width
            ),
            y=surface_y + 0.008,
            color=edge_color,
            double_sided=True,
        )
    return root


def render_context_ditch(
    item: ContextLinearObject, parent: Entity, editable: bool = False
) -> Entity:
    root = create_context_root(item, parent, editable)
    points = context_local_points(item)
    bank_color = to_color(context_color_shade(item.color, 1.28))
    channel_color = to_color(secondary_color_of(item))
    drain_color = to_color(context_color_shade(item.color, 0.70))
    for start, end in zip(points, points[1:]):
        for side in (-1, 1):
            create_context_segment(
                root,
                start,
                end,
                item.width_m * 0.30,
                0.11,
                0.02,
                bank_color,
                lateral_offset=side * item.width_m * 0.34,
            )
        create_context_segment(
            root,
            start,
            end,
            item.width_m * 0.42,
            0.025,
            0.015,
            channel_color,
        )
        create_context_segment(
            root,
            start,
            end,
            item.width_m * 0.10,
            0.012,
            0.042,
            drain_color,
        )
    return root


def render_context_ditch_dash(
    item: ContextLinearObject, parent: Entity, editable: bool = False
) -> Entity:
    """Render one independently editable blue marker of the drainage ditch."""
    root = create_context_root(item, parent, editable)
    points = context_local_points(item)
    for start, end in zip(points, points[1:]):
        create_context_segment(
            root,
            start,
            end,
            item.width_m,
            item.height_m,
            0.012,
            to_color(item.color),
        )
        cap_height = min(0.025, item.height_m * 0.25)
        create_context_segment(
            root,
            start,
            end,
            item.width_m,
            cap_height,
            item.height_m - cap_height,
            to_color(secondary_color_of(item)),
        )
    return root


def render_context_fence(
    item: ContextLinearObject, parent: Entity, editable: bool = False
) -> Entity:
    root = create_context_root(item, parent, editable)
    points = context_local_points(item)
    for start, end in zip(points, points[1:]):
        create_context_segment(
            root,
            start,
            end,
            item.width_m,
            item.height_m,
            0,
            to_color(item.color),
        )
        cap_height = min(0.05, item.height_m * 0.08)
        create_context_segment(
            root,
            start,
            end,
            item.width_m,
            cap_height,
            item.height_m - cap_height,
            to_color(secondary_color_of(item)),
        )
    return root


def render_surroundings(
    parent: Entity, editable: bool = False, layout_id: str = ""
) -> Entity:
    root = Entity(parent=parent)
    surroundings = editor.project.surroundings
    for area in surroundings.areas:
        render_context_area(area, root)
    for item in surroundings.linear_objects:
        if item.style == "boundary_fence":
            continue
        line_editable = editable and item.style in {
            "road",
            "ditch_dash",
            "fence",
        }
        if item.style == "road":
            item_root = render_context_road(item, root, line_editable)
        elif item.style == "ditch":
            item_root = render_context_ditch(item, root, False)
        elif item.style == "ditch_dash":
            item_root = render_context_ditch_dash(item, root, line_editable)
        elif item.style == "fence":
            item_root = render_context_fence(item, root, line_editable)
        else:
            continue
        if line_editable and isinstance(item_root, MovableGroup):
            configure_drag(item_root, "surrounding_linear", item.id, layout_id)
        elif line_editable:
            configure_static_selection(
                item_root, "surrounding_linear", item.id, layout_id
            )
    for building in surroundings.buildings:
        building_root = render_building(building, root, editable=editable)
        if editable and isinstance(building_root, MovableGroup):
            configure_drag(
                building_root,
                "surrounding_building",
                building.id,
                layout_id,
            )
        elif editable:
            configure_static_selection(
                building_root, "surrounding_building", building.id, layout_id
            )
        else:
            building_root.collider = None
    for feature in surroundings.features:
        feature_root = render_feature(feature, root, editable=editable)
        if editable and isinstance(feature_root, MovableGroup):
            configure_drag(
                feature_root,
                "surrounding_feature",
                feature.id,
                layout_id,
            )
        elif editable:
            configure_static_selection(
                feature_root, "surrounding_feature", feature.id, layout_id
            )
        else:
            feature_root.collider = None
    for primitive in surroundings.primitives:
        primitive_root = render_primitive(primitive, root, editable=editable)
        if editable and isinstance(primitive_root, MovableGroup):
            configure_drag(
                primitive_root,
                "surrounding_primitive",
                primitive.id,
                layout_id,
            )
        elif editable:
            configure_static_selection(
                primitive_root, "surrounding_primitive", primitive.id, layout_id
            )
        else:
            primitive_root.collider = None
    return root


def points_match(first: Point2D, second: Point2D, tolerance: float = 1e-5) -> bool:
    return (
        abs(first.x - second.x) <= tolerance
        and abs(first.z - second.z) <= tolerance
    )


def boundary_fence_override(
    start: Point2D, end: Point2D
) -> ContextLinearObject | None:
    for item in editor.project.surroundings.linear_objects:
        if item.style != "boundary_fence":
            continue
        for override_start, override_end in zip(item.points, item.points[1:]):
            direct = points_match(start, override_start) and points_match(
                end, override_end
            )
            reverse = points_match(start, override_end) and points_match(
                end, override_start
            )
            if direct or reverse:
                return item
    return None


def create_fence_wall(
    start: Point2D,
    end: Point2D,
    height: float,
    fence_root: Entity,
    wall_color: Rgba | None = None,
    thickness_m: float | None = None,
) -> Entity:
    fence = editor.project.plot.fence
    if fence is None:
        raise DomainValidationError("The site source has no fence")
    dx = end.x - start.x
    dz = end.z - start.z
    length = (dx * dx + dz * dz) ** 0.5
    wall = Entity(
        parent=fence_root,
        model="cube",
        collider="box",
        position=((start.x + end.x) / 2, height / 2, (start.z + end.z) / 2),
        rotation_y=-degrees(atan2(dz, dx)),
        scale=(length, height, thickness_m or fence.thickness_m),
        color=to_color(wall_color or fence.color),
        texture="white_cube",
        shader=lit_with_shadows_shader,
    )
    wall.on_click = lambda: select_object(
        fence_root, "fence", FENCE_OBJECT_ID, current_layout_id
    )
    return wall


def create_horizontal_fence(
    minimum_x: float,
    maximum_x: float,
    z: float,
    height: float,
    openings: list[tuple[float, float]],
    fence_root: Entity,
) -> None:
    cursor = minimum_x
    for opening_start, opening_end in sorted(openings):
        opening_start = max(minimum_x, opening_start)
        opening_end = min(maximum_x, opening_end)
        if opening_start > cursor:
            create_fence_wall(
                Point2D(cursor, z), Point2D(opening_start, z), height, fence_root
            )
        cursor = max(cursor, opening_end)
    if cursor < maximum_x:
        create_fence_wall(
            Point2D(cursor, z), Point2D(maximum_x, z), height, fence_root
        )


def render_fence(parent) -> Entity | None:
    plot = editor.project.plot
    if plot.fence is None:
        return None
    fence_root = Entity(parent=parent)
    fence_root.selection_size = None
    boundary = plot.boundary
    minimum_z = min(point.z for point in boundary)
    maximum_z = max(point.z for point in boundary)
    front_openings: list[tuple[float, float]] = []
    rear_openings: list[tuple[float, float]] = []

    for feature in editor.project.fixed_features:
        if feature.kind not in {"gate", "wicket"}:
            continue
        interval = (
            feature.center.x - feature.size.width / 2,
            feature.center.x + feature.size.width / 2,
        )
        if feature.center.z > (minimum_z + maximum_z) / 2:
            front_openings.append(interval)
        else:
            rear_openings.append(interval)

    front_left = plot.marker("9").position
    front_right = plot.marker("1").position
    rear_left = plot.marker("5").position
    rear_right = plot.marker("4").position
    create_horizontal_fence(
        front_left.x,
        front_right.x,
        maximum_z,
        plot.fence.front_height_m,
        front_openings,
        fence_root,
    )
    create_horizontal_fence(
        rear_left.x,
        rear_right.x,
        minimum_z,
        plot.fence.other_height_m,
        rear_openings,
        fence_root,
    )

    for start, end in zip(boundary, boundary[1:] + boundary[:1]):
        if abs(start.z - end.z) < 1e-6 and (
            abs(start.z - minimum_z) < 1e-6 or abs(start.z - maximum_z) < 1e-6
        ):
            continue
        override = boundary_fence_override(start, end)
        create_fence_wall(
            start,
            end,
            override.height_m if override is not None else plot.fence.other_height_m,
            fence_root,
            wall_color=override.color if override is not None else None,
            thickness_m=override.width_m if override is not None else None,
        )
    return fence_root


selected_root: Entity | None = None
selection_outline: Entity | None = None
current_layout_id = editor.project.active_layout_id
current_mode = "design"
design_only_controls: list[Entity] = []


def clear_selection() -> None:
    global selected_root, selection_outline
    if "color_palette_panel" in globals():
        close_color_palette()
    if selection_outline is not None:
        destroy(selection_outline)
    selected_root = None
    selection_outline = None
    protected_checkbox.value = False
    protected_checkbox.enabled = False
    selected_name_text.text = "Объект не выбран"
    delete_button.enabled = False
    restore_button.enabled = False


def select_object(
    root: Entity, collection: str, item_id: str, layout_id: str
) -> None:
    global selected_root, selection_outline
    if selection_outline is not None:
        destroy(selection_outline)

    selected_root = root
    root.edit_collection = collection
    root.edit_item_id = item_id
    root.edit_layout_id = layout_id
    selection_size = getattr(root, "selection_size", None)
    if selection_size is not None:
        width, height, depth = selection_size
        selection_outline = Entity(
            parent=root,
            model="cube",
            position=(0, height / 2, 0),
            scale=(width + 0.16, height + 0.16, depth + 0.16),
            color=color.yellow,
            wireframe=True,
        )
    item = editor.get_item(layout_id, collection, item_id)
    populate_object_fields(item, collection)
    protected_checkbox.value = item.protected
    protected_checkbox.enabled = True
    item_name = getattr(item, "name", "Забор")
    item_center = getattr(item, "center", None)
    arc_text = (
        f"; дуга={item.arc_angle_deg:g}°"
        if isinstance(item, PrimitiveObject) and item.shape == "arc"
        else ""
    )
    selected_name_text.text = (
        f"{item_name}: X={item_center.x:g}; Z={item_center.z:g}{arc_text}"
        if item_center is not None
        else item_name
    )
    delete_button.enabled = current_mode == "design" and not item.protected
    restore_button.enabled = (
        current_mode == "site"
        and collection in {"fence", "fixed_building", "fixed_feature"}
        and editor.is_fixed_hidden(layout_id, item_id)
    )
    arc_hint = ", R/T — кривизна" if getattr(item, "shape", "") == "arc" else ""
    set_status(
        f"Выбран: {item_id}. A/D — X, W/S — Z, Q/E — поворот{arc_hint}"
    )


def configure_drag(root: MovableGroup, collection: str, item_id: str, layout_id: str):
    root.edit_collection = collection
    root.edit_item_id = item_id
    root.edit_layout_id = layout_id

    def on_drag() -> None:
        select_object(root, collection, item_id, layout_id)
        set_status(f"Перемещение: {item_id}")

    def on_drop() -> None:
        requested = Point2D(round(root.x, 2), round(root.z, 2))
        root.y = 0
        try:
            editor.move_item(layout_id, collection, item_id, requested)
        except (DomainValidationError, ValueError) as exc:
            root.position = root.start_pos
            set_status(str(exc), error=True)
            return
        root.position = (requested.x, 0, requested.z)
        item = editor.get_item(layout_id, collection, item_id)
        selected_name_text.text = (
            f"{item.name}: X={requested.x:g}; Z={requested.z:g}"
        )
        set_status(f"Сохранено: {item_id} ({requested.x:g}; {requested.z:g})")

    root.drag = on_drag
    root.drop = on_drop
    root.on_click = lambda: select_object(root, collection, item_id, layout_id)


def configure_static_selection(
    root: Entity, collection: str, item_id: str, layout_id: str
) -> None:
    root.edit_collection = collection
    root.edit_item_id = item_id
    root.edit_layout_id = layout_id
    root.on_click = lambda: select_object(root, collection, item_id, layout_id)


def on_protection_changed(value: bool) -> None:
    if selected_root is None:
        return
    collection = selected_root.edit_collection
    item_id = selected_root.edit_item_id
    layout_id = selected_root.edit_layout_id
    try:
        editor.set_item_protected(
            layout_id,
            collection,
            item_id,
            value,
        )
    except (DomainValidationError, ValueError) as exc:
        protected_checkbox.value = not value
        set_status(str(exc), error=True)
        return
    state = "защищён" if value else "не защищён"
    show_layout(layout_id)
    rendered = find_rendered_root(collection, item_id)
    if rendered is not None:
        select_object(rendered, collection, item_id, layout_id)
    set_status(f"{item_id}: {state}")


def delete_selected() -> None:
    if current_mode != "design":
        set_status("Удаление и скрытие доступны в режиме «Дизайн»", error=True)
        return
    if selected_root is None:
        set_status("Сначала выберите объект", error=True)
        return
    item_id = selected_root.edit_item_id
    try:
        result = editor.delete_or_hide_item(
            selected_root.edit_layout_id,
            selected_root.edit_collection,
            item_id,
        )
    except (DomainValidationError, ValueError) as exc:
        set_status(str(exc), error=True)
        return
    show_layout(current_layout_id)
    action = "Скрыт в этом дизайне" if result == "hidden" else "Удалён"
    set_status(f"{action}: {item_id}")


def restore_selected() -> None:
    if selected_root is None:
        return
    item_id = selected_root.edit_item_id
    try:
        editor.restore_fixed_item(current_layout_id, item_id)
    except (DomainValidationError, ValueError) as exc:
        set_status(str(exc), error=True)
        return
    show_layout(current_layout_id)
    set_status(f"Объект возвращён в дизайн: {item_id}")


stationary_root = Entity(parent=scene)
Entity(
    parent=stationary_root,
    model="plane",
    scale=20,
    y=-0.04,
    color=color.rgb32(105, 135, 92),
    texture="white_cube",
    shader=lit_with_shadows_shader,
)
Entity(
    parent=stationary_root,
    model=make_plot_mesh(),
    y=0,
    color=color.rgb32(145, 178, 122),
    double_sided=True,
    shader=lit_with_shadows_shader,
)
GRID_STEP_M = 2
GRID_MARGIN_M = 5
coordinate_grid_root: Entity | None = None
coordinate_grid_enabled = False
cursor_projection_marker = Entity(parent=scene, enabled=False)
Entity(
    parent=cursor_projection_marker,
    model=make_ring_mesh(),
    position=(0, 0.065, 0),
    scale=(1.20, 0.025, 1.20),
    color=color.rgb32(255, 45, 210),
    double_sided=True,
    unlit=True,
    always_on_top=True,
    render_queue=1,
)
Entity(
    parent=cursor_projection_marker,
    model=make_cylinder_mesh(),
    position=(0, 0.072, 0),
    scale=(0.50, 0.035, 0.50),
    color=color.rgb32(255, 240, 35),
    unlit=True,
    always_on_top=True,
    render_queue=2,
)


def coordinate_grid_bounds() -> tuple[int, int, int, int]:
    boundary = editor.project.plot.boundary
    minimum_x = (
        floor((min(point.x for point in boundary) - GRID_MARGIN_M) / GRID_STEP_M)
        * GRID_STEP_M
    )
    maximum_x = (
        ceil((max(point.x for point in boundary) + GRID_MARGIN_M) / GRID_STEP_M)
        * GRID_STEP_M
    )
    minimum_z = (
        floor((min(point.z for point in boundary) - GRID_MARGIN_M) / GRID_STEP_M)
        * GRID_STEP_M
    )
    maximum_z = (
        ceil((max(point.z for point in boundary) + GRID_MARGIN_M) / GRID_STEP_M)
        * GRID_STEP_M
    )
    return minimum_x, maximum_x, minimum_z, maximum_z


def add_grid_ground_label(
    parent: Entity,
    text: str,
    x: float,
    z: float,
    text_color,
    scale: float = 12,
) -> Text:
    return Text(
        parent=parent,
        text=text,
        position=(x, 0.04, z),
        rotation_x=90,
        origin=(0, 0),
        scale=scale,
        color=text_color,
        double_sided=True,
    )


def render_coordinate_grid() -> Entity:
    minimum_x, maximum_x, minimum_z, maximum_z = coordinate_grid_bounds()
    root = Entity(parent=scene, enabled=False)
    root.coordinate_bounds = (minimum_x, maximum_x, minimum_z, maximum_z)
    grid_color = color.rgba32(220, 225, 230, 155)
    label_color = color.rgb32(35, 40, 45)
    x_axis_color = color.rgb32(245, 68, 45)
    z_axis_color = color.rgb32(35, 125, 255)
    origin_color = color.rgb32(255, 220, 35)
    total_width = maximum_x - minimum_x
    total_depth = maximum_z - minimum_z
    center_x = (minimum_x + maximum_x) / 2
    center_z = (minimum_z + maximum_z) / 2

    for x in range(minimum_x, maximum_x + GRID_STEP_M, GRID_STEP_M):
        if x != 0:
            line = Entity(
                parent=root,
                model="cube",
                position=(x, 0.012, center_z),
                scale=(0.025, 0.012, total_depth),
                color=grid_color,
                texture="white_cube",
            )
            line.grid_role = "grid_x"
        if x != 0:
            add_grid_ground_label(
                root, f"{x}", x, minimum_z + 0.65, label_color
            )

    for z in range(minimum_z, maximum_z + GRID_STEP_M, GRID_STEP_M):
        if z != 0:
            line = Entity(
                parent=root,
                model="cube",
                position=(center_x, 0.013, z),
                scale=(total_width, 0.012, 0.025),
                color=grid_color,
                texture="white_cube",
            )
            line.grid_role = "grid_z"
        if z != 0:
            add_grid_ground_label(
                root, f"{z}", minimum_x + 0.65, z, label_color
            )

    x_axis = Entity(
        parent=root,
        model="cube",
        position=(center_x, 0.021, 0),
        scale=(total_width, 0.025, 0.10),
        color=x_axis_color,
        texture="white_cube",
    )
    x_axis.grid_role = "x_axis"
    z_axis = Entity(
        parent=root,
        model="cube",
        position=(0, 0.022, center_z),
        scale=(0.10, 0.025, total_depth),
        color=z_axis_color,
        texture="white_cube",
    )
    z_axis.grid_role = "z_axis"
    origin = Entity(
        parent=root,
        model=CYLINDER_MESH,
        position=(0, 0.025, 0),
        scale=(0.55, 0.055, 0.55),
        color=origin_color,
    )
    origin.grid_role = "origin"
    origin_beacon = Entity(
        parent=root,
        model="sphere",
        position=(0, 0.24, 0),
        scale=0.42,
        color=origin_color,
    )
    origin_beacon.grid_role = "origin_beacon"

    add_grid_ground_label(
        root, "X", maximum_x - 0.7, 0.55, x_axis_color, scale=15
    )
    add_grid_ground_label(
        root, "Z", 0.55, maximum_z - 0.7, z_axis_color, scale=15
    )
    add_grid_ground_label(
        root, "0, 0", 0.8, 0.8, origin_color, scale=14
    )

    north = editor.project.plot.north_unit_vector
    north_color = color.rgb32(255, 55, 210)
    north_start = Point2D(minimum_x + 3.0, minimum_z + 3.0)
    north_end = Point2D(
        north_start.x + north.x * 8.0,
        north_start.z + north.z * 8.0,
    )
    north_arrow = create_context_segment(
        root,
        north_start,
        north_end,
        width=0.18,
        height=0.025,
        y=0.055,
        segment_color=north_color,
    )
    north_arrow.grid_role = "north_arrow"
    arrow_base = Point2D(
        north_end.x - north.x * 1.5,
        north_end.z - north.z * 1.5,
    )
    perpendicular = Point2D(-north.z, north.x)
    for side in (-1, 1):
        wing = Point2D(
            arrow_base.x + perpendicular.x * 0.8 * side,
            arrow_base.z + perpendicular.z * 0.8 * side,
        )
        create_context_segment(
            root,
            north_end,
            wing,
            width=0.18,
            height=0.025,
            y=0.055,
            segment_color=north_color,
        )
    add_grid_ground_label(
        root,
        "СЕВЕР",
        north_end.x + north.x * 1.0,
        north_end.z + north.z * 1.0,
        north_color,
        scale=15,
    )
    return root


def toggle_coordinate_grid() -> None:
    global coordinate_grid_root, coordinate_grid_enabled
    coordinate_grid_enabled = not coordinate_grid_enabled
    if coordinate_grid_root is None:
        coordinate_grid_root = render_coordinate_grid()
    coordinate_grid_root.enabled = coordinate_grid_enabled
    coordinate_readout.enabled = coordinate_grid_enabled
    if coordinate_grid_enabled:
        update_coordinate_readout()
    else:
        cursor_projection_marker.enabled = False
    grid_button.text = "Сетка: вкл" if coordinate_grid_enabled else "Сетка"
    grid_button.color = color.azure if coordinate_grid_enabled else color.dark_gray
    state = "включена" if coordinate_grid_enabled else "выключена"
    set_status(f"Координатная сетка 2 м {state}; объекты привязаны центром X/Z")


def mouse_ground_point(screen_position=None) -> Point2D | None:
    """Intersect the camera ray with the flat site plane, independent of colliders."""
    near = Point3()
    far = Point3()
    if screen_position is None:
        try:
            position = mouse.position
        except AttributeError:
            return None
    else:
        position = screen_position
    if not camera.lens.extrude(Vec2(position.x, position.y), near, far):
        return None
    near_world = scene.getRelativePoint(camera, near)
    far_world = scene.getRelativePoint(camera, far)
    delta_y = far_world.y - near_world.y
    if abs(delta_y) <= 1e-9:
        return None
    ratio = -near_world.y / delta_y
    if ratio < 0:
        return None
    return Point2D(
        near_world.x + (far_world.x - near_world.x) * ratio,
        near_world.z + (far_world.z - near_world.z) * ratio,
    )


def update_coordinate_readout(screen_position=None) -> None:
    if not coordinate_grid_enabled:
        return
    point = mouse_ground_point(screen_position)
    if point is None:
        cursor_projection_marker.enabled = False
        coordinate_readout.text = "X =   —        Z =   —"
        return
    cursor_projection_marker.enabled = True
    cursor_projection_marker.position = (point.x, 0, point.z)
    cursor_projection_marker.projected_point = point
    coordinate_readout.text = (
        f"X = {point.x:+07.2f} м    Z = {point.z:+07.2f} м"
    )


layout_root: Entity | None = None
source_objects_root: Entity | None = None


def show_layout(layout_id: str) -> None:
    global layout_root, source_objects_root, current_layout_id
    editor.project.layout(layout_id)
    current_layout_id = layout_id
    clear_selection()
    if layout_root is not None:
        destroy(layout_root)
    if source_objects_root is not None:
        destroy(source_objects_root)
    layout_root = Entity(parent=scene)
    source_objects_root = Entity(parent=scene)
    layout = editor.project.layout(layout_id)
    render_surroundings(
        source_objects_root,
        editable=current_mode == "site",
        layout_id=layout_id,
    )

    hidden_ids = set(layout.hidden_fixed_ids) if current_mode == "design" else set()
    if editor.project.plot.fence is not None and FENCE_OBJECT_ID not in hidden_ids:
        render_fence(source_objects_root)
    for fixed_building in editor.project.fixed_buildings:
        if fixed_building.id in hidden_ids:
            continue
        root = render_building(
            fixed_building,
            source_objects_root,
            editable=current_mode == "site",
        )
        if isinstance(root, MovableGroup):
            configure_drag(root, "fixed_building", fixed_building.id, layout_id)
        else:
            configure_static_selection(
                root, "fixed_building", fixed_building.id, layout_id
            )
    for fixed_feature in editor.project.fixed_features:
        if fixed_feature.id in hidden_ids:
            continue
        root = render_feature(
            fixed_feature,
            source_objects_root,
            editable=current_mode == "site",
        )
        if isinstance(root, MovableGroup):
            configure_drag(root, "fixed_feature", fixed_feature.id, layout_id)
        else:
            configure_static_selection(
                root, "fixed_feature", fixed_feature.id, layout_id
            )

    if current_mode == "design":
        for building in layout.buildings:
            root = render_building(building, layout_root, editable=True)
            if isinstance(root, MovableGroup):
                configure_drag(root, "building", building.id, layout_id)
            else:
                configure_static_selection(root, "building", building.id, layout_id)
        for feature in layout.features:
            root = render_feature(feature, layout_root, editable=True)
            if isinstance(root, MovableGroup):
                configure_drag(root, "feature", feature.id, layout_id)
            else:
                configure_static_selection(root, "feature", feature.id, layout_id)
        for item in layout.primitives:
            root = render_primitive(item, layout_root, editable=True)
            if isinstance(root, MovableGroup):
                configure_drag(root, "primitive", item.id, layout_id)
            else:
                configure_static_selection(root, "primitive", item.id, layout_id)

    short_layout_name = layout.name.removeprefix("Вариант ")
    design_menu.text = f"Схема: {short_layout_name}"
    mode_name = "Создание участка" if current_mode == "site" else "Дизайн"
    layout_label.text = f"{mode_name} — {layout.name}"
    set_status(f"Открыт {layout.name}")


def switch_design(layout_id: str) -> None:
    try:
        editor.set_active_layout(layout_id)
    except (DomainValidationError, ValueError) as exc:
        set_status(str(exc), error=True)
        return
    show_layout(layout_id)


def set_mode(mode: str) -> None:
    global current_mode
    if mode not in {"site", "design"}:
        raise ValueError(f"Unknown editor mode: {mode}")
    editor.save()
    current_mode = mode
    for control in design_only_controls:
        control.enabled = mode == "design"
    refresh_shape_controls()
    refresh_nature_controls()
    for field in input_fields:
        field.enabled = True
    object_panel_title.text = (
        "Параметры исходного объекта"
        if mode == "site"
        else "Создать / изменить объект"
    )
    site_mode_button.color = color.azure if mode == "site" else color.dark_gray
    design_mode_button.color = color.azure if mode == "design" else color.dark_gray
    show_layout(current_layout_id)


def parse_positive(field: InputField, label: str) -> float:
    try:
        value = float(field.text.strip().replace(",", "."))
    except ValueError as exc:
        raise DomainValidationError(f"{label}: требуется число") from exc
    if value <= 0:
        raise DomainValidationError(f"{label}: значение должно быть больше нуля")
    return value


def parse_color(value: str) -> Rgba:
    raw = value.strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(character * 2 for character in raw)
    if len(raw) != 6:
        raise DomainValidationError("Цвет: используйте формат #RRGGBB")
    try:
        return Rgba(*(int(raw[index : index + 2], 16) for index in (0, 2, 4)))
    except ValueError as exc:
        raise DomainValidationError("Цвет: используйте формат #RRGGBB") from exc


def color_to_hex(value: Rgba) -> str:
    return f"#{value.red:02X}{value.green:02X}{value.blue:02X}"


field_update_generation = 0
suppress_field_updates = False
active_color_field: InputField | None = None


def refresh_color_swatch(field: InputField) -> None:
    button = color_swatch_button if field is color_field else color2_swatch_button
    try:
        button.color = to_color(parse_color(field.text))
    except DomainValidationError:
        button.color = color.rgb32(65, 68, 73)


def close_color_palette() -> None:
    global active_color_field
    active_color_field = None
    color_palette_panel.enabled = False


def open_color_palette(field: InputField) -> None:
    global active_color_field
    if color_palette_panel.enabled and active_color_field is field:
        close_color_palette()
        return
    active_color_field = field
    color_palette_panel.enabled = True
    set_status("Выберите основной цвет или исправьте код вручную")


def choose_palette_color(name: str, value: str) -> None:
    if active_color_field is None:
        return
    field = active_color_field
    field.text = value
    refresh_color_swatch(field)
    close_color_palette()
    queue_selected_property_update()
    set_status(f"Выбран цвет: {name} {value}")


def on_editable_field_changed(field: InputField) -> None:
    if field is color_field or field is color2_field:
        refresh_color_swatch(field)
    queue_selected_property_update()


def object_size(item) -> Size3D | None:
    if isinstance(item, Building):
        return Size3D(
            item.footprint.width,
            item.footprint.depth,
            item.height_m,
        )
    if isinstance(item, SiteFeature):
        return Size3D(item.size.width, item.size.depth, item.height_m)
    if isinstance(item, PrimitiveObject):
        return item.size
    if isinstance(item, ContextLinearObject):
        return Size3D(item.length_m, item.width_m, item.height_m)
    return None


def populate_object_fields(item, collection: str) -> None:
    global field_update_generation, suppress_field_updates, selected_shape
    global selected_template, selected_nature_kind, selected_variant
    size = object_size(item)
    fields = (
        name_field,
        size_x_field,
        size_y_field,
        size_z_field,
        color_field,
        color2_field,
    )
    if size is None or collection == "fence":
        for field in fields:
            field.enabled = False
        set_status("Для забора используются параметры исходника участка")
        return

    field_update_generation += 1
    suppress_field_updates = True
    try:
        selected_shape = item.shape if isinstance(item, PrimitiveObject) else None
        selected_variant = getattr(item, "variant", "")
        if isinstance(item, SiteFeature) and item.kind in NATURE_VARIANTS:
            selected_template = None
            selected_nature_kind = item.kind
            template_menu.text = "Типовой объект"
        else:
            selected_nature_kind = None
            if isinstance(item, Building) and item.kind in TYPICAL_OBJECTS:
                selected_template = item.kind
                template_menu.text = f"Тип: {TYPICAL_OBJECTS[item.kind][0]}"
            elif isinstance(item, SiteFeature) and item.kind == "well":
                selected_template = "well"
                template_menu.text = "Тип: Колодец"
            else:
                selected_template = None
        for field in fields:
            field.enabled = True
        name_field.text = item.name
        size_x_field.text = f"{size.x:g}"
        size_y_field.text = f"{size.y:g}"
        size_z_field.text = f"{size.z:g}"
        color_field.text = color_to_hex(item.color)
        color2_field.text = color_to_hex(secondary_color_of(item))
        refresh_color_swatch(color_field)
        refresh_color_swatch(color2_field)
    finally:
        suppress_field_updates = False
    refresh_shape_controls()
    refresh_nature_controls()


def find_rendered_root(collection: str, item_id: str) -> Entity | None:
    roots: list[Entity] = []

    def collect(root: Entity | None) -> None:
        if root is None:
            return
        for child in root.children:
            roots.append(child)
            collect(child)

    collect(source_objects_root)
    collect(layout_root)
    return next(
        (
            root
            for root in roots
            if getattr(root, "edit_collection", None) == collection
            and getattr(root, "edit_item_id", None) == item_id
        ),
        None,
    )


def apply_selected_properties() -> None:
    if selected_root is None or selected_root.edit_collection == "fence":
        return
    layout_id = selected_root.edit_layout_id
    collection = selected_root.edit_collection
    item_id = selected_root.edit_item_id
    try:
        current_item = editor.get_item(layout_id, collection, item_id)
        variant = selected_variant
        size = Size3D(
            parse_positive(size_x_field, "Размер X"),
            parse_positive(size_y_field, "Размер Y"),
            parse_positive(size_z_field, "Высота Z"),
        )
        editor.update_item_properties(
            layout_id,
            collection,
            item_id,
            size,
            parse_color(color_field.text),
            name_field.text,
            variant,
            secondary_color=parse_color(color2_field.text),
        )
    except (DomainValidationError, ValueError) as exc:
        item = editor.get_item(layout_id, collection, item_id)
        populate_object_fields(item, collection)
        set_status(str(exc), error=True)
        return

    show_layout(layout_id)
    root = find_rendered_root(collection, item_id)
    if root is not None:
        select_object(root, collection, item_id, layout_id)
    set_status(f"Обновлён объект: {item_id}")


def queue_selected_property_update() -> None:
    global field_update_generation
    if suppress_field_updates or selected_root is None:
        return
    field_update_generation += 1
    generation = field_update_generation
    invoke(apply_queued_property_update, generation, delay=0.35)


def apply_queued_property_update(generation: int) -> None:
    if generation != field_update_generation:
        return
    apply_selected_properties()


selected_shape: str | None = None
selected_template: str | None = None
selected_nature_kind: str | None = None
selected_variant = ""
shape_buttons: dict[str, Button] = {}
nature_buttons: dict[str, Button] = {}
variant_menus: dict[str, DropdownMenu] = {}

PRIMITIVE_OBJECTS = {
    "cube": ("Куб", Size3D(2, 2, 2)),
    "cylinder": ("Цилиндр", Size3D(2, 2, 2)),
    "rectangular_prism": ("Параллелепипед", Size3D(3, 2, 2)),
    "arc": ("Дуга", Size3D(6, 2, 0.12)),
}

TYPICAL_OBJECTS = {
    "house": ("Дом", Size3D(12, 8, 3.6), "#B27A55", "#6A3F36"),
    "bathhouse": ("Баня", Size3D(5, 5, 5.5), "#9A7450", "#496A43"),
    "shed": ("Сарай", Size3D(4, 3, 4.0), "#8D6749", "#654735"),
    "toilet": ("Туалет", Size3D(1.2, 1.2, 2.2), "#825B3D", "#553B2D"),
    "garage": ("Гараж", Size3D(6, 7, 3.6), "#667686", "#46545D"),
    "well": ("Колодец", Size3D(1.4, 1.4, 1.5), "#91918C", "#4F5B63"),
}

NATURE_OBJECTS = {
    "tree": {
        "label": "Дерево",
        "size": Size3D(4, 4, 7),
        "variants": (
            ("pine", "Сосна", "#2F6B35"),
            ("birch", "Берёза", "#63A84C"),
            ("apple", "Яблоня", "#5E993D"),
            ("pine_photo", "Сосна фото", "#FFFFFF"),
            ("birch_photo", "Берёза фото", "#FFFFFF"),
            ("ash_photo", "Ясень фото", "#FFFFFF"),
        ),
    },
    "bush": {
        "label": "Куст",
        "size": Size3D(2.2, 2.2, 1.6),
        "variants": (
            ("narrow", "Узкие", "#4A8C43"),
            ("wide", "Широкие", "#3F843A"),
            ("raspberry", "Малина", "#4E8F4D"),
        ),
    },
    "garden_bed": {
        "label": "Грядка",
        "size": Size3D(5, 1.2, 0.75),
        "variants": (
            ("carrot", "Морковь", "#4C9A3D"),
            ("onion", "Лук", "#55A94F"),
            ("strawberry", "Клубника", "#4C8B42"),
        ),
    },
}

ARC_OBJECT = {
    "label": "Дуга",
    "variants": (
        ("asphalt", "Асфальт", "#25282A"),
        ("gravel", "Щебень", "#BEBEB6"),
        ("ground", "Грунт", "#8A6847"),
        ("wood", "Дерево", "#9B6B3F"),
        ("stone", "Камень", "#777C80"),
        ("grass", "Трава", "#5D8C4D"),
        ("bushes", "Кусты", "#3F743B"),
    ),
}
if (
    frozenset(value for value, _label, _color in ARC_OBJECT["variants"])
    != ARC_VARIANTS
):
    raise RuntimeError("Arc variant definitions must match the domain model")
VARIANT_OBJECTS = {**NATURE_OBJECTS, "arc": ARC_OBJECT}


def variant_details(kind: str, variant: str) -> tuple[str, str]:
    for value, label, default_color in VARIANT_OBJECTS[kind]["variants"]:
        if value == variant:
            return label, default_color
    raise DomainValidationError(f"Неизвестный вариант объекта: {variant}")


def variant_label(value: str) -> str:
    if not value:
        return "-"
    for definition in VARIANT_OBJECTS.values():
        for variant, label, _default_color in definition["variants"]:
            if variant == value:
                return label
    return value


def refresh_shape_controls() -> None:
    is_primitive = selected_template is None and selected_nature_kind is None
    for shape, button in shape_buttons.items():
        button.color = (
            color.azure
            if is_primitive and shape == selected_shape
            else color.dark_gray
        )


def refresh_nature_controls() -> None:
    for kind, button in nature_buttons.items():
        button.color = color.azure if kind == selected_nature_kind else color.dark_gray
    active_kind = (
        selected_nature_kind
        if selected_nature_kind is not None
        else "arc"
        if selected_shape == "arc"
        else "none"
    )
    for kind, menu in variant_menus.items():
        is_active = kind == active_kind
        menu.enabled = is_active
        if is_active:
            menu.text = f"Вариант: {variant_label(selected_variant)}"


def select_shape(shape: str) -> None:
    global selected_shape, selected_template, selected_nature_kind
    global selected_variant
    clear_selection()
    selected_shape = shape
    selected_template = None
    selected_nature_kind = None
    selected_variant = "gravel" if shape == "arc" else ""
    template_menu.text = "Типовой объект"
    label, default_size = PRIMITIVE_OBJECTS[shape]
    name_field.text = label
    size_x_field.text = f"{default_size.x:g}"
    size_y_field.text = f"{default_size.y:g}"
    size_z_field.text = f"{default_size.z:g}"
    color_field.text = (
        variant_details("arc", selected_variant)[1]
        if shape == "arc"
        else "#C97B45"
    )
    color2_field.text = color_to_hex(darker(parse_color(color_field.text), 0.72))
    refresh_shape_controls()
    refresh_nature_controls()
    set_status(f"Выбран примитив: {label}")


def select_nature_variant(kind: str, variant: str) -> None:
    global selected_variant
    if kind not in VARIANT_OBJECTS:
        return
    selected_variant = variant
    label, default_color = variant_details(kind, variant)
    color_field.text = default_color
    color2_field.text = (
        default_color
        if default_color == "#FFFFFF"
        else color_to_hex(darker(parse_color(default_color), 0.78))
    )
    if selected_root is None and kind == "tree" and variant in PHOTO_TREE_DEFAULT_SIZES:
        default_size = PHOTO_TREE_DEFAULT_SIZES[variant]
        size_x_field.text = f"{default_size.x:g}"
        size_y_field.text = f"{default_size.y:g}"
        size_z_field.text = f"{default_size.z:g}"
    refresh_nature_controls()
    if selected_root is not None:
        apply_selected_properties()
    set_status(f"Выбран вариант: {label}")


def select_nature(kind: str) -> None:
    global selected_shape, selected_template, selected_nature_kind
    global selected_variant
    clear_selection()
    selected_template = None
    selected_nature_kind = kind
    first_variant, _label, default_color = NATURE_OBJECTS[kind]["variants"][0]
    selected_variant = first_variant
    selected_shape = None
    template_menu.text = "Типовой объект"
    default_size = NATURE_OBJECTS[kind]["size"]
    name_field.text = NATURE_OBJECTS[kind]["label"]
    size_x_field.text = f"{default_size.x:g}"
    size_y_field.text = f"{default_size.y:g}"
    size_z_field.text = f"{default_size.z:g}"
    color_field.text = default_color
    color2_field.text = color_to_hex(darker(parse_color(default_color), 0.78))
    refresh_shape_controls()
    refresh_nature_controls()
    set_status(f"Выбран природный объект: {NATURE_OBJECTS[kind]['label']}")


def select_template(template: str) -> None:
    global selected_shape, selected_template, selected_nature_kind
    global selected_variant
    clear_selection()
    selected_template = template
    selected_nature_kind = None
    selected_variant = ""
    label, default_size, default_color, default_secondary = TYPICAL_OBJECTS[template]
    selected_shape = None
    refresh_shape_controls()
    refresh_nature_controls()
    template_menu.text = f"Тип: {label}"
    name_field.text = label
    size_x_field.text = f"{default_size.x:g}"
    size_y_field.text = f"{default_size.y:g}"
    size_z_field.text = f"{default_size.z:g}"
    color_field.text = default_color
    color2_field.text = default_secondary
    set_status(f"Выбран типовой объект: {label}")


def darker(value: Rgba, factor: float = 0.55) -> Rgba:
    return Rgba(
        round(value.red * factor),
        round(value.green * factor),
        round(value.blue * factor),
        value.alpha,
    )


def typical_roof_spec(
    template: str, size: Size3D, roof_color: Rgba
) -> RoofSpec:
    if template in {"bathhouse", "shed"}:
        roof_height = size.y / 2
        if roof_height >= size.z:
            raise DomainValidationError(
                "Для двускатной крыши 45° высота Z должна быть больше Y / 2"
            )
        shape = "gable"
    elif template == "garage":
        roof_height = min(size.z * 0.18, size.y * 0.12)
        shape = "shed"
    else:
        roof_height = size.z * 0.25
        shape = "gable"
    return RoofSpec(
        shape=shape,
        height_m=roof_height,
        overhang_m=min(size.x, size.y) * 0.04,
        ridge_axis="x",
        color=roof_color,
    )


def add_object_from_panel() -> None:
    try:
        size_x = parse_positive(size_x_field, "Размер X")
        size_y = parse_positive(size_y_field, "Размер Y")
        size_z = parse_positive(size_z_field, "Высота Z")
        if selected_shape == "cube":
            size_y = size_x
            size_z = size_x
        size = Size3D(size_x, size_y, size_z)
        object_color = parse_color(color_field.text)
        object_secondary_color = parse_color(color2_field.text)
        center = Point2D(0, plot_center_z)
        if selected_nature_kind is not None:
            default_name = NATURE_OBJECTS[selected_nature_kind]["label"]
        elif selected_template is not None:
            default_name = TYPICAL_OBJECTS[selected_template][0]
        elif selected_shape is not None:
            default_name = PRIMITIVE_OBJECTS[selected_shape][0]
        else:
            raise DomainValidationError(
                "Выберите примитив, типовой или природный объект для добавления"
            )
        object_name = name_field.text.strip() or default_name

        if selected_nature_kind is not None:
            if not selected_variant:
                raise DomainValidationError("Выберите вариант природного объекта")
            item = SiteFeature(
                id=f"nature-{selected_nature_kind}-{uuid4().hex[:8]}",
                kind=selected_nature_kind,
                variant=selected_variant,
                name=object_name,
                center=center,
                size=Size2D(size_x, size_y),
                shape=(
                    "rectangle"
                    if selected_nature_kind == "garden_bed"
                    else "circle"
                ),
                color=object_color,
                secondary_color=object_secondary_color,
                height_m=size_z,
                movable=True,
                note=(
                    "Природный объект; X/Y/Z задают общую габаритную оболочку, "
                    "variant задаёт внешний вид."
                ),
            )
        elif selected_template == "well":
            ring_height = size_z * (0.7 / 1.5)
            item = SiteFeature(
                id=f"typical-well-{uuid4().hex[:8]}",
                kind="well",
                name=object_name,
                center=center,
                size=Size2D(size_x, size_y),
                shape="circle",
                color=object_color,
                secondary_color=object_secondary_color,
                height_m=size_z,
                movable=True,
                variant=selected_variant,
                well_structure=WellStructure(
                    ring_height_m=ring_height,
                    roof_height_m=size_z - ring_height,
                    roof_overhang_m=min(size_x, size_y) * (0.2 / 1.4),
                    ridge_axis="x",
                    roof_color=object_secondary_color,
                ),
                note="Типовой колодец; редактируется общая цилиндрическая оболочка.",
            )
        elif selected_template is not None:
            roof = typical_roof_spec(
                selected_template, size, object_secondary_color
            )
            item = Building(
                id=f"typical-{selected_template}-{uuid4().hex[:8]}",
                kind=selected_template,
                name=object_name,
                center=center,
                footprint=Size2D(size_x, size_y),
                height_m=size_z,
                floors=1,
                color=object_color,
                secondary_color=object_secondary_color,
                movable=True,
                variant=selected_variant,
                wall_height_m=size_z - roof.height_m,
                roof=roof,
                note="Типовой объект; редактируется общий параллелепипед X/Y/Z.",
            )
        elif selected_shape is not None:
            item = PrimitiveObject(
                id=f"custom-{uuid4().hex[:8]}",
                name=object_name,
                shape=selected_shape,
                center=center,
                size=size,
                color=object_color,
                secondary_color=object_secondary_color,
                movable=True,
                variant=selected_variant,
                arc_angle_deg=45.0,
                note=(
                    "Добавлено через 3D-панель; у дуги X — длина по оси, "
                    "Y — ширина, Z — высота, R/T меняют кривизну."
                    if selected_shape == "arc"
                    else "Добавлено через 3D-панель; X/Y — план, Z — высота."
                ),
            )

        if current_mode == "site":
            if isinstance(item, Building):
                editor.add_site_building(item)
            elif isinstance(item, SiteFeature):
                editor.add_site_feature(item)
            else:
                editor.add_site_primitive(item)
        elif isinstance(item, Building):
            editor.add_building(current_layout_id, item)
        elif isinstance(item, SiteFeature):
            editor.add_feature(current_layout_id, item)
        else:
            editor.add_primitive(current_layout_id, item)
    except (DomainValidationError, ValueError) as exc:
        set_status(str(exc), error=True)
        return

    show_layout(current_layout_id)
    set_status(f"Добавлен объект: {item.name}; перетащите его мышью")


def save_project() -> None:
    try:
        editor.save()
    except ValueError as exc:
        set_status(str(exc), error=True)
        return
    set_status("Проект сохранён в data.json")


plot_center_z = (
    min(point.z for point in editor.project.plot.boundary)
    + max(point.z for point in editor.project.plot.boundary)
) / 2

panel = Entity(
    parent=camera.ui,
    model="quad",
    position=(0.61, 0, 0.1),
    scale=(0.32, 0.94),
    color=color.rgba32(30, 35, 42, 235),
)

site_mode_button = Button(
    parent=camera.ui,
    text="Создание участка",
    position=(0.535, 0.43),
    scale=(0.14, 0.04),
    color=color.dark_gray,
    text_size=0.62,
    on_click=lambda: set_mode("site"),
)
design_mode_button = Button(
    parent=camera.ui,
    text="Дизайн",
    position=(0.68, 0.43),
    scale=(0.12, 0.04),
    color=color.azure,
    text_size=0.7,
    on_click=lambda: set_mode("design"),
)

design_menu = DropdownMenu(
    text="Выбор схемы",
    buttons=tuple(
        DropdownMenuButton(
            layout.name,
            on_click=lambda selected=layout.id: switch_design(selected),
        )
        for layout in editor.project.layouts
    ),
    parent=camera.ui,
    position=(0.47, 0.382),
    scale=(0.195, 0.032),
    color=color.rgb32(65, 72, 82),
    text_size=0.50,
    z=-2,
)
grid_button = Button(
    parent=camera.ui,
    text="Сетка",
    position=(0.72, 0.366),
    scale=(0.09, 0.032),
    color=color.dark_gray,
    text_size=0.55,
    on_click=toggle_coordinate_grid,
)
coordinate_readout = Text(
    parent=camera.ui,
    text="X = +000.00 м    Z = +000.00 м",
    position=(-0.05, 0.475, -10),
    origin=(0, 0.5),
    scale=1.30,
    color=color.rgb32(255, 235, 45),
    background=True,
    enabled=False,
)
template_menu = DropdownMenu(
    text="Типовой объект",
    buttons=tuple(
        DropdownMenuButton(
            label,
            on_click=lambda selected=kind: select_template(selected),
        )
        for kind, (label, _size, _color, _secondary_color) in TYPICAL_OBJECTS.items()
    ),
    parent=camera.ui,
    position=(0.47, 0.296),
    scale=(0.28, 0.032),
    color=color.rgb32(78, 84, 94),
    text_size=0.58,
    z=-1.9,
)
object_panel_title = Text(
    parent=camera.ui,
    text="Добавить 3D-объект",
    position=(0.47, 0.342),
    origin=(-0.5, 0.5),
    scale=0.9,
    color=color.white,
)

shape_definitions = (
    ("cube", "Куб", 0.49),
    ("cylinder", "Цилиндр", 0.60),
    ("rectangular_prism", "Паралл.", 0.71),
)
for shape, label, x_position in shape_definitions:
    button = Button(
        parent=camera.ui,
        text=label,
        position=(x_position, 0.252),
        scale=(0.095, 0.038),
        color=color.dark_gray,
        text_size=0.66,
        on_click=lambda selected=shape: select_shape(selected),
    )
    shape_buttons[shape] = button

nature_definitions = (
    ("tree", "Дерево", 0.49),
    ("bush", "Куст", 0.60),
    ("garden_bed", "Грядка", 0.71),
)
for nature_kind, label, x_position in nature_definitions:
    button = Button(
        parent=camera.ui,
        text=label,
        position=(x_position, 0.211),
        scale=(0.095, 0.038),
        color=color.dark_gray,
        text_size=0.7,
        on_click=lambda selected=nature_kind: select_nature(selected),
    )
    nature_buttons[nature_kind] = button

arc_button = Button(
    parent=camera.ui,
    text="Дуга",
    position=(0.49, 0.170),
    scale=(0.095, 0.038),
    color=color.dark_gray,
    text_size=0.70,
    on_click=lambda: select_shape("arc"),
)
shape_buttons["arc"] = arc_button

for variant_kind, definition in VARIANT_OBJECTS.items():
    menu = DropdownMenu(
        text="Вариант: -",
        buttons=tuple(
            DropdownMenuButton(
                label,
                on_click=lambda selected_kind=variant_kind, selected_variant=variant: (
                    select_nature_variant(selected_kind, selected_variant)
                ),
            )
            for variant, label, _default_color in definition["variants"]
        ),
        parent=camera.ui,
        position=(0.47, 0.128),
        scale=(0.28, 0.032),
        color=color.rgb32(78, 84, 94),
        text_size=0.58,
        z=-1.85,
        enabled=False,
    )
    variant_menus[variant_kind] = menu

variant_menus["none"] = DropdownMenu(
    text="Вариант: -",
    buttons=(),
    parent=camera.ui,
    position=(0.47, 0.128),
    scale=(0.28, 0.032),
    color=color.rgb32(78, 84, 94),
    text_size=0.58,
    z=-1.85,
)

field_color = color.rgba32(238, 240, 242, 255)
name_field = CyrillicInputField(
    parent=camera.ui,
    label="Имя",
    default_value="Новый объект",
    position=(0.61, 0.075),
    scale=(0.27, 0.036),
    color=field_color,
)
size_x_field = CyrillicInputField(
    parent=camera.ui,
    label="Размер X",
    default_value="2.0",
    position=(0.61, 0.022),
    scale=(0.27, 0.036),
    color=field_color,
)
size_y_field = CyrillicInputField(
    parent=camera.ui,
    label="Размер Y",
    default_value="2.0",
    position=(0.61, -0.031),
    scale=(0.27, 0.036),
    color=field_color,
)
size_z_field = CyrillicInputField(
    parent=camera.ui,
    label="Высота Z",
    default_value="2.0",
    position=(0.61, -0.084),
    scale=(0.27, 0.036),
    color=field_color,
)
color_field = CyrillicInputField(
    parent=camera.ui,
    label="Цвет",
    default_value="#C97B45",
    position=(0.61, -0.137),
    scale=(0.225, 0.036),
    color=field_color,
)
color2_field = CyrillicInputField(
    parent=camera.ui,
    label="Цвет-2",
    default_value="#914F32",
    position=(0.61, -0.180),
    scale=(0.225, 0.036),
    color=field_color,
)
color_swatch_button = Button(
    parent=camera.ui,
    text="▼",
    position=(0.744, -0.137),
    scale=(0.032, 0.036),
    color=to_color(parse_color(color_field.text)),
    text_color=color.black,
    text_size=0.45,
    on_click=lambda: open_color_palette(color_field),
)
color2_swatch_button = Button(
    parent=camera.ui,
    text="▼",
    position=(0.744, -0.180),
    scale=(0.032, 0.036),
    color=to_color(parse_color(color2_field.text)),
    text_color=color.black,
    text_size=0.45,
    on_click=lambda: open_color_palette(color2_field),
)

color_palette_panel = Entity(parent=camera.ui, z=-20, enabled=False)
Entity(
    parent=color_palette_panel,
    model="quad",
    position=(0.395, -0.174, 0.01),
    scale=(0.195, 0.205),
    color=color.rgba32(35, 40, 47, 248),
)
Text(
    parent=color_palette_panel,
    text="16 основных цветов",
    position=(0.305, -0.082),
    origin=(-0.5, 0.5),
    scale=0.58,
    color=color.white,
)
for index, (palette_name, palette_value) in enumerate(PALETTE_COLORS):
    column = index % 4
    row = index // 4
    Button(
        parent=color_palette_panel,
        text="",
        position=(0.333 + column * 0.042, -0.125 - row * 0.041),
        scale=(0.034, 0.032),
        color=to_color(parse_color(palette_value)),
        highlight_color=to_color(parse_color(palette_value)),
        pressed_color=color.white,
        on_click=lambda selected_name=palette_name, selected_value=palette_value: (
            choose_palette_color(selected_name, selected_value)
        ),
    )

input_fields = (
    name_field,
    size_x_field,
    size_y_field,
    size_z_field,
    color_field,
    color2_field,
)
for field in input_fields:
    field.text_color = color.black
    field.submit_on = ["enter"]
    field.on_submit = apply_selected_properties
    field.on_value_changed = lambda current_field=field: on_editable_field_changed(
        current_field
    )

add_button = Button(
    parent=camera.ui,
    text="Добавить",
    position=(0.55, -0.225),
    scale=(0.13, 0.05),
    color=color.azure,
    text_size=0.7,
    on_click=add_object_from_panel,
)
save_button = Button(
    parent=camera.ui,
    text="Сохранить",
    position=(0.68, -0.225),
    scale=(0.11, 0.05),
    color=color.rgb32(75, 145, 85),
    text_size=0.7,
    on_click=save_project,
)

selected_name_text = Text(
    parent=camera.ui,
    text="Объект не выбран",
    position=(0.47, -0.270),
    origin=(-0.5, 0.5),
    scale=0.72,
    color=color.white,
)
protected_checkbox = ProtectedCheckBox(
    on_change=on_protection_changed,
    parent=camera.ui,
    start_value=False,
    position=(0.49, -0.312),
    scale=0.025,
    color=color.azure,
    enabled=False,
)
Text(
    parent=camera.ui,
    text="Защищён",
    position=(0.515, -0.299),
    origin=(-0.5, 0.5),
    scale=0.72,
    color=color.white,
)
delete_button = Button(
    parent=camera.ui,
    text="Удалить / скрыть",
    position=(0.545, -0.357),
    scale=(0.14, 0.045),
    color=color.rgb32(170, 62, 62),
    text_size=0.68,
    enabled=False,
    on_click=delete_selected,
)
restore_button = Button(
    parent=camera.ui,
    text="Вернуть в дизайн",
    position=(0.69, -0.357),
    scale=(0.13, 0.045),
    color=color.rgb32(70, 125, 78),
    text_size=0.62,
    enabled=False,
    on_click=restore_selected,
)

design_only_controls.extend(
    [
        delete_button,
    ]
)

status_text = Text(
    parent=camera.ui,
    text="Готово",
    position=(0.47, -0.405),
    origin=(-0.5, 0.5),
    scale=0.68,
    color=color.light_gray,
    wordwrap=31,
)
layout_label = Text(
    parent=camera.ui,
    text=" ",
    position=(-0.74, 0.44),
    origin=(-0.5, 0.5),
    scale=0.82,
    color=color.black,
)
Text(
    parent=camera.ui,
    text=(
        "ЛКМ по объекту — перемещение\n"
        "A/D — ось X; W/S — ось Z; Q/E — поворот\n"
        "R/T — уменьшить/увеличить кривизну дуги\n"
        "ПКМ — вращение камеры; средняя кнопка — панорама\n"
        "Колесо — масштаб; 1/2/3 — варианты"
    ),
    position=(-0.74, -0.40),
    origin=(-0.5, -0.5),
    scale=0.64,
    color=color.black,
)


def set_status(message: str, error: bool = False) -> None:
    status_text.text = message
    status_text.color = color.rgb32(255, 135, 120) if error else color.light_gray


select_template("house")
set_mode("design")

camera.fov = 55
camera.position = (0, 0, -72)
editor_camera = EditorCamera(
    position=(0, 1.5, plot_center_z),
    rotation=(32, -8, 0),
    move_speed=20,
    rotate_key="right mouse",
    ignore_scroll_on_ui=True,
)

sun = DirectionalLight(shadows=True)
sun.look_at(Vec3(1, -2, -1))
AmbientLight(color=color.rgba32(145, 145, 150, 255))
Sky(color=color.rgb32(178, 202, 226))

layout_keys = {
    str(index): layout.id for index, layout in enumerate(editor.project.layouts, start=1)
}


def update() -> None:
    update_coordinate_readout()


def input(key: str) -> None:
    if any(field.active for field in input_fields):
        return
    if key in layout_keys:
        switch_design(layout_keys[key])
        return

    if (
        selected_root is None
        or not isinstance(selected_root, MovableGroup)
        or held_keys["right mouse"]
        or held_keys["middle mouse"]
    ):
        return

    movement_step = 1.0 if held_keys["shift"] else 0.25
    rotation_step = 15.0 if held_keys["shift"] else 5.0
    curvature_step = 15.0 if held_keys["shift"] else 5.0
    delta_x = 0.0
    delta_y = 0.0
    if key == "a":
        delta_x = -movement_step
    elif key == "d":
        delta_x = movement_step
    elif key == "w":
        delta_y = movement_step
    elif key == "s":
        delta_y = -movement_step
    elif key in {"r", "t"}:
        collection = selected_root.edit_collection
        item_id = selected_root.edit_item_id
        layout_id = selected_root.edit_layout_id
        item = editor.get_item(layout_id, collection, item_id)
        if not isinstance(item, PrimitiveObject) or item.shape != "arc":
            set_status("R/T изменяют кривизну только у примитива «Дуга»", error=True)
            return
        direction = -1 if key == "r" else 1
        requested_angle = max(
            5.0,
            min(175.0, item.arc_angle_deg + direction * curvature_step),
        )
        try:
            editor.set_arc_angle(
                layout_id,
                collection,
                item_id,
                requested_angle,
            )
        except (DomainValidationError, ValueError) as exc:
            set_status(str(exc), error=True)
            return
        show_layout(layout_id)
        rendered = find_rendered_root(collection, item_id)
        if rendered is not None:
            select_object(rendered, collection, item_id, layout_id)
        set_status(f"{item_id}: кривизна {requested_angle:g}°")
        return
    elif key not in {"q", "e"}:
        return

    try:
        if key in {"q", "e"}:
            direction = -1 if key == "q" else 1
            new_rotation = (selected_root.rotation_y + direction * rotation_step) % 360
            editor.rotate_item(
                selected_root.edit_layout_id,
                selected_root.edit_collection,
                selected_root.edit_item_id,
                new_rotation,
            )
            selected_root.rotation_y = new_rotation
        else:
            new_center = Point2D(
                round(selected_root.x + delta_x, 2),
                round(selected_root.z + delta_y, 2),
            )
            editor.move_item(
                selected_root.edit_layout_id,
                selected_root.edit_collection,
                selected_root.edit_item_id,
                new_center,
            )
            selected_root.position = (new_center.x, 0, new_center.z)
            moved_item = editor.get_item(
                selected_root.edit_layout_id,
                selected_root.edit_collection,
                selected_root.edit_item_id,
            )
            selected_name_text.text = (
                f"{moved_item.name}: X={new_center.x:g}; Z={new_center.z:g}"
            )
    except (DomainValidationError, ValueError) as exc:
        set_status(str(exc), error=True)
        return

    set_status(
        f"{selected_root.edit_item_id}: X={selected_root.x:g}, "
        f"Z={selected_root.z:g}, угол={selected_root.rotation_y:g}°"
    )


if not SKIP_APP_LOOP:
    app.run()
