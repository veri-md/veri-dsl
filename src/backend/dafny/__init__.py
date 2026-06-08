"""
Dafny verification backend.

Provides:
  - DafnyParser:  parses Dafny .dfy → VeriDslProgram AST
  - DafnyPrinter: emits  VeriDslProgram AST → Dafny .dfy
  - DafnyBackend: combined backend
"""

from typing import FrozenSet, Type

from backend.base import (
    Backend, BackendParser, BackendPrinter,
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

from backend.dafny.parser import parse_dafny as _parse_dafny_raw
from backend.dafny.printer import DafnyPrinter as _RawDafnyPrinter


class DafnyParser(BackendParser):
    """Parse Dafny .dfy source into shared VeriDslProgram AST."""

    def parse(self, text: str) -> 'VeriDslProgram':
        from veri_ast import VeriDslProgram
        return _parse_dafny_raw(text)

    @property
    def supported_declarations(self) -> FrozenSet[Type[Declaration]]:
        return frozenset({
            ModuleDecl, OpenDecl, IncludeDecl,
            TypeAbstract, TypeAlias, TypeRecord, TypeVariant,
            LetDecl, ValDecl,
        })

    @property
    def supported_types(self) -> FrozenSet[Type[TypeExpr]]:
        return frozenset({
            PrimType, TypeVar, NamedType, AppType,
            RefinedType, TupleType, ListType, OptionType, BufferType,
        })

    @property
    def supported_expressions(self) -> FrozenSet[Type[Expr]]:
        return frozenset({
            Var, QualifiedVar, Const,
            App, BinOp, UnaryOp,
            FieldAccess, RecordUpdate, IfExpr,
            Match,
            Forall, Exists, Lambda,
            ArrayIndex, Len,
        })

    @property
    def supported_patterns(self) -> FrozenSet[Type[Pattern]]:
        return frozenset({
            PatWild, PatVar, PatConst, PatApp,
            PatTuple,
        })


class DafnyPrinter(BackendPrinter):
    """Emit VeriDslProgram AST as Dafny .dfy source text."""

    def __init__(self):
        self._printer = _RawDafnyPrinter()

    def print(self, program: 'VeriDslProgram') -> str:
        from veri_ast import VeriDslProgram
        return self._printer.print(program)

    @property
    def supported_declarations(self) -> FrozenSet[Type[Declaration]]:
        return frozenset({
            ModuleDecl, OpenDecl,
            TypeAbstract, TypeAlias, TypeRecord, TypeVariant,
            LetDecl, ValDecl, ImportedDecl, ExternDecl,
            PragmaDecl,
            # TargetDecl — deliberately skipped (Dafny target marker, not emitted as Dafny code)
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
            ArrayIndex, Len,
            Contains, Sel, Live, Modifies,
            BufferGet, BufferLength,
        })

    @property
    def supported_patterns(self) -> FrozenSet[Type[Pattern]]:
        return frozenset({
            PatWild, PatVar, PatConst, PatCons, PatApp,
            PatTuple,
        })


class DafnyBackend(Backend):
    """Dafny verification backend: Dafny .dfy ↔ VeriDslProgram AST."""

    name = "dafny"

    def __init__(self):
        super().__init__(DafnyParser(), DafnyPrinter())
