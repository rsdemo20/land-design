"""Application service for editing a project without depending on Ursina."""

from __future__ import annotations

from dataclasses import replace

from .domain import (
    Building,
    ContextLinearObject,
    DomainValidationError,
    FENCE_OBJECT_ID,
    Point2D,
    PrimitiveObject,
    Rgba,
    SiteFeature,
    Size2D,
    Size3D,
)
from .geometry import building_inside_plot, feature_inside_plot, primitive_inside_plot
from .ports import ProjectRepository


class ProjectEditor:
    """Edit the site source and its saved design variants."""

    _layout_collections = {
        "building": ("buildings", building_inside_plot),
        "feature": ("features", feature_inside_plot),
        "primitive": ("primitives", primitive_inside_plot),
    }
    _fixed_collections = {
        "fixed_building": "fixed_buildings",
        "fixed_feature": "fixed_features",
    }
    _surrounding_collections = {
        "surrounding_linear": "linear_objects",
        "surrounding_building": "buildings",
        "surrounding_feature": "features",
        "surrounding_primitive": "primitives",
    }

    def __init__(self, repository: ProjectRepository) -> None:
        self.repository = repository
        self.project = repository.load()

    def set_active_layout(self, layout_id: str) -> None:
        """Persist the current design before selecting and persisting another one."""
        self.project.layout(layout_id)
        self.save()
        self.project = replace(self.project, active_layout_id=layout_id)
        self.save()

    def add_primitive(self, layout_id: str, item: PrimitiveObject) -> None:
        self._add_layout_item(layout_id, "primitive", item)

    def add_building(self, layout_id: str, item: Building) -> None:
        self._add_layout_item(layout_id, "building", item)

    def add_feature(self, layout_id: str, item: SiteFeature) -> None:
        self._add_layout_item(layout_id, "feature", item)

    def add_site_primitive(self, item: PrimitiveObject) -> None:
        self._add_surrounding_item("surrounding_primitive", item)

    def add_site_building(self, item: Building) -> None:
        self._add_surrounding_item("surrounding_building", item)

    def add_site_feature(self, item: SiteFeature) -> None:
        self._add_surrounding_item("surrounding_feature", item)

    def _add_surrounding_item(self, collection: str, item) -> None:
        """Add an unrestricted source object, including outside the plot."""
        attribute = self._surrounding_collections[collection]
        surroundings = self.project.surroundings
        existing_ids = {
            value.id
            for value in (
                surroundings.areas
                + surroundings.linear_objects
                + surroundings.buildings
                + surroundings.features
                + surroundings.primitives
            )
        }
        if item.id in existing_ids:
            raise DomainValidationError(
                f"Object id '{item.id}' already exists in the site source"
            )
        self.project = replace(
            self.project,
            surroundings=replace(
                surroundings,
                **{attribute: getattr(surroundings, attribute) + (item,)},
            ),
        )
        self.save()

    def _add_layout_item(self, layout_id: str, collection: str, item) -> None:
        layout = self.project.layout(layout_id)
        existing_ids = {
            value.id
            for value in layout.buildings + layout.features + layout.primitives
        }
        if item.id in existing_ids:
            raise DomainValidationError(
                f"Object id '{item.id}' already exists in layout '{layout_id}'"
            )
        attribute, validator = self._layout_collections[collection]
        if not validator(item, self.project.plot):
            raise DomainValidationError("New object must fit inside the plot")

        items = getattr(layout, attribute)
        self._replace_layout(replace(layout, **{attribute: items + (item,)}))
        self.save()

    def update_item_properties(
        self,
        layout_id: str,
        collection: str,
        item_id: str,
        size: Size3D,
        color: Rgba,
        name: str | None = None,
        variant: str | None = None,
        secondary_color: Rgba | None = None,
    ) -> None:
        """Update the editable bounding primitive of any non-fence object."""
        if collection == "fence":
            raise DomainValidationError(
                "Fence dimensions are edited as site-source parameters"
            )

        selected = self.get_item(layout_id, collection, item_id)
        is_surrounding = collection in self._surrounding_collections
        changes = {"color": color}
        if name is not None and name.strip():
            changes["name"] = name.strip()
        if variant is not None and hasattr(selected, "variant"):
            changes["variant"] = variant

        if isinstance(selected, Building):
            effective_secondary = (
                secondary_color
                if secondary_color is not None
                else _shade_color(color)
                if selected.roof is not None
                else selected.secondary_color or color
            )
            changes.update(
                footprint=Size2D(size.x, size.y),
                height_m=size.z,
                secondary_color=effective_secondary,
            )
            if selected.roof is not None:
                if selected.kind in {"bathhouse", "shed"}:
                    roof_height = size.y / 2
                    if roof_height >= size.z:
                        raise DomainValidationError(
                            "For a 45-degree gable roof, Z must exceed Y / 2"
                        )
                else:
                    roof_ratio = selected.roof.height_m / selected.height_m
                    roof_height = size.z * roof_ratio
                old_minimum = min(
                    selected.footprint.width, selected.footprint.depth
                )
                overhang_ratio = selected.roof.overhang_m / old_minimum
                roof = replace(
                    selected.roof,
                    height_m=roof_height,
                    overhang_m=min(size.x, size.y) * overhang_ratio,
                    color=effective_secondary,
                )
                changes.update(
                    wall_height_m=size.z - roof_height,
                    roof=roof,
                )
            transformed = replace(selected, **changes)
            validator = None if is_surrounding else building_inside_plot
        elif isinstance(selected, SiteFeature):
            effective_secondary = (
                secondary_color
                if secondary_color is not None
                else _shade_color(color)
                if selected.well_structure is not None
                else selected.secondary_color or color
            )
            changes.update(
                size=Size2D(size.x, size.y),
                height_m=size.z,
                secondary_color=effective_secondary,
            )
            if selected.well_structure is not None:
                ring_ratio = (
                    selected.well_structure.ring_height_m / selected.height_m
                )
                old_minimum = min(selected.size.width, selected.size.depth)
                overhang_ratio = (
                    selected.well_structure.roof_overhang_m / old_minimum
                )
                changes["well_structure"] = replace(
                    selected.well_structure,
                    ring_height_m=size.z * ring_ratio,
                    roof_height_m=size.z * (1 - ring_ratio),
                    roof_overhang_m=min(size.x, size.y) * overhang_ratio,
                    roof_color=effective_secondary,
                )
            transformed = replace(selected, **changes)
            validator = None if is_surrounding else feature_inside_plot
        elif isinstance(selected, PrimitiveObject):
            changes.update(
                size=size,
                secondary_color=(
                    secondary_color
                    if secondary_color is not None
                    else selected.secondary_color or color
                ),
            )
            if selected.shape == "cube" and not (
                abs(size.x - size.y) <= 1e-6
                and abs(size.x - size.z) <= 1e-6
            ):
                changes["shape"] = "rectangular_prism"
            transformed = replace(selected, **changes)
            validator = None if is_surrounding else primitive_inside_plot
        elif isinstance(selected, ContextLinearObject):
            center = selected.center
            scale = size.x / selected.length_m
            changes.update(
                points=tuple(
                    Point2D(
                        center.x + (point.x - center.x) * scale,
                        center.z + (point.z - center.z) * scale,
                    )
                    for point in selected.points
                ),
                width_m=size.y,
                height_m=size.z,
                secondary_color=(
                    secondary_color
                    if secondary_color is not None
                    else selected.secondary_color or color
                ),
            )
            transformed = replace(selected, **changes)
            validator = None
        else:
            raise DomainValidationError(f"Unsupported object type: {collection}")

        if validator is not None and not validator(transformed, self.project.plot):
            raise DomainValidationError("Object must remain inside the plot")

        if is_surrounding:
            self._replace_surrounding_item(collection, item_id, transformed)
        elif collection in self._fixed_collections:
            attribute = self._fixed_collections[collection]
            items = getattr(self.project, attribute)
            self.project = replace(
                self.project,
                **{
                    attribute: tuple(
                        transformed if item.id == item_id else item
                        for item in items
                    )
                },
            )
        else:
            attribute, _ = self._layout_collections[collection]
            layout = self.project.layout(layout_id)
            items = getattr(layout, attribute)
            self._replace_layout(
                replace(
                    layout,
                    **{
                        attribute: tuple(
                            transformed if item.id == item_id else item
                            for item in items
                        )
                    },
                )
            )
        self.save()

    def set_arc_angle(
        self,
        layout_id: str,
        collection: str,
        item_id: str,
        arc_angle_deg: float,
    ) -> None:
        """Change arc curvature while preserving its centre, length and width."""
        selected = self.get_item(layout_id, collection, item_id)
        if not isinstance(selected, PrimitiveObject) or selected.shape != "arc":
            raise DomainValidationError("Curvature can only be changed for an arc")
        transformed = replace(selected, arc_angle_deg=float(arc_angle_deg))
        is_surrounding = collection in self._surrounding_collections
        if not is_surrounding and not primitive_inside_plot(
            transformed, self.project.plot
        ):
            raise DomainValidationError("Object must remain inside the plot")
        if is_surrounding:
            self._replace_surrounding_item(collection, item_id, transformed)
        else:
            attribute, _validator = self._layout_collections[collection]
            layout = self.project.layout(layout_id)
            items = getattr(layout, attribute)
            self._replace_layout(
                replace(
                    layout,
                    **{
                        attribute: tuple(
                            transformed if item.id == item_id else item
                            for item in items
                        )
                    },
                )
            )
        self.save()

    def get_item(self, layout_id: str, collection: str, item_id: str):
        if collection == "fence":
            if item_id != FENCE_OBJECT_ID or self.project.plot.fence is None:
                raise DomainValidationError("The site source has no fence")
            return self.project.plot.fence

        if collection in self._fixed_collections:
            items = getattr(self.project, self._fixed_collections[collection])
        elif collection in self._surrounding_collections:
            items = getattr(
                self.project.surroundings,
                self._surrounding_collections[collection],
            )
        else:
            try:
                attribute, _ = self._layout_collections[collection]
            except KeyError as exc:
                raise DomainValidationError(
                    f"Unknown editable collection: {collection}"
                ) from exc
            items = getattr(self.project.layout(layout_id), attribute)

        selected = next((item for item in items if item.id == item_id), None)
        if selected is None:
            raise DomainValidationError(f"Unknown {collection}: {item_id}")
        return selected

    def set_item_protected(
        self,
        layout_id: str,
        collection: str,
        item_id: str,
        protected: bool,
    ) -> None:
        selected = self.get_item(layout_id, collection, item_id)
        updated = replace(selected, protected=bool(protected))

        if collection == "fence":
            self.project = replace(
                self.project,
                plot=replace(self.project.plot, fence=updated),
            )
        elif collection in self._fixed_collections:
            attribute = self._fixed_collections[collection]
            items = getattr(self.project, attribute)
            self.project = replace(
                self.project,
                **{
                    attribute: tuple(
                        updated if item.id == item_id else item for item in items
                    )
                },
            )
        elif collection in self._surrounding_collections:
            self._replace_surrounding_item(collection, item_id, updated)
        else:
            attribute, _ = self._layout_collections[collection]
            layout = self.project.layout(layout_id)
            items = getattr(layout, attribute)
            self._replace_layout(
                replace(
                    layout,
                    **{
                        attribute: tuple(
                            updated if item.id == item_id else item for item in items
                        )
                    },
                )
            )
        self.save()

    def delete_or_hide_item(
        self, layout_id: str, collection: str, item_id: str
    ) -> str:
        """Delete a design object or hide a source object in one design."""
        selected = self.get_item(layout_id, collection, item_id)
        if selected.protected:
            raise DomainValidationError(
                "Object is protected. Clear the 'Protected' checkbox first"
            )

        if collection == "fence" or collection in self._fixed_collections:
            layout = self.project.layout(layout_id)
            if item_id not in layout.hidden_fixed_ids:
                self._replace_layout(
                    replace(
                        layout,
                        hidden_fixed_ids=layout.hidden_fixed_ids + (item_id,),
                    )
                )
                self.save()
            return "hidden"

        attribute, _ = self._layout_collections[collection]
        layout = self.project.layout(layout_id)
        items = getattr(layout, attribute)
        self._replace_layout(
            replace(
                layout,
                **{attribute: tuple(item for item in items if item.id != item_id)},
            )
        )
        self.save()
        return "deleted"

    def restore_fixed_item(self, layout_id: str, item_id: str) -> None:
        layout = self.project.layout(layout_id)
        if item_id not in layout.hidden_fixed_ids:
            return
        self._replace_layout(
            replace(
                layout,
                hidden_fixed_ids=tuple(
                    hidden_id
                    for hidden_id in layout.hidden_fixed_ids
                    if hidden_id != item_id
                ),
            )
        )
        self.save()

    def is_fixed_hidden(self, layout_id: str, item_id: str) -> bool:
        return item_id in self.project.layout(layout_id).hidden_fixed_ids

    def move_item(
        self,
        layout_id: str,
        collection: str,
        item_id: str,
        center: Point2D,
    ) -> None:
        self.transform_item(
            layout_id=layout_id,
            collection=collection,
            item_id=item_id,
            center=center,
        )

    def rotate_item(
        self,
        layout_id: str,
        collection: str,
        item_id: str,
        rotation_y: float,
    ) -> None:
        self.transform_item(
            layout_id=layout_id,
            collection=collection,
            item_id=item_id,
            rotation_y=rotation_y,
        )

    def transform_item(
        self,
        layout_id: str,
        collection: str,
        item_id: str,
        center: Point2D | None = None,
        rotation_y: float | None = None,
    ) -> None:
        if collection in self._surrounding_collections:
            selected = self.get_item(layout_id, collection, item_id)
            if selected.protected:
                raise DomainValidationError(
                    "Object is protected. Clear the 'Protected' checkbox first"
                )
            if not selected.movable:
                raise DomainValidationError(f"Object '{item_id}' is stationary")

            if isinstance(selected, ContextLinearObject):
                changes = {}
                if center is not None:
                    current_center = selected.center
                    delta_x = center.x - current_center.x
                    delta_z = center.z - current_center.z
                    changes["points"] = tuple(
                        Point2D(point.x + delta_x, point.z + delta_z)
                        for point in selected.points
                    )
                if rotation_y is not None:
                    changes["rotation_y"] = rotation_y % 360
                transformed = replace(selected, **changes)
            else:
                changes = {}
                if center is not None:
                    changes["center"] = center
                if rotation_y is not None:
                    changes["rotation_y"] = rotation_y % 360
                transformed = replace(selected, **changes)

            self._replace_surrounding_item(collection, item_id, transformed)
            self.save()
            return

        if collection in self._fixed_collections:
            selected = self.get_item(layout_id, collection, item_id)
            if selected.protected:
                raise DomainValidationError(
                    "Object is protected. Clear the 'Protected' checkbox first"
                )
            if not selected.movable:
                raise DomainValidationError(f"Object '{item_id}' is stationary")

            changes = {}
            if center is not None:
                changes["center"] = center
            if rotation_y is not None:
                changes["rotation_y"] = rotation_y % 360
            transformed = replace(selected, **changes)
            attribute = self._fixed_collections[collection]
            items = getattr(self.project, attribute)
            self.project = replace(
                self.project,
                **{
                    attribute: tuple(
                        transformed if item.id == item_id else item
                        for item in items
                    )
                },
            )
            self.save()
            return

        try:
            attribute, validator = self._layout_collections[collection]
        except KeyError as exc:
            raise DomainValidationError(
                f"Only design objects can be moved: {collection}"
            ) from exc

        layout = self.project.layout(layout_id)
        items = getattr(layout, attribute)
        selected = self.get_item(layout_id, collection, item_id)
        if selected.protected:
            raise DomainValidationError(
                "Object is protected. Clear the 'Protected' checkbox first"
            )
        if not selected.movable:
            raise DomainValidationError(f"Object '{item_id}' is stationary")

        changes = {}
        if center is not None:
            changes["center"] = center
        if rotation_y is not None:
            changes["rotation_y"] = rotation_y % 360
        transformed = replace(selected, **changes)
        if not validator(transformed, self.project.plot):
            raise DomainValidationError("Object must remain inside the plot")

        updated_items = tuple(
            transformed if item.id == item_id else item for item in items
        )
        self._replace_layout(replace(layout, **{attribute: updated_items}))
        self.save()

    def save(self) -> None:
        self.repository.save(self.project)

    def _replace_layout(self, updated_layout) -> None:
        self.project = replace(
            self.project,
            layouts=tuple(
                updated_layout if layout.id == updated_layout.id else layout
                for layout in self.project.layouts
            ),
        )

    def _replace_surrounding_item(
        self, collection: str, item_id: str, transformed
    ) -> None:
        attribute = self._surrounding_collections[collection]
        surroundings = self.project.surroundings
        items = getattr(surroundings, attribute)
        self.project = replace(
            self.project,
            surroundings=replace(
                surroundings,
                **{
                    attribute: tuple(
                        transformed if item.id == item_id else item
                        for item in items
                    )
                },
            ),
        )


def _shade_color(value: Rgba, factor: float = 0.55) -> Rgba:
    return Rgba(
        round(value.red * factor),
        round(value.green * factor),
        round(value.blue * factor),
        value.alpha,
    )
