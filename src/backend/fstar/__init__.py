"""
F* verification backend.

Provides:
  - FStarParser:  parses F* .fsti → VeriDslProgram AST
  - FStarPrinter: emits  VeriDslProgram AST → F* .fsti
  - FStarBackend: combined backend
"""

from typing import FrozenSet, Type

from backend.base import (
    Backend, BackendParser, BackendPrinter,
    _ALL_DECLARATION_TYPES, _ALL_TYPE_TYPES, _ALL_EXPR_TYPES, _ALL_PATTERN_TYPES,
    # AST types
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

# Re-use the existing implementations
from backend.fstar.parser import parse_fstar as _parse_fstar_raw
from backend.fstar.parser import FStarParser as _RawFStarParser
from backend.fstar.printer import FStarPrinter as _RawFStarPrinter


class FStarParser(BackendParser):
    """Parse F* .fsti source into shared VeriDslProgram AST."""

    def parse(self, text: str) -> 'VeriDslProgram':
        from veri_ast import VeriDslProgram
        return _parse_fstar_raw(text)

    @property
    def supported_declarations(self) -> FrozenSet[Type[Declaration]]:
        return frozenset({
            ModuleDecl, OpenDecl, IncludeDecl, FriendDecl,
            TypeAbstract, TypeAlias, TypeRecord, TypeVariant,
            LetDecl, ValDecl,
            # PragmaDecl, TargetDecl — not in F* but produced by parser
        })

    @property
    def supported_types(self) -> FrozenSet[Type[TypeExpr]]:
        return frozenset({
            PrimType, TypeVar, NamedType, AppType,
            RefinedType, ArrowType, TupleType,
        })

    @property
    def supported_expressions(self) -> FrozenSet[Type[Expr]]:
        return frozenset({
            Var, QualifiedVar, Const,
            App, BinOp, UnaryOp,
            FieldAccess, RecordUpdate, IfExpr,
            Match,
            Forall, Exists, Lambda,
            ArrayIndex,
        })

    @property
    def supported_patterns(self) -> FrozenSet[Type[Pattern]]:
        return frozenset({
            PatWild, PatVar, PatConst, PatCons, PatApp,
            PatTuple, PatOr, PatRecord,
        })


class FStarPrinter(BackendPrinter):
    """Emit VeriDslProgram AST as F* .fsti source text."""

    def __init__(self):
        self._printer = _RawFStarPrinter()

    def print(self, program: 'VeriDslProgram') -> str:
        from veri_ast import VeriDslProgram
        return self._printer.print(program)

    @property
    def supported_declarations(self) -> FrozenSet[Type[Declaration]]:
        return frozenset({
            ModuleDecl, OpenDecl, IncludeDecl, FriendDecl,
            TypeAbstract, TypeAlias, TypeRecord, TypeVariant,
            LetDecl, ValDecl, ImportedDecl, ExternDecl,
            # TargetDecl — deliberately skipped (F* target marker, not emitted as F* code)
            # PragmaDecl — skipped
        })

    @property
    def supported_types(self) -> FrozenSet[Type[TypeExpr]]:
        return frozenset({
            PrimType, TypeVar, NamedType, AppType,
            RefinedType, ArrowType, TupleType,
        })

    @property
    def supported_expressions(self) -> FrozenSet[Type[Expr]]:
        return frozenset({
            Var, QualifiedVar, Const,
            App, BinOp, UnaryOp,
            FieldAccess, RecordUpdate, IfExpr,
            Match,
            Forall, Exists, Lambda,
            ArrayIndex, ArrayLen, Len,
        })

    @property
    def supported_patterns(self) -> FrozenSet[Type[Pattern]]:
        return frozenset({
            PatWild, PatVar, PatConst, PatCons, PatApp,
            PatTuple, PatOr,
        })


class FStarBackend(Backend):
    """F* verification backend: F* .fsti ↔ VeriDslProgram AST."""

    name = "fstar"

    def __init__(self):
        super().__init__(FStarParser(), FStarPrinter())
