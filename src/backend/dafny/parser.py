"""
dafny_parser.py — Recursive-descent parser for Dafny syntax into VeriDslProgram AST.

Maps Dafny constructs to the shared Veri DSL AST (from veri_ast.py).
Supports the Dafny subset we generate from dafny_printer.py.

Covers:
  - function / function method / method / predicate
  - datatype / class / newtype / type
  - requires / ensures / decreases / modifies / reads
  - forall / exists
  - match / case
  - if / then / else
  - Dafny types: nat, int, bool, string, seq<T>, set<T>, map<T,U>, Option<T>
"""

import re
from typing import List, Optional, Tuple, Union
from veri_ast import *


# ── Tokenizer ────────────────────────────────────────────────────────────────

class Token:
    def __init__(self, kind: str, value: str, pos: int):
        self.kind = kind
        self.value = value
        self.pos = pos

    def __repr__(self):
        return f'Token({self.kind}, {self.value!r})'


TOKEN_SPEC = [
    ('COMMENT_LINE',  r'//[^\n]*'),
    ('COMMENT_BLOCK', r'/\*.*?\*/'),
    ('INT',           r'\d+'),
    ('FLOAT',         r'\d+\.\d+([eE][+-]?\d+)?'),
    ('STRING',        r'"[^"]*"'),
    ('KEYWORD',       r'\b(module|import|datatype|class|newtype|type|'
                      r'function|method|predicate|constructor|static|ghost|'
                      r'requires|ensures|decreases|modifies|reads|'
                      r'forall|exists|match|case|if|then|else|'
                      r'returns|return|var|const|let|new|this|'
                      r'True|False|None|Some|null|'
                      r'nat|int|bool|string|char|real|'
                      r'seq|set|multiset|map|Option|'
                      r'assert|assume|calc|print|'
                      r'reads_changes_only|include|opened|abstract|'
                      r'extends|trait|inductive|coinductive)\b'),
    ('VAR',           r'[a-zA-Z_][a-zA-Z0-9_]*'),
    ('QUANTIFIER',    r'::'),
    ('ARROW',         r'=>'),
    ('PIPE',          r'\|'),
    ('COLON',         r':'),
    ('SEMICOLON',     r';'),
    ('COMMA',         r','),
    ('DOT',           r'\.'),
    ('LPAREN',        r'\('),
    ('RPAREN',        r'\)'),
    ('LBRACKET',      r'\['),
    ('RBRACKET',      r'\]'),
    ('LBRACE',        r'\{'),
    ('RBRACE',        r'\}'),
    ('EQUALS',        r'=='),
    ('NEQ',           r'!='),
    ('LE',            r'<='),
    ('GE',            r'>='),
    ('LT',            r'<'),
    ('GT',            r'>'),
    ('ASSIGN',        r'='),
    ('PLUS',          r'\+'),
    ('MINUS',         r'-'),
    ('STAR',          r'\*'),
    ('SLASH',         r'/'),
    ('PERCENT',       r'%'),
    ('BANG',          r'!'),
    ('AMPERSAND',     r'&'),
    ('HAT',           r'\^'),
    ('UNDERSCORE',    r'_'),
    ('WS',            r'\s+'),
]

TOKEN_RE = re.compile(
    '|'.join(f'(?P<{name}>{pattern})' for name, pattern in TOKEN_SPEC),
    re.DOTALL
)


class DafnyTokenizer:
    def __init__(self, text: str):
        self.text = self._preprocess(text)
        self.pos = 0
        self.tokens: List[Token] = []
        self._tokenize()

    @staticmethod
    def _preprocess(text: str) -> str:
        """Strip #TODO, #FIXME markers (from Veri DSL interop)."""
        lines = text.split('\n')
        cleaned = []
        for line in lines:
            line = re.sub(r'\s*#TODO.*$', '', line)
            cleaned.append(line)
        return '\n'.join(cleaned)

    def _tokenize(self):
        for m in TOKEN_RE.finditer(self.text):
            kind = m.lastgroup
            val = m.group()
            if kind == 'WS' or kind.startswith('COMMENT'):
                continue
            if kind == 'KEYWORD' and val in ('True', 'False', 'None', 'null'):
                if val == 'True':
                    kind, val = 'BOOL', 'true'
                elif val == 'False':
                    kind, val = 'BOOL', 'false'
                elif val == 'None' or val == 'null':
                    kind = 'NONE'
            self.tokens.append(Token(kind, val, m.start()))
        self.tokens.append(Token('EOF', '', len(self.text)))

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def next(self) -> Token:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect(self, kind: str, value: Optional[str] = None):
        t = self.next()
        if t.kind != kind or (value is not None and t.value != value):
            raise SyntaxError(f'Expected {kind}({value}) at pos {t.pos}, got {t}')
        return t

    def skip(self, kind: str, value: Optional[str] = None) -> bool:
        if self.peek().kind == kind and (value is None or self.peek().value == value):
            self.next()
            return True
        return False

    def maybe(self, kind: str, value: Optional[str] = None) -> Optional[Token]:
        if self.peek().kind == kind and (value is None or self.peek().value == value):
            return self.next()
        return None


# ── Parser ──────────────────────────────────────────────────────────────────

class DafnyParser:
    """Parse Dafny syntax text into VeriDslProgram AST."""

    def __init__(self, text: str):
        self.tok = DafnyTokenizer(text)
        self.program = VeriDslProgram()

    def parse(self) -> VeriDslProgram:
        while self.tok.peek().kind != 'EOF':
            decl = self._parse_decl()
            if decl is not None:
                self.program.add(decl)
        return self.program

    # ── Declaration dispatch ───────────────────────────────────────────────

    def _parse_decl(self) -> Optional[Declaration]:
        t = self.tok.peek()
        if t.kind != 'KEYWORD':
            self.tok.next()
            return None

        kw = t.value

        if kw == 'module':
            return self._parse_module()
        elif kw == 'import':
            return self._parse_import()
        elif kw == 'include':
            return self._parse_include()
        elif kw == 'datatype':
            return self._parse_datatype()
        elif kw == 'class':
            return self._parse_class()
        elif kw == 'newtype':
            return self._parse_newtype()
        elif kw == 'type':
            return self._parse_type_alias()
        elif kw == 'function':
            return self._parse_function()
        elif kw == 'method':
            return self._parse_method()
        elif kw == 'predicate':
            return self._parse_predicate()
        elif kw == 'const':
            return self._parse_const()
        elif kw in ('static', 'ghost', 'abstract', 'opened'):
            self.tok.next()  # consume qualifier
            return self._parse_decl()
        else:
            # Skip unrecognized keywords
            self.tok.next()
            return None

    # ── Module ──────────────────────────────────────────────────────────────

    def _parse_module(self) -> ModuleDecl:
        self.tok.expect('KEYWORD', 'module')
        name = self._parse_qident()
        return ModuleDecl(name=name)

    # ── Imports ─────────────────────────────────────────────────────────────

    def _parse_import(self) -> OpenDecl:
        self.tok.expect('KEYWORD', 'import')
        self.tok.skip('KEYWORD', 'opened')  # optional
        path = self._parse_qident()
        return OpenDecl(path=path)

    def _parse_include(self) -> IncludeDecl:
        self.tok.expect('KEYWORD', 'include')
        path_str = self.tok.expect('STRING').value.strip('"')
        parts = path_str.split('.')
        return IncludeDecl(path=QualifiedIdent(parts))

    # ── Qualified identifier ────────────────────────────────────────────────

    def _parse_qident(self) -> QualifiedIdent:
        t = self.tok.next()
        parts = [t.value]
        while self.tok.peek().kind == 'DOT':
            self.tok.next()
            parts.append(self.tok.next().value)
        return QualifiedIdent(parts)

    # ── Datatype (→ TypeVariant or TypeRecord) ──────────────────────────────

    def _parse_datatype(self) -> Declaration:
        self.tok.expect('KEYWORD', 'datatype')
        name = self._parse_qident().parts[-1]
        params = self._parse_generic_params()

        # Handle datatype without '=' (implicit tuple-like)
        if self.tok.peek().kind == 'LBRACE':
            self.tok.next()
            fields = []
            while self.tok.peek().kind not in ('RBRACE', 'EOF'):
                if self.tok.peek().kind == 'VAR' and \
                   self.tok.tokens[self.tok.pos + 1].kind == 'COLON':
                    fname = self.tok.next().value
                    self.tok.expect('COLON')
                    ftype = self._parse_type()
                    fields.append(Binder(name=fname, typ=ftype))
                    self.tok.skip('SEMICOLON')
                else:
                    self.tok.next()
            self.tok.skip('RBRACE')
            return TypeRecord(name=name, params=params, fields=fields)

        self.tok.expect('ASSIGN', '=')

        TOP_LEVEL_KW = frozenset([
            'function', 'function', 'method', 'predicate',
            'datatype', 'class', 'newtype', 'type', 'const',
            'module', 'import', 'include',
        ])

        constructors = []
        is_first = True
        while self.tok.peek().kind != 'EOF':
            # Check if next token starts a new top-level decl
            if self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value in TOP_LEVEL_KW:
                break
            # Skip PIPE except for first constructor
            if not is_first:
                if not self.tok.skip('PIPE'):
                    break
            if self.tok.peek().kind in ('EOF', 'SEMICOLON'):
                break
            # Consume constructor name (VAR, KEYWORD, or NONE)
            t = self.tok.next()
            cname = t.value
            args = []
            if self.tok.skip('LPAREN'):
                while self.tok.peek().kind not in ('RPAREN', 'EOF'):
                    aname = self.tok.next().value
                    self.tok.expect('COLON')
                    atype = self._parse_type()
                    args.append(Binder(name=aname, typ=atype))
                    self.tok.skip('COMMA')
                self.tok.expect('RPAREN')
            constructors.append(Constructor(name=cname, args=args))
            is_first = False

        if len(constructors) == 1 and constructors[0].args:
            # Single constructor with fields → TypeRecord
            return TypeRecord(name=name, params=params,
                              fields=constructors[0].args)
        elif len(constructors) > 1:
            # Multiple constructors → TypeVariant
            return TypeVariant(name=name, params=params,
                               constructors=constructors)
        else:
            # Single constructor with no args → TypeAbstract
            return TypeAbstract(name=name, params=params)

    # ── Class (→ TypeRecord) ────────────────────────────────────────────────

    def _parse_class(self) -> TypeRecord:
        self.tok.expect('KEYWORD', 'class')
        name = self._parse_qident().parts[-1]
        params = self._parse_generic_params()
        self.tok.skip('LBRACE')
        fields = []
        while self.tok.peek().kind not in ('RBRACE', 'EOF'):
            if self.tok.peek().kind == 'VAR' and \
               self.tok.tokens[self.tok.pos + 1].kind == 'COLON':
                fname = self.tok.next().value
                self.tok.expect('COLON')
                ftype = self._parse_type()
                fields.append(Binder(name=fname, typ=ftype))
                self.tok.skip('SEMICOLON')
            else:
                # Skip method declarations inside class
                self._skip_until(['RBRACE', 'KEYWORD'])
                break
        self.tok.skip('RBRACE')
        return TypeRecord(name=name, params=params, fields=fields)

    # ── Newtype (→ TypeAlias with RefinedType) ──────────────────────────────

    def _parse_newtype(self) -> TypeAlias:
        self.tok.expect('KEYWORD', 'newtype')
        name = self.tok.next().value
        self.tok.expect('ASSIGN', '=')
        # newtype X = x: T | P
        binder_name = None
        if self.tok.peek().kind == 'VAR' and \
           self.tok.tokens[self.tok.pos + 1].kind == 'COLON':
            binder_name = self.tok.next().value
            self.tok.expect('COLON')
        base_type = self._parse_type()
        pred = None
        if self.tok.skip('PIPE'):
            pred = self._parse_expr()
        if binder_name and pred:
            return TypeAlias(name=name,
                             typ=RefinedType(Binder(binder_name, base_type), pred))
        else:
            return TypeAlias(name=name, typ=base_type)

    # ── Type alias ─────────────────────────────────────────────────────────

    def _parse_type_alias(self) -> TypeAlias:
        self.tok.expect('KEYWORD', 'type')
        name = self.tok.next().value
        params = self._parse_generic_params()
        if self.tok.skip('ASSIGN', '='):
            # type X = T or type X = x: T | P
            binder_name = None
            if self.tok.peek().kind == 'VAR' and \
               self.tok.tokens[self.tok.pos + 1].kind == 'COLON':
                binder_name = self.tok.next().value
                self.tok.expect('COLON')
            base_type = self._parse_type()
            pred = None
            if self.tok.skip('PIPE'):
                pred = self._parse_expr()
            if binder_name and pred:
                return TypeAlias(name=name, params=params,
                                 typ=RefinedType(Binder(binder_name, base_type), pred))
            else:
                return TypeAlias(name=name, params=params, typ=base_type)
        else:
            return TypeAbstract(name=name, params=params)

    # ── Generic type parameters ────────────────────────────────────────────

    def _parse_generic_params(self) -> List[TypeVar]:
        params = []
        if self.tok.peek().kind == 'LT':
            self.tok.next()  # consume <
            while self.tok.peek().kind not in ('GT', 'EOF'):
                pname = self.tok.next().value
                params.append(TypeVar(pname))
                self.tok.skip('COMMA')
            self.tok.expect('GT')
        return params

    # ── Function (→ LetDecl) ────────────────────────────────────────────────

    def _parse_function(self) -> LetDecl:
        self.tok.expect('KEYWORD', 'function')
        is_method = self.tok.skip('KEYWORD', 'method')  # function method
        name = self.tok.next().value
        params = self._parse_params()
        ret_type = None
        if self.tok.skip('COLON'):
            ret_type = self._parse_type()
        body = None
        # Parse contracts
        requires, ensures, decreases = self._parse_contracts()
        # Parse body: Dafny supports { body } or = body
        if self.tok.peek().kind == 'LBRACE':
            self.tok.next()
            body = self._parse_expr()
            self.tok.skip('SEMICOLON')
            self.tok.skip('RBRACE')
        elif self.tok.skip('ASSIGN', '='):
            if self.tok.peek().kind == 'LBRACE':
                self.tok.next()
                body = self._parse_expr()
                self.tok.skip('SEMICOLON')
                self.tok.expect('RBRACE')
            else:
                body = self._parse_expr()
            if self.tok.skip('KEYWORD', 'ensures'):
                self._skip_until(['SEMICOLON'])
            self.tok.skip('SEMICOLON')
        decl = LetDecl(name=name, params=params, typ=ret_type, body=body,
                       recursive=True)
        return decl

    # ── Predicate (→ LetDecl returning bool) ────────────────────────────────

    def _parse_predicate(self) -> LetDecl:
        self.tok.expect('KEYWORD', 'predicate')
        name = self.tok.next().value
        params = self._parse_params()
        body = None
        # Parse contracts
        requires, ensures, decreases = self._parse_contracts()
        pred_type = PrimType('bool')
        # Parse body: Dafny supports { body } or = body
        if self.tok.peek().kind == 'LBRACE':
            self.tok.next()
            body = self._parse_expr()
            self.tok.skip('SEMICOLON')
            self.tok.skip('RBRACE')
        elif self.tok.skip('ASSIGN', '='):
            if self.tok.peek().kind == 'LBRACE':
                self.tok.next()
                body = self._parse_expr()
                self.tok.skip('SEMICOLON')
                self.tok.expect('RBRACE')
            else:
                body = self._parse_expr()
            self.tok.skip('SEMICOLON')
        return LetDecl(name=name, params=params, typ=pred_type, body=body,
                       recursive=True)

    # ── Method (→ ValDecl) ─────────────────────────────────────────────────

    def _parse_method(self) -> ValDecl:
        self.tok.expect('KEYWORD', 'method')
        name = self.tok.next().value
        params = self._parse_params()
        # Returns: method f(x: T) returns (r: R)
        out_params = []
        if self.tok.skip('KEYWORD', 'returns'):
            self.tok.skip('LPAREN')
            while self.tok.peek().kind not in ('RPAREN', 'EOF'):
                pname = self.tok.next().value
                self.tok.expect('COLON')
                ptype = self._parse_type()
                out_params.append(Binder(name=pname, typ=ptype))
                self.tok.skip('COMMA')
            self.tok.skip('RPAREN')
        # Parse contracts
        requires, ensures, decreases = self._parse_contracts()
        # Body: method f(...) { ... }
        self.tok.skip('LBRACE')
        # Skip body tokens
        depth = 1
        while self.tok.peek().kind != 'EOF' and depth > 0:
            t = self.tok.next()
            if t.kind == 'LBRACE': depth += 1
            elif t.kind == 'RBRACE': depth -= 1
        ret_type = out_params[0].typ if len(out_params) == 1 else (
            TupleType([p.typ for p in out_params]) if out_params else PrimType('unit')
        )
        contract = PrePost(
            requires=requires,
            ensures=ensures,
            decreases=decreases,
        )
        return ValDecl(name=name, params=params, return_type=ret_type,
                       contract=contract, effect='Pure')

    # ── Const ───────────────────────────────────────────────────────────────

    def _parse_const(self) -> LetDecl:
        self.tok.expect('KEYWORD', 'const')
        name = self.tok.next().value
        typ = None
        if self.tok.skip('COLON'):
            typ = self._parse_type()
        body = None
        if self.tok.skip('ASSIGN', '='):
            body = self._parse_expr()
        self.tok.skip('SEMICOLON')
        return LetDecl(name=name, typ=typ, body=body)

    # ── Parameters ──────────────────────────────────────────────────────────

    def _parse_params(self) -> List[Binder]:
        params = []
        if not self.tok.skip('LPAREN'):
            return params
        if self.tok.peek().kind == 'RPAREN':
            self.tok.next()
            return params
        while self.tok.peek().kind not in ('RPAREN', 'EOF'):
            ghost = self.tok.skip('KEYWORD', 'ghost')
            pname = self.tok.next().value
            self.tok.expect('COLON')
            ptype = self._parse_type()
            params.append(Binder(name=pname, typ=ptype, implicit=ghost))
            self.tok.skip('COMMA')
        self.tok.expect('RPAREN')
        return params

    # ── Contracts ──────────────────────────────────────────────────────────

    def _parse_contracts(self) -> Tuple[Optional[Expr], Optional[Expr], Optional[Expr]]:
        requires = None
        ensures = None
        decreases = None
        while True:
            t = self.tok.peek()
            if t.kind != 'KEYWORD':
                break
            kw = t.value
            if kw == 'requires':
                self.tok.next()
                req = self._parse_expr()
                if requires is None:
                    requires = req
                else:
                    requires = BinOp('and', requires, req)
            elif kw == 'ensures':
                self.tok.next()
                ens = self._parse_expr()
                if ensures is None:
                    ensures = ens
                else:
                    ensures = BinOp('and', ensures, ens)
            elif kw == 'decreases':
                self.tok.next()
                decreases = self._parse_expr()
            elif kw in ('modifies', 'reads'):
                # Skip modifies/reads for now
                self.tok.next()
                self._parse_expr()
            else:
                break
        return requires, ensures, decreases

    # ── Type parsing ───────────────────────────────────────────────────────

    def _parse_type(self) -> TypeExpr:
        return self._parse_atomic_type()

    def _parse_atomic_type(self) -> TypeExpr:
        t = self.tok.peek()

        # Handle primitive types
        if t.kind == 'KEYWORD':
            name = t.value
            if name in ('nat', 'int', 'bool', 'string', 'char', 'real'):
                self.tok.next()
                prim = PrimType(name)
                # Check for generics: seq<int>, set<bool>, etc.
                if self.tok.peek().kind == 'LT':
                    self.tok.next()
                    args = [self._parse_type()]
                    self.tok.expect('GT')
                    if name == 'seq':
                        return ListType(args[0])
                    elif name == 'set':
                        return AppType(NamedType(QualifiedIdent(['Set'])), args)
                    elif name == 'multiset':
                        return AppType(NamedType(QualifiedIdent(['Multiset'])), args)
                    elif name == 'map':
                        # map<K,V>
                        if self.tok.peek().kind == 'COMMA':
                            self.tok.next()
                            vtype = self._parse_type()
                            self.tok.expect('GT')
                            return AppType(NamedType(QualifiedIdent(['Map'])),
                                           [args[0], vtype])
                        self.tok.expect('GT')
                        return AppType(NamedType(QualifiedIdent(['Map'])),
                                       [args[0], PrimType('unit')])
                    else:
                        return AppType(NamedType(QualifiedIdent([name.capitalize()])),
                                       args)
                return prim
            elif name == 'seq':
                # seq<T>
                self.tok.next()
                self.tok.expect('LT')
                elem = self._parse_type()
                self.tok.expect('GT')
                return ListType(elem)
            elif name == 'set':
                self.tok.next()
                self.tok.expect('LT')
                elem = self._parse_type()
                self.tok.expect('GT')
                return AppType(NamedType(QualifiedIdent(['Set'])), [elem])
            elif name == 'multiset':
                self.tok.next()
                self.tok.expect('LT')
                elem = self._parse_type()
                self.tok.expect('GT')
                return AppType(NamedType(QualifiedIdent(['Multiset'])), [elem])
            elif name == 'map':
                self.tok.next()
                self.tok.expect('LT')
                ktype = self._parse_type()
                self.tok.expect('COMMA')
                vtype = self._parse_type()
                self.tok.expect('GT')
                return AppType(NamedType(QualifiedIdent(['Map'])), [ktype, vtype])
            elif name == 'Option':
                self.tok.next()
                self.tok.expect('LT')
                elem = self._parse_type()
                self.tok.expect('GT')
                return OptionType(elem)
            elif name == 'bool':
                self.tok.next()
                return PrimType('bool')
            elif name in ('int', 'nat', 'real'):
                self.tok.next()
                return PrimType(name)
            # Fall through for other keywords

        # Handle parens: (T) or (T, U, ...)
        if t.kind == 'LPAREN':
            self.tok.next()
            types = [self._parse_type()]
            while self.tok.skip('COMMA'):
                types.append(self._parse_type())
            self.tok.expect('RPAREN')
            if len(types) == 1:
                return types[0]
            return TupleType(types)

        # Handle arrow: -> (Dafny function types)
        # We don't fully parse Dafny arrow types; treat as NamedType

        # Handle named type
        if t.kind == 'VAR' or t.kind == 'KEYWORD':
            name = self._parse_qident()
            # Check for generics
            if self.tok.peek().kind == 'LT':
                self.tok.next()
                args = []
                while self.tok.peek().kind not in ('GT', 'EOF'):
                    args.append(self._parse_type())
                    self.tok.skip('COMMA')
                self.tok.expect('GT')
                return AppType(NamedType(name), args)
            return NamedType(name)

        # Handle undersocre
        if t.kind == 'UNDERSCORE':
            self.tok.next()
            return TypeVar('_')

        raise SyntaxError(f'Expected type at pos {t.pos}, got {t}')

    # ── Expression parsing ─────────────────────────────────────────────────

    def _parse_expr(self) -> Expr:
        return self._parse_impl_expr()

    def _parse_impl_expr(self) -> Expr:
        """Parse implication: left ==> right"""
        left = self._parse_or_expr()
        if self.tok.skip('ARROW', '==>') or self.tok.skip('IMPLIES') or \
           (self.tok.peek().kind == 'EQUALS' and self.tok.tokens[self.tok.pos + 1].kind == 'GT'):
            # ==> or =>
            if self.tok.peek().kind == 'EQUALS':
                self.tok.next(); self.tok.next()  # consume =>
            right = self._parse_impl_expr()
            return BinOp('==>', left, right)
        return left

    def _parse_or_expr(self) -> Expr:
        left = self._parse_and_expr()
        while self.tok.peek().kind == 'PIPE' and \
              self.tok.tokens[self.tok.pos + 1].kind == 'PIPE':
            self.tok.next(); self.tok.next()  # consume ||
            right = self._parse_and_expr()
            left = BinOp('or', left, right)
        # Also handle '||' as two BAR tokens (see above)
        # Also handle keyword 'or'
        while self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == 'or':
            self.tok.next()
            right = self._parse_and_expr()
            left = BinOp('or', left, right)
        return left

    def _parse_and_expr(self) -> Expr:
        left = self._parse_not_expr()
        while self.tok.peek().kind == 'AMPERSAND' and \
              self.tok.tokens[self.tok.pos + 1].kind == 'AMPERSAND':
            self.tok.next(); self.tok.next()  # consume &&
            right = self._parse_not_expr()
            left = BinOp('and', left, right)
        # Also handle '&&' as two tokens
        while self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == 'and':
            self.tok.next()
            right = self._parse_not_expr()
            left = BinOp('and', left, right)
        return left

    def _parse_not_expr(self) -> Expr:
        if self.tok.peek().kind == 'BANG':
            self.tok.next()
            inner = self._parse_not_expr()
            return UnaryOp('not', inner)
        if self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value in ('neg', '!'):
            self.tok.next()
            inner = self._parse_not_expr()
            return UnaryOp('not', inner)
        return self._parse_cmp_expr()

    def _parse_cmp_expr(self) -> Expr:
        left = self._parse_add_expr()
        while True:
            t = self.tok.peek()
            # Check for ==> vs ==: lookahead
            if t.kind == 'EQUALS':
                # If followed by >, it's ==>, not == — break,
                # _parse_impl_expr will handle it
                if self.tok.pos + 1 < len(self.tok.tokens) and \
                   self.tok.tokens[self.tok.pos + 1].kind == 'GT':
                    break
                self.tok.next()
                right = self._parse_add_expr()
                left = BinOp('==', left, right)
            elif t.kind == 'NEQ':
                self.tok.next()
                right = self._parse_add_expr()
                left = BinOp('!=', left, right)
            elif t.kind == 'LE':
                self.tok.next()
                right = self._parse_add_expr()
                left = BinOp('<=', left, right)
            elif t.kind == 'GE':
                self.tok.next()
                right = self._parse_add_expr()
                left = BinOp('>=', left, right)
            elif t.kind == 'LT':
                self.tok.next()
                right = self._parse_add_expr()
                left = BinOp('<', left, right)
            elif t.kind == 'GT':
                self.tok.next()
                right = self._parse_add_expr()
                left = BinOp('>', left, right)
            elif t.kind == 'KEYWORD' and t.value == 'in':
                self.tok.next()
                right = self._parse_add_expr()
                left = App(Var('in'), [left, right])
            else:
                break
        return left

    def _parse_add_expr(self) -> Expr:
        left = self._parse_mul_expr()
        while True:
            t = self.tok.peek()
            if t.kind == 'PLUS':
                self.tok.next()
                right = self._parse_mul_expr()
                left = BinOp('+', left, right)
            elif t.kind == 'MINUS':
                self.tok.next()
                right = self._parse_mul_expr()
                left = BinOp('-', left, right)
            elif t.kind == 'KEYWORD' and t.value in ('plus', 'add'):
                self.tok.next()
                right = self._parse_mul_expr()
                left = BinOp('+', left, right)
            else:
                break
        return left

    def _parse_mul_expr(self) -> Expr:
        left = self._parse_unary_expr()
        while True:
            t = self.tok.peek()
            if t.kind == 'STAR':
                self.tok.next()
                right = self._parse_unary_expr()
                left = BinOp('*', left, right)
            elif t.kind == 'SLASH':
                self.tok.next()
                right = self._parse_unary_expr()
                left = BinOp('/', left, right)
            elif t.kind == 'PERCENT':
                self.tok.next()
                right = self._parse_unary_expr()
                left = BinOp('%', left, right)
            else:
                break
        return left

    def _parse_unary_expr(self) -> Expr:
        if self.tok.peek().kind == 'MINUS':
            self.tok.next()
            inner = self._parse_unary_expr()
            return UnaryOp('-', inner)
        if self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == 'neg':
            self.tok.next()
            inner = self._parse_unary_expr()
            return UnaryOp('-', inner)
        return self._parse_apply_expr()

    def _parse_apply_expr(self) -> Expr:
        left = self._parse_atom_expr()
        while True:
            t = self.tok.peek()
            # Function application: f(x)
            if t.kind == 'LPAREN':
                self.tok.next()
                args = []
                if self.tok.peek().kind != 'RPAREN':
                    args.append(self._parse_expr())
                    while self.tok.skip('COMMA'):
                        args.append(self._parse_expr())
                self.tok.expect('RPAREN')
                left = App(left, args)
            # Field access: x.f
            elif t.kind == 'DOT':
                self.tok.next()
                fname = self.tok.next().value
                left = FieldAccess(left, fname)
            # Index: x[i]
            elif t.kind == 'LBRACKET':
                self.tok.next()
                if self.tok.peek().kind == 'RBRACKET':
                    # |x| length
                    self.tok.next()
                    left = Len(left)
                else:
                    idx = self._parse_expr()
                    self.tok.expect('RBRACKET')
                    left = ArrayIndex(left, idx)
            else:
                break
        return left

    def _parse_atom_expr(self) -> Expr:
        t = self.tok.peek()

        # Integer literal
        if t.kind == 'INT':
            self.tok.next()
            return Const(int(t.value))

        # Float literal
        if t.kind == 'FLOAT':
            self.tok.next()
            return Const(float(t.value))

        # String literal
        if t.kind == 'STRING':
            self.tok.next()
            return Const(t.value.strip('"'))

        # Boolean
        if t.kind == 'BOOL':
            self.tok.next()
            return Const(t.value == 'true')

        # None/null
        if t.kind == 'NONE':
            self.tok.next()
            return Const(None)

        # |x| length
        if t.kind == 'PIPE':
            self.tok.next()
            inner = self._parse_expr()
            self.tok.expect('PIPE')
            return Len(inner)

        # forall, exists
        if t.kind == 'KEYWORD' and t.value in ('forall', 'exists'):
            return self._parse_quantifier(t.value == 'forall')

        # if/then/else
        if t.kind == 'KEYWORD' and t.value == 'if':
            return self._parse_if_expr()

        # match/case
        if t.kind == 'KEYWORD' and t.value == 'match':
            return self._parse_match_expr()

        # var x := expr (let binding)
        if t.kind == 'KEYWORD' and t.value == 'var':
            return self._parse_var_expr()

        # new X(...)
        if t.kind == 'KEYWORD' and t.value == 'new':
            return self._parse_new_expr()

        # Parenthesized expression
        if t.kind == 'LPAREN':
            self.tok.next()
            inner = self._parse_expr()
            self.tok.expect('RPAREN')
            return inner

        # negative number: -(expr)
        if t.kind == 'MINUS':
            self.tok.next()
            inner = self._parse_atom_expr()
            return UnaryOp('-', inner)

        # Bare identifier or qualified name
        if t.kind == 'VAR' or t.kind == 'KEYWORD':
            name = self._parse_qident()
            return QualifiedVar(name) if len(name.parts) > 1 else Var(name.parts[0])

        # Underscore
        if t.kind == 'UNDERSCORE':
            self.tok.next()
            return Var('_placeholder')

        raise SyntaxError(f'Unexpected token at pos {t.pos}: {t}')

    # ── Quantifiers ────────────────────────────────────────────────────────

    def _parse_quantifier(self, is_forall: bool) -> Expr:
        self.tok.next()  # consume forall/exists
        binders = []
        # forall x :: body  or  forall x: T :: body
        while self.tok.peek().kind not in ('QUANTIFIER', 'EOF'):
            ghost = self.tok.skip('KEYWORD', 'ghost')
            pname = self.tok.next().value
            ptype = None
            if self.tok.skip('COLON'):
                ptype = self._parse_type()
            else:
                ptype = TypeVar('_')
            binders.append(Binder(name=pname, typ=ptype, implicit=ghost))
            self.tok.skip('COMMA')
        self.tok.expect('QUANTIFIER')  # ::
        body = self._parse_expr()

        # For forall x: T :: body, translate to: (forall (x: T). body)
        if is_forall:
            return Forall(binders=binders, body=body)
        else:
            return Exists(binders=binders, body=body)

    # ── If/then/else ───────────────────────────────────────────────────────

    def _parse_if_expr(self) -> IfExpr:
        self.tok.next()  # consume if
        cond = self._parse_expr()
        self.tok.expect('KEYWORD', 'then')
        then_expr = self._parse_expr()
        if self.tok.skip('KEYWORD', 'else'):
            else_expr = self._parse_expr()
        else:
            else_expr = Const(None)
        return IfExpr(cond=cond, then_expr=then_expr, else_expr=else_expr)

    # ── Match ──────────────────────────────────────────────────────────────

    def _parse_match_expr(self) -> Match:
        self.tok.next()  # consume match
        expr = self._parse_expr()
        self.tok.expect('LBRACE')
        cases = []
        while self.tok.peek().kind not in ('RBRACE', 'EOF'):
            if self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == 'case':
                self.tok.next()
                # Parse pattern
                pat = self._parse_pattern()
                self.tok.skip('ARROW', '=>')
                val = self._parse_expr()
                cases.append(MatchCase(pattern=pat, expr=val))
            else:
                break
        self.tok.expect('RBRACE')
        return Match(expr=expr, cases=cases)

    # ── Pattern parsing ────────────────────────────────────────────────────

    def _parse_pattern(self) -> Pattern:
        t = self.tok.peek()
        if t.kind == 'UNDERSCORE':
            self.tok.next()
            return PatWild()
        if t.kind == 'INT':
            self.tok.next()
            return PatConst(int(t.value))
        if t.kind == 'BOOL':
            self.tok.next()
            return PatConst(t.value == 'true')
        if t.kind == 'STRING':
            self.tok.next()
            return PatConst(t.value.strip('"'))
        if t.kind == 'NONE':
            self.tok.next()
            return PatApp('None', [])
        if t.kind == 'LPAREN':
            self.tok.next()
            pats = []
            while self.tok.peek().kind != 'RPAREN':
                pats.append(self._parse_pattern())
                self.tok.skip('COMMA')
            self.tok.expect('RPAREN')
            if len(pats) == 1:
                return pats[0]
            return PatTuple(pats)
        if t.kind == 'LBRACKET':
            # List pattern: [] or [x, y, ...]
            self.tok.next()
            pats = []
            rest_var = None
            rest_dotdot = False
            while self.tok.peek().kind not in ('RBRACKET', 'EOF'):
                # Check for ..
                if self.tok.peek().kind == 'DOT' and \
                   self.tok.tokens[self.tok.pos + 1].kind == 'DOT':
                    self.tok.next(); self.tok.next()
                    rest_var = self.tok.next().value if self.tok.peek().kind == 'VAR' else '_'
                    rest_dotdot = True
                elif self.tok.peek().kind == 'DOT' and \
                     self.tok.tokens[self.tok.pos + 1].kind == 'DOT' and \
                     self.tok.tokens[self.tok.pos + 2].kind == 'DOT':
                    self.tok.next(); self.tok.next(); self.tok.next()
                    rest_var = self.tok.next().value if self.tok.peek().kind == 'VAR' else '_'
                    rest_dotdot = True
                else:
                    pats.append(self._parse_pattern())
                self.tok.skip('COMMA')
            self.tok.expect('RBRACKET')
            # Build Cons chain
            result = PatVar(rest_var) if rest_var else PatApp('Nil', [])
            for p in reversed(pats):
                result = PatApp('Cons', [p, result])
            return result
        if t.kind == 'KEYWORD':
            kw = t.value
            if kw in ('None',):
                self.tok.next()
                return PatApp('None', [])
            if kw == 'Some':
                self.tok.next()
                if self.tok.skip('LPAREN'):
                    inner = self._parse_pattern()
                    self.tok.expect('RPAREN')
                    return PatApp('Some', [inner])
                return PatApp('Some', [PatWild()])
        # Default: var or constructor pattern
        name = t.value
        self.tok.next()
        # Constructor with payload: C(x, y)
        if self.tok.peek().kind == 'LPAREN':
            self.tok.next()
            args = []
            while self.tok.peek().kind not in ('RPAREN', 'EOF'):
                args.append(self._parse_pattern())
                self.tok.skip('COMMA')
            self.tok.expect('RPAREN')
            return PatApp(name, args)
        # Handle :: (Cons) patterns: hd :: tl
        if self.tok.peek().kind == 'QUANTIFIER':
            self.tok.next()  # consume ::
            tail_pat = self._parse_pattern()
            return PatApp('Cons', [PatVar(name), tail_pat])
        return PatVar(name)

    # ── Other expressions ──────────────────────────────────────────────────

    def _parse_var_expr(self) -> Expr:
        """var x := expr  →  treat as let binding (return body)"""
        self.tok.next()  # consume var
        name = self.tok.next().value
        self.tok.skip('COLON')
        typ = None
        if self.tok.peek().kind == 'VAR':
            typ = self._parse_type()
        self.tok.expect('ASSIGN', '=')
        val = self._parse_expr()
        return val  # just return the value

    def _parse_new_expr(self) -> Expr:
        """new X(...)  →  treat as constructor call"""
        self.tok.next()  # consume new
        name = self.tok.next().value
        if self.tok.skip('LPAREN'):
            args = []
            while self.tok.peek().kind not in ('RPAREN', 'EOF'):
                args.append(self._parse_expr())
                self.tok.skip('COMMA')
            self.tok.expect('RPAREN')
            return App(Var(name), args)
        return Var(name)

    # ── Helpers ────────────────────────────────────────────────────────────

    def _skip_until(self, targets: List[str]):
        """Skip tokens until one of the target kinds or values is reached."""
        while self.tok.peek().kind != 'EOF':
            t = self.tok.peek()
            if t.kind in targets:
                break
            if t.kind == 'KEYWORD' and t.value in targets:
                break
            self.tok.next()


# ── Top-level convenience wrapper ──────────────────────────────────────────

def parse_dafny(text: str) -> VeriDslProgram:
    """Parse Dafny syntax text into VeriDslProgram AST.

    Args:
        text: Dafny source code (subset)

    Returns:
        VeriDslProgram AST representing the parsed declarations

    Raises:
        SyntaxError: If parsing fails
    """
    parser = DafnyParser(text)
    return parser.parse()
