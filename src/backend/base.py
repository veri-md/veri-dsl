"""
Abstract base classes for verification backends.

Each backend must implement:
  - BackendParser.parse(text)  → VeriDslProgram
  - BackendPrinter.print(prog) → str

And declare which AST node types it supports for completeness checking.
"""

from abc import ABC, abstractmethod
from typing import FrozenSet, Type

from veri_ast import (
    VeriDslProgram,
    # Declarations
    ModuleDecl, OpenDecl, IncludeDecl, FriendDecl,
    TypeAbstract, TypeAlias, TypeRecord, TypeVariant,
    LetDecl, ValDecl, TargetDecl, ImportedDecl, ExternDecl, PragmaDecl,
    Declaration,
    # Type expressions
    PrimType, TypeVar, NamedType, AppType,
    RefinedType, ArrowType, TupleType, ListType, OptionType, BufferType,
    TypeExpr,
    # Expressions
    Var, QualifiedVar, Const,
    App, BinOp, UnaryOp,
    FieldAccess, RecordUpdate, IfExpr,
    Match,
    Forall, Exists, Lambda,
    ArrayIndex, ArrayLen, Len,
    Contains, Sel, Live, Modifies,
    BufferGet, BufferLength,
    Expr,
    # Patterns
    PatWild, PatVar, PatConst, PatCons, PatApp,
    PatTuple, PatRecord, PatOr,
    Pattern,
)


# ── Catalog of all known AST node types ────────────────────────────────────

_ALL_DECLARATION_TYPES: FrozenSet[Type[Declaration]] = frozenset({
    ModuleDecl, OpenDecl, IncludeDecl, FriendDecl,
    TypeAbstract, TypeAlias, TypeRecord, TypeVariant,
    LetDecl, ValDecl, TargetDecl, ImportedDecl, ExternDecl, PragmaDecl,
})

_ALL_TYPE_TYPES: FrozenSet[Type[TypeExpr]] = frozenset({
    PrimType, TypeVar, NamedType, AppType,
    RefinedType, ArrowType, TupleType, ListType, OptionType, BufferType,
})

_ALL_EXPR_TYPES: FrozenSet[Type[Expr]] = frozenset({
    Var, QualifiedVar, Const,
    App, BinOp, UnaryOp,
    FieldAccess, RecordUpdate, IfExpr,
    Match,
    Forall, Exists, Lambda,
    ArrayIndex, ArrayLen, Len,
    Contains, Sel, Live, Modifies,
    BufferGet, BufferLength,
})

_ALL_PATTERN_TYPES: FrozenSet[Type[Pattern]] = frozenset({
    PatWild, PatVar, PatConst, PatCons, PatApp,
    PatTuple, PatRecord, PatOr,
})


# ── Veri DSL keywords catalog ───────────────────────────────────────────────────

_ALL_KEYWORDS: FrozenSet[str] = frozenset({
    # Declarations
    'module', 'import', 'class', 'enum', 'variant',
    'type', 'def', 'CONSTRAINT', 'TARGET', 'EXTERN',
    # Contracts
    'REQUIRES', 'ENSURES', 'DECREASES', 'WHERE',
    # Expressions
    'FORALL', 'EXISTS', 'IN', 'match', 'case',
    'lambda', 'if', 'else', 'True', 'False', 'None', 'Some',
    'and', 'or', 'not', 'len', 'array_len',
    'STATE_READ_ONLY', 'STATE_WRITE_ONLY', 'STATE_READ_WRITE',
    'PURE', 'GHOST', 'LEMMA',
    'SMTPat',
})


# ── Base classes ────────────────────────────────────────────────────────────

class BackendParser(ABC):
    """Parse target-language text into an VeriDslProgram AST."""

    @abstractmethod
    def parse(self, text: str) -> VeriDslProgram:
        """Parse text in the backend's target language into the shared AST."""
        ...

    @property
    @abstractmethod
    def supported_declarations(self) -> FrozenSet[Type[Declaration]]:
        """Declaration AST node types this parser can produce."""
        ...

    @property
    @abstractmethod
    def supported_types(self) -> FrozenSet[Type[TypeExpr]]:
        """Type AST node types this parser can produce."""
        ...

    @property
    @abstractmethod
    def supported_expressions(self) -> FrozenSet[Type[Expr]]:
        """Expression AST node types this parser can produce."""
        ...

    @property
    @abstractmethod
    def supported_patterns(self) -> FrozenSet[Type[Pattern]]:
        """Pattern AST node types this parser can produce."""
        ...


class BackendPrinter(ABC):
    """Print an VeriDslProgram AST into target-language text."""

    @abstractmethod
    def print(self, program: VeriDslProgram) -> str:
        """Render a shared AST into target-language source text."""
        ...

    @property
    @abstractmethod
    def supported_declarations(self) -> FrozenSet[Type[Declaration]]:
        """Declaration AST node types this printer can emit."""
        ...

    @property
    @abstractmethod
    def supported_types(self) -> FrozenSet[Type[TypeExpr]]:
        """Type AST node types this printer can emit."""
        ...

    @property
    @abstractmethod
    def supported_expressions(self) -> FrozenSet[Type[Expr]]:
        """Expression AST node types this printer can emit."""
        ...

    @property
    @abstractmethod
    def supported_patterns(self) -> FrozenSet[Type[Pattern]]:
        """Pattern AST node types this printer can emit."""
        ...


class Backend(ABC):
    """A complete verification backend = parser + printer."""

    name: str

    def __init__(self, parser: BackendParser, printer: BackendPrinter):
        self.parser = parser
        self.printer = printer

    def parse(self, text: str) -> VeriDslProgram:
        return self.parser.parse(text)

    def emit(self, program: VeriDslProgram) -> str:
        return self.printer.print(program)

    @property
    def supported_declarations(self) -> FrozenSet[Type[Declaration]]:
        return self.printer.supported_declarations | self.parser.supported_declarations

    @property
    def supported_types(self) -> FrozenSet[Type[TypeExpr]]:
        return self.printer.supported_types | self.parser.supported_types

    @property
    def supported_expressions(self) -> FrozenSet[Type[Expr]]:
        return self.printer.supported_expressions | self.parser.supported_expressions

    @property
    def supported_patterns(self) -> FrozenSet[Type[Pattern]]:
        return self.printer.supported_patterns | self.parser.supported_patterns
