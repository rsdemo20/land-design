from __future__ import annotations

import tempfile
import unittest
from math import atan2, degrees, hypot, radians
from pathlib import Path

from core import (
    ARC_VARIANTS,
    Building,
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
    project_geometry_issues,
)


PROJECT_FILE = Path(__file__).parents[1] / "data.json"


class ProjectCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = JsonProjectRepository(PROJECT_FILE).load()

    def test_plot_geometry_matches_known_dimensions(self) -> None:
        plot = self.project.plot

        self.assertAlmostEqual(plot.area_sqm, 1643.0530842, places=3)
        self.assertAlmostEqual(
            plot.marker("1").position.distance_to(plot.marker("3").position),
            13.0,
            places=5,
        )
        self.assertAlmostEqual(
            plot.marker("9").position.distance_to(plot.marker("7").position),
            39.0,
            places=5,
        )
        self.assertAlmostEqual(
            plot.marker("7").position.distance_to(plot.marker("5").position),
            21.0,
            places=5,
        )
        self.assertAlmostEqual(
            plot.marker("5").position.distance_to(plot.marker("6").position),
            6.22,
            places=5,
        )
        north = plot.north_unit_vector
        point_7 = plot.marker("7").position
        point_3 = plot.marker("3").position
        reference_x = point_3.x - point_7.x
        reference_z = point_3.z - point_7.z
        reference_length = (reference_x**2 + reference_z**2) ** 0.5
        self.assertEqual(plot.north_axis, "custom_vector")
        self.assertAlmostEqual(north.x, reference_x / reference_length, places=9)
        self.assertAlmostEqual(north.z, reference_z / reference_length, places=9)

    def test_saved_design_objects_have_valid_known_dimensions(self) -> None:
        for layout in self.project.layouts:
            buildings_by_kind = {building.kind: building for building in layout.buildings}
            house = buildings_by_kind.get("house")
            if house is not None:
                self.assertEqual(
                    (house.footprint.width, house.footprint.depth), (12, 8)
                )
                self.assertEqual(house.floors, 1)

            features = {feature.id: feature for feature in layout.features}
            existing_driveway = features.get("existing_driveway")
            if existing_driveway is not None:
                self.assertEqual(existing_driveway.size.depth, 3.0)
            planned_pad = features.get("planned_gravel_pad")
            if planned_pad is not None:
                self.assertGreater(planned_pad.size.width, 0)
            garage = buildings_by_kind.get("garage")
            if garage is not None:
                self.assertGreater(garage.footprint.width, 0)
                self.assertIsNotNone(garage.roof)
                self.assertEqual(garage.roof.shape, "shed")
                self.assertEqual(garage.roof.color, garage.secondary_color)

            bathhouse = buildings_by_kind.get("bathhouse")
            if bathhouse is not None:
                self.assertIsNotNone(bathhouse.roof)
                self.assertEqual(bathhouse.roof.shape, "gable")
                roof_angle = degrees(
                    atan2(
                        bathhouse.roof.height_m,
                        bathhouse.footprint.depth / 2,
                    )
                )
                self.assertAlmostEqual(roof_angle, 45.0, places=6)
                self.assertEqual(bathhouse.roof.color, bathhouse.secondary_color)

            for item in layout.buildings + layout.features + layout.primitives:
                self.assertIsNotNone(item.secondary_color)

    def test_fixed_objects_and_geometry_are_valid(self) -> None:
        self.assertEqual({item.kind for item in self.project.fixed_buildings}, {"toilet"})
        self.assertEqual(
            {item.kind for item in self.project.fixed_features},
            {"gate", "wicket", "well"},
        )
        self.assertEqual(project_geometry_issues(self.project), ())

        features = {feature.id: feature for feature in self.project.fixed_features}
        front_gate = features["front_gate"]
        front_wicket = features["front_wicket"]
        rear_wicket = features["rear_wicket"]
        point_9 = self.project.plot.marker("9").position
        point_5 = self.project.plot.marker("5").position

        self.assertEqual(front_gate.size.width, 4.3)
        self.assertEqual(front_wicket.size.width, 0.8)
        self.assertEqual(rear_wicket.size.width, 0.8)
        self.assertAlmostEqual(
            front_gate.center.x - front_gate.size.width / 2 - point_9.x,
            5.0,
            places=5,
        )
        self.assertAlmostEqual(
            front_gate.center.x + front_gate.size.width / 2,
            front_wicket.center.x - front_wicket.size.width / 2,
            places=5,
        )
        self.assertAlmostEqual(
            rear_wicket.center.x - rear_wicket.size.width / 2 - point_5.x,
            2.5,
            places=5,
        )

        well = next(
            feature
            for feature in self.project.fixed_features
            if feature.kind == "well"
        )
        self.assertEqual(well.height_m, 1.5)
        self.assertIsNotNone(well.well_structure)
        self.assertEqual(well.well_structure.ring_height_m, 0.7)
        self.assertEqual(well.well_structure.roof_height_m, 0.8)
        self.assertEqual(well.color, Rgba(145, 145, 140))
        east_front = self.project.plot.marker("1").position
        east_rear = self.project.plot.marker("4").position
        fence_distance = abs(
            (east_rear.x - east_front.x) * (east_front.z - well.center.z)
            - (east_front.x - well.center.x) * (east_rear.z - east_front.z)
        ) / east_front.distance_to(east_rear)
        self.assertAlmostEqual(fence_distance, 4.0, delta=0.1)
        self.assertNotIn("2", self.project.plot.markers_by_id)

        self.assertEqual(self.project.plot.fence.front_height_m, 2.0)
        self.assertEqual(self.project.plot.fence.other_height_m, 1.8)
        toilet = self.project.fixed_buildings[0]
        self.assertTrue(toilet.movable)
        self.assertTrue(well.movable)
        self.assertTrue(
            all(
                not item.movable
                for item in self.project.fixed_features
                if item.kind in {"gate", "wicket"}
            )
        )

        for layout in self.project.layouts:
            house = next(
                (item for item in layout.buildings if item.kind == "house"), None
            )
            if house is None:
                continue
            self.assertIsNotNone(house.roof)
            self.assertAlmostEqual(
                house.wall_height_m + house.roof.height_m,
                house.height_m,
            )
            self.assertEqual(house.roof.shape, "gable")
            self.assertGreater(house.roof.height_m, 0)

    def test_json_repository_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project.json"
            repository = JsonProjectRepository(target)
            repository.save(self.project)
            restored = repository.load()

        self.assertEqual(restored, self.project)

    def test_surroundings_match_reference_scene(self) -> None:
        surroundings = self.project.surroundings
        self.assertEqual(len(surroundings.areas), 5)
        lines = {item.id: item for item in surroundings.linear_objects}
        primitives = {item.id: item for item in surroundings.primitives}
        entry = primitives["road-straight-entry"]
        arc = primitives["road-turn-arc"]
        northeast = primitives["road-straight-northeast"]
        self.assertEqual(entry.shape, "rectangular_prism")
        self.assertEqual(arc.shape, "arc")
        self.assertEqual(northeast.shape, "rectangular_prism")
        for road_part in (entry, arc, northeast):
            self.assertGreater(road_part.size.x, 0)
            self.assertGreater(road_part.size.y, 0)
            self.assertGreater(road_part.size.z, 0)
            self.assertIn(road_part.variant, ARC_VARIANTS)
            self.assertTrue(road_part.movable)
        self.assertGreaterEqual(arc.arc_angle_deg, 5)
        self.assertLessEqual(arc.arc_angle_deg, 175)
        self.assertGreater(
            arc.size.x / radians(arc.arc_angle_deg),
            arc.size.y / 2,
        )

        driveway = lines["driveway-over-ditch"]

        self.assertGreater(driveway.width_m, 0)
        self.assertGreater(driveway.length_m, 0)
        self.assertAlmostEqual(
            driveway.points[0].x,
            driveway.points[-1].x,
            places=6,
        )
        ditch_dashes = [
            item
            for item in surroundings.linear_objects
            if item.id.startswith("front-drainage-ditch")
        ]
        self.assertEqual(len(ditch_dashes), 7)
        for dash in ditch_dashes:
            self.assertEqual(dash.style, "ditch_dash")
            self.assertGreater(dash.width_m, 0)
            self.assertGreater(dash.length_m, 0)
            self.assertTrue(dash.movable)
        for fence_id in (
            "east-boundary-neighbour-fence",
            "west-boundary-neighbour-fence",
            "east-cross-fence-3",
            "west-cross-fence-9",
            "west-cross-fence-8",
            "west-cross-fence-7",
            "west-cross-fence-6",
        ):
            fence = lines[fence_id]
            self.assertIn(fence.style, {"fence", "boundary_fence"})
            self.assertGreater(fence.length_m, 0)
            self.assertGreater(fence.height_m, 0)
            self.assertGreater(fence.width_m, 0)
        for marker_id in ("8", "7", "6"):
            fence = lines[f"west-cross-fence-{marker_id}"]
            self.assertEqual(len(fence.points), 2)

        house = next(
            item
            for item in surroundings.buildings
            if item.id == "east-neighbour-large-house"
        )
        self.assertEqual(house.kind, "neighbour_house")
        self.assertGreater(house.footprint.width, 0)
        self.assertGreater(house.footprint.depth, 0)
        self.assertGreater(house.height_m, 0)
        self.assertTrue(house.movable)
        self.assertIsNotNone(house.roof)

        pole = primitives["utility-pole-front"]
        self.assertEqual(pole.id, "utility-pole-front")
        self.assertGreater(pole.size.x, 0)
        self.assertGreater(pole.size.y, 0)
        self.assertGreater(pole.size.z, 0)
        self.assertTrue(pole.movable)

    def test_editor_adds_and_moves_primitive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project.json"
            repository = JsonProjectRepository(target)
            repository.save(self.project)
            editor = ProjectEditor(repository)
            item = PrimitiveObject(
                id="test-box",
                name="Тестовый объект",
                shape="rectangular_prism",
                center=Point2D(0, 10),
                size=Size3D(2, 3, 1.5),
                color=Rgba(120, 80, 40),
            )

            editor.add_primitive("balanced", item)
            editor.move_item(
                "balanced", "primitive", "test-box", Point2D(1.0, 11.0)
            )
            editor.rotate_item("balanced", "primitive", "test-box", 30.0)
            restored = repository.load()
            saved = next(
                value
                for value in restored.layout("balanced").primitives
                if value.id == "test-box"
            )
            self.assertEqual(saved.center, Point2D(1.0, 11.0))

    def test_surrounding_objects_support_site_source_editing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project.json"
            repository = JsonProjectRepository(target)
            repository.save(self.project)
            editor = ProjectEditor(repository)

            road = editor.get_item(
                "balanced", "surrounding_primitive", "road-turn-arc"
            )
            editor.set_item_protected(
                "balanced", "surrounding_primitive", road.id, False
            )
            requested_center = Point2D(road.center.x + 1, road.center.z + 2)
            editor.move_item(
                "balanced", "surrounding_primitive", road.id, requested_center
            )
            editor.rotate_item(
                "balanced", "surrounding_primitive", road.id, 15
            )
            moved_road = editor.get_item(
                "balanced", "surrounding_primitive", road.id
            )
            self.assertEqual(moved_road.center, requested_center)
            self.assertEqual(moved_road.rotation_y, 15)

            editor.update_item_properties(
                "balanced",
                "surrounding_primitive",
                road.id,
                Size3D(moved_road.size.x, 4.0, 0.1),
                Rgba(175, 176, 170),
                "Test road",
                "stone",
            )
            editor.set_arc_angle(
                "balanced", "surrounding_primitive", road.id, 75
            )
            updated_road = editor.get_item(
                "balanced", "surrounding_primitive", road.id
            )
            self.assertEqual(updated_road.size.y, 4.0)
            self.assertEqual(updated_road.size.z, 0.1)
            self.assertEqual(updated_road.color, Rgba(175, 176, 170))
            self.assertEqual(updated_road.variant, "stone")
            self.assertEqual(updated_road.arc_angle_deg, 75)

            outside = PrimitiveObject(
                id="outside-source-arc",
                name="Внешняя дуга",
                shape="arc",
                center=Point2D(100, 100),
                size=Size3D(8, 1.5, 0.1),
                color=Rgba(190, 190, 182),
                variant="gravel",
            )
            editor.add_site_primitive(outside)
            self.assertEqual(
                editor.get_item(
                    "balanced", "surrounding_primitive", outside.id
                ).center,
                Point2D(100, 100),
            )
            with self.assertRaises(DomainValidationError):
                editor.add_primitive("balanced", outside)

            outside_building = Building(
                id="outside-source-building",
                kind="shed",
                name="Внешний сарай",
                center=Point2D(110, 100),
                footprint=Size2D(4, 3),
                height_m=3,
                floors=1,
                color=Rgba(120, 90, 60),
            )
            outside_feature = SiteFeature(
                id="outside-source-tree",
                kind="tree",
                variant="pine",
                name="Внешняя сосна",
                center=Point2D(120, 100),
                size=Size2D(4, 4),
                shape="circle",
                color=Rgba(47, 107, 53),
                height_m=7,
            )
            editor.add_site_building(outside_building)
            editor.add_site_feature(outside_feature)
            restored_source = repository.load().surroundings
            self.assertIn(outside_building, restored_source.buildings)
            self.assertIn(outside_feature, restored_source.features)

            pole = editor.get_item(
                "balanced", "surrounding_primitive", "utility-pole-front"
            )
            editor.set_item_protected(
                "balanced", "surrounding_primitive", pole.id, False
            )
            editor.move_item(
                "balanced",
                "surrounding_primitive",
                pole.id,
                Point2D(3, 67),
            )
            moved_pole = editor.get_item(
                "balanced", "surrounding_primitive", pole.id
            )
            self.assertEqual(moved_pole.center, Point2D(3, 67))

    def test_fixed_objects_move_only_after_protection_is_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project.json"
            repository = JsonProjectRepository(target)
            repository.save(self.project)
            editor = ProjectEditor(repository)

            for collection, item_id, target_center in (
                ("fixed_feature", "well", Point2D(9.9, 18.0)),
                ("fixed_building", "toilet", Point2D(-14.0, 3.5)),
            ):
                editor.set_item_protected(
                    "balanced", collection, item_id, True
                )
                with self.assertRaises(DomainValidationError):
                    editor.move_item(
                        "balanced", collection, item_id, target_center
                    )

                editor.set_item_protected(
                    "balanced", collection, item_id, False
                )
                editor.move_item(
                    "balanced", collection, item_id, target_center
                )
                moved = editor.get_item("balanced", collection, item_id)
                self.assertEqual(moved.center, target_center)

    def test_arc_variants_and_default_curvature(self) -> None:
        self.assertEqual(
            ARC_VARIANTS,
            frozenset(
                {
                    "asphalt",
                    "gravel",
                    "ground",
                    "wood",
                    "stone",
                    "grass",
                    "bushes",
                }
            ),
        )
        arc = PrimitiveObject(
            id="default-arc",
            name="Дуга",
            shape="arc",
            center=Point2D(0, 10),
            size=Size3D(6, 2, 0.1),
            color=Rgba(190, 190, 182),
            variant="gravel",
        )
        self.assertEqual(arc.arc_angle_deg, 45)
        with self.assertRaises(DomainValidationError):
            PrimitiveObject(
                id="invalid-arc",
                name="Дуга",
                shape="arc",
                center=Point2D(0, 10),
                size=Size3D(2, 2, 0.1),
                color=Rgba(0, 0, 0),
                variant="water",
            )

    def test_nature_variant_is_validated_edited_and_persisted(self) -> None:
        self.assertTrue(
            {"pine_photo", "birch_photo", "ash_photo"}
            <= NATURE_VARIANTS["tree"]
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project.json"
            repository = JsonProjectRepository(target)
            repository.save(self.project)
            editor = ProjectEditor(repository)
            tree = SiteFeature(
                id="test-tree",
                kind="tree",
                variant="pine",
                name="Сосна",
                center=Point2D(0, 10),
                size=Size2D(4, 4),
                shape="circle",
                color=Rgba(47, 107, 53),
                height_m=7,
            )

            editor.add_feature("balanced", tree)
            editor.update_item_properties(
                "balanced",
                "feature",
                "test-tree",
                Size3D(5, 4.5, 6),
                Rgba(94, 153, 61),
                "Яблоня",
                "apple",
            )
            saved = next(
                item
                for item in repository.load().layout("balanced").features
                if item.id == "test-tree"
            )

            self.assertEqual(saved.variant, "apple")
            self.assertEqual(saved.name, "Яблоня")
            self.assertEqual(saved.size, Size2D(5, 4.5))
            self.assertEqual(saved.height_m, 6)

        with self.assertRaises(DomainValidationError):
            SiteFeature(
                id="invalid-tree",
                kind="tree",
                variant="willow",
                name="Ива",
                center=Point2D(0, 10),
                size=Size2D(4, 4),
                shape="circle",
                color=Rgba(40, 100, 40),
                height_m=5,
            )
            self.assertEqual(saved.rotation_y, 30.0)

            with self.assertRaises(DomainValidationError):
                editor.move_item(
                    "balanced", "primitive", "test-box", Point2D(100, 100)
                )

    def test_protection_deletion_hiding_and_design_switching(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project.json"
            repository = JsonProjectRepository(target)
            repository.save(self.project)
            editor = ProjectEditor(repository)

            with self.assertRaises(DomainValidationError):
                editor.delete_or_hide_item(
                    "balanced", "fixed_feature", "front_gate"
                )
            editor.set_item_protected(
                "balanced", "fixed_feature", "front_gate", False
            )
            self.assertEqual(
                editor.delete_or_hide_item(
                    "balanced", "fixed_feature", "front_gate"
                ),
                "hidden",
            )
            self.assertIn(
                "front_gate", editor.project.layout("balanced").hidden_fixed_ids
            )
            self.assertNotIn(
                "front_gate", editor.project.layout("east_house").hidden_fixed_ids
            )
            self.assertTrue(
                any(item.id == "front_gate" for item in editor.project.fixed_features)
            )

            editor.restore_fixed_item("balanced", "front_gate")
            self.assertNotIn(
                "front_gate", editor.project.layout("balanced").hidden_fixed_ids
            )

            editor.set_item_protected("balanced", "fence", FENCE_OBJECT_ID, False)
            self.assertEqual(
                editor.delete_or_hide_item("balanced", "fence", FENCE_OBJECT_ID),
                "hidden",
            )
            self.assertIsNotNone(editor.project.plot.fence)
            self.assertIn(
                FENCE_OBJECT_ID, editor.project.layout("balanced").hidden_fixed_ids
            )

            removable = PrimitiveObject(
                id="removable-box",
                name="Удаляемый объект",
                shape="rectangular_prism",
                center=Point2D(0, 10),
                size=Size3D(1, 1, 1),
                color=Rgba(100, 100, 100),
            )
            editor.add_primitive("balanced", removable)
            editor.set_item_protected(
                "balanced", "primitive", removable.id, True
            )
            with self.assertRaises(DomainValidationError):
                editor.delete_or_hide_item(
                    "balanced", "primitive", removable.id
                )
            editor.set_item_protected(
                "balanced", "primitive", removable.id, False
            )
            self.assertEqual(
                editor.delete_or_hide_item(
                    "balanced", "primitive", removable.id
                ),
                "deleted",
            )
            self.assertFalse(
                any(
                    item.id == removable.id
                    for item in editor.project.layout("balanced").primitives
                )
            )

            editor.set_active_layout("east_house")
            restored = repository.load()
            self.assertEqual(restored.active_layout_id, "east_house")
            self.assertIn(
                FENCE_OBJECT_ID, restored.layout("balanced").hidden_fixed_ids
            )

    def test_editor_updates_bounding_dimensions_and_color(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "project.json"
            repository = JsonProjectRepository(target)
            repository.save(self.project)
            editor = ProjectEditor(repository)

            cube = PrimitiveObject(
                id="editable-cube",
                name="Куб",
                shape="cube",
                center=Point2D(0, 10),
                size=Size3D(1, 1, 1),
                color=Rgba(100, 100, 100),
            )
            editor.add_primitive("balanced", cube)
            editor.update_item_properties(
                "balanced",
                "primitive",
                cube.id,
                Size3D(2, 3, 4),
                Rgba(20, 40, 60),
                "Новый размер",
            )
            resized_cube = editor.get_item("balanced", "primitive", cube.id)
            self.assertEqual(resized_cube.size, Size3D(2, 3, 4))
            self.assertEqual(resized_cube.shape, "rectangular_prism")
            self.assertEqual(resized_cube.color, Rgba(20, 40, 60))
            self.assertEqual(resized_cube.name, "Новый размер")

            building = Building(
                id="editable-house",
                kind="house",
                name="Дом",
                center=Point2D(0, 30),
                footprint=Size2D(4, 3),
                height_m=3,
                floors=1,
                color=Rgba(160, 120, 80),
                wall_height_m=2.25,
                roof=RoofSpec(
                    shape="gable",
                    height_m=0.75,
                    overhang_m=0.1,
                    ridge_axis="x",
                    color=Rgba(80, 60, 40),
                ),
            )
            editor.add_building("balanced", building)
            editor.update_item_properties(
                "balanced",
                "building",
                building.id,
                Size3D(8, 5, 4),
                Rgba(120, 100, 80),
                secondary_color=Rgba(35, 55, 75),
            )
            resized_building = editor.get_item(
                "balanced", "building", building.id
            )
            self.assertEqual(resized_building.footprint, Size2D(8, 5))
            self.assertEqual(resized_building.height_m, 4)
            self.assertEqual(resized_building.wall_height_m, 3)
            self.assertEqual(resized_building.roof.height_m, 1)
            self.assertEqual(resized_building.secondary_color, Rgba(35, 55, 75))
            self.assertEqual(resized_building.roof.color, Rgba(35, 55, 75))

            editor.update_item_properties(
                "balanced",
                "fixed_feature",
                "well",
                Size3D(2, 2, 2),
                Rgba(150, 150, 145),
            )
            resized_well = editor.get_item(
                "balanced", "fixed_feature", "well"
            )
            self.assertEqual(resized_well.size, Size2D(2, 2))
            self.assertEqual(resized_well.height_m, 2)
            self.assertAlmostEqual(
                resized_well.well_structure.ring_height_m,
                2 * 0.7 / 1.5,
            )

            with self.assertRaises(DomainValidationError):
                editor.update_item_properties(
                    "balanced",
                    "building",
                    building.id,
                    Size3D(100, 100, 4),
                    Rgba(120, 100, 80),
                )


if __name__ == "__main__":
    unittest.main()
