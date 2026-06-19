#!/usr/bin/env python3
"""Unit tests for the Dafny printer (backend/dafny/printer.py).

Run:
    PYTHONPATH=src python3 -m unittest tests.test_dafny_printer
"""

import sys
import unittest
from pathlib import Path

_src = Path(__file__).resolve().parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from veri_parser import parse_veri
from backend.dafny import DafnyPrinter


def dafny(veri: str) -> str:
    return DafnyPrinter().print(parse_veri(veri))


class TestLemmaPrint(unittest.TestCase):
    """`def f(...) -> Lemma:` is the DSL surface for a proof obligation. It must
    emit a Dafny `lemma` (proposition in `ensures`, proof in the body), NOT a
    `function f(...): Lemma` (which treats `Lemma` as a return type and is invalid
    Dafny). A bodyless lemma is an assumed axiom — the proof body is filled in
    later via the `#TODO` / agent-fill path.
    """

    BASE = (
        "module Test\n"
        "def add_comm(a: int, b: int) -> Lemma:\n"
        "    REQUIRES a >= 0\n"
        "    ENSURES a + b == b + a\n"
    )

    def test_emits_lemma_keyword(self):
        out = dafny(self.BASE)
        self.assertIn("lemma add_comm(a: int, b: int)", out)

    def test_not_a_function_returning_lemma(self):
        """Regression: `-> Lemma` used to emit `function ...: Lemma`."""
        out = dafny(self.BASE)
        self.assertNotIn("function add_comm", out)
        self.assertNotIn(": Lemma", out)

    def test_contract_clauses_emitted(self):
        out = dafny(self.BASE)
        self.assertIn("requires a >= 0", out)
        self.assertIn("ensures a + b == b + a", out)

    def test_bodyless_lemma_has_no_body_block(self):
        """A lemma with no source body emits no `{ ... }` (assumed axiom)."""
        out = dafny(self.BASE)
        tail = out.split("ensures a + b == b + a", 1)[1]
        self.assertNotIn("{", tail)  # nothing opens a proof body after the ensures

    def test_decreases_emitted(self):
        veri = (
            "module Test\n"
            "def shrink(n: nat) -> Lemma:\n"
            "    REQUIRES n >= 0\n"
            "    ENSURES n + 0 == n\n"
            "    DECREASES n\n"
        )
        out = dafny(veri)
        self.assertIn("lemma shrink(", out)
        self.assertIn("decreases n", out)


if __name__ == "__main__":
    unittest.main()
