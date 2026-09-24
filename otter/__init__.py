"""Otter's safe expression parser and numerical evaluation engine."""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, TypeAlias

Node: TypeAlias = tuple

__version__ = "0.1.0"


def _numerical_derivative(function: Callable[[float], float], value: float) -> float:
    step = 1e-5 * max(1.0, abs(value))
    return (float(function(value + step)) - float(function(value - step))) / (2 * step)


def _numerical_integral(function: Callable[[float], float], lower: float, upper: float) -> float:
    intervals = 128
    step = (upper - lower) / intervals
    total = float(function(lower)) + float(function(upper))
    total += 4 * sum(float(function(lower + index * step)) for index in range(1, intervals, 2))
    total += 2 * sum(float(function(lower + index * step)) for index in range(2, intervals, 2))
    return total * step / 3


def _function_table(function: Callable[[float], float], values: list[float]) -> list[tuple[float, float]]:
    if not isinstance(values, list):
        raise ValueError("table() needs a list of x values")
    points: list[tuple[float, float]] = []
    for value in values:
        if not _is_number(value):
            raise ValueError("table() x values must be finite numbers")
        result = float(function(float(value)))
        if not math.isfinite(result):
            raise ValueError("table() produced a non-finite value")
        points.append((float(value), result))
    return points


FUNCTIONS: dict[str, Callable[[float], float]] = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "sqrt": math.sqrt,
    "abs": abs,
    "exp": math.exp,
    "ln": math.log,
    "log": math.log10,
    "floor": math.floor,
    "ceil": math.ceil,
    "derivative": _numerical_derivative,
    "integral": _numerical_integral,
    "table": _function_table,
}
CONSTANTS = {"pi": math.pi, "e": math.e}
TOKEN_RE = re.compile(r"\s*(?:(\d+(?:\.\d*)?|\.\d+)(?:([eE][+-]?\d+))?|([A-Za-z_][A-Za-z_0-9]*)|((?:<=|>=|!=|==)|.))")
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")
SLIDER_RE = re.compile(r"\s*\[\s*([^,\]]+)\s*,\s*([^,\]]+)\s*,\s*([^\]]+)\s*\]\s*$")


class ExpressionError(ValueError):
    """invalid or unsupported graph expression."""


def _tokens(source: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    while pos < len(source):
        match = TOKEN_RE.match(source, pos)
        if not match:
            raise ExpressionError(f"Unexpected input near {source[pos:pos + 12]!r}")
        number, exponent, name, other = match.groups()
        pos = match.end()
        if number is not None:
            out.append(("number", number + (exponent or "")))
        elif name is not None:
            out.append(("name", name.lower()))
        elif other in "+-*/^()%{},<>[]=!:":
            out.append((other, other))
        elif other in ("<=", ">=", "!=", "=="):
            out.append((other, other))
        elif other in ("°", "~"):
            out.append(("degree", other))
        else:
            raise ExpressionError(f"Unsupported character {other!r}")
    out.append(("end", ""))
    return out


class _Parser:
    def __init__(
        self,
        source: str,
        variables: set[str] | frozenset[str] = frozenset(),
        functions: set[str] | frozenset[str] = frozenset(),
    ):
        self.tokens = _tokens(source)
        self.index = 0
        self.variables = variables
        self.functions = functions

    def peek(self) -> tuple[str, str]:
        return self.tokens[self.index]

    def take(self) -> tuple[str, str]:
        token = self.peek()
        self.index += 1
        return token

    def split_name(self, value: str) -> list[Node] | None:
        """split adjacent single letters, so xy means x*y."""
        atoms = sorted(set(self.variables) | {"x", "y", *CONSTANTS}, key=len, reverse=True)
        memo: dict[int, list[Node] | None] = {}

        def split(offset: int) -> list[Node] | None:
            if offset == len(value):
                return []
            if offset in memo:
                return memo[offset]
            for atom in atoms:
                if value.startswith(atom, offset):
                    suffix = split(offset + len(atom))
                    if suffix is not None:
                        node: Node = ("variable", atom) if atom in ("x", "y") or atom in self.variables else ("constant", atom)
                        memo[offset] = [node, *suffix]
                        return memo[offset]
            memo[offset] = None
            return None

        return split(0)

    def parse(self) -> Node:
        if self.peek()[0] == "end":
            raise ExpressionError("Enter an expression")
        node = self.expression(0)
        if self.peek()[0] != "end":
            raise ExpressionError(f"Unexpected {self.peek()[1]!r}")
        return node

    def expression(self, min_bp: int) -> Node:
        kind, value = self.take()
        if kind == "number":
            left: Node = ("number", float(value))
        elif kind == "name":
            if (value in FUNCTIONS or value in self.functions) and self.peek()[0] == "(":
                self.take()
                arguments = []
                if self.peek()[0] != ")":
                    function_names = (set(FUNCTIONS) - {"derivative", "integral", "table"}) | set(self.functions)
                    if value in ("derivative", "integral", "table") and self.peek()[0] == "name" and self.peek()[1] in function_names and self.tokens[self.index + 1][0] == ",":
                        arguments.append(("function_ref", self.take()[1]))
                    else:
                        arguments.append(self.expression(0))
                    while self.peek()[0] == ",":
                        self.take()
                        arguments.append(self.expression(0))
                if self.take()[0] != ")":
                    raise ExpressionError("Expected ')'")
                left = ("call", value, tuple(arguments))
            elif value in ("x", "y"):
                left = ("variable", value)
            elif value in CONSTANTS:
                left = ("constant", value)
            elif value in self.variables:
                left = ("variable", value)
            elif value in FUNCTIONS or value in self.functions:
                raise ExpressionError(f"Write {value} with parentheses, such as {value}(x)")
            else:
                pieces = self.split_name(value)
                if not pieces:
                    raise ExpressionError(f"Unknown name {value!r}")
                left = pieces[0]
                for piece in pieces[1:]:
                    left = ("binary", "*", left, piece)
        elif kind in ("+", "-"):
            left = ("unary", kind, self.expression(25))
        elif kind == "(":
            values = [self.expression(0)]
            while self.peek()[0] == ",":
                self.take()
                values.append(self.expression(0))
            if self.take()[0] != ")":
                raise ExpressionError("Expected ')'")
            left = ("tuple", tuple(values)) if len(values) > 1 else values[0]
        elif kind == "[":
            values = []
            if self.peek()[0] != "]":
                values.append(self.expression(0))
                while self.peek()[0] == ",":
                    self.take()
                    values.append(self.expression(0))
            if self.take()[0] != "]":
                raise ExpressionError("Expected ']'")
            left = ("list", tuple(values))
        else:
            raise ExpressionError(f"Expected a number, variable, or '(', got {value!r}")

        while True:
            kind, _ = self.peek()
            if kind == "degree":
                self.take()
                left = ("binary", "/", ("binary", "*", left, ("constant", "pi")), ("number", 180.0))
                continue
            if kind == "!":
                self.take()
                left = ("factorial", left)
                continue
            if kind == "[":
                self.take()
                index = self.expression(0)
                if self.take()[0] != "]":
                    raise ExpressionError("Expected ']'")
                left = ("index", left, index)
                continue
            implicit = kind in ("number", "name", "(")
            if kind in ("+", "-"):
                left_bp, right_bp, operator = 10, 11, kind
            elif kind in ("*", "/", "%"):
                left_bp, right_bp, operator = 20, 21, kind
            elif kind == "^":
                left_bp, right_bp, operator = 30, 30, kind
            elif kind in ("<", "<=", ">", ">=", "!=", "==", "="):
                left_bp, right_bp, operator = 5, 6, kind
            elif implicit:
                left_bp, right_bp, operator = 20, 21, "*"
            else:
                break
            if left_bp < min_bp:
                break
            if not implicit or kind in ("+", "-", "*", "/", "%", "^", "<", "<=", ">", ">=", "!="):
                self.take()
            right = self.expression(right_bp)
            left = ("compare", operator, left, right) if kind in ("<", "<=", ">", ">=", "!=", "==", "=") else ("binary", operator, left, right)
        return left


def _python_node(node: Node) -> ast.expr:
    kind = node[0]
    if kind == "number":
        return ast.Constant(value=node[1])
    if kind == "constant":
        return ast.Constant(value=CONSTANTS[node[1]])
    if kind == "variable":
        if node[1] in ("x", "y"):
            return ast.Name(id=node[1], ctx=ast.Load())
        return ast.Subscript(value=ast.Name(id="variables", ctx=ast.Load()), slice=ast.Constant(value=node[1]), ctx=ast.Load())
    if kind == "function_ref":
        if node[1] in FUNCTIONS:
            return ast.Name(id=f"__f_{node[1]}", ctx=ast.Load())
        return ast.Subscript(value=ast.Name(id="functions", ctx=ast.Load()), slice=ast.Constant(value=node[1]), ctx=ast.Load())
    if kind == "unary":
        operator = ast.UAdd() if node[1] == "+" else ast.USub()
        return ast.UnaryOp(op=operator, operand=_python_node(node[2]))
    if kind == "call":
        function = ast.Name(id=f"__f_{node[1]}", ctx=ast.Load()) if node[1] in FUNCTIONS else ast.Subscript(value=ast.Name(id="functions", ctx=ast.Load()), slice=ast.Constant(value=node[1]), ctx=ast.Load())
        return ast.Call(func=function, args=[_python_node(argument) for argument in node[2]], keywords=[])
    if kind == "tuple":
        return ast.Tuple(elts=[_python_node(value) for value in node[1]], ctx=ast.Load())
    if kind == "list":
        return ast.List(elts=[_python_node(value) for value in node[1]], ctx=ast.Load())
    if kind == "factorial":
        return ast.Call(func=ast.Name(id="__factorial", ctx=ast.Load()), args=[_python_node(node[1])], keywords=[])
    if kind == "index":
        index_node = node[2]
        index_expression = _python_node(index_node)
        if index_node[0] == "number" and float(index_node[1]).is_integer():
            index_expression = ast.Constant(value=int(index_node[1]))
        if node[1] == ("variable", "ans"):
            history = ast.Subscript(
                value=ast.Name(id="variables", ctx=ast.Load()),
                slice=ast.Constant(value="ans_history"),
                ctx=ast.Load(),
            )
            one_based_index = ast.BinOp(left=index_expression, op=ast.Sub(), right=ast.Constant(value=1))
            return ast.Subscript(value=history, slice=one_based_index, ctx=ast.Load())
        one_based_index = ast.BinOp(left=index_expression, op=ast.Sub(), right=ast.Constant(value=1))
        return ast.Subscript(value=_python_node(node[1]), slice=one_based_index, ctx=ast.Load())
    if kind == "piecewise":
        fallback: ast.expr = ast.Constant(value=float("nan"))
        for condition, value in reversed(node[1]):
            fallback = ast.IfExp(test=_python_node(condition), body=_python_node(value), orelse=fallback)
        return fallback
    if kind == "and":
        return ast.BoolOp(op=ast.And(), values=[_python_node(value) for value in node[1]])
    if kind == "compare":
        comparisons = {"<": ast.Lt(), "<=": ast.LtE(), ">": ast.Gt(), ">=": ast.GtE(), "!=": ast.NotEq(), "==": ast.Eq(), "=": ast.Eq()}
        return ast.Compare(left=_python_node(node[2]), ops=[comparisons[node[1]]], comparators=[_python_node(node[3])])
    operators = {"+": ast.Add(), "-": ast.Sub(), "*": ast.Mult(), "/": ast.Div(), "%": ast.Mod(), "^": ast.Pow()}
    return ast.BinOp(left=_python_node(node[2]), op=operators[node[1]], right=_python_node(node[3]))


def _factorial(value: float) -> int:
    if not math.isfinite(value) or value < 0 or value != int(value):
        raise ValueError("Factorial needs a non-negative integer")
    return math.factorial(int(value))


def _compile_function(root: Node) -> Callable[[float, float, dict[str, float], dict[str, Callable]], Any]:
    args = ast.arguments(
        posonlyargs=[],
        args=[ast.arg(arg="x"), ast.arg(arg="y"), ast.arg(arg="variables"), ast.arg(arg="functions")],
        vararg=None,
        kwonlyargs=[],
        kw_defaults=[],
        kwarg=None,
        defaults=[],
    )
    expression = ast.Expression(body=ast.Lambda(args=args, body=_python_node(root)))
    ast.fix_missing_locations(expression)
    namespace: dict[str, object] = {"__builtins__": {}, "__factorial": _factorial}
    namespace.update({f"__f_{name}": function for name, function in FUNCTIONS.items()})
    return eval(compile(expression, "<graf-expression>", "eval"), namespace)


def _has_variable(node: Node) -> bool:
    if node and isinstance(node[0], str) and node[0] == "variable":
        return True
    children = node[1:] if node and isinstance(node[0], str) else node
    return any(_has_variable(child) for child in children if isinstance(child, tuple))


def _has_coordinate(node: Node) -> bool:
    if node and isinstance(node[0], str) and node[0] == "variable" and node[1] in ("x", "y"):
        return True
    children = node[1:] if node and isinstance(node[0], str) else node
    return any(_has_coordinate(child) for child in children if isinstance(child, tuple))


def _has_symbol(node: Node, symbol: str) -> bool:
    if node and isinstance(node[0], str) and node[0] == "variable" and node[1] == symbol:
        return True
    children = node[1:] if node and isinstance(node[0], str) else node
    return any(_has_symbol(child, symbol) for child in children if isinstance(child, tuple))


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _is_point(value: Any) -> bool:
    return isinstance(value, (tuple, list)) and len(value) == 2 and all(_is_number(item) for item in value)


def _is_number_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(_is_number(item) for item in value)


def _is_point_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(_is_point(item) for item in value)


@dataclass(frozen=True)
class ParsedRelation:
    """a parsed graph row; explicit gives y, implicit a residual."""

    kind: str
    root: Node | tuple[Node, Node]
    source: str
    variable_name: str | None = None
    operator: str | None = None
    domain: Node | None = None
    function_args: tuple[str, ...] = ()
    slider: tuple[float, float, float] | None = None
    _compiled: Any = field(init=False, repr=False, compare=False)
    _domain_compiled: Any = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.kind in ("parametric", "point"):
            object.__setattr__(self, "_compiled", (_compile_function(self.root[0]), _compile_function(self.root[1])))
        elif self.kind == "polygon":
            object.__setattr__(self, "_compiled", tuple(_compile_function(node) for node in self.root))
        else:
            object.__setattr__(self, "_compiled", _compile_function(self.root))
        object.__setattr__(self, "_domain_compiled", _compile_function(self.domain) if self.domain is not None else None)

    def evaluate(self, x: float, y: float, variables: dict[str, float] | None = None, functions: dict[str, Callable] | None = None) -> float:
        if self.kind in ("parametric", "point", "polygon"):
            raise ExpressionError("This row does not evaluate to a scalar")
        value = self._compiled(x, y, variables or {}, functions or {})
        if isinstance(value, complex):
            raise ArithmeticError("Result is not real")
        result = float(value)
        if not math.isfinite(result):
            raise ArithmeticError("Result is not finite")
        return result

    def evaluate_point(self, variables: dict[str, float] | None = None, functions: dict[str, Callable] | None = None) -> tuple[float, float]:
        if self.kind != "point":
            raise ExpressionError("This row is not a point")
        values = variables or {}
        return (float(self._compiled[0](0.0, 0.0, values, functions or {})), float(self._compiled[1](0.0, 0.0, values, functions or {})))

    def evaluate_polygon(self, variables: dict[str, float] | None = None, functions: dict[str, Callable] | None = None) -> list[tuple[float, float]]:
        """polygon vertices in the order written."""
        if self.kind != "polygon":
            raise ExpressionError("This row is not a polygon")
        values: list[Any] = []
        for compiled in self._compiled:
            try:
                values.append(compiled(0.0, 0.0, variables or {}, functions or {}))
            except (ArithmeticError, ValueError, OverflowError, TypeError, KeyError) as error:
                raise ExpressionError("Could not evaluate a polygon vertex") from error
        if len(values) == 2 and all(_is_number_list(value) for value in values):
            return [(float(x), float(y)) for x, y in zip(values[0], values[1])]
        points: list[tuple[float, float]] = []
        for value in values:
            if _is_point(value):
                points.append((float(value[0]), float(value[1])))
            elif _is_point_list(value):
                points.extend((float(px), float(py)) for px, py in value)
            else:
                raise ExpressionError("polygon() needs points or lists of points")
        return points

    def point_values(self, variables: dict[str, float] | None = None, functions: dict[str, Callable] | None = None) -> list[tuple[float, float]] | None:
        """world points for point, list, or polygon rows."""
        try:
            if self.kind == "point":
                return [self.evaluate_point(variables, functions)]
            if self.kind == "polygon":
                return self.evaluate_polygon(variables, functions)
            if self.kind == "list":
                value = self.evaluate_value(variables, functions)
                if _is_point_list(value):
                    return [(float(px), float(py)) for px, py in value]
                if _is_point(value):
                    return [(float(value[0]), float(value[1]))]
        except (ArithmeticError, ValueError, OverflowError, KeyError, TypeError, IndexError):
            return None
        return None

    def assigned_value(self, variables: dict[str, float] | None = None, functions: dict[str, Callable] | None = None) -> Any:
        """assignment value, scalar or list/point."""
        if self.kind != "assignment" or not isinstance(self.root, tuple) or _has_coordinate(self.root):
            return None
        try:
            value = self._compiled(0.0, 0.0, variables or {}, functions or {})
        except (ArithmeticError, ValueError, OverflowError, KeyError, TypeError):
            return None
        return None if isinstance(value, complex) else value

    def evaluate_value(self, variables: dict[str, float] | None = None, functions: dict[str, Callable] | None = None) -> Any:
        """value of a non-graph row such as a list or tuple."""
        if self.kind == "point":
            return self.evaluate_point(variables, functions)
        if self.kind == "polygon":
            return self.evaluate_polygon(variables, functions)
        if self.kind in ("parametric", "polar"):
            raise ExpressionError("This row is a graph, not a scalar value")
        return self._compiled(0.0, 0.0, variables or {}, functions or {})

    def evaluate_polar(self, theta: float, variables: dict[str, float] | None = None, functions: dict[str, Callable] | None = None) -> float:
        if self.kind != "polar":
            raise ExpressionError("This row is not polar")
        values = dict(variables or {})
        values["theta"] = theta
        return self.evaluate(0.0, 0.0, values, functions)

    def evaluate_parametric(self, parameter: float, variables: dict[str, float] | None = None, functions: dict[str, Callable] | None = None) -> tuple[float, float]:
        if self.kind != "parametric":
            raise ExpressionError("This row is not parametric")
        values = variables or {}
        return (float(self._compiled[0](parameter, 0.0, {**values, "t": parameter}, functions or {})), float(self._compiled[1](parameter, 0.0, {**values, "t": parameter}, functions or {})))

    def allows(self, x: float, y: float, variables: dict[str, float] | None = None, functions: dict[str, Callable] | None = None) -> bool:
        if self._domain_compiled is None:
            return True
        try:
            return bool(self._domain_compiled(x, y, variables or {}, functions or {}))
        except (ArithmeticError, ValueError, OverflowError, KeyError):
            return False

    def contains_value(self, value: float) -> bool:
        if self.kind != "inequality" or self.operator is None:
            return False
        if self.operator == "<":
            return value < 0
        if self.operator == "<=":
            return value <= 0
        if self.operator == ">":
            return value > 0
        if self.operator == ">=":
            return value >= 0
        return value != 0

    def explicit_inequality_boundary(self) -> tuple[ParsedRelation, str] | None:
        """y=f(x) and the edge to fill toward, when isolatable."""
        if self.kind != "inequality" or self.operator not in ("<", "<=", ">", ">="):
            return None
        root = self.root
        if not isinstance(root, tuple) or len(root) != 4 or root[:2] != ("binary", "-"):
            return None
        left, right = root[2], root[3]
        y_node = ("variable", "y")
        if left == y_node and not _has_symbol(right, "y"):
            fill_edge = "bottom" if self.operator in ("<", "<=") else "top"
            return ParsedRelation("explicit", right, self.source, domain=self.domain), fill_edge
        if right == y_node and not _has_symbol(left, "y"):
            fill_edge = "bottom" if self.operator in (">", ">=") else "top"
            return ParsedRelation("explicit", left, self.source, domain=self.domain), fill_edge
        return None

    def constant_value(self) -> float | None:
        """scalar result for a standalone constant, if defined."""
        if self.kind not in ("explicit", "assignment") or (self.kind == "explicit" and "=" in self.source) or not isinstance(self.root, tuple) or _has_variable(self.root):
            return None
        try:
            return self.evaluate(0.0, 0.0)
        except (ArithmeticError, ValueError, OverflowError, TypeError):
            return None

    def scalar_value(self, variables: dict[str, float] | None = None, functions: dict[str, Callable] | None = None) -> float | None:
        """scalar result when the row has no x or y."""
        if self.kind not in ("explicit", "assignment") or (self.kind == "explicit" and "=" in self.source) or not isinstance(self.root, tuple):
            return None
        if _has_coordinate(self.root):
            return None
        try:
            return self.evaluate(0.0, 0.0, variables, functions)
        except (ArithmeticError, ValueError, OverflowError, KeyError, TypeError):
            return None

    def is_scalar_expression(self) -> bool:
        """whether the row gives one scalar answer."""
        return self.kind in ("explicit", "assignment") and not (self.kind == "explicit" and "=" in self.source) and isinstance(self.root, tuple) and not _has_coordinate(self.root)


def _top_level_split(source: str, separator: str) -> tuple[str, str] | None:
    depth = 0
    for index, character in enumerate(source):
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif character == separator and depth == 0:
            return source[:index], source[index + 1:]
    return None


def _top_level_parts(source: str, separator: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(source):
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif character == separator and depth == 0:
            parts.append(source[start:index].strip())
            start = index + 1
    parts.append(source[start:].strip())
    return parts


def _piecewise_root(source: str, variables: set[str] | frozenset[str], functions: set[str] | frozenset[str]) -> Node | None:
    if not (source.startswith("{") and source.endswith("}")):
        return None
    pieces = []
    for part in _top_level_parts(source[1:-1], ","):
        pair = _top_level_split(part, ":")
        if pair is None:
            raise ExpressionError("Piecewise branches need condition:value")
        condition, value = pair
        pieces.append((
            _Parser(condition, variables, functions).parse(),
            _Parser(value, variables, functions).parse(),
        ))
    if not pieces:
        raise ExpressionError("Piecewise expression is empty")
    return ("piecewise", tuple(pieces))


def _constant_ast_value(root: Node) -> float:
    compiled = _compile_function(root)
    value = compiled(0.0, 0.0, {}, {})
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ExpressionError("Slider values must be finite numbers")
    return float(value)


def _domain_sources(source: str) -> tuple[str, list[str]]:
    """split trailing {condition} groups (stacked AND); piecewise stays put."""
    conditions: list[str] = []
    while source.endswith("}"):
        depth = 0
        opening = None
        for index in range(len(source) - 1, -1, -1):
            if source[index] == "}":
                depth += 1
            elif source[index] == "{":
                depth -= 1
                if depth == 0:
                    opening = index
                    break
        if opening is None:
            break
        condition = source[opening + 1:-1].strip()
        if _top_level_split(condition, ":") is not None:
            break
        conditions.append(condition)
        source = source[:opening].strip()
    conditions.reverse()
    return source, conditions


def _top_level_relation(source: str) -> tuple[str, str, str] | None:
    depth = 0
    operators = ("<=", ">=", "!=", "==", "=", "<", ">")
    index = 0
    while index < len(source):
        character = source[index]
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif depth == 0:
            for operator in operators:
                if source.startswith(operator, index):
                    return source[:index], operator, source[index + len(operator):]
        index += 1
    return None


def _polygon_arguments(source: str) -> str | None:
    """inside of a top-level polygon(...) call, or None."""
    match = re.match(r"(?is)\s*polygon\s*\(", source)
    if match is None:
        return None
    opening = match.end() - 1
    depth = 0
    for index in range(opening, len(source)):
        character = source[index]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return source[opening + 1:index] if not source[index + 1:].strip() else None
    return None


@lru_cache(maxsize=1024)
def _parse_relation_cached(source: str, variables: frozenset[str], functions: frozenset[str]) -> ParsedRelation:
    """parse a graph row of any kind."""
    source = source.strip()
    if not source:
        raise ExpressionError("Enter an expression")
    expression_source, domain_sources = _domain_sources(source)
    parse_variables = set(variables) | {"x", "y", "t", "theta", "ans"}
    domain = None
    for condition in domain_sources:
        node = _Parser(condition, parse_variables, functions).parse()
        domain = node if domain is None else ("and", (domain, node))
    polygon_inside = _polygon_arguments(expression_source)
    if polygon_inside is not None:
        parts = [part for part in _top_level_parts(polygon_inside, ",") if part]
        if not parts:
            raise ExpressionError("polygon() needs at least one point")
        arguments = tuple(_Parser(part, parse_variables, functions).parse() for part in parts)
        return ParsedRelation("polygon", arguments, source, domain=domain)
    if expression_source.startswith("(") and expression_source.endswith(")"):
        inside = expression_source[1:-1]
        pair = _top_level_split(inside, ",")
        if pair is not None:
            first, second = pair
            roots = (
                _Parser(first, parse_variables, functions).parse(),
                _Parser(second, parse_variables, functions).parse(),
            )
            return ParsedRelation("parametric" if any(_has_symbol(root, "t") for root in roots) else "point", roots, source, domain=domain)
    if expression_source.startswith("[") and expression_source.endswith("]"):
        root = _Parser(expression_source, parse_variables, functions).parse()
        return ParsedRelation("list", root, source, domain=domain)
    relation = _top_level_relation(expression_source)
    if relation is None:
        piecewise = _piecewise_root(expression_source, parse_variables, functions)
        root = piecewise if piecewise is not None else _Parser(expression_source, parse_variables, functions).parse()
        kind = "list" if root[0] == "call" and root[1] == "table" else "explicit"
        return ParsedRelation(kind, root, source, domain=domain)
    left, operator, right = relation
    if _top_level_relation(left) is not None or _top_level_relation(right) is not None:
        raise ExpressionError("Use one relation operator per graph row")
    if operator == "==":
        operator = "="
    left, right = left.strip().lower(), right.strip()
    if not left or not right:
        raise ExpressionError("Complete both sides of '='")
    if operator == "=" and left == "r":
        rhs = _Parser(right, parse_variables, functions).parse()
        return ParsedRelation("polar", rhs, source, domain=domain)
    slider = None
    slider_match = SLIDER_RE.search(right) if operator == "=" else None
    if slider_match is not None and not right[:slider_match.start()].strip():
        # bare [a, b, c] is a list, not a slider range
        slider_match = None
    if slider_match:
        right = right[:slider_match.start()].strip()
        try:
            slider = tuple(_constant_ast_value(_Parser(value, parse_variables, functions).parse()) for value in slider_match.groups())
        except (ArithmeticError, ValueError, OverflowError, KeyError, TypeError) as error:
            raise ExpressionError("Slider bounds and step must be finite constants") from error
        if slider[0] >= slider[1] or slider[2] <= 0:
            raise ExpressionError("Slider range must be min < max with a positive step")
    function_match = re.fullmatch(r"([A-Za-z_][A-Za-z_0-9]*)\s*\(([^)]*)\)", left)
    if operator == "=" and function_match:
        function_name = function_match.group(1).lower()
        parameters = tuple(part.strip().lower() for part in function_match.group(2).split(",") if part.strip())
        if not parameters or any(not IDENTIFIER_RE.fullmatch(parameter) for parameter in parameters):
            raise ExpressionError("Function parameters must be names")
        rhs = _Parser(right, parse_variables | set(parameters), functions).parse()
        return ParsedRelation("function", rhs, source, function_name, function_args=parameters)
    piecewise = _piecewise_root(right, parse_variables, functions)
    rhs = piecewise if piecewise is not None else _Parser(right, parse_variables, functions).parse()
    if operator == "=" and left == "y":
        return ParsedRelation("explicit", rhs, source, domain=domain)
    if operator == "=" and IDENTIFIER_RE.fullmatch(left) and left not in ("x", "y"):
        name = left.lower()
        if name in CONSTANTS or name in FUNCTIONS:
            raise ExpressionError(f"Cannot redefine {name!r}")
        return ParsedRelation("assignment", rhs, source, name, domain=domain, slider=slider)
    lhs = _Parser(left, parse_variables, functions).parse()
    if operator == "=":
        return ParsedRelation("implicit", ("binary", "-", lhs, rhs), source, operator=operator, domain=domain)
    return ParsedRelation("inequality", ("binary", "-", lhs, rhs), source, operator=operator, domain=domain)


def parse_relation(source: str, variables: set[str] | frozenset[str] = frozenset(), functions: set[str] | frozenset[str] = frozenset()) -> ParsedRelation:
    """parse and compile a graph row, reusing recent identical inputs."""
    return _parse_relation_cached(source.strip(), frozenset(variables), frozenset(functions))


__all__ = ["ExpressionError", "ParsedRelation", "parse_relation", "__version__"]
