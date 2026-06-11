"""
Veri DSL AST — Common representation for F* .fsti and Veri DSL .veri files.

This AST captures the subset of F* that appears in .veri.md contract files:
  - Module declarations, opens/imports
  - Type definitions (abstract, alias, record, variant)
  - Let definitions (constants, predicates)
  - Val declarations with pre/post conditions
  - Expressions (as nested trees)
"""

from dataclasses import dataclass, field
from typing import List, Optional, Union


# ── Identifiers ──────────────────────────────────────────────────────────────

@dataclass
class Ident:
    name: str

    def __str__(self): return self.name

@dataclass
class QualifiedIdent:
    parts: List[str]

    def __str__(self): return '.'.join(self.parts)

    @property
    def head(self) -> str: return self.parts[0] if self.parts else ''

# ── Types ────────────────────────────────────────────────────────────────────

@dataclass
class TypeVar:
    name: str
    kind: Optional['Term'] = None   # e.g. Type, eqtype

@dataclass
class PrimType:
    name: str                        # int, nat, bool, string, float, Type, Type0, unit

@dataclass
class NamedType:
    path: QualifiedIdent             # qualified type name

@dataclass
class AppType:
    func: 'TypeExpr'
    args: List['TypeExpr']

@dataclass
class RefinedType:
    binder: 'Binder'
    predicate: 'Term'

@dataclass
class ArrowType:
    params: List['Binder']
    result: 'TypeExpr'
    effect: Optional[str] = None     # Tot, Pure, ST, GTot, Lemma

@dataclass
class TupleType:
    items: List['TypeExpr']

@dataclass
class ListType:
    elem: 'TypeExpr'

@dataclass
class OptionType:
    elem: 'TypeExpr'

@dataclass
class BufferType:
    elem: 'TypeExpr'

TypeExpr = Union[PrimType, NamedType, AppType, RefinedType, ArrowType,
                 TupleType, ListType, OptionType, BufferType, TypeVar]


# ── Bindings / Parameters ───────────────────────────────────────────────────

@dataclass
class Binder:
    name: Optional[str]              # None = anonymous/wild
    typ: TypeExpr
    implicit: bool = False
    direction: Optional[str] = None  # IN, OUT, IN OUT (DSL-only)
    refinement: Optional['Term'] = None  # for inline refinements like x:t{p}

@dataclass
class Param:
    name: str
    typ: TypeExpr
    direction: Optional[str] = None


# ── Expressions ──────────────────────────────────────────────────────────────

@dataclass
class Var:
    name: str

@dataclass
class QualifiedVar:
    path: QualifiedIdent

@dataclass
class Const:
    value: Union[bool, int, float, str, None]  # None = unit

@dataclass
class App:
    func: 'Expr'
    args: List['Expr']

@dataclass
class BinOp:
    op: str         # and, or, ==>, =, <, >, <=, >=, +, -, *, /, %, ==, !=
    left: 'Expr'
    right: 'Expr'

@dataclass
class UnaryOp:
    op: str         # not, -
    expr: 'Expr'

@dataclass
class FieldAccess:
    expr: 'Expr'
    field: str

@dataclass
class RecordUpdate:
    expr: 'Expr'
    updates: List[tuple[str, 'Expr']]   # (field_name, value)

@dataclass
class IfExpr:
    cond: 'Expr'
    then_expr: 'Expr'
    else_expr: 'Expr'

@dataclass
class MatchCase:
    pattern: 'Pattern'
    expr: 'Expr'

@dataclass
class Match:
    expr: 'Expr'
    cases: List[MatchCase]

@dataclass
class Forall:
    binders: List[Binder]
    body: 'Expr'

@dataclass
class Exists:
    binders: List[Binder]
    body: 'Expr'

@dataclass
class Lambda:
    params: List[str]
    body: 'Expr'

@dataclass
class ArrayIndex:
    arr: 'Expr'
    index: 'Expr'

@dataclass
class ArrayLen:
    arr: 'Expr'

@dataclass
class Len:
    expr: 'Expr'

@dataclass
class Contains:
    heap: 'Expr'
    ref: 'Expr'

@dataclass
class Sel:
    heap: 'Expr'
    ref: 'Expr'

@dataclass
class Live:
    heap: 'Expr'
    buffer: 'Expr'

@dataclass
class Modifies:
    locs: 'Expr'
    h0: 'Expr'
    h1: 'Expr'

@dataclass
class BufferGet:
    heap: 'Expr'
    buf: 'Expr'
    index: 'Expr'

@dataclass
class BufferLength:
    expr: 'Expr'

Expr = Union[Var, QualifiedVar, Const, App, BinOp, UnaryOp, FieldAccess,
             RecordUpdate, IfExpr, Match, Forall, Exists, Lambda,
             ArrayIndex, ArrayLen, Len, Contains, Sel, Live, Modifies,
             BufferGet, BufferLength]


# ── Patterns ─────────────────────────────────────────────────────────────────

@dataclass
class PatWild:
    pass

@dataclass
class PatVar:
    name: str

@dataclass
class PatConst:
    value: Union[bool, int, float, str, None]

@dataclass
class PatCons:
    head: 'Pattern'
    tail: 'Pattern'

@dataclass
class PatApp:
    name: str
    args: List['Pattern']

@dataclass
class PatTuple:
    items: List['Pattern']

@dataclass
class PatRecord:
    fields: List[tuple[str, 'Pattern']]

@dataclass
class PatOr:
    patterns: List['Pattern']

Pattern = Union[PatWild, PatVar, PatConst, PatCons, PatApp,
                PatTuple, PatRecord, PatOr]


# ── Effects and Conditions ────────────────────────────────────────────────────

@dataclass
class PrePost:
    requires: Optional[Expr] = None
    ensures: Optional[Expr] = None
    decreases: Optional[Expr] = None
    smt_pats: List[List[Expr]] = field(default_factory=list)


# ── Declarations ──────────────────────────────────────────────────────────────

@dataclass
class ModuleDecl:
    name: QualifiedIdent

@dataclass
class OpenDecl:
    path: QualifiedIdent
    restriction: Optional[List[str]] = None

@dataclass
class IncludeDecl:
    path: QualifiedIdent

@dataclass
class FriendDecl:
    path: QualifiedIdent

@dataclass
class TypeAbstract:
    name: str
    params: List[TypeVar] = field(default_factory=list)
    kind: Optional['Expr'] = None        # eqtype, Type, etc.

@dataclass
class TypeAlias:
    name: str
    params: List[TypeVar] = field(default_factory=list)
    typ: TypeExpr = None

@dataclass
class TypeRecord:
    name: str
    params: List[TypeVar] = field(default_factory=list)
    fields: List[Binder] = field(default_factory=list)

@dataclass
class TypeVariant:
    name: str
    params: List[TypeVar] = field(default_factory=list)
    constructors: List['Constructor'] = field(default_factory=list)

@dataclass
class Constructor:
    name: str
    args: List[Binder] = field(default_factory=list)
    typ: Optional[TypeExpr] = None

@dataclass
class LetDecl:
    name: str
    params: List[Binder] = field(default_factory=list)
    typ: Optional[TypeExpr] = None
    body: Optional[Expr] = None
    recursive: bool = False
    qualifiers: List[str] = field(default_factory=list)

@dataclass
class ValDecl:
    name: str
    params: List[Binder] = field(default_factory=list)
    return_type: Optional[TypeExpr] = None
    effect: str = 'Tot'
    contract: PrePost = field(default_factory=PrePost)
    body: Optional[Expr] = None       # optional implementation body (for functions with contracts + code)
    qualifiers: List[str] = field(default_factory=list)
    smt_pats: List[List[Expr]] = field(default_factory=list)

@dataclass
class FStarOpaqueDecl:
    """Opaque F* declaration that couldn't be parsed as FCL.
    
    Preserved verbatim for round-trip printing.
    Used as fallback for F* syntax (record types, etc.)
    that FCL parser doesn't support.
    """
    text: str

@dataclass
class TargetDecl:
    """Target language declaration for a .veri.md file."""
    target: str  # 'f-star-c', 'dafny-rust'

@dataclass
class ImportedDecl:
    """A function imported from another Veri DSL module."""
    name: str
    params: List[Binder] = field(default_factory=list)
    return_type: Optional[TypeExpr] = None
    contract: 'PrePost' = field(default_factory=lambda: PrePost())
    module_path: Optional[str] = None

@dataclass
class ExternDecl:
    """External (C/Dafny) function declaration with a contract."""
    name: str
    params: List[Binder] = field(default_factory=list)
    return_type: Optional[TypeExpr] = None
    contract: 'PrePost' = field(default_factory=lambda: PrePost())
    extern_lang: Optional[str] = None  # 'C', 'Rust'

@dataclass
class PragmaDecl:
    text: str

Declaration = Union[ModuleDecl, OpenDecl, IncludeDecl, FriendDecl,
                    TypeAbstract, TypeAlias, TypeRecord, TypeVariant,
                    LetDecl, ValDecl, FStarOpaqueDecl, TargetDecl,
                    ImportedDecl, ExternDecl, PragmaDecl]

Term = Expr  # Aliased for readability


# ── Top-level ─────────────────────────────────────────────────────────────────

@dataclass
class VeriDslProgram:
    module: Optional[ModuleDecl] = None
    decls: List[Declaration] = field(default_factory=list)

    def add(self, decl: Declaration):
        self.decls.append(decl)
