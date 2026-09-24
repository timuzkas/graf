import unittest

from graf.expressions import parse_relation
from graf.plotting import Viewport, contour_implicit, find_axis_crossings, find_intersections, refine_intersection, sample_explicit, sample_explicit_adaptive, snap_to_nearest_point


class ViewportTests(unittest.TestCase):
    def test_world_screen_round_trip(self):
        view = Viewport(center_x=2, center_y=-3, scale=40)
        pixel = view.world_to_screen(4, 1, 800, 600)
        world = view.screen_to_world(*pixel, 800, 600)
        self.assertAlmostEqual(world[0], 4)
        self.assertAlmostEqual(world[1], 1)

    def test_pan_changes_center_in_graph_direction(self):
        view = Viewport(scale=10)
        view.pan_pixels(20, 30)
        self.assertAlmostEqual(view.center_x, -2)
        self.assertAlmostEqual(view.center_y, 3)

    def test_zoom_keeps_pointer_anchor_fixed(self):
        view = Viewport()
        before = view.screen_to_world(110, 170, 400, 300)
        view.zoom_at(1.7, 110, 170, 400, 300)
        after = view.screen_to_world(110, 170, 400, 300)
        self.assertAlmostEqual(before[0], after[0])
        self.assertAlmostEqual(before[1], after[1])

    def test_explicit_line_and_asymptote_split(self):
        view = Viewport(scale=30)
        line = sample_explicit(parse_relation("x"), view, 400, 300)
        self.assertEqual(len(line), 1)
        self.assertAlmostEqual(line[0][200][1], 150, delta=2)
        reciprocal = sample_explicit(parse_relation("1/x"), view, 400, 300)
        self.assertGreaterEqual(len(reciprocal), 2)

    def test_steep_curve_stays_near_the_visible_canvas(self):
        paths = sample_explicit_adaptive(parse_relation("x^6"), Viewport(), 800, 600)
        points = [point for path in paths for point in path]
        self.assertTrue(points)
        self.assertTrue(all(-48 <= x <= 848 and -48 <= y <= 648 for x, y in points))
        segments = [(first, second) for path in paths for first, second in zip(path, path[1:])]
        self.assertEqual(find_intersections([segments]), [])

    def test_circle_has_contours_in_all_quadrants(self):
        view = Viewport(scale=45)
        segments = contour_implicit(parse_relation("x^2+y^2=4"), view, 400, 300)
        self.assertGreater(len(segments), 20)
        points = [point for segment in segments for point in segment]
        self.assertTrue(any(x < 200 and y < 150 for x, y in points))
        self.assertTrue(any(x > 200 and y < 150 for x, y in points))
        self.assertTrue(any(x < 200 and y > 150 for x, y in points))
        self.assertTrue(any(x > 200 and y > 150 for x, y in points))

    def test_intersections_are_found_between_sampled_curves(self):
        first = [((0.0, 5.0), (10.0, 5.0))]
        second = [((5.0, 0.0), (5.0, 10.0))]
        points = find_intersections([first, second])
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0], (5.0, 5.0))

    def test_zoomed_out_intersection_refines_to_equation_solution(self):
        view = Viewport(scale=3)
        rough_point = view.world_to_screen(1.996, 4.021, 400, 300)
        first = (parse_relation("y=x^2"), {}, {})
        second = (parse_relation("y=4"), {}, {})
        refined = refine_intersection(rough_point, first, second, view, 400, 300)
        x, y = view.screen_to_world(*refined, 400, 300)
        self.assertAlmostEqual(x, 2.0, places=8)
        self.assertAlmostEqual(y, 4.0, places=8)

    def test_axis_crossings_are_interpolated_and_merged(self):
        curves = [
            [((0.0, 10.0), (10.0, 0.0)), ((10.0, 0.0), (20.0, -10.0))],
            [((11.0, 2.0), (11.0, -2.0))],
        ]
        self.assertEqual(find_axis_crossings(curves, 0.0, 100.0), [(10.0, 0.0)])

    def test_axis_crossings_include_a_tangent_vertex(self):
        curve = [[((0.0, 5.0), (10.0, 0.0)), ((10.0, 0.0), (20.0, 5.0))]]
        self.assertEqual(find_axis_crossings(curve, 0.0, 100.0), [(10.0, 0.0)])

    def test_point_snapping_picks_nearest_point_within_radius(self):
        points = [(20.0, 20.0), (31.0, 30.0)]
        self.assertEqual(snap_to_nearest_point((22.0, 21.0), points), points[0])
        self.assertIsNone(snap_to_nearest_point((50.0, 50.0), points))

    def test_explicit_domain_is_checked_against_the_curve_value(self):
        view = Viewport(scale=30)
        # y > 2 is screen row 150 - 2*30 = 90
        for sampler in (sample_explicit, sample_explicit_adaptive):
            with self.subTest(sampler=sampler.__name__):
                paths = sampler(parse_relation("x{y > 2}"), view, 400, 300)
                points = [point for path in paths for point in path]
                self.assertTrue(points, "clipped curve should still render above y = 2")
                self.assertTrue(all(py < 91 for _, py in points), "curve leaked below y = 2")

    def test_explicit_domain_can_remove_everything(self):
        view = Viewport(scale=30)
        self.assertEqual(sample_explicit(parse_relation("x{y > 1000}"), view, 400, 300), [])


if __name__ == "__main__":
    unittest.main()
