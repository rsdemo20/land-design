"""Geometry operations that do not depend on the rendering engine."""

from __future__ import annotations

from math import ceil, cos, radians, sin

from .domain import Building, Point2D, Plot, PrimitiveObject, Project, SiteFeature, Size2D


def point_in_polygon(point: Point2D, polygon: tuple[Point2D, ...]) -> bool:
    """Return True when a point is inside or on the edge of a polygon."""
    inside = False
    previous = polygon[-1]

    for current in polygon:
        if _point_on_segment(point, previous, current):
            return True

        crosses = (current.z > point.z) != (previous.z > point.z)
        if crosses:
            x_at_z = (
                (previous.x - current.x)
                * (point.z - current.z)
                / (previous.z - current.z)
                + current.x
            )
            if point.x < x_at_z:
                inside = not inside
        previous = current

    return inside


def footprint_corners(
    center: Point2D, size: Size2D, rotation_y: float = 0.0
) -> tuple[Point2D, ...]:
    """Return four corners for a possibly rotated rectangular footprint."""
    angle = radians(rotation_y)
    cosine = cos(angle)
    sine = sin(angle)
    half_width = size.width / 2
    half_depth = size.depth / 2
    result = []

    for local_x, local_z in (
        (-half_width, -half_depth),
        (half_width, -half_depth),
        (half_width, half_depth),
        (-half_width, half_depth),
    ):
        result.append(
            Point2D(
                center.x + local_x * cosine + local_z * sine,
                center.z - local_x * sine + local_z * cosine,
            )
        )
    return tuple(result)


def building_inside_plot(building: Building, plot: Plot) -> bool:
    return footprint_inside_plot(
        building.center, building.footprint, building.rotation_y, plot
    )


def footprint_inside_plot(
    center: Point2D, size: Size2D, rotation_y: float, plot: Plot
) -> bool:
    return all(
        point_in_polygon(corner, plot.boundary)
        for corner in footprint_corners(center, size, rotation_y)
    )


def feature_inside_plot(feature: SiteFeature, plot: Plot) -> bool:
    return footprint_inside_plot(feature.center, feature.size, feature.rotation_y, plot)


def primitive_inside_plot(item: PrimitiveObject, plot: Plot) -> bool:
    if item.shape == "arc":
        return all(
            point_in_polygon(point, plot.boundary)
            for point in arc_footprint_points(item)
        )
    return footprint_inside_plot(item.center, item.size.footprint, item.rotation_y, plot)


def arc_footprint_points(item: PrimitiveObject) -> tuple[Point2D, ...]:
    """Sample both edges of an arc for an accurate plot-boundary check."""
    angle = radians(item.arc_angle_deg)
    half_angle = angle / 2
    radius = item.size.x / angle
    radii = (radius - item.size.y / 2, radius + item.size.y / 2)
    chord_offset = radius * cos(half_angle)
    rotation = radians(item.rotation_y)
    rotation_cosine = cos(rotation)
    rotation_sine = sin(rotation)
    segments = max(8, ceil(item.arc_angle_deg / 5))
    result: list[Point2D] = []
    for index in range(segments + 1):
        sample = -half_angle + angle * index / segments
        for edge_radius in radii:
            local_x = edge_radius * sin(sample)
            local_z = edge_radius * cos(sample) - chord_offset
            result.append(
                Point2D(
                    item.center.x
                    + local_x * rotation_cosine
                    + local_z * rotation_sine,
                    item.center.z
                    - local_x * rotation_sine
                    + local_z * rotation_cosine,
                )
            )
    return tuple(result)


def project_geometry_issues(project: Project) -> tuple[str, ...]:
    """Collect actionable placement errors without involving Ursina."""
    issues: list[str] = []
    area_difference = abs(
        project.plot.area_sqm - project.plot.dimensions.declared_area_sqm
    )
    if area_difference > max(5.0, project.plot.dimensions.declared_area_sqm * 0.02):
        issues.append(
            "Calculated plot area differs from declared area by "
            f"{area_difference:.1f} m²"
        )

    for building in project.fixed_buildings:
        if not building_inside_plot(building, project.plot):
            issues.append(f"Fixed building '{building.id}' crosses the plot boundary")

    for feature in project.fixed_features:
        if not feature_inside_plot(feature, project.plot):
            issues.append(f"Fixed feature '{feature.id}' crosses the plot boundary")

    for layout in project.layouts:
        for building in layout.buildings:
            if not building_inside_plot(building, project.plot):
                issues.append(
                    f"Building '{building.id}' in layout '{layout.id}' "
                    "crosses the plot boundary"
                )
        for feature in layout.features:
            if not feature_inside_plot(feature, project.plot):
                issues.append(
                    f"Feature '{feature.id}' in layout '{layout.id}' "
                    "crosses the plot boundary"
                )
        for item in layout.primitives:
            if not primitive_inside_plot(item, project.plot):
                issues.append(
                    f"Primitive '{item.id}' in layout '{layout.id}' "
                    "crosses the plot boundary"
                )
    return tuple(issues)


def _point_on_segment(
    point: Point2D, start: Point2D, end: Point2D, tolerance: float = 1e-8
) -> bool:
    cross = (point.z - start.z) * (end.x - start.x) - (
        point.x - start.x
    ) * (end.z - start.z)
    if abs(cross) > tolerance:
        return False
    return (
        min(start.x, end.x) - tolerance
        <= point.x
        <= max(start.x, end.x) + tolerance
        and min(start.z, end.z) - tolerance
        <= point.z
        <= max(start.z, end.z) + tolerance
    )
