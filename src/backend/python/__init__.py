"""
Python-assert verification backend.

Decorators go on *real implementation code*, not on generated wrappers.

Provides:
  - ConditionsPrinter:  VeriDslProgram AST → Python _conditions.py (requires/ensures)
  - verify_python_backend: structural AST comparison + import + dry-run
  - verify_implementation: real-source decorator check against Veri DSL spec
  - PythonBackend:       combined backend with parser + printer

The generated _conditions.py is imported by the real code:
    from python_runtime import contract
    from my_spec_conditions import add_element__requires, add_element__ensures

    @contract(requires=add_element__requires, ensures=add_element__ensures)
    def add_element(existing, new_elem):
        ...

Runtime behavior is controlled by CONTRACT_ASSERT_ENABLED:
  - Enabled  (CI / fuzz testing): evaluate requires/ensures, raise on violation
  - Disabled (production): pass-through, zero overhead

Target: TARGET python-assert
"""

from typing import FrozenSet, List, Optional, Tuple, Type
from pathlib import Path

from backend.base import (
    Backend, BackendParser, BackendPrinter,
    ModuleDecl, OpenDecl, IncludeDecl, FriendDecl,
    TypeAbstract, TypeAlias, TypeRecord, TypeVariant,
    LetDecl, ValDecl, TargetDecl, ImportedDecl, ExternDecl, PragmaDecl,
    Declaration,
    PrimType, TypeVar, NamedType, AppType,
    RefinedType, ArrowType, TupleType, ListType, OptionType, BufferType,
    TypeExpr,
    Var, QualifiedVar, Const,
    App, BinOp, UnaryOp,
    FieldAccess, RecordUpdate, IfExpr,
    Match,
    Forall, Exists, Lambda,
    ArrayIndex, ArrayLen, Len,
    Contains, Sel, Live, Modifies,
    BufferGet, BufferLength,
    Expr,
    PatWild, PatVar, PatConst, PatCons, PatApp,
    PatTuple, PatRecord, PatOr,
    Pattern,
)
from veri_ast import VeriDslProgram

from backend.python.conditions import ConditionsPrinter
from backend.python.verify import (
    verify_python_backend,
    verify_implementation,
    VerificationResult,
)


class PythonParser(BackendParser):
    """Python parser stub — Python roundtrip not yet implemented.

    The Python backend is one-way: Veri DSL → Python _conditions.py.
    Parsing Python back to Veri DSL is optional (F*/Dafny backends need it
    for conversion; Python just generates condition functions).
    """

    def parse(self, text: str) -> VeriDslProgram:
        raise NotImplementedError(
            "Python→Veri DSL parsing not implemented for the python-assert backend. "
            "This backend generates Python condition functions from Veri DSL specs."
        )

    @property
    def supported_declarations(self) -> FrozenSet[Type[Declaration]]:
        return frozenset()

    @property
    def supported_types(self) -> FrozenSet[Type[TypeExpr]]:
        return frozenset()

    @property
    def supported_expressions(self) -> FrozenSet[Type[Expr]]:
        return frozenset()

    @property
    def supported_patterns(self) -> FrozenSet[Type[Pattern]]:
        return frozenset()


class PythonPrinterBackend(BackendPrinter):
    """Emit VeriDslProgram AST as Python _conditions.py module.

    Decorators go on real code; this printer only generates the
    condition predicate functions (_conditions.py). The library
    author applies @contract manually:
        from python_runtime import contract
        from my_conditions import fn__requires, fn__ensures

        @contract(requires=fn__requires, ensures=fn__ensures)
        def fn(...):
            ...
    """

    def __init__(self):
        self._conditions = ConditionsPrinter()

    def print(self, program: VeriDslProgram) -> str:
        """Print a guide/docstring (no wrapper generation needed)."""
        module_name = self._module_name(program)
        return (
            f'"""Veri DSL spec: {module_name}\n'
            f'Target: python-assert\n\n'
            f'Decorators go on real implementation code. Generated conditions\n'
            f'are in {module_name}_conditions.py. Apply @contract in your code:\n\n'
            f'    from python_runtime import contract\n'
            f'    from {module_name}_conditions import <fn>__requires, <fn>__ensures\n\n'
            f'    @contract(requires=<fn>__requires, ensures=<fn>__ensures)\n'
            f'    def <fn>(...):\n'
            f'        ...\n'
            f'"""'
        )

    def print_conditions(self, program: VeriDslProgram) -> str:
        """Print the conditions module."""
        module_name = self._module_name(program)
        return self._conditions.emit(program, module_name=module_name)

    def _module_name(self, program: VeriDslProgram) -> str:
        if program.module and program.module.name.parts:
            return program.module.name.parts[-1]
        return "generated"

    def emit_both(self, program: VeriDslProgram) -> Tuple[str, str]:
        """Return (guide.py, _conditions.py) as a pair."""
        return self.print(program), self.print_conditions(program)

    @property
    def supported_declarations(self) -> FrozenSet[Type[Declaration]]:
        return frozenset({
            ModuleDecl, OpenDecl, IncludeDecl, FriendDecl,
            TypeAbstract, TypeAlias, TypeRecord, TypeVariant,
            LetDecl, ValDecl, ImportedDecl, ExternDecl,
            PragmaDecl,
        })

    @property
    def supported_types(self) -> FrozenSet[Type[TypeExpr]]:
        return frozenset({
            PrimType, TypeVar, NamedType, AppType,
            RefinedType, ArrowType, TupleType, ListType, OptionType, BufferType,
        })

    @property
    def supported_expressions(self) -> FrozenSet[Type[Expr]]:
        return frozenset({
            Var, QualifiedVar, Const,
            App, BinOp, UnaryOp,
            FieldAccess, RecordUpdate, IfExpr,
            Match,
            Forall, Exists, Lambda,
            Len, ArrayIndex,
        })

    @property
    def supported_patterns(self) -> FrozenSet[Type[Pattern]]:
        return frozenset({
            PatWild, PatVar, PatConst, PatApp,
            PatCons, PatTuple,
        })


class PythonBackend(Backend):
    """Python-assert backend: Veri DSL → Python _conditions.py + verification.

    No wrapper generation. The user puts @contract on their real code
    and imports the generated condition functions.

    Verification:
      - Structural AST comparison: Veri DSL contracts ↔ Python conditions
      - Real-source decorator check: verify @contract refs match Veri DSL spec
      - Import check: can the generated conditions be loaded?
      - Dry-run: CONTRACT_DRY_RUN evaluates conditions without calling functions
    """

    name = "python"

    def __init__(self):
        super().__init__(PythonParser(), PythonPrinterBackend())

    def emit_module(self, program: VeriDslProgram) -> str:
        """Generate a guide (not a wrapper)."""
        return self.printer.print(program)

    def emit_conditions(self, program: VeriDslProgram) -> str:
        """Generate the conditions module."""
        return self.printer.print_conditions(program)

    def verify(
        self,
        program: VeriDslProgram,
        py_path: Path,
        conditions_path: Path,
    ) -> VerificationResult:
        """Run verification on generated output (conditions + AST)."""
        return verify_python_backend(program, py_path, conditions_path)

    def verify_implementation(
        self,
        program: VeriDslProgram,
        real_source_path: Path,
        conditions_path: Optional[Path] = None,
    ) -> VerificationResult:
        """Verify real Python code has correct @contract decorators.

        Args:
            program: Parsed Veri DSL spec AST
            real_source_path: Path to the real Python implementation
            conditions_path: Optional path to _conditions.py for cross-ref
        """
        return verify_implementation(program, real_source_path, conditions_path)
