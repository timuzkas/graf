import math
import unittest

from graf.expressions import ExpressionError, parse_relation
from graf import __version__ as GRAF_VERSION
from otter import __version__ as OTTER_VERSION


class ExpressionTests(unittest.TestCase):
    def test_otter_is_a_versioned_public_package(self):
        self.assertRegex(OTTER_VERSION, r"^\d+\.\d+\.\d+$")
        self.assertRegex(GRAF_VERSION, r"^\d+\.\d+\.\d+$")
        self.assertEqual(parse_relation("2 + 2").constant_value(), 4)

    def test_precedence_and_right_associative_power(self):
        self.assertEqual(parse_relation("2+3*4").evaluate(0, 0), 14)
        self.assertEqual(parse_relation("2^3^2").evaluate(0, 0), 512)
        self.assertEqual(parse_relation("-x^2").evaluate(3, 0), -9)

    def test_implicit_multiplication_and_functions(self):
        self.assertAlmostEqual(parse_relation("2x + sin(pi/2)").evaluate(3, 0), 7)
        self.assertEqual(parse_relation("sqrt(9) + abs(-2)").evaluate(0, 0), 5)

    def test_numerical_calculus_with_builtin_functions(self):
        derivative = parse_relation("derivative(sin, 0)").constant_value()
        integral = parse_relation("integral(sin, 0, pi)").constant_value()
        self.assertAlmostEqual(derivative, 1.0, places=8)
        self.assertAlmostEqual(integral, 2.0, places=8)

    def test_numerical_calculus_with_defined_functions(self):
        functions = {"f": lambda value: value**2}
        derivative = parse_relation("derivative(f, 3)", functions={"f"})
        integral = parse_relation("integral(f, 0, 3)", functions={"f"})
        self.assertAlmostEqual(derivative.scalar_value(functions=functions), 6.0, places=7)
        self.assertAlmostEqual(integral.scalar_value(functions=functions), 9.0, places=7)

    def test_user_functions_work_in_plain_and_parametric_expressions(self):
        functions = {"f": lambda value: value + 1}
        plain = parse_relation("f(2)", functions={"f"})
        parametric = parse_relation("(f(t), t)", functions={"f"})
        self.assertEqual(plain.scalar_value(functions=functions), 3)
        self.assertEqual(parametric.evaluate_parametric(2, functions=functions), (3.0, 2.0))

    def test_function_table_creates_plottable_points(self):
        functions = {"f": lambda value: value**2}
        table = parse_relation("table(f, [-2, 0, 3])", functions={"f"})
        self.assertEqual(table.kind, "list")
        self.assertEqual(table.point_values(functions=functions), [(-2.0, 4.0), (0.0, 0.0), (3.0, 9.0)])

    def test_function_table_accepts_builtin_functions(self):
        table = parse_relation("table(sin, [0, pi/2, pi])")
        points = table.point_values()
        self.assertIsNotNone(points)
        self.assertAlmostEqual(points[0][1], 0.0)
        self.assertAlmostEqual(points[1][1], 1.0)
        self.assertAlmostEqual(points[2][1], 0.0, places=8)

    def test_parsed_relations_are_cached(self):
        self.assertIs(parse_relation("x^2", {"a"}), parse_relation("x^2", frozenset({"a"})))

    def test_degree_suffix_converts_to_radians(self):
        self.assertAlmostEqual(parse_relation("sin(30°)").evaluate(0, 0), 0.5)
        self.assertAlmostEqual(parse_relation("cos(180°)").evaluate(0, 0), -1)

    def test_constant_expressions_have_scalar_results(self):
        self.assertEqual(parse_relation("2^2").constant_value(), 4)
        self.assertAlmostEqual(parse_relation("sin(30°)").constant_value(), 0.5)
        self.assertIsNone(parse_relation("x^2").constant_value())
        self.assertIsNone(parse_relation("y=2").constant_value())
        self.assertIsNone(parse_relation("1/0").constant_value())

    def test_named_variables_and_assignments(self):
        assignment = parse_relation("a=2")
        self.assertEqual(assignment.kind, "assignment")
        self.assertEqual(assignment.variable_name, "a")
        self.assertEqual(assignment.evaluate(0, 0), 2)
        expression = parse_relation("a*x+1", {"a"})
        self.assertEqual(expression.evaluate(3, 0, {"a": 4}), 13)
        self.assertEqual(parse_relation("a+1", {"a"}).scalar_value({"a": 4}), 5)
        self.assertEqual(parse_relation("ans+1", {"ans"}).evaluate(0, 0, {"ans": 4}), 5)

    def test_rejects_undefined_named_variables(self):
        with self.assertRaises(ExpressionError):
            parse_relation("a*x")

    def test_explicit_and_implicit_relations(self):
        self.assertEqual(parse_relation("y = x^2").evaluate(3, 50), 9)
        circle = parse_relation("x^2 + y^2 = 4")
        self.assertEqual(circle.kind, "implicit")
        self.assertEqual(circle.evaluate(0, 0), -4)

    def test_rejects_unknown_and_malformed_input(self):
        for source in ("z+1", "sin x", "x=1=2", "sqrt(", ""):
            with self.subTest(source=source), self.assertRaises(ExpressionError):
                parse_relation(source)

    def test_nonfinite_results_fail(self):
        with self.assertRaises(ArithmeticError):
            parse_relation("1/0").evaluate(0, 0)
        with self.assertRaises(ValueError):
            parse_relation("sqrt(-1)").evaluate(0, 0)
        self.assertAlmostEqual(parse_relation("log(100)").evaluate(0, 0), 2)

    def test_tilde_is_a_degree_alias(self):
        self.assertAlmostEqual(parse_relation("sin(30~)").evaluate(0, 0), 0.5)
        self.assertAlmostEqual(parse_relation("cos(180~)").evaluate(0, 0), -1)

    def test_list_of_points_exposes_world_points(self):
        relation = parse_relation("[(1, 2), (3, 4)]")
        self.assertEqual(relation.kind, "list")
        self.assertEqual(relation.point_values(), [(1.0, 2.0), (3.0, 4.0)])
        self.assertIsNone(parse_relation("[1, 2, 3]").point_values())

    def test_polygon_accepts_points_and_point_lists(self):
        self.assertEqual(
            parse_relation("polygon((0, 0), (1, 1), (2, 0))").point_values(),
            [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)],
        )
        self.assertEqual(
            parse_relation("polygon([(0, 0), (1, 1)], (3, 3))").point_values(),
            [(0.0, 0.0), (1.0, 1.0), (3.0, 3.0)],
        )
        self.assertEqual(
            parse_relation("polygon([0, 1, 2], [0, 1, 0])").point_values(),
            [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)],
        )

    def test_polygon_rejects_non_point_arguments(self):
        with self.assertRaises(ExpressionError):
            parse_relation("polygon()")
        self.assertIsNone(parse_relation("polygon(1, 2)").point_values())

    def test_list_assignment_does_not_collide_with_slider_syntax(self):
        listing = parse_relation("L = [1, 2, 3]")
        self.assertEqual(listing.kind, "assignment")
        self.assertIsNone(listing.slider)
        self.assertEqual(listing.assigned_value(), [1.0, 2.0, 3.0])
        slider = parse_relation("a = 1[0, 10, 0.5]")
        self.assertEqual(slider.constant_value(), 1)
        self.assertEqual(slider.slider, (0.0, 10.0, 0.5))

    def test_stacked_brace_groups_are_anded(self):
        relation = parse_relation("2x^a{x > 1}{y > 2}", {"a"})
        self.assertEqual(relation.kind, "explicit")
        self.assertTrue(relation.allows(2, 3, {"a": 2}))
        self.assertFalse(relation.allows(0, 3, {"a": 2}), "x > 1 should fail")
        self.assertFalse(relation.allows(2, 1, {"a": 2}), "y > 2 should fail")
        self.assertFalse(relation.allows(0, 0, {"a": 2}))

    def test_piecewise_braces_are_not_treated_as_a_domain(self):
        relation = parse_relation("y = {x < 0: -x, x >= 0: x}")
        self.assertIsNone(relation.domain)
        self.assertEqual(relation.evaluate(-3, 0), 3)
        self.assertEqual(relation.evaluate(4, 0), 4)


if __name__ == "__main__":
    unittest.main()
