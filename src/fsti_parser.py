"""
fsti_parser.py — Recursive-descent parser for the F* subset that appears
in .veri.md files (module decls, types, vals, lets, and their expressions).

No external dependencies. Works on raw text.
"""

import re
from typing import List, Optional, Tuple, Union
from veri_ast import *


# ── Tokenizer ────────────────────────────────────────────────────────────────

class Token:
    def __init__(self, kind: str, value: str, pos: int):
        self.kind = kind    # IDENT, INT, FLOAT, STRING, KEYWORD, SYMBOL, EOF
        self.value = value
        self.pos = pos

    def __repr__(self):
        return f'Token({self.kind}, {self.value!r})'

TOKEN_SPEC = [
    ('COMMENT_LINE',  r'//[^\n]*'),
    ('COMMENT_BLOCK', r'\(\*.*?\*\)'),
    ('INT',           r'\d+'),
    ('FLOAT',         r'\d+\.\d+([eE][+-]?\d+)?'),
    ('STRING',        r'"[^"]*"'),
    ('KEYWORD',       r'\b(module|open|include|friend|type|let|rec|and|val|'
                      r'assume|unfold|inline_for_extraction|irreducible|noextract|'
                      r'private|noeq|unopteq|new|logic|opaque|'
                      r'requires|ensures|decreases|fun|match|with|if|then|else|in|let|'
                      r'forall|exists|True|False|Some|None|'
                      r'Pure|Tot|GTot|ST|Lemma|Dv|ML|Exn|'
                      r'Set|Type|Type0|eqtype|prop|bool|int|nat|string|float|unit|'
                      r'modifies|contains|sel|live|loc_buffer|loc_reference|loc_union|'
                      r'Buffer|HyperStack|Heap|FStar|List)\b'),
    ('VAR',           r'[a-zA-Z_][a-zA-Z0-9_]*'),
    ('QUIDENT',       r'[a-zA-Z_][a-zA-Z0-9_.]*'),  # qualified ident
    ('ARROW',         r'->'),
    ('BAR_ARROW',     r'\|->'),
    ('SQUIGGLY_ARROW', r'~>'),
    ('IMPLIES',       r'==>'),
    ('EQUALS',        r'=='),
    ('COLON_EQUALS',  r':='),
    ('IFF',           r'<==>'),
    ('DISJUNCTION',   r'\\\/'),
    ('CONJUNCTION',   r'/\\(?!/)'),
    ('AMP_CONJUNCTION', r'&&'),
    ('LBRACE_BAR',    r'\{-\||\{\|'),
    ('BAR_RBRACE',    r'\|-\}|\|\}'),
    ('LPAREN',        r'\('),
    ('RPAREN',        r'\)'),
    ('LBRACKET',      r'\['),
    ('RBRACKET',      r'\]'),
    ('LBRACE',        r'\{'),
    ('RBRACE',        r'\}'),
    ('LESS_EQUAL',    r'<='),
    ('GREATER_EQUAL', r'>='),
    ('COMMA',         r','),
    ('DOT',           r'\.'),
    ('SEMICOLON',     r';'),
    ('COLON',         r':'),
    ('BAR',           r'\|'),
    ('PIPE_LEFT',     r'<\|'),
    ('PIPE_RIGHT',    r'\|>'),
    ('BACKTICK',      r'`'),
    ('AT',            r'@'),
    ('HASH',          r'#'),
    ('HAT',           r'\^'),
    ('TILDE',         r'~'),
    ('BANG',          r'!'),
    ('QUESTION',      r'\?'),
    ('STAR',          r'\*'),
    ('SLASH',         r'/'),
    ('PLUS',          r'\+'),
    ('MINUS',         r'-'),
    ('PERCENT',       r'%'),
    ('LESS',          r'<'),
    ('GREATER',       r'>'),
    ('EQUALS_SIGN',   r'='),
    ('UNDERSCORE',    r'_'),
    ('AMPERSAND',     r'&'),
    ('WS',            r'\s+'),
]

TOKEN_RE = re.compile('|'.join(f'(?P<{name}>{pattern})' for name, pattern in TOKEN_SPEC),
                       re.DOTALL)


class Tokenizer:
    def __init__(self, text: str):
        self.text = self._preprocess(text)
        self.pos = 0
        self.tokens: List[Token] = []
        self._tokenize()

    @staticmethod
    def _preprocess(text: str) -> str:
        """Strip #TODO, #FIXME markers and control flow annotations."""
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
            # Normalize certain tokens
            if kind == 'KEYWORD' and val in ('True', 'False'):
                kind = 'BOOL'
            elif kind in ('VAR', 'QUIDENT') and self._is_keyword(val):
                kind = 'KEYWORD'
                if val in ('module', 'open', 'type', 'let', 'val', 'rec',
                           'requires', 'ensures', 'decreases'):
                    pass  # keep as keyword
            self.tokens.append(Token(kind, val, m.start()))
        self.tokens.append(Token('EOF', '', len(self.text)))

    def _is_keyword(self, w: str) -> bool:
        keywords = {'module', 'open', 'include', 'friend', 'type', 'let', 'rec',
                     'and', 'val', 'assume', 'unfold', 'inline_for_extraction',
                     'irreducible', 'noextract', 'private', 'noeq', 'unopteq',
                     'new', 'logic', 'opaque', 'requires', 'ensures', 'decreases',
                     'fun', 'match', 'with', 'if', 'then', 'else',
                     'forall', 'exists', 'True', 'False', 'Some', 'None',
                     'Pure', 'Tot', 'GTot', 'ST', 'Lemma', 'Dv', 'ML', 'Exn',
                     'Set', 'Type', 'Type0', 'eqtype', 'prop', 'bool', 'int',
                     'nat', 'string', 'float', 'unit',
                     'modifies', 'contains', 'sel', 'live',
                     'loc_buffer', 'loc_reference', 'loc_union',
                     'Buffer', 'HyperStack', 'Heap'}
        return w in keywords

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


# ── Parser ────────────────────────────────────────────────────────────────────

class FStarParser:
    """Parse F* .fsti text into VeriDslProgram AST."""

    def __init__(self, text: str):
        self.tok = Tokenizer(text)
        self.program = VeriDslProgram()
        self._extra_binders: List[Binder] = []  # multi-name binder overflow

    def parse(self) -> VeriDslProgram:
        while self.tok.peek().kind != 'EOF':
            decl = self._parse_decl()
            if decl is not None:
                self.program.add(decl)
        return self.program

    def _parse_decl(self) -> Optional[Declaration]:
        """Parse a single top-level declaration."""
        kw = self.tok.peek().value if self.tok.peek().kind == 'KEYWORD' else None

        if kw == 'module':
            return self._parse_module()
        elif kw == 'open':
            return self._parse_open()
        elif kw == 'include':
            return self._parse_include()
        elif kw == 'friend':
            return self._parse_friend()
        elif kw == 'type':
            return self._parse_type_decl()
        elif kw == 'let':
            return self._parse_let()
        elif kw == 'val':
            return self._parse_val()
        elif kw == 'assume':
            return self._parse_assume_val()
        elif kw in ('unfold', 'inline_for_extraction', 'irreducible',
                    'noextract', 'private', 'noeq', 'unopteq', 'new', 'opaque'):
            # Qualifier followed by a declaration
            qual = self.tok.next().value
            next_kw = self.tok.peek().value if self.tok.peek().kind == 'KEYWORD' else None
            if next_kw == 'val':
                decl = self._parse_val()
                if decl:
                    decl.qualifiers.append(qual)
                return decl
            elif next_kw == 'type':
                decl = self._parse_type_decl()
                return decl
            elif next_kw == 'let':
                decl = self._parse_let()
                if decl:
                    decl.qualifiers.append(qual)
                return decl
            # else: fall through as unknown
        # Skip things we don't understand (e.g. #push-options)
        self.tok.next()
        return None

    def _parse_module(self) -> ModuleDecl:
        self.tok.expect('KEYWORD', 'module')
        name = self._parse_quident()
        return ModuleDecl(name=name)

    def _parse_open(self) -> OpenDecl:
        self.tok.expect('KEYWORD', 'open')
        path = self._parse_quident()
        return OpenDecl(path=path)

    def _parse_include(self) -> IncludeDecl:
        self.tok.expect('KEYWORD', 'include')
        path = self._parse_quident()
        return IncludeDecl(path=path)

    def _parse_friend(self) -> FriendDecl:
        self.tok.expect('KEYWORD', 'friend')
        path = self._parse_quident()
        return FriendDecl(path=path)

    def _parse_quident(self) -> QualifiedIdent:
        """Parse a dotted identifier like FStar.List.Tot or key_name."""
        parts = []
        # Could start with a keyword if it's a type name
        t = self.tok.next()
        if t.kind in ('VAR', 'KEYWORD', 'INT'):
            parts.append(t.value)
        else:
            raise SyntaxError(f'Expected identifier at pos {t.pos}, got {t}')
        while self.tok.peek().kind == 'DOT':
            self.tok.next()  # consume .
            t = self.tok.next()
            if t.kind in ('VAR', 'KEYWORD', 'INT'):  # e.g. contains, Sel, type names
                parts.append(t.value)
            else:
                raise SyntaxError(f'Expected identifier after dot at pos {t.pos}, got {t}')
        return QualifiedIdent(parts)

    # ── Type declarations ──────────────────────────────────────────────────

    def _parse_type_decl(self) -> Declaration:
        self.tok.expect('KEYWORD', 'type')
        name = self.tok.expect('VAR').value if self.tok.peek().kind == 'VAR' else self.tok.expect('KEYWORD').value

        # Params?
        params = self._parse_type_params()

        # Kind annotation?
        kind = None
        if self.tok.skip('COLON'):
            kind = self._parse_term()

        # Check what follows
        if self.tok.peek().kind == 'EOF' or self.tok.peek().kind in ('KEYWORD',):
            return TypeAbstract(name=name, params=params, kind=kind)

        if self.tok.peek().kind == 'EQUALS_SIGN':
            self.tok.next()  # consume =
            return self._parse_type_body(name, params, kind)

        # Abstract (nothing after name/kind)
        return TypeAbstract(name=name, params=params, kind=kind)

    def _parse_type_params(self) -> List[TypeVar]:
        params = []
        while self.tok.peek().kind == 'HASH' or self.tok.peek().kind == 'LPAREN':
            if self.tok.peek().kind == 'HASH':
                self.tok.next()  # #
            self.tok.expect('LPAREN')
            while self.tok.peek().kind != 'RPAREN':
                if self.tok.peek().kind == 'COMMA':
                    self.tok.next()
                pname = self.tok.next().value
                pkind = None
                if self.tok.skip('COLON'):
                    pkind = self._parse_atomic_type()
                params.append(TypeVar(pname, pkind))
                if self.tok.peek().kind == 'COMMA':
                    self.tok.next()
            self.tok.expect('RPAREN')
        return params

    def _parse_type_body(self, name: str, params: List[TypeVar],
                         kind: Optional[Term]) -> Declaration:
        """Parse type definition body: record, variant, alias, or refined."""

        # Record type
        if self.tok.peek().kind == 'LBRACE':
            fields = self._parse_record_fields()
            return TypeRecord(name=name, params=params, fields=fields)

        # Variant (starts with |)
        if self.tok.peek().kind == 'BAR':
            constructors = self._parse_variant_constructors()
            return TypeVariant(name=name, params=params, constructors=constructors)

        # Otherwise: parse a type expression (alias or refined)
        texpr = self._parse_type_expr()

        # Check if it's a refined type: `binder{refinement}` pattern
        if isinstance(texpr, RefinedType):
            return TypeAlias(name=name, params=params, typ=texpr)
        else:
            return TypeAlias(name=name, params=params, typ=texpr)

    def _parse_record_fields(self) -> List[Binder]:
        self.tok.expect('LBRACE')
        fields = []
        while self.tok.peek().kind != 'RBRACE':
            if self.tok.peek().kind == 'SEMICOLON':
                self.tok.next()
                continue
            # Field name + colon + type
            fname = self.tok.next().value
            self.tok.expect('COLON')
            # Handle `contains` style backtick ops? No, just type expr.
            ftype = self._parse_type_expr()
            fields.append(Binder(name=fname, typ=ftype))
            if self.tok.peek().kind == 'SEMICOLON':
                self.tok.next()
            elif self.tok.peek().kind == 'COMMA':
                self.tok.next()
        self.tok.expect('RBRACE')
        return fields

    def _parse_variant_constructors(self) -> List[Constructor]:
        constructors = []
        while self.tok.peek().kind == 'BAR':
            self.tok.next()
            cname = self.tok.next().value if self.tok.peek().kind in ('VAR', 'KEYWORD') else self.tok.expect('VAR').value
            args = []
            typ = None
            if self.tok.peek().kind == 'COLON':
                self.tok.next()
                typ = self._parse_type_expr()
            elif self.tok.peek().kind == 'LPAREN':
                # Payload: `Ctor (arg1: t1) (arg2: t2)`
                while self.tok.peek().kind == 'LPAREN':
                    self.tok.expect('LPAREN')
                    aname = self.tok.next().value
                    if self.tok.skip('COLON'):
                        atype = self._parse_type_expr()
                    else:
                        atype = PrimType('unit')
                    args.append(Binder(name=aname, typ=atype))
                    # Consume remaining args in the paren
                    while self.tok.peek().kind != 'RPAREN':
                        if self.tok.peek().kind == 'COMMA':
                            self.tok.next()
                        aname2 = self.tok.next().value
                        if self.tok.skip('COLON'):
                            atype2 = self._parse_type_expr()
                        else:
                            atype2 = PrimType('unit')
                        args.append(Binder(name=aname2, typ=atype2))
                    self.tok.expect('RPAREN')
                # Skip -> continuation if present
                if self.tok.peek().kind == 'ARROW':
                    self.tok.next()
                    self._parse_type_expr()
            constructors.append(Constructor(name=cname, args=args, typ=typ))
        return constructors

    # ── Expression / Term parsing ──────────────────────────────────────────

    def _parse_type_expr(self) -> TypeExpr:
        """Parse a type expression (may be a refined type with {pred})."""
        base = self._parse_atomic_type()

        # Binder pattern: `name: type` (e.g. in `type X = buf:circular_buffer{...}`)
        if self.tok.peek().kind == 'COLON':
            if isinstance(base, TypeVar) or isinstance(base, NamedType):
                name = base.name if isinstance(base, TypeVar) else base.path.parts[-1]
                self.tok.next()  # :
                typ = self._parse_type_expr()
                # If followed by LBRACE, it's a refined binder
                if self.tok.peek().kind == 'LBRACE':
                    self.tok.next()  # {
                    pred = self._parse_term()
                    self.tok.expect('RBRACE')
                    return RefinedType(binder=Binder(name=name, typ=typ), predicate=pred)
                else:
                    # Just a named binder as type (uncommon but valid)
                    return typ

        # Refinement: `base{pred}`
        if self.tok.peek().kind == 'LBRACE':
            self.tok.next()  # {
            pred = self._parse_term()
            self.tok.expect('RBRACE')
            b = Binder(name='x', typ=base)
            return RefinedType(binder=b, predicate=pred)

        # Arrow: `t1 -> t2`
        if self.tok.peek().kind == 'ARROW':
            self.tok.next()
            result = self._parse_type_expr()
            b = Binder(name=None, typ=base)
            return ArrowType(params=[b], result=result)

        return base

    def _parse_atomic_type(self) -> TypeExpr:
        """Parse an atomic type term."""
        t = self.tok.peek()

        # Parenthesized
        if t.kind == 'LPAREN':
            self.tok.next()
            # Could be a binder: `(x: t)` or just `(t1 * t2)`
            if self.tok.peek().kind == 'RPAREN':
                self.tok.next()
                return PrimType('unit')
            first = self._parse_type_expr()
            # Check for tuple
            if self.tok.peek().kind == 'STAR':
                self.tok.next()
                items = [first]
                while True:
                    items.append(self._parse_type_expr())
                    if not self.tok.skip('STAR'):
                        break
                self.tok.expect('RPAREN')
                return TupleType(items=items)
            # Check for `x: t` pattern (binder)
            if isinstance(first, TypeVar) or isinstance(first, NamedType):
                if self.tok.peek().kind == 'COLON':
                    self.tok.next()
                    typ = self._parse_type_expr()
                    self.tok.expect('RPAREN')
                    return typ
            self.tok.expect('RPAREN')
            return first

        # Underbar as wild type
        if t.kind == 'UNDERSCORE':
            self.tok.next()
            return TypeVar('_')

        # Keyword types
        if t.kind == 'KEYWORD' and t.value in ('Type', 'Type0', 'eqtype', 'prop', 'bool', 'int', 'nat', 'string', 'float', 'unit'):
            self.tok.next()
            return PrimType(t.value)

        # Forall/Exists in type position
        if t.kind == 'KEYWORD' and t.value in ('forall', 'exists'):
            # These appear in ensures clauses - parse as formula terms
            return self._parse_term()  # Hmm, this mixes type/term

        # Variable/con/unqualified name
        if t.kind == 'VAR' or (t.kind == 'KEYWORD'):
            name = t.value
            self.tok.next()

            # Check for ` ` backtick operator (e.g. `contains`)
            if self.tok.peek().kind == 'BACKTICK':
                # This is: expr `op` expr
                self.tok.next()  # backtick
                op = self.tok.next().value  # operator name
                self.tok.expect('BACKTICK')
                right = self._parse_atomic_type()
                return AppType(func=NamedType(QualifiedIdent([op])),
                               args=[PrimType('x'), right])

            # Check if it's a qualified name (dot-separated)
            parts = [name]
            while self.tok.peek().kind == 'DOT':
                self.tok.next()
                n = self.tok.next()
                if n.kind in ('VAR', 'KEYWORD', 'INT'):
                    parts.append(n.value)
                else:
                    break
            if len(parts) > 1:
                named = NamedType(QualifiedIdent(parts))
            else:
                # Could be a type variable
                named = TypeVar(name) if name[0].islower() else NamedType(QualifiedIdent([name]))

            # Application?
            if self._is_type_app():
                args = []
                while self._is_type_app():
                    args.append(self._parse_atomic_type())
                    # Effect keywords like Pure/ST/Lemma can have only
                    # ONE type arg (the return type); subsequent LPAREN
                    # are contract clauses, not type args.
                    if name in ('Pure', 'ST', 'Lemma', 'Tot', 'GTot', 'Dv', 'ML', 'Exn'):
                        break
                return AppType(func=named, args=args)

            return named

        # INT
        if t.kind == 'INT':
            self.tok.next()
            return Const(int(t.value))

        # Tuple/Lambda starts normally
        raise SyntaxError(f'Unexpected token in type: {t}')

    def _is_type_app(self) -> bool:
        """Check if next token starts a type application argument.
        Only returns True for things that can actually be types."""
        t = self.tok.peek()
        if t.kind == 'LPAREN':
            return True
        if t.kind == 'VAR':
            return True
        if t.kind == 'KEYWORD' and t.value in (
            'Type', 'Type0', 'eqtype', 'prop', 'bool', 'int', 'nat',
            'string', 'float', 'unit', 'list', 'option', 'Set', 'FStar',
            'Buffer', 'HyperStack', 'Heap', 'Prims'
        ):
            return True
        if t.kind in ('INT', 'FLOAT'):
            return True
        return False

    def _parse_term(self) -> Term:
        """Parse a general term/expression."""
        return self._parse_disjunction()

    def _parse_disjunction(self) -> Term:
        left = self._parse_conjunction()
        while self.tok.peek().kind in ('DISJUNCTION',) or \
              (self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == '\\/'):
            if self.tok.peek().kind == 'DISJUNCTION':
                self.tok.next()
            else:
                self.tok.next()  # keyword value
            right = self._parse_conjunction()
            left = BinOp(op='or', left=left, right=right)
        return left

    def _parse_conjunction(self) -> Term:
        left = self._parse_implication()
        while self.tok.peek().kind in ('CONJUNCTION', 'AMP_CONJUNCTION') or \
              (self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == '/\\'):
            if self.tok.peek().kind in ('CONJUNCTION', 'AMP_CONJUNCTION'):
                self.tok.next()
            else:
                self.tok.next()
            right = self._parse_implication()
            left = BinOp(op='and', left=left, right=right)
        return left

    def _parse_implication(self) -> Term:
        left = self._parse_iff()
        if self.tok.peek().kind == 'IMPLIES' or \
           (self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == '==>') or \
           (self.tok.peek().kind == 'RARROW' and self.tok.peek().value == '=>') or \
           (self.tok.peek().kind == 'DOUBLE_ARROW' and self.tok.peek().value == '=>') or \
           (self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == '=>'):
            self.tok.next()
            right = self._parse_implication()  # right-associative
            left = BinOp(op='==>', left=left, right=right)
        return left

    def _parse_iff(self) -> Term:
        left = self._parse_equality()
        if self.tok.peek().kind == 'IFF':
            self.tok.next()
            right = self._parse_equality()
            left = BinOp(op='<==>', left=left, right=right)
        return left

    def _parse_equality(self) -> Term:
        left = self._parse_comparison()
        while self.tok.peek().kind in ('EQUALS', 'EQUALS_SIGN') or \
              (self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == '='):
            op = self.tok.next().value
            right = self._parse_comparison()
            if op == '=' or op == '==':
                left = BinOp(op='==', left=left, right=right)
            else:
                left = BinOp(op=op, left=left, right=right)
        # Also check for !=,  <> 
        if self.tok.peek().kind == 'BANG':
            self.tok.next()
            if self.tok.peek().kind == 'EQUALS_SIGN':
                self.tok.next()
                right = self._parse_comparison()
                left = BinOp(op='!=', left=left, right=right)
        return left

    def _parse_comparison(self) -> Term:
        left = self._parse_addition()
        # Check for comparison operators (<, >, <=, >=)
        while self.tok.peek().kind in ('LESS', 'GREATER', 'LESS_EQUAL', 'GREATER_EQUAL') or \
              (self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value in ('<', '>')):
            op = self.tok.next().value
            # Handle `<>` (F* not-equal) — two separate tokens
            if op == '<' and self.tok.peek().kind in ('GREATER',) and \
               self.tok.peek().value in ('>',):
                self.tok.next()
                right = self._parse_addition()
                left = BinOp(op='!=', left=left, right=right)
            else:
                right = self._parse_addition()
                left = BinOp(op=op, left=left, right=right)
        return left

    def _parse_addition(self) -> Term:
        left = self._parse_multiplication()
        while self.tok.peek().kind == 'PLUS' or self.tok.peek().kind == 'MINUS':
            op = self.tok.next().value if self.tok.peek().kind == 'PLUS' else self.tok.next().value
            right = self._parse_multiplication()
            left = BinOp(op=op, left=left, right=right)
        return left

    def _parse_multiplication(self) -> Term:
        left = self._parse_unary()
        while self.tok.peek().kind in ('STAR', 'SLASH', 'PERCENT'):
            op = self.tok.next().value
            right = self._parse_unary()
            left = BinOp(op=op, left=left, right=right)
        return left

    def _parse_unary(self) -> Term:
        if self.tok.peek().kind == 'MINUS' or self.tok.peek().kind == 'TILDE':
            op = self.tok.next().value
            expr = self._parse_atom()
            return UnaryOp(op='not' if op == '~' else '-', expr=expr)
        if self.tok.peek().kind == 'BANG':
            self.tok.next()
            expr = self._parse_atom()
            return UnaryOp(op='!', expr=expr)
        return self._parse_atom()

    def _parse_atom(self) -> Term:
        t = self.tok.peek()

        # LBRACE — record literal or record update
        if t.kind == 'LBRACE':
            self.tok.next()
            # Check for record update: `{ expr with field = val; ... }`
            if self.tok.peek().kind != 'RBRACE':
                inner = self._parse_term()
                if self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == 'with':
                    self.tok.next()
                    updates = self._parse_record_updates()
                    self.tok.expect('RBRACE')
                    return RecordUpdate(expr=inner, updates=updates)
                # Could be just `{ expr }` — skip
                self.tok.expect('RBRACE')
                return inner
            self.tok.expect('RBRACE')
            return Const(True)

        # LPAREN
        if t.kind == 'LPAREN':
            self.tok.next()
            if self.tok.peek().kind == 'RPAREN':
                self.tok.next()
                return Const(None)  # unit
            expr = self._parse_term()
            # Check for tuple
            if self.tok.peek().kind == 'COMMA':
                self.tok.next()
                items = [expr]
                while True:
                    items.append(self._parse_term())
                    if not self.tok.skip('COMMA'):
                        break
                self.tok.expect('RPAREN')
                return App(Var('tuple'), items)
            self.tok.expect('RPAREN')
            return expr

        # LBRACKET (for SMTPat and attributes)
        if t.kind == 'LBRACKET':
            self.tok.next()
            # Check for SMTPat
            if self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == 'SMTPat':
                self.tok.next()
                self.tok.expect('LPAREN')
                pat_expr = self._parse_term()
                self.tok.expect('RPAREN')
                self.tok.expect('RBRACKET')
                return App(Var('SMTPat'), [pat_expr])
            # Skip brackets content
            depth = 1
            while depth > 0 and self.tok.peek().kind != 'EOF':
                if self.tok.next().kind == 'RBRACKET':
                    depth -= 1
            return Const(True)

        # forall / exists
        if t.kind == 'KEYWORD' and t.value in ('forall', 'exists'):
            return self._parse_quantifier()

        # fun
        if t.kind == 'KEYWORD' and t.value == 'fun':
            return self._parse_lambda()

        # match
        if t.kind == 'KEYWORD' and t.value == 'match':
            return self._parse_match()

        # if
        if t.kind == 'KEYWORD' and t.value == 'if':
            return self._parse_if()

        # let
        if t.kind == 'KEYWORD' and t.value == 'let':
            return self._parse_let_expr()

        # True / False
        if t.kind == 'BOOL':
            self.tok.next()
            return Const(t.value == 'True')

        # Some / None
        if t.kind == 'KEYWORD' and t.value == 'None':
            self.tok.next()
            return Var('None')
        if t.kind == 'KEYWORD' and t.value == 'Some':
            self.tok.next()
            if self.tok.peek().kind == 'LPAREN':
                self.tok.next()
                arg = self._parse_term()
                self.tok.expect('RPAREN')
                return App(Var('Some'), [arg])
            return Var('Some')

        # INT / FLOAT
        if t.kind == 'INT':
            self.tok.next()
            return Const(int(t.value))
        if t.kind == 'FLOAT':
            self.tok.next()
            return Const(float(t.value))

        # STRING
        if t.kind == 'STRING':
            self.tok.next()
            return Const(t.value[1:-1])  # strip quotes

        # Variable / Identifier
        if t.kind == 'VAR' or t.kind == 'KEYWORD':
            name = t.value
            self.tok.next()

            # Check for backtick operators: `h `contains` ref`
            if self.tok.peek().kind == 'BACKTICK':
                self.tok.next()
                op = self.tok.next().value
                self.tok.expect('BACKTICK')
                right = self._parse_atom()
                return BinOp(op=op, left=Var(name), right=right)

            # Check for `!x` dereference
            # Check for `.field`
            base = self._build_postfix(name)
            return self._parse_postfix(base)

        # DOT only (e.g. `.data` in record update)
        if t.kind == 'DOT':
            return self._parse_postfix(Var('.'))

        # UNDERSCORE (wild in patterns)
        if t.kind == 'UNDERSCORE':
            self.tok.next()
            return Var('_')

        # MINUS (negative number)
        if t.kind == 'MINUS':
            self.tok.next()
            if self.tok.peek().kind == 'INT':
                val = int(self.tok.next().value)
                return Const(-val)
            if self.tok.peek().kind == 'FLOAT':
                val = float(self.tok.next().value)
                return Const(-val)
            return UnaryOp(op='-', expr=self._parse_atom())

        # TILDE (negation in formulas)
        if t.kind == 'TILDE':
            self.tok.next()
            return UnaryOp(op='not', expr=self._parse_atom())

        # HASH (type application marker in args)
        if t.kind == 'HASH':
            self.tok.next()
            return self._parse_atom()

        raise SyntaxError(f'Unexpected token in expression: {t}')

    def _build_postfix(self, name: str) -> Term:
        """Build a variable/app reference with possible qualified name and postfix ops."""
        # Build qualified name
        parts = [name]
        while self.tok.peek().kind == 'DOT':
            self.tok.next()
            n = self.tok.next()
            if n.kind in ('VAR', 'KEYWORD', 'INT'):
                parts.append(n.value)
            else:
                self.tok.pos -= 2  # un-consume dot and n
                break

        base: Term
        if len(parts) > 1:
            base = QualifiedVar(QualifiedIdent(parts))
        else:
            base = Var(parts[0])

        return base

    def _parse_postfix(self, base: Term) -> Term:
        """Apply postfix operations: field access, app, array index, implicit app."""
        while True:
            t = self.tok.peek()
            # Application: LPAREN with args
            if t.kind == 'LPAREN':
                self.tok.next()
                if self.tok.peek().kind == 'RPAREN':
                    self.tok.next()
                    base = App(func=base, args=[])
                else:
                    args = self._parse_call_args()
                    self.tok.expect('RPAREN')
                    base = App(func=base, args=args)
            # Field access: .field
            elif t.kind == 'DOT':
                self.tok.next()
                fname = self.tok.next()
                if fname.kind in ('VAR', 'KEYWORD', 'INT'):
                    # Check for record update: `{ buf with field = val }`
                    if self.tok.peek().kind == 'LBRACE':
                        self.tok.next()
                        self.tok.expect('KEYWORD', 'with')
                        updates = self._parse_record_updates()
                        self.tok.expect('RBRACE')
                        base = RecordUpdate(expr=base, updates=updates)
                    else:
                        base = FieldAccess(expr=base, field=fname.value)
                else:
                    break
            # Subscript: `[i]`
            elif t.kind == 'LBRACKET':
                self.tok.next()
                idx = self._parse_term()
                self.tok.expect('RBRACKET')
                base = ArrayIndex(arr=base, index=idx)
            # Check for BACKTICK operator: h `contains` ref
            elif t.kind == 'BACKTICK':
                self.tok.next()
                op = self.tok.next().value
                self.tok.expect('BACKTICK')
                right = self._parse_atom()
                base = BinOp(op=op, left=base, right=right)
            # Implicit application: `f x` (unparenthesized)
            # Only apply when base is a Var/App (a function-like thing)
            # and next token looks like an argument start.
            # Does NOT apply to multi-part qualified names like `cache.entries`
            # (which are field accesses, not function expressions).
            elif self._is_implicit_app() and not self._is_field_access(base):
                args = []
                while self._is_implicit_app():
                    args.append(self._parse_implicit_arg())
                base = App(func=base, args=args)
            else:
                break
        return base

    def _is_field_access(self, base: Term) -> bool:
        """Check if the base expression is a field access result.
        Implicit app should not apply to field accesses.
        Module-qualified names (first part uppercase) ARE function names.
        Field accesses (first part lowercase) are values, not functions."""
        if isinstance(base, QualifiedVar):
            parts = base.path.parts
            if len(parts) >= 2 and parts[0][0].islower():
                return True  # e.g. cache.entries, buf.head, h0.data_ref
        if isinstance(base, FieldAccess):
            return True
        return False

    def _is_implicit_app(self) -> bool:
        """Check if next token starts an unparenthesized function argument.
        Avoids consuming binary operators and structural tokens."""
        t = self.tok.peek()
        if t.kind in ('EOF', 'RPAREN', 'RBRACE', 'RBRACKET',
                      'SEMICOLON', 'COMMA', 'COLON', 'ARROW', 'BAR',
                      'DOT', 'EQUALS_SIGN', 'EQUALS',
                      'IMPLIES', 'IFF', 'DISJUNCTION', 'CONJUNCTION',
                      'AMP_CONJUNCTION',
                      'LESS', 'LESS_EQUAL', 'GREATER', 'GREATER_EQUAL',
                      'PLUS', 'MINUS', 'STAR', 'SLASH', 'PERCENT',
                      'BACKTICK', 'AT', 'HASH', 'HAT', 'BANG',
                      'PIPE_LEFT', 'PIPE_RIGHT',
                      'LBRACKET', 'RBRACKET'):
            return False
        if t.kind == 'KEYWORD' and t.value in (
            'then', 'else', 'with', 'in', 'let', 'where',
            'requires', 'ensures', 'decreases',
            'fun', 'match', 'if', 'let',
            'forall', 'exists',
            'Tot', 'GTot', 'Pure', 'ST', 'Lemma', 'Dv', 'ML', 'Exn',
            'and', 'or', 'not',
        ):
            return False
        return True

    def _parse_implicit_arg(self) -> Term:
        """Parse a single unparenthesized function argument."""
        t = self.tok.peek()
        if t.kind == 'LBRACE':
            self.tok.next()
            # Could be record literal or nested
            arg = self._parse_term()
            self.tok.expect('RBRACE')
            return arg
        if t.kind == 'LBRACKET':
            self.tok.next()
            arg = self._parse_term()
            while self.tok.peek().kind == 'SEMICOLON':
                self.tok.next()
                more = self._parse_term()
                arg = App(Var('Cons'), [arg, more])
            self.tok.expect('RBRACKET')
            return arg
        return self._parse_atom()

    def _parse_call_args(self) -> List[Term]:
        args = []
        while self.tok.peek().kind != 'RPAREN' and self.tok.peek().kind != 'EOF':
            args.append(self._parse_term())
            if self.tok.peek().kind == 'COMMA':
                self.tok.next()
        return args

    def _parse_record_updates(self) -> List[tuple[str, Term]]:
        updates = []
        while self.tok.peek().kind != 'RBRACE':
            fname_t = self.tok.next()
            fname = fname_t.value
            if fname_t.kind == 'RBRACE':
                break
            if self.tok.peek().kind == 'EQUALS_SIGN' or (self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == '='):
                self.tok.next()
                val = self._parse_term()
                updates.append((fname, val))
            if self.tok.peek().kind == 'SEMICOLON':
                self.tok.next()
        return updates

    def _parse_quantifier(self) -> Term:
        is_forall = self.tok.next().value == 'forall'
        # Parse binders
        binders = self._parse_quantifier_binders()
        # Body
        if self.tok.peek().kind == 'DOT':
            self.tok.next()
        body = self._parse_term()
        if is_forall:
            return Forall(binders=binders, body=body)
        else:
            return Exists(binders=binders, body=body)

    def _parse_quantifier_binders(self) -> List[Binder]:
        binders = []
        while True:
            t = self.tok.peek()
            if t.kind == 'LPAREN':
                self.tok.next()
                if self.tok.peek().kind == 'RPAREN':
                    self.tok.next()
                    break
                # Collect multiple names before COLON: `(i j: nat)`
                names = []
                while self.tok.peek().kind != 'COLON':
                    if self.tok.peek().kind in ('VAR', 'KEYWORD'):
                        names.append(self.tok.next().value)
                    elif self.tok.peek().kind == 'RPAREN':
                        break
                    else:
                        break
                if self.tok.peek().kind == 'COLON':
                    self.tok.next()
                    typ = self._parse_type_expr()
                    for n in names:
                        binders.append(Binder(name=n, typ=typ))
                self.tok.expect('RPAREN')
            elif t.kind == 'VAR':
                name = self.tok.next().value
                if self.tok.peek().kind == 'COLON':
                    self.tok.next()
                    typ = self._parse_type_expr()
                    binders.append(Binder(name=name, typ=typ))
                else:
                    binders.append(Binder(name=name, typ=TypeVar('_', kind=PrimType('Type'))))
                if self.tok.peek().kind == 'DOT' or self.tok.peek().kind == 'ARROW':
                    break
                if self.tok.peek().kind == 'COMMA':
                    self.tok.next()
            else:
                break
        return binders

    def _parse_lambda(self) -> Term:
        self.tok.expect('KEYWORD', 'fun')
        # Parse binder(s)
        params = []
        # Single var or parenthesized binder
        while True:
            if self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value in ('->',):
                if self.tok.peek().value == '->':
                    break
            if self.tok.peek().kind == 'ARROW':
                break
            if self.tok.peek().kind == 'VAR':
                pname = self.tok.next().value
                params.append(pname)
            elif self.tok.peek().kind == 'LPAREN':
                self.tok.next()
                pname = self.tok.next().value if self.tok.peek().kind != 'RPAREN' else ''
                # Skip type annotation after colon
                if self.tok.skip('COLON'):
                    self._parse_type_expr()
                self.tok.expect('RPAREN')
                if pname:
                    params.append(pname)
            elif self.tok.peek().kind == 'KEYWORD':
                # Could be 'result' or similar
                pname = self.tok.next().value
                params.append(pname)
            else:
                break

        if self.tok.peek().kind == 'ARROW':
            self.tok.next()  # ->

        body = self._parse_term()
        return Lambda(params=params, body=body)

    def _parse_match(self) -> Term:
        self.tok.expect('KEYWORD', 'match')
        expr = self._parse_term()
        # Handle `match x, y with` -> tuple match
        if self.tok.peek().kind == 'COMMA':
            items = [expr]
            while self.tok.peek().kind == 'COMMA':
                self.tok.next()
                items.append(self._parse_term())
            expr = App(Var('tuple'), items)
        self.tok.expect('KEYWORD', 'with')
        cases = []
        while self.tok.peek().kind == 'BAR':
            self.tok.next()
            pat = self._parse_pattern()
            # Handle tuple patterns: `| a, b -> expr`
            if self.tok.peek().kind == 'COMMA':
                pats = [pat]
                while self.tok.peek().kind == 'COMMA':
                    self.tok.next()
                    pats.append(self._parse_pattern())
                pat = PatTuple(pats)
            if self.tok.peek().kind == 'ARROW':
                self.tok.next()
            case_expr = self._parse_term()
            cases.append(MatchCase(pattern=pat, expr=case_expr))
        return Match(expr=expr, cases=cases)

    def _parse_if(self) -> Term:
        self.tok.expect('KEYWORD', 'if')
        cond = self._parse_term()
        self.tok.expect('KEYWORD', 'then')
        then_expr = self._parse_term()
        # Skip else
        if self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == 'else':
            self.tok.next()
            else_expr = self._parse_term()
        else:
            else_expr = Const(None)
        return IfExpr(cond=cond, then_expr=then_expr, else_expr=else_expr)

    def _parse_let_expr(self) -> Term:
        """Parse `let x = e1 in e2` expression (rare in interfaces)."""
        self.tok.expect('KEYWORD', 'let')
        name = self.tok.next().value
        self.tok.expect('EQUALS_SIGN')
        val = self._parse_term()
        self.tok.expect('KEYWORD', 'in')
        body = self._parse_term()
        return App(Var('let_in'), [Var(name), val, body])

    def _parse_pattern(self) -> Pattern:
        """Parse a match pattern."""
        t = self.tok.peek()
        if t.kind == 'UNDERSCORE':
            self.tok.next()
            return PatWild()

        if t.kind == 'INT':
            self.tok.next()
            return PatConst(int(t.value))
        if t.kind == 'VAR' or t.kind == 'KEYWORD':
            name = t.value
            self.tok.next()
            # Could be a constructor with args
            # Check for parenthesized args: `Some(v, ...)`
            if self.tok.peek().kind == 'LPAREN':
                self.tok.next()
                args = []
                while self.tok.peek().kind != 'RPAREN':
                    args.append(self._parse_pattern())
                    if self.tok.peek().kind == 'COMMA':
                        self.tok.next()
                self.tok.expect('RPAREN')
                return PatApp(name, args)
            # Check for unparenthesized constructor arg: `Some v`
            # (next token is a variable, not an operator)
            if self.tok.peek().kind == 'VAR' and name.istitle():
                arg = self._parse_pattern()
                return PatApp(name, [arg])
            # :: cons pattern
            if self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == '::':
                self.tok.next()
                tail = self._parse_pattern()
                return PatCons(head=PatVar(name), tail=tail)
            # Or if next is BAR (alternation)
            if self.tok.peek().kind == 'BAR':
                pats = [PatVar(name)]
                while self.tok.peek().kind == 'BAR':
                    self.tok.next()
                    pats.append(self._parse_pattern())
                return PatOr(pats)
            return PatVar(name)
        # Also handle KEYWORD patterns (Some, None, True, False)
        if t.kind == 'KEYWORD':
            name = t.value
            self.tok.next()
            if t.value == 'None':
                return PatApp('None', [])
            elif t.value in ('True', 'False'):
                return PatConst(t.value == 'True')
            elif t.value == 'Some':
                if self.tok.peek().kind == 'LPAREN':
                    self.tok.next()
                    args = []
                    while self.tok.peek().kind != 'RPAREN':
                        args.append(self._parse_pattern())
                        if self.tok.peek().kind == 'COMMA':
                            self.tok.next()
                    self.tok.expect('RPAREN')
                    return PatApp('Some', args)
                return PatApp('Some', [PatWild()])
            return PatVar(name)
            if self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == '::':
                self.tok.next()
                tail = self._parse_pattern()
                return PatCons(head=PatVar(t.value), tail=tail)
            # Or if next is BAR (alternation)
            if self.tok.peek().kind == 'BAR':
                pats = [PatVar(t.value)]
                while self.tok.peek().kind == 'BAR':
                    self.tok.next()
                    pats.append(self._parse_pattern())
                return PatOr(pats)
            return PatVar(t.value)
        return PatWild()

    # ── Val declarations ─────────────────────────────────────────────────

    def _parse_val(self) -> Optional[ValDecl]:
        self.tok.expect('KEYWORD', 'val')
        name = self.tok.next().value if self.tok.peek().kind == 'VAR' else self.tok.expect('VAR').value
        self.tok.expect('COLON')

        # Parse arrow-type: `param1 -> param2 -> ... -> effect ret (requires ...) (ensures ...)`
        params = []
        return_type = None
        effect = 'Tot'
        contract = PrePost()

        # Parse binders separated by arrows
        has_more = True
        while has_more:
            t = self.tok.peek()

            # Drain extra binders from multi-name groups
            if self._extra_binders:
                params.append(self._extra_binders.pop(0))
                continue

            # Check for effect keyword
            if t.kind == 'KEYWORD' and t.value in ('Tot', 'GTot', 'Pure', 'ST', 'Lemma', 'Dv', 'ML', 'Exn'):
                effect = t.value
                self.tok.next()
                if effect == 'Lemma':
                    # Lemma has NO return type — contracts directly follow
                    return_type = None
                    contract = self._parse_contract_clauses()
                else:
                    # Pure/ST/Tot/GTot: parse return type first
                    return_type = self._parse_val_return_type()
                    contract = self._parse_contract_clauses()
                break
            elif t.kind == 'ARROW':
                self.tok.next()
                continue
            elif t.kind == 'KEYWORD' and t.value == 'requires':
                contract = self._parse_contract_clauses_non_paren()
                break
            elif t.kind == 'EOF' or t.kind == 'LBRACKET':
                # LBRACKET = SMTPat attribute at end
                # Skip attributes here
                break
            else:
                try:
                    b = self._parse_binder()
                    if b is not None:
                        params.append(b)
                        # Drain any extra binders from multi-name groups
                        while self._extra_binders:
                            params.append(self._extra_binders.pop(0))
                    else:
                        has_more = False
                except (SyntaxError, StopIteration):
                    has_more = False

        # Handle remaining SMTPats / attributes on val
        while self.tok.peek().kind == 'LBRACKET':
            # Skip brackets
            self.tok.next()
            depth = 1
            while depth > 0 and self.tok.peek().kind != 'EOF':
                n = self.tok.next()
                if n.kind == 'LBRACKET': depth += 1
                elif n.kind == 'RBRACKET': depth -= 1

        # Handle trailing "assume val" pattern: if no type was found,
        # try to use the last param as the return type
        if effect == 'Tot' and return_type is None:
            if params:
                last = params[-1]
                return_type = last.typ
                params = params[:-1]

        decl = ValDecl(
            name=name,
            params=params,
            return_type=return_type,
            effect=effect,
            contract=contract,
        )
        return decl

    def _parse_val_return_type(self) -> TypeExpr:
        """Parse a return type expression in a val declaration.
        Stops at LPAREN (start of contract clause) or ARROW (next binder)."""
        return self._parse_simple_type()

    def _parse_simple_type(self) -> TypeExpr:
        """Parse a simple (non-applied) type: primitive, named, or qualified,
        with optional refinement. Does NOT parse type application `t args`,
        since that would eat contract clauses."""
        # Collect qualified name parts
        parts = []
        t = self.tok.peek()
        prim_types = ('Type', 'Type0', 'eqtype', 'prop', 'bool', 'int',
                      'nat', 'string', 'float', 'unit')
        if t.kind == 'KEYWORD' and t.value in prim_types:
            self.tok.next()
            typ: TypeExpr = PrimType(t.value)
        elif t.kind == 'VAR' or t.kind == 'KEYWORD':
            name = self.tok.next().value
            parts = [name]
            while self.tok.peek().kind == 'DOT':
                self.tok.next()
                p = self.tok.next()
                if p.kind in ('VAR', 'KEYWORD', 'INT'):
                    parts.append(p.value)
                else:
                    break
            if len(parts) > 1:
                typ = NamedType(QualifiedIdent(parts))
            else:
                typ = NamedType(QualifiedIdent(parts))
            # Type application: `option (type)`, `list (type)`, etc.
            # Type application via parentheses: `option (type)`
            if self.tok.peek().kind == 'LPAREN':
                type_ctors = ('option', 'list', 'Set', 'buffer', 'ref', 'array',
                             'FStar', 'Prims', 'HyperStack', 'Heap')
                name_str = parts[0] if parts else ''
                if name_str in type_ctors or (len(parts) > 1 and parts[0] in type_ctors):
                    self.tok.next()  # consume (
                    # The inner type may be a tuple: `(int * type)`
                    first_inner = self._parse_simple_type()
                    if self.tok.peek().kind == 'STAR':
                        self.tok.next()
                        items = [first_inner]
                        while True:
                            items.append(self._parse_simple_type())
                            if not self.tok.skip('STAR'):
                                break
                        inner = TupleType(items=items)
                    else:
                        inner = first_inner
                    self.tok.expect('RPAREN')
                    typ = AppType(func=typ, args=[inner])
            # Implicit type application: `option int` → AppType(option, [int])
            # Only applies to known type constructors
            if self._is_next_type_arg():
                type_ctors = ('option', 'list', 'Set', 'buffer', 'ref', 'array')
                name_str = parts[0] if parts else ''
                if name_str in type_ctors:
                    arg = self._parse_simple_arg_type()
                    typ = AppType(func=typ, args=[arg])
        elif t.kind == 'LPAREN':
            self.tok.next()
            # Recursively parse the inside as a simple type
            inner = self._parse_simple_type()
            # Check for tuple: `(int * type)` after the first type
            if self.tok.peek().kind == 'STAR':
                self.tok.next()
                items = [inner]
                while True:
                    items.append(self._parse_simple_type())
                    if not self.tok.skip('STAR'):
                        break
                self.tok.expect('RPAREN')
                return TupleType(items=items)
            self.tok.expect('RPAREN')
            return inner
        else:
            return self._parse_atomic_type()  # fallback
        # Check for refinement
        if self.tok.peek().kind == 'LBRACE':
            self.tok.next()
            pred = self._parse_term()
            self.tok.expect('RBRACE')
            b = Binder(name='x', typ=typ)
            return RefinedType(binder=b, predicate=pred)

        return typ



    def _is_next_type_arg(self) -> bool:
        """Check if the next token starts a type argument.
        This is for implicit type application like `option int`."""
        t = self.tok.peek()
        if t.kind == 'KEYWORD' and t.value in (
            'Type', 'Type0', 'eqtype', 'prop', 'bool', 'int', 'nat',
            'string', 'float', 'unit'
        ):
            return True
        if t.kind == 'VAR':
            return True
        if t.kind in ('INT', 'FLOAT'):
            return True
        # Don't consume LPAREN — that's for contract clauses or explicit app
        if t.kind in ('LPAREN', 'LBRACE'):
            return False
        return False

    def _parse_simple_arg_type(self) -> TypeExpr:
        """Parse a single type argument for implicit type application."""
        t = self.tok.peek()
        if t.kind == 'KEYWORD' and t.value in (
            'Type', 'Type0', 'eqtype', 'prop', 'bool', 'int', 'nat',
            'string', 'float', 'unit'
        ):
            self.tok.next()
            return PrimType(t.value)
        if t.kind == 'VAR':
            name = self.tok.next().value
            parts = [name]
            while self.tok.peek().kind == 'DOT':
                self.tok.next()
                p = self.tok.next()
                if p.kind in ('VAR', 'KEYWORD', 'INT'):
                    parts.append(p.value)
                else:
                    break
            return NamedType(QualifiedIdent(parts))
        return self._parse_simple_type()
    def _parse_binder(self) -> Optional[Binder]:
        """Parse a single binder: `name: type` or `(name: type)` or `_ : type`.
        The type expression parser stops at ARROW (since arrows separate
        binders in val declarations)."""
        t = self.tok.peek()

        # Underbar wild binder
        if t.kind == 'UNDERSCORE':
            self.tok.next()
            if self.tok.peek().kind == 'COLON':
                self.tok.next()
                typ = self._parse_binder_type()
                return Binder(name=None, typ=typ)
            return Binder(name=None, typ=TypeVar('_'))

        # Implicit: `#name: type`
        implicit = False
        if t.kind == 'HASH':
            self.tok.next()
            implicit = True
            t = self.tok.peek()  # refresh t after consuming #

        # Parenthesized: `(name: type)`, `(#name: type)`, or `(x y: type)`
        if t.kind == 'LPAREN':
            self.tok.next()
            if self.tok.peek().kind == 'RPAREN':
                self.tok.next()
                return None
            # Check for implicit binder: `(#name: type)`
            implicit_inner = implicit
            if self.tok.peek().kind == 'HASH':
                self.tok.next()
                implicit_inner = True
            # Could be `(name: type)` or just `(type)`
            names: List[str] = []
            if self.tok.peek().kind == 'VAR' or self.tok.peek().kind == 'KEYWORD':
                # Collect all consecutive names before COLON: `(x y z: type)`
                while self.tok.peek().kind in ('VAR', 'KEYWORD'):
                    names.append(self.tok.next().value)
                    # Stop collecting names if next is COLON or RPAREN
                    if self.tok.peek().kind == 'COLON' or self.tok.peek().kind == 'RPAREN':
                        break
                    # If next is not also a VAR/KEYWORD, stop
                    if self.tok.peek().kind not in ('VAR', 'KEYWORD'):
                        break
                if self.tok.peek().kind == 'COLON':
                    self.tok.next()
                    typ = self._parse_binder_type()
                    self.tok.expect('RPAREN')
                    # Multi-name pattern: `(x y: type)` — buffer extra names
                    if len(names) > 1:
                        extra_binders = [Binder(name=n, typ=typ, implicit=implicit_inner) for n in names[1:]]
                        self._extra_binders = extra_binders + self._extra_binders
                    return Binder(name=names[0], typ=typ, implicit=implicit_inner)
                else:
                    # Just a parenthesized type (no colon)
                    # Put back the names and parse as type
                    self.tok.pos -= len(names)
                    typ = self._parse_binder_type()
                    self.tok.expect('RPAREN')
                    return Binder(name=None, typ=typ, implicit=implicit_inner)
            else:
                typ = self._parse_binder_type()
                self.tok.expect('RPAREN')
                return Binder(name=None, typ=typ, implicit=implicit_inner)

        # Simple `name : type`
        if t.kind == 'VAR' or t.kind == 'KEYWORD':
            name = t.value
            self.tok.next()
            if self.tok.peek().kind == 'COLON':
                self.tok.next()
                typ = self._parse_binder_type()
                return Binder(name=name, typ=typ, implicit=implicit)
            else:
                # Just a name (type variable)
                return Binder(name=name, typ=TypeVar(name), implicit=implicit)

        return None

    def _parse_binder_type(self) -> TypeExpr:
        """Parse a type expression that stops at ARROW, since ARROW
        separates binders in val declarations."""
        typ = self._parse_atomic_type()
        # Handle refinement: `base{pred}`
        if self.tok.peek().kind == 'LBRACE':
            self.tok.next()
            pred = self._parse_term()
            self.tok.expect('RBRACE')
            b = Binder(name='x', typ=typ)
            return RefinedType(binder=b, predicate=pred)
        # Handle COLON binder pattern: `name:type{refinement}`
        if self.tok.peek().kind == 'COLON' and isinstance(typ, TypeVar):
            name = typ.name
            self.tok.next()
            inner = self._parse_atomic_type()
            if self.tok.peek().kind == 'LBRACE':
                self.tok.next()
                pred = self._parse_term()
                self.tok.expect('RBRACE')
                return RefinedType(binder=Binder(name=name, typ=inner), predicate=pred)
            return inner
        return typ

    def _parse_contract_clauses(self) -> PrePost:
        contract = PrePost()
        # Parse requires/ensures/decreases clauses in parens
        while True:
            t = self.tok.peek()
            if t.kind == 'LPAREN':
                self.tok.next()
                body_parsed = False
                if self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == 'requires':
                    self.tok.next()
                    contract.requires = self._parse_term()
                    body_parsed = True
                elif self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == 'ensures':
                    self.tok.next()
                    # Skip `fun h ->` or `fun h0 r h1 ->` preamble for ST
                    if self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == 'fun':
                        self._skip_fun_preamble()
                    contract.ensures = self._parse_term()
                    body_parsed = True
                elif self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == 'decreases':
                    self.tok.next()
                    contract.decreases = self._parse_term()
                    body_parsed = True

                if body_parsed:
                    # The body may have consumed the closing RPAREN already
                    # (e.g., `(ensures (fun ...))`), or it may not
                    # (e.g., `(requires True)`).  Accept either.
                    if self.tok.peek().kind == 'RPAREN':
                        self.tok.next()
                else:
                    # Non-body content; skip to matching RPAREN
                    depth = 1
                    while depth > 0 and self.tok.peek().kind != 'EOF':
                        if self.tok.peek().kind == 'LPAREN':
                            depth += 1
                        elif self.tok.peek().kind == 'RPAREN':
                            depth -= 1
                            if depth == 0:
                                self.tok.next()
                                break
                        self.tok.next()
            elif t.kind == 'KEYWORD' and t.value in ('requires', 'ensures', 'decreases'):
                kw = self.tok.next().value
                if kw == 'requires':
                    contract.requires = self._parse_term()
                elif kw == 'ensures':
                    contract.ensures = self._parse_term()
                elif kw == 'decreases':
                    contract.decreases = self._parse_term()
            elif t.kind == 'LBRACKET':
                # SMTPat
                self.tok.next()
                if self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == 'SMTPat':
                    self.tok.next()
                    self.tok.expect('LPAREN')
                    pat = self._parse_term()
                    self.tok.expect('RPAREN')
                    contract.smt_pats.append([pat])
                else:
                    # Skip bracket content
                    depth = 1
                    while depth > 0 and self.tok.peek().kind != 'EOF':
                        n = self.tok.next()
                        if n.kind == 'LBRACKET':
                            depth += 1
                        elif n.kind == 'RBRACKET':
                            depth -= 1
            else:
                break
        return contract

    def _skip_fun_preamble(self):
        """Skip `fun h ->`, `fun h0 r h1 ->`, `fun h0 () h1 ->`, etc. before ensures body."""
        self.tok.expect('KEYWORD', 'fun')
        # Skip binder names and parenthesized patterns
        while True:
            t = self.tok.peek()
            if t.kind == 'ARROW':
                self.tok.next()
                break
            if t.kind == 'KEYWORD' and t.value in ('->',):
                self.tok.next()
                break
            if t.kind == 'VAR' or t.kind == 'KEYWORD':
                self.tok.next()
            elif t.kind == 'LPAREN':
                # Skip parenthesized patterns like `()`, `(v)`, etc.
                self.tok.next()
                depth = 1
                while depth > 0 and self.tok.peek().kind != 'EOF':
                    if self.tok.peek().kind == 'LPAREN':
                        depth += 1
                    elif self.tok.peek().kind == 'RPAREN':
                        depth -= 1
                        if depth == 0:
                            self.tok.next()
                            break
                    self.tok.next()
            else:
                break

    def _parse_assume_val(self) -> Optional[ValDecl]:
        self.tok.expect('KEYWORD', 'assume')
        return self._parse_val()

    # ── Let declarations ───────────────────────────────────────────────────

    def _parse_let(self) -> Optional[LetDecl]:
        self.tok.expect('KEYWORD', 'let')
        rec = self.tok.skip('KEYWORD', 'rec')

        name = self.tok.next().value if self.tok.peek().kind == 'VAR' else self.tok.expect('VAR').value

        # Type params? (uncommon but possible: `#a: Type`)
        params = []
        while self.tok.peek().kind in ('HASH', 'LPAREN', 'VAR'):
            # Drain extra binders first
            if self._extra_binders:
                params.append(self._extra_binders.pop(0))
                continue
            if self.tok.peek().kind == 'HASH':
                # #a: Type  -- type parameter
                self.tok.next()
                pname = self.tok.next().value
                if self.tok.peek().kind == 'COLON':
                    self.tok.next()
                    pkind = self._parse_type_expr()
                else:
                    pkind = PrimType('Type')
                params.append(Binder(name=pname, typ=pkind, implicit=True))
            elif self.tok.peek().kind == 'LPAREN':
                b = self._parse_binder()
                if b is not None:
                    params.append(b)
                    # Drain any extra binders from multi-name groups
                    while self._extra_binders:
                        params.append(self._extra_binders.pop(0))
                else:
                    break
            else:
                # Unadorned var: could be a single binder without parens
                # Actually let's parse binder (which will check for colon)
                # First: check if this VAR is actually followed by COLON
                pname = self.tok.next().value if self.tok.peek().kind == 'VAR' else None
                if pname and self.tok.peek().kind == 'COLON':
                    self.tok.pos -= 1  # put back pname
                    b = self._parse_binder()
                    if b:
                        params.append(b)
                    else:
                        break
                elif pname and self.tok.peek().kind in ('ARROW',):
                    # just a parameter name without type
                    params.append(Binder(name=pname, typ=TypeVar(pname)))
                elif pname:
                    # treat as a simple name, no binder -> body follows
                    self.tok.pos -= 1  # put back
                    break
                else:
                    break

        # Return type annotation
        typ = None
        if self.tok.peek().kind == 'COLON':
            self.tok.next()
            typ = self._parse_simple_type()
            # Effect keyword like `Pure` returns just the effect name as a type.
            # The actual return type follows as an implicit argument.
            # Consume it if present (before reaching LPAREN which starts contracts)
            if self._is_next_type_arg():
                arg = self._parse_simple_arg_type()
                if isinstance(typ, NamedType):
                    typ = AppType(func=typ, args=[arg])
                else:
                    typ = arg

        # Consume any contract clauses (requires/ensures) after the type
        # annotation, as in `let rec f ... : Effect t (requires P) (ensures Q) = ...`
        while self.tok.peek().kind == 'LPAREN':
            save_pos = self.tok.pos
            self.tok.next()  # consume (
            kw = self.tok.peek()
            if kw.kind == 'KEYWORD' and kw.value in ('requires', 'ensures', 'decreases'):
                self.tok.next()
                # Parse the contract body and skip to matching RPAREN
                depth = 1
                while depth > 0 and self.tok.peek().kind != 'EOF':
                    if self.tok.peek().kind == 'LPAREN':
                        depth += 1
                        self.tok.next()
                    elif self.tok.peek().kind == 'RPAREN':
                        depth -= 1
                        self.tok.next()  # consume RPAREN
                    else:
                        self.tok.next()
                if depth == 0:
                    continue  # successfully consumed this contract clause
            else:
                # Not a contract clause, restore position and break
                self.tok.pos = save_pos
                break

        # Equals sign + body
        if self.tok.peek().kind == 'EQUALS_SIGN' or \
           (self.tok.peek().kind == 'KEYWORD' and self.tok.peek().value == '='):
            self.tok.next()
            body = self._parse_term()
        else:
            body = None

        return LetDecl(
            name=name, params=params, typ=typ, body=body, recursive=rec
        )


# ── Entry point ──────────────────────────────────────────────────────────────

def parse_fstar(text: str) -> VeriDslProgram:
    """Parse F* text (from .fsti or veri block) into VeriDslProgram AST."""
    parser = FStarParser(text)
    return parser.parse()
