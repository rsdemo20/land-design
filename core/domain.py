"""Framework-independent domain model for a land-plot planning project."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import cos, hypot, radians, sin
from typing import Iterable


class DomainValidationError(ValueError):
    """Raised when persisted project data violates a domain invariant."""


FENCE_OBJECT_ID = "plot_fence"
NATURE_VARIANTS = {
    "tree": frozenset(
        {
            "pine",
            "birch",
            "apple",
            "pine_photo",
            "birch_photo",
            "ash_photo",
        }
    ),
    "bush": frozenset({"narrow", "wide", "raspberry"}),
    "garden_bed": frozenset({"carrot", "onion", "strawberry"}),
}
ARC_VARIANTS = frozenset(
    {"asphalt", "gravel", "ground", "wood", "stone", "grass", "bushes"}
)


@dataclass(frozen=True)
class Point2D:
    x: float
    z: float

    def distance_to(self, other: "Point2D") -> float:
        return hypot(self.x - other.x, self.z - other.z)


@dataclass(frozen=True)
class Size2D:
    width: float
    depth: float

    def __post_init__(self) -> None:
        if self.width <= 0 or self.depth <= 0:
            raise DomainValidationError("Object width and depth must be positive")


@dataclass(frozen=True)
class Size3D:
    """User-facing X/Y footprint dimensions and vertical Z height."""

    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        if self.x <= 0 or self.y <= 0 or self.z <= 0:
            raise DomainValidationError("3D object dimensions X, Y and Z must be positive")

    @property
    def footprint(self) -> Size2D:
        return Size2D(width=self.x, depth=self.y)


@dataclass(frozen=True)
class Rgba:
    red: int
    green: int
    blue: int
    alpha: int = 255

    def __post_init__(self) -> None:
        channels = (self.red, self.green, self.blue, self.alpha)
        if any(not 0 <= channel <= 255 for channel in channels):
            raise DomainValidationError("RGBA channels must be in the range 0..255")


@dataclass(frozen=True)
class PlotDimensions:
    front_width_m: float
    rear_width_m: float
    left_side_m: float
    right_side_m: float
    declared_area_sqm: float

    def __post_init__(self) -> None:
        values = (
            self.front_width_m,
            self.rear_width_m,
            self.left_side_m,
            self.right_side_m,
            self.declared_area_sqm,
        )
        if any(value <= 0 for value in values):
            raise DomainValidationError("Plot dimensions and area must be positive")


@dataclass(frozen=True)
class PlotMarker:
    id: str
    position: Point2D
    role: str
    accuracy: str = "model"
    note: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raise DomainValidationError("Plot marker id cannot be empty")


@dataclass(frozen=True)
class HatchStyle:
    spacing_m: float
    line_width_m: float
    color: Rgba

    def __post_init__(self) -> None:
        if self.spacing_m <= 0 or self.line_width_m <= 0:
            raise DomainValidationError("Hatch spacing and line width must be positive")


@dataclass(frozen=True)
class FenceStyle:
    front_height_m: float
    other_height_m: float
    thickness_m: float
    color: Rgba
    protected: bool = True

    def __post_init__(self) -> None:
        if (
            self.front_height_m <= 0
            or self.other_height_m <= 0
            or self.thickness_m <= 0
        ):
            raise DomainValidationError("Fence heights and thickness must be positive")


@dataclass(frozen=True)
class Plot:
    id: str
    name: str
    dimensions: PlotDimensions
    markers: tuple[PlotMarker, ...]
    boundary_order: tuple[str, ...]
    corner_ids: tuple[str, ...]
    north_axis: str
    north_direction: Point2D
    north_reference: str
    fill_color: Rgba
    boundary_color: Rgba
    hatch: HatchStyle
    fence: FenceStyle | None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if len(self.boundary_order) < 3:
            raise DomainValidationError("A plot boundary requires at least three markers")

        marker_ids = [marker.id for marker in self.markers]
        if len(marker_ids) != len(set(marker_ids)):
            raise DomainValidationError("Plot marker ids must be unique")

        known_ids = set(marker_ids)
        missing = (set(self.boundary_order) | set(self.corner_ids)) - known_ids
        if missing:
            raise DomainValidationError(
                f"Unknown marker ids referenced by plot boundary: {sorted(missing)}"
            )
        if self.north_axis not in {"+z", "custom_vector"}:
            raise DomainValidationError(
                "north_axis must be '+z' or 'custom_vector'"
            )
        if self.north_direction.distance_to(Point2D(0, 0)) <= 1e-9:
            raise DomainValidationError("North direction vector cannot be zero")
        if not self.north_reference:
            raise DomainValidationError("North direction reference is required")
        if self.area_sqm <= 0:
            raise DomainValidationError("Plot polygon area must be positive")

    @property
    def markers_by_id(self) -> dict[str, PlotMarker]:
        return {marker.id: marker for marker in self.markers}

    @property
    def boundary(self) -> tuple[Point2D, ...]:
        by_id = self.markers_by_id
        return tuple(by_id[marker_id].position for marker_id in self.boundary_order)

    @property
    def corners(self) -> tuple[Point2D, ...]:
        by_id = self.markers_by_id
        return tuple(by_id[marker_id].position for marker_id in self.corner_ids)

    @property
    def area_sqm(self) -> float:
        vertices = self.boundary
        cross_sum = sum(
            current.x * following.z - following.x * current.z
            for current, following in zip(vertices, vertices[1:] + vertices[:1])
        )
        return abs(cross_sum) / 2

    @property
    def north_unit_vector(self) -> Point2D:
        length = self.north_direction.distance_to(Point2D(0, 0))
        return Point2D(
            self.north_direction.x / length,
            self.north_direction.z / length,
        )

    def marker(self, marker_id: str) -> PlotMarker:
        try:
            return self.markers_by_id[marker_id]
        except KeyError as exc:
            raise KeyError(f"Unknown plot marker: {marker_id}") from exc


@dataclass(frozen=True)
class RoofSpec:
    shape: str
    height_m: float
    overhang_m: float
    ridge_axis: str
    color: Rgba

    def __post_init__(self) -> None:
        if self.shape not in {"gable", "shed", "flat"}:
            raise DomainValidationError(f"Unsupported roof shape: {self.shape}")
        if self.height_m <= 0 or self.overhang_m < 0:
            raise DomainValidationError("Roof height must be positive and overhang non-negative")
        if self.ridge_axis not in {"x", "y"}:
            raise DomainValidationError("Roof ridge_axis must be 'x' or 'y'")


@dataclass(frozen=True)
class WellStructure:
    ring_height_m: float
    roof_height_m: float
    roof_overhang_m: float
    ridge_axis: str
    roof_color: Rgba

    def __post_init__(self) -> None:
        if self.ring_height_m <= 0 or self.roof_height_m <= 0:
            raise DomainValidationError("Well ring and roof heights must be positive")
        if self.roof_overhang_m < 0:
            raise DomainValidationError("Well roof overhang must be non-negative")
        if self.ridge_axis not in {"x", "y"}:
            raise DomainValidationError("Well roof ridge_axis must be 'x' or 'y'")

    @property
    def total_height_m(self) -> float:
        return self.ring_height_m + self.roof_height_m


@dataclass(frozen=True)
class Building:
    id: str
    kind: str
    name: str
    center: Point2D
    footprint: Size2D
    height_m: float
    floors: int
    color: Rgba
    movable: bool = True
    wall_height_m: float | None = None
    roof: RoofSpec | None = None
    rotation_y: float = 0.0
    note: str = ""
    protected: bool = False
    variant: str = ""
    secondary_color: Rgba | None = None

    def __post_init__(self) -> None:
        if self.secondary_color is None:
            object.__setattr__(self, "secondary_color", self.color)
        if not self.id or not self.kind or not self.name:
            raise DomainValidationError("Building id, kind and name are required")
        if self.height_m <= 0:
            raise DomainValidationError("Building height must be positive")
        if self.floors < 1:
            raise DomainValidationError("Building must have at least one floor")
        if self.wall_height_m is not None and not 0 < self.wall_height_m <= self.height_m:
            raise DomainValidationError("Building wall height must fit inside total height")
        if self.roof is not None:
            if self.wall_height_m is None:
                raise DomainValidationError("A roof requires wall_height_m")
            if abs(self.wall_height_m + self.roof.height_m - self.height_m) > 1e-6:
                raise DomainValidationError(
                    "Building total height must equal wall height plus roof height"
                )
            if self.roof.overhang_m * 2 >= min(
                self.footprint.width, self.footprint.depth
            ):
                raise DomainValidationError("Roof overhang leaves no room for walls")


@dataclass(frozen=True)
class SiteFeature:
    id: str
    kind: str
    name: str
    center: Point2D
    size: Size2D
    shape: str
    color: Rgba
    height_m: float = 0.2
    movable: bool = True
    rotation_y: float = 0.0
    note: str = ""
    well_structure: WellStructure | None = None
    protected: bool = False
    variant: str = ""
    secondary_color: Rgba | None = None

    def __post_init__(self) -> None:
        if self.secondary_color is None:
            object.__setattr__(self, "secondary_color", self.color)
        if not self.id or not self.kind or not self.name:
            raise DomainValidationError("Feature id, kind and name are required")
        if self.shape not in {"rectangle", "circle"}:
            raise DomainValidationError(
                f"Unsupported feature shape '{self.shape}' for feature '{self.id}'"
            )
        if self.height_m <= 0:
            raise DomainValidationError("Feature height must be positive")
        if self.well_structure is not None:
            if self.kind != "well":
                raise DomainValidationError(
                    "Well structure can only be assigned to a well feature"
                )
            if abs(self.height_m - self.well_structure.total_height_m) > 1e-6:
                raise DomainValidationError(
                    "Well total height must equal ring height plus roof height"
                )
        allowed_variants = NATURE_VARIANTS.get(self.kind)
        if allowed_variants is not None and self.variant not in allowed_variants:
            raise DomainValidationError(
                f"Unsupported variant '{self.variant}' for feature kind '{self.kind}'"
            )


@dataclass(frozen=True)
class PrimitiveObject:
    id: str
    name: str
    shape: str
    center: Point2D
    size: Size3D
    color: Rgba
    movable: bool = True
    rotation_y: float = 0.0
    note: str = ""
    protected: bool = False
    variant: str = ""
    arc_angle_deg: float = 45.0
    secondary_color: Rgba | None = None

    def __post_init__(self) -> None:
        if self.secondary_color is None:
            object.__setattr__(self, "secondary_color", self.color)
        if not self.id or not self.name:
            raise DomainValidationError("Primitive id and name are required")
        if self.shape not in {"cube", "cylinder", "rectangular_prism", "arc"}:
            raise DomainValidationError(f"Unsupported primitive shape: {self.shape}")
        if self.shape == "cube" and (
            abs(self.size.x - self.size.y) > 1e-6
            or abs(self.size.x - self.size.z) > 1e-6
        ):
            raise DomainValidationError("Cube dimensions X, Y and Z must be equal")
        if self.shape == "arc":
            if self.variant and self.variant not in ARC_VARIANTS:
                raise DomainValidationError(
                    f"Unsupported arc variant: {self.variant}"
                )
            if not 5.0 <= self.arc_angle_deg <= 175.0:
                raise DomainValidationError(
                    "Arc curvature angle must be in the range 5..175 degrees"
                )
            radius = self.size.x / radians(self.arc_angle_deg)
            if radius <= self.size.y / 2:
                raise DomainValidationError(
                    "Arc X length is too short for its Y width and curvature"
                )


@dataclass(frozen=True)
class ContextArea:
    """A stationary polygon outside the editable plot, such as neighbouring land."""

    id: str
    kind: str
    name: str
    boundary: tuple[Point2D, ...]
    color: Rgba
    height_m: float = 0.02
    note: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.kind or not self.name:
            raise DomainValidationError("Context area id, kind and name are required")
        if len(self.boundary) < 3:
            raise DomainValidationError("A context area requires at least three points")
        if self.height_m < 0:
            raise DomainValidationError("Context area height cannot be negative")
        cross_sum = sum(
            current.x * following.z - following.x * current.z
            for current, following in zip(
                self.boundary, self.boundary[1:] + self.boundary[:1]
            )
        )
        if abs(cross_sum) <= 1e-6:
            raise DomainValidationError("Context area boundary must have a positive area")


@dataclass(frozen=True)
class ContextLinearObject:
    """An editable context polyline used for roads, ditches and fences."""

    id: str
    kind: str
    name: str
    points: tuple[Point2D, ...]
    width_m: float
    height_m: float
    color: Rgba
    style: str
    note: str = ""
    movable: bool = True
    rotation_y: float = 0.0
    protected: bool = True
    variant: str = ""
    secondary_color: Rgba | None = None

    def __post_init__(self) -> None:
        if self.secondary_color is None:
            object.__setattr__(self, "secondary_color", self.color)
        if not self.id or not self.kind or not self.name:
            raise DomainValidationError(
                "Context linear object id, kind and name are required"
            )
        if len(self.points) < 2:
            raise DomainValidationError(
                "A context linear object requires at least two points"
            )
        if self.width_m <= 0 or self.height_m <= 0:
            raise DomainValidationError(
                "Context linear object width and height must be positive"
            )
        if self.style not in {
            "road",
            "ditch",
            "ditch_dash",
            "fence",
            "boundary_fence",
        }:
            raise DomainValidationError(
                f"Unsupported context linear style: {self.style}"
            )
        if any(
            start.distance_to(end) <= 1e-6
            for start, end in zip(self.points, self.points[1:])
        ):
            raise DomainValidationError(
                "Adjacent context linear object points must be different"
            )

    @property
    def center(self) -> Point2D:
        """Stable editing centre of the unrotated reference polyline."""
        return Point2D(
            (min(point.x for point in self.points) + max(point.x for point in self.points))
            / 2,
            (min(point.z for point in self.points) + max(point.z for point in self.points))
            / 2,
        )

    @property
    def length_m(self) -> float:
        return sum(
            start.distance_to(end)
            for start, end in zip(self.points, self.points[1:])
        )

    @property
    def world_points(self) -> tuple[Point2D, ...]:
        """Polyline after applying its editable rotation around ``center``."""
        angle = radians(self.rotation_y)
        cosine = cos(angle)
        sine = sin(angle)
        center = self.center
        return tuple(
            Point2D(
                center.x
                + (point.x - center.x) * cosine
                + (point.z - center.z) * sine,
                center.z
                - (point.x - center.x) * sine
                + (point.z - center.z) * cosine,
            )
            for point in self.points
        )


@dataclass(frozen=True)
class Surroundings:
    """Site-source scene editable without the plot-boundary restriction."""

    areas: tuple[ContextArea, ...] = field(default_factory=tuple)
    linear_objects: tuple[ContextLinearObject, ...] = field(default_factory=tuple)
    buildings: tuple[Building, ...] = field(default_factory=tuple)
    features: tuple[SiteFeature, ...] = field(default_factory=tuple)
    primitives: tuple[PrimitiveObject, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        all_items = (
            self.areas
            + self.linear_objects
            + self.buildings
            + self.features
            + self.primitives
        )
        _ensure_unique_ids(all_items, "surroundings")


@dataclass(frozen=True)
class LayoutVariant:
    id: str
    name: str
    description: str
    buildings: tuple[Building, ...]
    features: tuple[SiteFeature, ...]
    primitives: tuple[PrimitiveObject, ...] = field(default_factory=tuple)
    hidden_fixed_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _ensure_unique_ids(self.buildings, f"layout '{self.id}' buildings")
        _ensure_unique_ids(self.features, f"layout '{self.id}' features")
        _ensure_unique_ids(self.primitives, f"layout '{self.id}' primitives")
        all_ids = [item.id for item in self.buildings + self.features + self.primitives]
        if len(all_ids) != len(set(all_ids)):
            raise DomainValidationError(
                f"Ids must be unique across every object in layout '{self.id}'"
            )
        if len(self.hidden_fixed_ids) != len(set(self.hidden_fixed_ids)):
            raise DomainValidationError(
                f"Hidden fixed ids must be unique in layout '{self.id}'"
            )


@dataclass(frozen=True)
class Project:
    schema_version: int
    id: str
    name: str
    plot: Plot
    fixed_buildings: tuple[Building, ...]
    fixed_features: tuple[SiteFeature, ...]
    surroundings: Surroundings
    layouts: tuple[LayoutVariant, ...]
    active_layout_id: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.schema_version < 1:
            raise DomainValidationError("schema_version must be at least 1")
        if not self.id or not self.name:
            raise DomainValidationError("Project id and name are required")
        if not self.layouts:
            raise DomainValidationError("At least one layout variant is required")

        _ensure_unique_ids(self.fixed_buildings, "fixed buildings")
        _ensure_unique_ids(self.fixed_features, "fixed features")
        _ensure_unique_ids(self.layouts, "layout variants")
        fixed_ids = [
            item.id for item in self.fixed_buildings + self.fixed_features
        ]
        if len(fixed_ids) != len(set(fixed_ids)):
            raise DomainValidationError(
                "Ids must be unique across all fixed buildings and features"
            )
        known_fixed_ids = set(fixed_ids)
        if self.plot.fence is not None:
            known_fixed_ids.add(FENCE_OBJECT_ID)
        for layout in self.layouts:
            unknown_hidden = set(layout.hidden_fixed_ids) - known_fixed_ids
            if unknown_hidden:
                raise DomainValidationError(
                    f"Layout '{layout.id}' hides unknown fixed ids: "
                    f"{sorted(unknown_hidden)}"
                )
        self.layout(self.active_layout_id)

    def layout(self, layout_id: str) -> LayoutVariant:
        for layout in self.layouts:
            if layout.id == layout_id:
                return layout
        raise DomainValidationError(f"Unknown layout variant: {layout_id}")

    def all_buildings(self, layout_id: str) -> tuple[Building, ...]:
        return self.fixed_buildings + self.layout(layout_id).buildings


def _ensure_unique_ids(items: Iterable[object], collection_name: str) -> None:
    ids = [getattr(item, "id", None) for item in items]
    if any(not item_id for item_id in ids):
        raise DomainValidationError(f"Every item in {collection_name} must have an id")
    if len(ids) != len(set(ids)):
        raise DomainValidationError(f"Ids in {collection_name} must be unique")
