#!/usr/bin/env python3
"""Unit tests for left-associative arithmetic parsing (veri_parser.py).

Regression: `_parse_addition` / `_parse_multiplication` used a
`for op in [...]` loop that consumed each operator at most once. A chain of
three or more terms — `a + b + c`, or a termination measure
`len(x) + len(y) + len(z)` in a DECREASES — failed with
"Unexpected in expression: Token(PLUS, '+')" because the trailing `+ c` was
left unconsumed. The parsers must loop, building an arbitrarily long
left-associative chain.

Run:
    PYTHONPATH=src python3 -m unittest tests.test_parser_arithmetic
"""

import sys
import unittest
from pathlib import Path

_src = Path(__file__).resolve().parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from veri_parser import parse_veri
from backend.dafny import DafnyPrinter
from veri_ast import BinOp, LetDecl


def body_expr(veri: str):
    """The body expression of the first function declaration in `veri`."""
    prog = parse_veri(veri)
    for decl in prog.decls:
        if isinstance(decl, LetDecl) and decl.body is not None:
            return decl.body
    raise AssertionError("no function declaration with a body found")


def fn(ret: str) -> str:
    return (
        "module T\n"
        "def f(a: nat, b: nat, c: nat, d: nat) -> nat:\n"
        f"    return {ret}\n"
    )


class TestAdditionChain(unittest.TestCase):
    def test_three_term_addition_parses(self):
        # Used to raise SyntaxError on the second '+'.
        self.assertIsInstance(body_expr(fn("a + b + c")), BinOp)

    def test_three_term_addition_left_associative(self):
        # (a + b) + c : outer '+', left is the nested (a + b) BinOp.
        expr = body_expr(fn("a + b + c"))
        self.assertEqual(expr.op, "+")
        self.assertIsInstance(expr.left, BinOp)
        self.assertEqual(expr.left.op, "+")

    def test_four_term_addition_parses(self):
        expr = body_expr(fn("a + b + c + d"))
        self.assertEqual(expr.op, "+")

    def test_chained_subtraction(self):
        # `a - b - c` also broke: the for-loop took one PLUS then one MINUS,
        # never a second MINUS.
        expr = body_expr(fn("a - b - c"))
        self.assertEqual(expr.op, "-")
        self.assertIsInstance(expr.left, BinOp)
        self.assertEqual(expr.left.op, "-")


class TestMultiplicationChain(unittest.TestCase):
    def test_three_term_multiplication(self):
        expr = body_expr(fn("a * b * c"))
        self.assertEqual(expr.op, "*")
        self.assertIsInstance(expr.left, BinOp)


class TestDecreasesMeasure(unittest.TestCase):
    """The real-world trigger: a three-difference termination measure, as used
    by `derive`/`saturate_seq` once the state carries names + ips + constraints.
    """

    VERI = (
        "module T\n"
        "def derive(a: nat, b: nat, c: nat) -> Lemma:\n"
        "    ENSURES a == a\n"
        "    DECREASES len(a) + len(b) + len(c)\n"
    )

    def test_three_term_decreases_renders(self):
        # `len(x)` lowers to Dafny cardinality `|x|`; the three terms must all
        # survive as a left-associative `+` chain.
        out = DafnyPrinter().print(parse_veri(self.VERI))
        self.assertIn("decreases |a| + |b| + |c|", out)


if __name__ == "__main__":
    unittest.main()
