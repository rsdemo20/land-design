"""Upgrade data.json with secondary colours and standard utility-building roofs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from core import Building, JsonProjectRepository, Rgba, RoofSpec


PROJECT_FILE = Path(__file__).parents[1] / "data.json"
DEFAULT_ROOF_COLORS = {
    "bathhouse": Rgba(73, 106, 67),
    "shed": Rgba(101, 71, 53),
    "garage": Rgba(70, 84, 93),
}


def migrate_building(building: Building) -> Building:
    secondary = building.secondary_color or building.color
    if building.kind in DEFAULT_ROOF_COLORS and secondary == building.color:
        secondary = DEFAULT_ROOF_COLORS[building.kind]

    roof = building.roof
    wall_height = building.wall_height_m
    total_height = building.height_m
    if building.kind in {"bathhouse", "shed"}:
        roof_height = building.footprint.depth / 2
        wall_height = wall_height or building.height_m
        total_height = wall_height + roof_height
        roof = RoofSpec(
            shape="gable",
            height_m=roof_height,
            overhang_m=min(
                roof.overhang_m if roof is not None else 0.20,
                min(building.footprint.width, building.footprint.depth) * 0.10,
            ),
            ridge_axis="x",
            color=secondary,
        )
    elif building.kind == "garage":
        wall_height = wall_height or building.height_m
        roof_height = (
            roof.height_m
            if roof is not None and roof.shape == "shed"
            else min(wall_height * 0.20, building.footprint.depth * 0.12)
        )
        total_height = wall_height + roof_height
        roof = RoofSpec(
            shape="shed",
            height_m=roof_height,
            overhang_m=min(
                roof.overhang_m if roof is not None else 0.20,
                min(building.footprint.width, building.footprint.depth) * 0.10,
            ),
            ridge_axis="x",
            color=secondary,
        )
    elif roof is not None:
        roof = replace(roof, color=secondary)

    return replace(
        building,
        height_m=total_height,
        wall_height_m=wall_height,
        roof=roof,
        secondary_color=secondary,
    )


def migrate_feature(feature):
    secondary = feature.secondary_color or feature.color
    structure = feature.well_structure
    if structure is not None:
        structure = replace(structure, roof_color=secondary)
    return replace(
        feature,
        secondary_color=secondary,
        well_structure=structure,
    )


def main() -> None:
    repository = JsonProjectRepository(PROJECT_FILE)
    project = repository.load()
    surroundings = replace(
        project.surroundings,
        linear_objects=tuple(
            replace(item, secondary_color=item.secondary_color or item.color)
            for item in project.surroundings.linear_objects
        ),
        buildings=tuple(
            migrate_building(item) for item in project.surroundings.buildings
        ),
        features=tuple(
            migrate_feature(item) for item in project.surroundings.features
        ),
        primitives=tuple(
            replace(item, secondary_color=item.secondary_color or item.color)
            for item in project.surroundings.primitives
        ),
    )
    layouts = tuple(
        replace(
            layout,
            buildings=tuple(migrate_building(item) for item in layout.buildings),
            features=tuple(migrate_feature(item) for item in layout.features),
            primitives=tuple(
                replace(item, secondary_color=item.secondary_color or item.color)
                for item in layout.primitives
            ),
        )
        for layout in project.layouts
    )
    migrated = replace(
        project,
        schema_version=6,
        fixed_buildings=tuple(
            migrate_building(item) for item in project.fixed_buildings
        ),
        fixed_features=tuple(
            migrate_feature(item) for item in project.fixed_features
        ),
        surroundings=surroundings,
        layouts=layouts,
    )
    repository.save(migrated)


if __name__ == "__main__":
    main()
