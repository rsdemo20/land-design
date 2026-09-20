"""JSON adapter for the project repository port."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .domain import (
    Building,
    ContextArea,
    ContextLinearObject,
    FenceStyle,
    HatchStyle,
    LayoutVariant,
    Plot,
    PlotDimensions,
    PlotMarker,
    Point2D,
    PrimitiveObject,
    Project,
    Rgba,
    RoofSpec,
    SiteFeature,
    Size2D,
    Size3D,
    Surroundings,
    WellStructure,
)
from .geometry import project_geometry_issues


class JsonProjectRepository:
    """Load and save a complete project as human-readable UTF-8 JSON."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> Project:
        with self.path.open("r", encoding="utf-8") as source:
            raw = json.load(source)
        project = _project_from_dict(raw)
        issues = project_geometry_issues(project)
        if issues:
            issue_lines = "\n".join(f"- {issue}" for issue in issues)
            raise ValueError(f"Invalid project geometry:\n{issue_lines}")
        return project

    def save(self, project: Project) -> None:
        issues = project_geometry_issues(project)
        if issues:
            issue_lines = "\n".join(f"- {issue}" for issue in issues)
            raise ValueError(f"Cannot save invalid project geometry:\n{issue_lines}")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary_path.open("w", encoding="utf-8", newline="\n") as target:
            json.dump(
                _project_to_dict(project),
                target,
                ensure_ascii=False,
                indent=2,
            )
            target.write("\n")
        temporary_path.replace(self.path)


def _project_from_dict(raw: dict[str, Any]) -> Project:
    project_data = raw["project"]
    plot_data = raw["plot"]
    dimension_data = plot_data["dimensions"]
    hatch_data = plot_data["hatch"]
    fence_data = plot_data.get("fence")
    if "fence" not in plot_data:
        fence_data = {
            "front_height_m": 2.0,
            "other_height_m": 1.8,
            "thickness_m": 0.15,
            "color": [55, 60, 65, 255],
        }

    plot = Plot(
        id=plot_data["id"],
        name=plot_data["name"],
        dimensions=PlotDimensions(
            front_width_m=float(dimension_data["front_width_m"]),
            rear_width_m=float(dimension_data["rear_width_m"]),
            left_side_m=float(dimension_data["left_side_m"]),
            right_side_m=float(dimension_data["right_side_m"]),
            declared_area_sqm=float(dimension_data["declared_area_sqm"]),
        ),
        markers=tuple(_marker_from_dict(item) for item in plot_data["markers"]),
        boundary_order=tuple(str(item) for item in plot_data["boundary_order"]),
        corner_ids=tuple(str(item) for item in plot_data["corner_ids"]),
        north_axis=plot_data["north_axis"],
        north_direction=_point_from_dict(
            plot_data.get("north_direction", {"x": 0.0, "z": 1.0})
        ),
        north_reference=plot_data.get("north_reference", "legacy +z axis"),
        fill_color=_color_from_list(plot_data["fill_color"]),
        boundary_color=_color_from_list(plot_data["boundary_color"]),
        hatch=HatchStyle(
            spacing_m=float(hatch_data["spacing_m"]),
            line_width_m=float(hatch_data["line_width_m"]),
            color=_color_from_list(hatch_data["color"]),
        ),
        fence=(
            FenceStyle(
                front_height_m=float(fence_data["front_height_m"]),
                other_height_m=float(fence_data["other_height_m"]),
                thickness_m=float(fence_data["thickness_m"]),
                color=_color_from_list(fence_data["color"]),
                protected=bool(fence_data.get("protected", True)),
            )
            if fence_data is not None
            else None
        ),
        notes=tuple(plot_data.get("notes", ())),
    )

    return Project(
        schema_version=max(6, int(raw["schema_version"])),
        id=project_data["id"],
        name=project_data["name"],
        plot=plot,
        fixed_buildings=tuple(
            _building_from_dict(item) for item in raw.get("fixed_buildings", ())
        ),
        fixed_features=tuple(
            _feature_from_dict(item) for item in raw.get("fixed_features", ())
        ),
        surroundings=_surroundings_from_dict(raw.get("surroundings", {})),
        layouts=tuple(_layout_from_dict(item) for item in raw["layouts"]),
        active_layout_id=raw["active_layout_id"],
        notes=tuple(project_data.get("notes", ())),
    )


def _marker_from_dict(raw: dict[str, Any]) -> PlotMarker:
    return PlotMarker(
        id=str(raw["id"]),
        position=_point_from_dict(raw["position"]),
        role=raw["role"],
        accuracy=raw.get("accuracy", "model"),
        note=raw.get("note", ""),
    )


def _surroundings_from_dict(raw: dict[str, Any]) -> Surroundings:
    return Surroundings(
        areas=tuple(_context_area_from_dict(item) for item in raw.get("areas", ())),
        linear_objects=tuple(
            _context_linear_from_dict(item) for item in raw.get("linear_objects", ())
        ),
        buildings=tuple(
            _building_from_dict(item) for item in raw.get("buildings", ())
        ),
        features=tuple(
            _feature_from_dict(item) for item in raw.get("features", ())
        ),
        primitives=tuple(
            _primitive_from_dict(item) for item in raw.get("primitives", ())
        ),
    )


def _context_area_from_dict(raw: dict[str, Any]) -> ContextArea:
    return ContextArea(
        id=raw["id"],
        kind=raw["kind"],
        name=raw["name"],
        boundary=tuple(_point_from_dict(point) for point in raw["boundary"]),
        color=_color_from_list(raw["color"]),
        height_m=float(raw.get("height_m", 0.02)),
        note=raw.get("note", ""),
    )


def _context_linear_from_dict(raw: dict[str, Any]) -> ContextLinearObject:
    primary_color = _color_from_list(raw["color"])
    return ContextLinearObject(
        id=raw["id"],
        kind=raw["kind"],
        name=raw["name"],
        points=tuple(_point_from_dict(point) for point in raw["points"]),
        width_m=float(raw["width_m"]),
        height_m=float(raw["height_m"]),
        color=primary_color,
        style=raw["style"],
        secondary_color=(
            _color_from_list(raw["secondary_color"])
            if raw.get("secondary_color")
            else primary_color
        ),
        note=raw.get("note", ""),
        movable=bool(raw.get("movable", True)),
        rotation_y=float(raw.get("rotation_y", 0.0)),
        protected=bool(raw.get("protected", True)),
        variant=raw.get("variant", ""),
    )


def _building_from_dict(raw: dict[str, Any]) -> Building:
    primary_color = _color_from_list(raw["color"])
    roof = _roof_from_dict(raw["roof"]) if raw.get("roof") else None
    return Building(
        id=raw["id"],
        kind=raw["kind"],
        name=raw["name"],
        center=_point_from_dict(raw["center"]),
        footprint=_size_from_dict(raw["footprint"]),
        height_m=float(raw["height_m"]),
        floors=int(raw["floors"]),
        color=primary_color,
        secondary_color=(
            _color_from_list(raw["secondary_color"])
            if raw.get("secondary_color")
            else roof.color
            if roof is not None
            else primary_color
        ),
        movable=bool(raw.get("movable", True)),
        wall_height_m=(
            float(raw["wall_height_m"])
            if raw.get("wall_height_m") is not None
            else None
        ),
        roof=roof,
        rotation_y=float(raw.get("rotation_y", 0.0)),
        note=raw.get("note", ""),
        protected=bool(raw.get("protected", not bool(raw.get("movable", True)))),
        variant=raw.get("variant", ""),
    )


def _feature_from_dict(raw: dict[str, Any]) -> SiteFeature:
    well_data = raw.get("well_structure")
    primary_color = _color_from_list(raw["color"])
    secondary_color = (
        _color_from_list(raw["secondary_color"])
        if raw.get("secondary_color")
        else _color_from_list(well_data["roof_color"])
        if well_data
        else primary_color
    )
    return SiteFeature(
        id=raw["id"],
        kind=raw["kind"],
        name=raw["name"],
        center=_point_from_dict(raw["center"]),
        size=_size_from_dict(raw["size"]),
        shape=raw["shape"],
        color=primary_color,
        secondary_color=secondary_color,
        height_m=float(raw.get("height_m", 0.2)),
        movable=bool(raw.get("movable", True)),
        rotation_y=float(raw.get("rotation_y", 0.0)),
        note=raw.get("note", ""),
        well_structure=(
            WellStructure(
                ring_height_m=float(well_data["ring_height_m"]),
                roof_height_m=float(well_data["roof_height_m"]),
                roof_overhang_m=float(well_data.get("roof_overhang_m", 0.0)),
                ridge_axis=well_data.get("ridge_axis", "x"),
                roof_color=_color_from_list(well_data["roof_color"]),
            )
            if well_data
            else None
        ),
        protected=bool(raw.get("protected", not bool(raw.get("movable", True)))),
        variant=raw.get("variant", ""),
    )


def _layout_from_dict(raw: dict[str, Any]) -> LayoutVariant:
    return LayoutVariant(
        id=raw["id"],
        name=raw["name"],
        description=raw.get("description", ""),
        buildings=tuple(_building_from_dict(item) for item in raw["buildings"]),
        features=tuple(_feature_from_dict(item) for item in raw["features"]),
        primitives=tuple(
            _primitive_from_dict(item) for item in raw.get("primitives", ())
        ),
        hidden_fixed_ids=tuple(str(item) for item in raw.get("hidden_fixed_ids", ())),
    )


def _roof_from_dict(raw: dict[str, Any]) -> RoofSpec:
    return RoofSpec(
        shape=raw["shape"],
        height_m=float(raw["height_m"]),
        overhang_m=float(raw.get("overhang_m", 0.0)),
        ridge_axis=raw.get("ridge_axis", "x"),
        color=_color_from_list(raw["color"]),
    )


def _primitive_from_dict(raw: dict[str, Any]) -> PrimitiveObject:
    primary_color = _color_from_list(raw["color"])
    return PrimitiveObject(
        id=raw["id"],
        name=raw["name"],
        shape=raw["shape"],
        center=_point_from_dict(raw["center"]),
        size=_size3d_from_dict(raw["size"]),
        color=primary_color,
        secondary_color=(
            _color_from_list(raw["secondary_color"])
            if raw.get("secondary_color")
            else primary_color
        ),
        movable=bool(raw.get("movable", True)),
        rotation_y=float(raw.get("rotation_y", 0.0)),
        note=raw.get("note", ""),
        protected=bool(raw.get("protected", not bool(raw.get("movable", True)))),
        variant=raw.get("variant", ""),
        arc_angle_deg=float(raw.get("arc_angle_deg", 45.0)),
    )


def _point_from_dict(raw: dict[str, Any]) -> Point2D:
    return Point2D(x=float(raw["x"]), z=float(raw["z"]))


def _size_from_dict(raw: dict[str, Any]) -> Size2D:
    return Size2D(width=float(raw["width"]), depth=float(raw["depth"]))


def _size3d_from_dict(raw: dict[str, Any]) -> Size3D:
    return Size3D(x=float(raw["x"]), y=float(raw["y"]), z=float(raw["z"]))


def _color_from_list(raw: list[int]) -> Rgba:
    channels = list(raw)
    if len(channels) == 3:
        channels.append(255)
    if len(channels) != 4:
        raise ValueError("A color must contain three or four RGBA channels")
    return Rgba(*map(int, channels))


def _project_to_dict(project: Project) -> dict[str, Any]:
    return {
        "schema_version": project.schema_version,
        "project": {
            "id": project.id,
            "name": project.name,
            "notes": list(project.notes),
        },
        "plot": {
            "id": project.plot.id,
            "name": project.plot.name,
            "north_axis": project.plot.north_axis,
            "north_direction": _point_to_dict(project.plot.north_direction),
            "north_reference": project.plot.north_reference,
            "dimensions": {
                "front_width_m": project.plot.dimensions.front_width_m,
                "rear_width_m": project.plot.dimensions.rear_width_m,
                "left_side_m": project.plot.dimensions.left_side_m,
                "right_side_m": project.plot.dimensions.right_side_m,
                "declared_area_sqm": project.plot.dimensions.declared_area_sqm,
            },
            "markers": [_marker_to_dict(item) for item in project.plot.markers],
            "boundary_order": list(project.plot.boundary_order),
            "corner_ids": list(project.plot.corner_ids),
            "fill_color": _color_to_list(project.plot.fill_color),
            "boundary_color": _color_to_list(project.plot.boundary_color),
            "hatch": {
                "spacing_m": project.plot.hatch.spacing_m,
                "line_width_m": project.plot.hatch.line_width_m,
                "color": _color_to_list(project.plot.hatch.color),
            },
            "fence": (
                {
                    "front_height_m": project.plot.fence.front_height_m,
                    "other_height_m": project.plot.fence.other_height_m,
                    "thickness_m": project.plot.fence.thickness_m,
                    "color": _color_to_list(project.plot.fence.color),
                    "protected": project.plot.fence.protected,
                }
                if project.plot.fence is not None
                else None
            ),
            "notes": list(project.plot.notes),
        },
        "fixed_buildings": [
            _building_to_dict(item) for item in project.fixed_buildings
        ],
        "fixed_features": [_feature_to_dict(item) for item in project.fixed_features],
        "surroundings": {
            "areas": [
                _context_area_to_dict(item) for item in project.surroundings.areas
            ],
            "linear_objects": [
                _context_linear_to_dict(item)
                for item in project.surroundings.linear_objects
            ],
            "buildings": [
                _building_to_dict(item) for item in project.surroundings.buildings
            ],
            "features": [
                _feature_to_dict(item) for item in project.surroundings.features
            ],
            "primitives": [
                _primitive_to_dict(item) for item in project.surroundings.primitives
            ],
        },
        "layouts": [_layout_to_dict(item) for item in project.layouts],
        "active_layout_id": project.active_layout_id,
    }


def _marker_to_dict(marker: PlotMarker) -> dict[str, Any]:
    return {
        "id": marker.id,
        "position": _point_to_dict(marker.position),
        "role": marker.role,
        "accuracy": marker.accuracy,
        "note": marker.note,
    }


def _context_area_to_dict(item: ContextArea) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "name": item.name,
        "boundary": [_point_to_dict(point) for point in item.boundary],
        "height_m": item.height_m,
        "color": _color_to_list(item.color),
        "note": item.note,
    }


def _context_linear_to_dict(item: ContextLinearObject) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "name": item.name,
        "points": [_point_to_dict(point) for point in item.points],
        "width_m": item.width_m,
        "height_m": item.height_m,
        "style": item.style,
        "color": _color_to_list(item.color),
        "secondary_color": _color_to_list(item.secondary_color or item.color),
        "movable": item.movable,
        "rotation_y": item.rotation_y,
        "protected": item.protected,
        "variant": item.variant,
        "note": item.note,
    }


def _building_to_dict(building: Building) -> dict[str, Any]:
    return {
        "id": building.id,
        "kind": building.kind,
        "name": building.name,
        "center": _point_to_dict(building.center),
        "footprint": _size_to_dict(building.footprint),
        "height_m": building.height_m,
        "floors": building.floors,
        "movable": building.movable,
        "wall_height_m": building.wall_height_m,
        "roof": _roof_to_dict(building.roof) if building.roof else None,
        "rotation_y": building.rotation_y,
        "protected": building.protected,
        "variant": building.variant,
        "color": _color_to_list(building.color),
        "secondary_color": _color_to_list(
            building.secondary_color or building.color
        ),
        "note": building.note,
    }


def _feature_to_dict(feature: SiteFeature) -> dict[str, Any]:
    result = {
        "id": feature.id,
        "kind": feature.kind,
        "name": feature.name,
        "center": _point_to_dict(feature.center),
        "size": _size_to_dict(feature.size),
        "shape": feature.shape,
        "height_m": feature.height_m,
        "movable": feature.movable,
        "rotation_y": feature.rotation_y,
        "protected": feature.protected,
        "variant": feature.variant,
        "color": _color_to_list(feature.color),
        "secondary_color": _color_to_list(
            feature.secondary_color or feature.color
        ),
        "note": feature.note,
    }
    if feature.well_structure is not None:
        result["well_structure"] = {
            "ring_height_m": feature.well_structure.ring_height_m,
            "roof_height_m": feature.well_structure.roof_height_m,
            "roof_overhang_m": feature.well_structure.roof_overhang_m,
            "ridge_axis": feature.well_structure.ridge_axis,
            "roof_color": _color_to_list(feature.well_structure.roof_color),
        }
    return result


def _layout_to_dict(layout: LayoutVariant) -> dict[str, Any]:
    return {
        "id": layout.id,
        "name": layout.name,
        "description": layout.description,
        "buildings": [_building_to_dict(item) for item in layout.buildings],
        "features": [_feature_to_dict(item) for item in layout.features],
        "primitives": [_primitive_to_dict(item) for item in layout.primitives],
        "hidden_fixed_ids": list(layout.hidden_fixed_ids),
    }


def _roof_to_dict(roof: RoofSpec) -> dict[str, Any]:
    return {
        "shape": roof.shape,
        "height_m": roof.height_m,
        "overhang_m": roof.overhang_m,
        "ridge_axis": roof.ridge_axis,
        "color": _color_to_list(roof.color),
    }


def _primitive_to_dict(item: PrimitiveObject) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "shape": item.shape,
        "center": _point_to_dict(item.center),
        "size": {"x": item.size.x, "y": item.size.y, "z": item.size.z},
        "movable": item.movable,
        "rotation_y": item.rotation_y,
        "protected": item.protected,
        "variant": item.variant,
        "arc_angle_deg": item.arc_angle_deg,
        "color": _color_to_list(item.color),
        "secondary_color": _color_to_list(item.secondary_color or item.color),
        "note": item.note,
    }


def _point_to_dict(point: Point2D) -> dict[str, float]:
    return {"x": point.x, "z": point.z}


def _size_to_dict(size: Size2D) -> dict[str, float]:
    return {"width": size.width, "depth": size.depth}


def _color_to_list(value: Rgba) -> list[int]:
    return [value.red, value.green, value.blue, value.alpha]
