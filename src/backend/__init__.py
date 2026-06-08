"""
Backend abstraction layer for Veri DSL DSL.

Each verification backend (F*, Dafny) provides:
  - A Parser:  target-language text → VeriDslProgram AST
  - A Printer: VeriDslProgram AST → target-language text

Backends register the AST node types they support, enabling
automatic completeness checking between backends.
"""

from backend.base import Backend, BackendParser, BackendPrinter
from backend.fstar import FStarBackend
from backend.dafny import DafnyBackend
from backend.python import PythonBackend
from backend.completeness import CompletenessChecker, check_all_backends

__all__ = [
    "Backend", "BackendParser", "BackendPrinter",
    "FStarBackend", "DafnyBackend", "PythonBackend",
    "CompletenessChecker", "check_all_backends",
]
