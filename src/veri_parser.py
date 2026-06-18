"""
veri_parser.py — Parse Veri DSL text into VeriDslProgram AST.

Supports the Python+SQL hybrid grammar defined in docs/dsl-grammar-v0.2.md.
"""

import re
from typing import Dict, List, Optional, Tuple, Union
from veri_ast import *

# Global field type registry shared across parser instances.
# merge_programs calls parse_veri once per block; without this, field types
# from class blocks are lost when function blocks are parsed, and FORALL
# binder types cannot be resolved.
_global_field_types: Dict[str, Dict[str, TypeExpr]] = {}

class VeriTokenizer:
    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.tokens = []
        self._tokenize()

    TOKEN_SPEC = [
        ('COMMENT',   r'#[^\n]*'),
        ('FLOAT',     r'\d+\.\d+([eE][+-]?\d+)?'),
        ('INT',       r'\d+'),
        ('STRING',    r'"[^"]*"'),
        ('KEYWORD',   r'\b(module|import|EXTERN|class|enum|variant|type|def|return|'
                      r'match|case|if|elif|else|in|lambda|'
                      r'REQUIRES|ENSURES|DECREASES|WHERE|CONSTRAINT|'
                      r'FORALL|EXISTS|IN|PURE|GHOST|LEMMA|'
                      r'STATE_READ_ONLY|STATE_WRITE_ONLY|STATE_READ_WRITE|'
                      r'True|False|None|Some|'
                      r'and|or|not|len|array_len)\b'),
        ('TYPE_KEYW', r'\b(int32|int64|float64|float32|bool|int|nat|'
                      r'string|uint32|uint64|byte|char|void|'
                      r'list|option|buffer|set|heap|mem|type)\b'),
        ('IDENT',     r'[a-zA-Z_][a-zA-Z0-9_.]*'),
        ('ARROW',     r'->'),
        ('DOUBLE_ARROW', r'=>'),
        ('IMPLIES',   r'==>'),
        ('EQUALS',    r'=='),
        ('NEQ',       r'!='),
        ('LE',        r'<='),
        ('GE',        r'>='),
        ('LT',        r'<'),
        ('GT',        r'>'),
        ('PLUS',      r'\+'),
        ('MINUS',     r'-'),
        ('STAR',      r'\*'),
        ('SLASH',     r'/'),
        ('PERCENT',   r'%'),
        ('ASSIGN',    r'='),
        ('COLON',     r':'),
        ('SEMICOLON', r';'),
        ('COMMA',     r','),
        ('DOT',       r'\.'),
        ('LPAREN',    r'\('),
        ('RPAREN',    r'\)'),
        ('LBRACKET',  r'\['),
        ('RBRACKET',  r'\]'),
        ('LBRACE',    r'\{'),
        ('RBRACE',    r'\}'),
        ('BAR',       r'\|'),
        ('UNDERSCORE', r'_'),
        ('AT',        r'@'),
        ('HASH',      r'#'),
        ('PIPE',      r'::'),
        ('WS',        r'[ \t\n\r]+'),
    ]

    TOKEN_RE = re.compile(
        '|'.join(f'(?P<{name}>{pattern})' for name, pattern in TOKEN_SPEC),
        re.DOTALL
    )

    class Token:
        def __init__(self, kind: str, value: str, pos: int):
            self.kind = kind
            self.value = value
            self.pos = pos
        def __repr__(self):
            return f'Token({self.kind}, {self.value!r})'

    def _tokenize(self):
        for m in self.TOKEN_RE.finditer(self.text):
            kind = m.lastgroup
            val = m.group()
            if kind == 'WS' or kind == 'COMMENT':
                continue
            if kind == 'KEYWORD':
                if val in ('True', 'False'):
                    kind = 'BOOL'
            elif kind == 'IDENT':
                parts = val.split('.')
                if len(parts) > 1:
                    kind = 'QIDENT'
            self.tokens.append(self.Token(kind, val, m.start()))
        self.tokens.append(self.Token('EOF', '', len(self.text)))

class VeriDslParser:
    """Parse Veri DSL text into VeriDslProgram AST."""

    def __init__(self, text: str):
        self.tok = VeriTokenizer(text)
        self.program = VeriDslProgram()
        self._field_types: dict[str, dict[str, TypeExpr]] = {}
        self._param_types: dict[str, TypeExpr] = {}
        self._quant_binders: dict[str, TypeExpr] = {}

    def parse(self) -> VeriDslProgram:
        while self.tok.tokens[0].kind != 'EOF':
            decl = self._parse_decl()
            if decl is not None:
                self.program.add(decl)
        return self.program

    def _peek(self): return self.tok.tokens[0]
    def _next(self): return self.tok.tokens.pop(0)
    def _expect(self, kind: str, value: Optional[str] = None):
        t = self._next()
        if t.kind != kind or (value is not None and t.value != value):
            raise SyntaxError(f'Expected {kind}({value}) at pos {t.pos}, got {t}')
        return t
    def _skip(self, kind: str, value: Optional[str] = None) -> bool:
        if self._peek().kind == kind and (value is None or self._peek().value == value):
            self._next()
            return True
        return False

    def _parse_decl(self) -> Optional[Declaration]:
        t = self._peek()
        if t.kind == 'KEYWORD':
            kw = t.value
            if kw == 'module': return self._parse_module()
            if kw == 'import': return self._parse_import()
            if kw == 'EXTERN': return self._parse_extern()
            if kw == 'class': return self._parse_class()
            if kw == 'enum': return self._parse_enum()
            if kw == 'variant': return self._parse_variant()
            if kw == 'type': return self._parse_type_decl()
            if kw == 'def': return self._parse_def()
            if kw == 'CONSTRAINT': self._next(); return self._parse_skipped_block('CONSTRAINT')
        elif t.kind == 'IDENT':
            name = self._next().value
            if self._peek().kind == 'COLON':
                self._next()
                typ = self._parse_type()
                self._expect('ASSIGN', '=')
                expr = self._parse_expr()
                return LetDecl(name=name, typ=typ, body=expr)
            return None
        self._next()
        return None

    def _parse_module(self) -> ModuleDecl:
        self._expect('KEYWORD', 'module')
        name = self._parse_qident()
        return ModuleDecl(name=name)

    def _parse_import(self) -> Declaration:
        """Parse: import <name>(<params>) -> <type>:  OR  import <path>"""
        self._expect('KEYWORD', 'import')
        if self._peek().kind == 'IDENT' and self._tokens(1).kind == 'LPAREN':
            # Imported function with signature
            name = self._next().value
            self._expect('LPAREN')
            params = []
            while self._peek().kind != 'RPAREN':
                pname = self._next().value
                self._expect('COLON')
                ptype = self._parse_type()
                params.append(Binder(name=pname, typ=ptype))
                self._skip('COMMA')
            self._expect('RPAREN')
            self._expect('ARROW')
            return_type = self._parse_type()
            self._expect('COLON')
            # Parse optional contract
            requires = None
            ensures = None
            if self._peek().kind == 'KEYWORD':
                if self._peek().value == 'REQUIRES':
                    self._next()
                    requires = self._parse_expr()
                if self._peek().value == 'ENSURES':
                    self._next()
                    ensures = self._parse_expr()
            return ImportedDecl(
                name=name, params=params, return_type=return_type,
                contract=PrePost(requires=requires, ensures=ensures)
            )
        else:
            # Simple module import
            path = self._parse_qident()
            return OpenDecl(path=path)

    def _tokens(self, n: int) -> Optional[dict]:
        """Peek at token n positions ahead (0 = current)."""
        idx = n
        if idx < len(self.tok.tokens):
            return self.tok.tokens[idx]
        return None

    def _parse_extern(self) -> Declaration:
        """Parse: EXTERN <name>(<params>) -> <type>:
           Optionally followed by REQUIRES/ENSURES."""
        self._expect('KEYWORD', 'EXTERN')
        name = self._next().value
        self._expect('LPAREN')
        params = []
        while self._peek().kind != 'RPAREN':
            pname = self._next().value
            self._expect('COLON')
            ptype = self._parse_type()
            params.append(Binder(name=pname, typ=ptype))
            self._skip('COMMA')
        self._expect('RPAREN')
        self._expect('ARROW')
        return_type = self._parse_type()
        self._expect('COLON')
        requires = None
        ensures = None
        while self._peek().kind == 'KEYWORD':
            if self._peek().value == 'REQUIRES':
                self._next()
                requires = self._parse_expr()
            elif self._peek().value == 'ENSURES':
                self._next()
                ensures = self._parse_expr()
            else:
                break
        return ExternDecl(
            name=name, params=params, return_type=return_type,
            contract=PrePost(requires=requires, ensures=ensures)
        )

    def _parse_qident(self) -> QualifiedIdent:
        t = self._next()
        parts = [t.value]
        while self._peek().kind == 'DOT':
            self._next()
            parts.append(self._next().value)
        return QualifiedIdent(parts)

    def _parse_class(self) -> TypeRecord:
        self._expect('KEYWORD', 'class')
        name = self._next().value
        self._expect('COLON')
        fields = []
        while True:
            # Skip blank lines/newlines
            while self._peek().kind in ('EOF',):
                if self._peek().kind == 'EOF':
                    break
            # Stop when we hit a keyword, EOF, or a line starting a new decl
            if self._peek().kind == 'EOF':
                break
            if self._peek().kind == 'KEYWORD' and self._peek().value not in ('True', 'False', 'Some', 'None', 'and', 'or', 'not'):
                kw = self._peek().value
                if kw in ('def', 'type', 'class', 'enum', 'variant', 'import'):
                    break
            if not (self._peek().kind in ('IDENT', 'TYPE_KEYW')):
                break
            fname = self._next().value
            self._expect('COLON')
            ftype = self._parse_type()
            fields.append(Binder(name=fname, typ=ftype))
            self._record_field_type(name, fname, ftype)
        return TypeRecord(name=name, fields=fields)

    def _parse_enum(self) -> TypeVariant:
        self._expect('KEYWORD', 'enum')
        name = self._next().value
        self._expect('COLON')
        ctors = []
        while self._peek().kind == 'IDENT':
            cname = self._next().value
            val = None
            if self._skip('ASSIGN', '='):
                val = int(self._next().value)
            ctors.append(Constructor(name=cname))
        return TypeVariant(name=name, constructors=ctors)

    def _parse_variant(self) -> TypeVariant:
        self._expect('KEYWORD', 'variant')
        name = self._next().value
        self._expect('COLON')
        ctors = []
        while self._skip('BAR'):
            cname = self._next().value
            args = []
            if self._skip('LPAREN'):
                while self._peek().kind != 'RPAREN':
                    aname = self._next().value
                    self._expect('COLON')
                    atype = self._parse_type()
                    args.append(Binder(name=aname, typ=atype))
                    if self._skip('COMMA'): continue
                self._expect('RPAREN')
            ctors.append(Constructor(name=cname, args=args))
        return TypeVariant(name=name, constructors=ctors)

    def _parse_type_decl(self) -> Declaration:
        self._expect('KEYWORD', 'type')
        name = self._next().value
        if self._peek().kind == 'COLON':
            self._next()
            kind = self._parse_type()
            return TypeAbstract(name=name, params=[], kind=kind)
        if self._skip('ASSIGN', '='):
            base = self._parse_type()
            if self._peek().kind == 'KEYWORD' and self._peek().value == 'WHERE':
                self._next()
                pred = self._parse_expr()
                return TypeAlias(name=name, typ=RefinedType(Binder('x', base), pred))
            return TypeAlias(name=name, typ=base)
        return TypeAbstract(name=name)

    def _has_name_ref(self, expr: object, name: str) -> bool:
        """Check if an expression (recursively) references the given name."""
        if expr is None: return False
        if isinstance(expr, Var) and expr.name == name: return True
        if isinstance(expr, QualifiedVar): return False
        if isinstance(expr, Const): return False
        # Check recursively
        for attr in ['func', 'expr', 'left', 'right', 'cond', 'then_expr', 'else_expr',
                      'arr', 'index', 'heap', 'ref', 'buf', 'h0', 'h1',
                      'locs', 'body']:
            child = getattr(expr, attr, None)
            if child is not None and self._has_name_ref(child, name):
                return True
        if isinstance(expr, App):
            if self._has_name_ref(expr.func, name): return True
            for a in expr.args:
                if self._has_name_ref(a, name): return True
        if isinstance(expr, Match):
            if self._has_name_ref(expr.expr, name): return True
            for c in expr.cases:
                if self._has_name_ref(c.expr, name): return True
        if isinstance(expr, (Forall, Exists)):
            return self._has_name_ref(expr.body, name)
        if isinstance(expr, RecordUpdate):
            if self._has_name_ref(expr.expr, name): return True
            for _, v in expr.updates:
                if self._has_name_ref(v, name): return True
        if isinstance(expr, IfExpr):
            return (self._has_name_ref(expr.cond, name) or
                    self._has_name_ref(expr.then_expr, name) or
                    self._has_name_ref(expr.else_expr, name))
        if isinstance(expr, BinOp):
            return (self._has_name_ref(expr.left, name) or
                    self._has_name_ref(expr.right, name))
        if isinstance(expr, UnaryOp):
            return self._has_name_ref(expr.expr, name)
        return False

    def _parse_def(self) -> Declaration:
        self._expect('KEYWORD', 'def')
        name = self._next().value
        params = []
        _def_name = name  # save for recursive detection
        # Reset param types for this function
        self._param_types = {}
        if self._skip('LPAREN'):
            while self._peek().kind != 'RPAREN':
                pname = self._next().value
                self._expect('COLON')
                dir = None
                if self._peek().kind == 'KEYWORD' and self._peek().value in (
                    'STATE_READ_ONLY', 'STATE_WRITE_ONLY', 'STATE_READ_WRITE'
                ):
                    dir = self._next().value
                ptype = self._parse_type()
                self._param_types[pname] = ptype
                if self._peek().kind == 'LBRACKET':
                    self._next()
                    array = True
                    if self._peek().kind == 'RBRACKET':
                        self._expect('RBRACKET')
                        ptype = AppType(NamedType(QualifiedIdent(['FStar', 'Seq', 'seq'])), [ptype])
                    else:
                        # T[n] = array of T with length n
                        self._parse_expr()  # skip size
                        self._expect('RBRACKET')
                        ptype = AppType(NamedType(QualifiedIdent(['FStar', 'Seq', 'seq'])), [ptype])
                params.append(Binder(name=pname, typ=ptype, direction=dir))
                if self._skip('COMMA'): continue
            self._expect('RPAREN')
        ret = None
        if self._skip('ARROW'):
            ret_name = self._next().value
            if ret_name == 'None':
                ret = None
            elif ret_name == 'nothing':
                raise SyntaxError("'nothing' is removed — use 'None' for void return")
            else:
                self.tok.tokens.insert(0, VeriTokenizer.Token('IDENT', ret_name, 0))
                ret = self._parse_type()

        # Record returning type as `result` so FORALL u IN result.users can resolve
        if ret is not None:
            self._param_types['result'] = ret

        self._expect('COLON')

        req = None
        ens = None
        dec = None
        while self._peek().kind == 'KEYWORD' and self._peek().value in ('REQUIRES', 'ENSURES', 'DECREASES'):
            kw = self._next().value
            # Use _parse_or() instead of _parse_expr() so trailing `if` on the next
            # line isn't accidentally consumed as a ternary expression.
            expr = self._parse_or()
            if kw == 'REQUIRES': req = expr
            elif kw == 'ENSURES': ens = expr
            elif kw == 'DECREASES': dec = expr

        # Consume optional body expression (present for functions with contracts + body,
        # or for pure implementation functions). Do this BEFORE creating ValDecl/LetDecl
        # so the token stream is consumed cleanly.
        body = None
        if self._peek().kind != 'EOF' and self._peek().kind != 'KEYWORD':
            # Expression starts with non-keyword (IDENT, INT, etc.)
            body = self._parse_expr()
        elif self._peek().kind == 'KEYWORD' and self._peek().value in ('return', 'if', 'match'):
            kw = self._peek().value
            if kw == 'return':
                self._next()
                body = self._parse_expr()
            elif kw in ('if', 'match'):
                body = self._parse_expr()

        if req is not None or ens is not None:
            return ValDecl(
                name=name, params=params, return_type=ret,
                contract=PrePost(requires=req, ensures=ens, decreases=dec),
                body=body)
        else:
            # Detect recursion: check if body references the function name
            is_rec = body is not None and len(params) > 0 and self._has_name_ref(body, _def_name)
            return LetDecl(name=name, params=params, typ=ret, body=body, recursive=is_rec)

    def _parse_constraint(self) -> PragmaDecl:
        self._expect('KEYWORD', 'CONSTRAINT')
        name = self._next().value
        self._expect('COLON')
        while self._peek().kind != 'KEYWORD' and self._peek().kind != 'EOF':
            self._next()
        return PragmaDecl(f'CONSTRAINT {name}: ...')

    def _parse_type(self) -> TypeExpr:
        t = self._peek()
        if t.kind == 'TYPE_KEYW':
            name = t.value
            self._next()
            # Handle `string(128)` - parenthesized size annotation
            if self._peek().kind == 'LPAREN':
                self._next()
                self._parse_expr()  # skip size
                self._expect('RPAREN')
            typ = PrimType(name)
            # Handle `option[...]`, `list[...]`, `buffer[...]` type application
            if self._peek().kind == 'LBRACKET':
                self._next()
                if self._peek().kind == 'RBRACKET':
                    # T[] → Buffer.buffer T
                    self._next()
                    return AppType(func=NamedType(QualifiedIdent(['FStar', 'Seq', 'seq'])), args=[PrimType(name)])
                arg = self._parse_type()
                self._expect('RBRACKET')
                return AppType(func=NamedType(QualifiedIdent([name])), args=[arg])
            return typ
        if t.kind == 'IDENT' or t.kind == 'QIDENT':
            if t.kind == 'QIDENT':
                # Already pre-split: Buffer.buffer → ['Buffer', 'buffer']
                parts = t.value.split('.')
                self._next()
            else:
                name = self._next().value
                parts = [name]
                while self._peek().kind == 'DOT':
                    self._next()
                    parts.append(self._next().value)
            typ = NamedType(QualifiedIdent(parts))
            if self._peek().kind == 'LBRACKET':
                self._next()
                if self._peek().kind == 'RBRACKET':
                    # T[] → Buffer.buffer T
                    self._next()
                    return AppType(func=NamedType(QualifiedIdent(['FStar', 'Seq', 'seq'])), args=[typ])
                arg = self._parse_type()
                self._expect('RBRACKET')
                return AppType(func=typ, args=[arg])
            return typ
        if t.kind == 'LPAREN':
            self._next()
            first = self._parse_type()
            if self._skip('COMMA') or self._skip('STAR'):
                items = [first]
                while True:
                    items.append(self._parse_type())
                    if not (self._skip('COMMA') or self._skip('STAR')):
                        break
                self._expect('RPAREN')
                return TupleType(items=items)
            self._expect('RPAREN')
            return first
        # Handle `type` keyword used as unconstrained type parameter
        if t.kind == 'KEYWORD' and t.value == 'type':
            self._next()
            return PrimType('Type')
        raise SyntaxError(f'Unexpected in type: {t}')

    def _parse_expr(self) -> Expr:
        return self._parse_ifexpr()

    def _parse_ifexpr(self) -> Expr:
        """Parse if-expression: leading form `if cond: A elif cond: B else: C`
        or ternary form `A if cond else B`."""
        # Leading if: `if cond: then_expr elif cond: then_expr else: then_expr`
        if self._peek().kind == 'KEYWORD' and self._peek().value == 'if':
            self._next()
            cond = self._parse_expr()
            self._skip('COLON')
            if self._peek().kind == 'KEYWORD' and self._peek().value == 'return':
                self._next()
            then_e = self._parse_expr()
            # Handle elif chain
            while self._peek().kind == 'KEYWORD' and self._peek().value == 'elif':
                self._next()
                elif_cond = self._parse_expr()
                self._skip('COLON')
                if self._peek().kind == 'KEYWORD' and self._peek().value == 'return':
                    self._next()
                elif_then = self._parse_expr()
                # Check for trailing else after this elif
                if self._peek().kind == 'KEYWORD' and self._peek().value == 'else':
                    self._next()
                    self._skip('COLON')
                    if self._peek().kind == 'KEYWORD' and self._peek().value == 'return':
                        self._next()
                    else_e = self._parse_ifexpr()
                    return IfExpr(cond=cond, then_expr=then_e,
                                  else_expr=IfExpr(cond=elif_cond, then_expr=elif_then, else_expr=else_e))
                # elif without else: the elif's else is None
                return IfExpr(cond=cond, then_expr=then_e,
                              else_expr=IfExpr(cond=elif_cond, then_expr=elif_then, else_expr=Constant('None')))
            # else on the original if
            if self._peek().kind == 'KEYWORD' and self._peek().value == 'else':
                self._next()
                self._skip('COLON')
                if self._peek().kind == 'KEYWORD' and self._peek().value == 'return':
                    self._next()
                else_e = self._parse_ifexpr()
                return IfExpr(cond=cond, then_expr=then_e, else_expr=else_e)
            return IfExpr(cond=cond, then_expr=then_e, else_expr=Constant('None'))

        # Ternary form: `A if cond else B`
        left = self._parse_or()
        if self._peek().kind == 'KEYWORD' and self._peek().value == 'if':
            self._next()
            cond = self._parse_expr()
            self._expect('KEYWORD', 'else')
            else_e = self._parse_ifexpr()
            return IfExpr(cond=cond, then_expr=left, else_expr=else_e)
        return left

    def _parse_or(self) -> Expr:
        left = self._parse_and()
        while self._skip('KEYWORD', 'or'):
            right = self._parse_and()
            left = BinOp('or', left, right)
        return left

    def _parse_and(self) -> Expr:
        left = self._parse_implies()
        while self._skip('KEYWORD', 'and'):
            right = self._parse_implies()
            left = BinOp('and', left, right)
        return left

    def _parse_implies(self) -> Expr:
        left = self._parse_equality()
        while self._skip('IMPLIES'):
            right = self._parse_equality()
            left = BinOp('==>', left, right)
        return left

    def _parse_equality(self) -> Expr:
        left = self._parse_comparison()
        for op in ['EQUALS', 'NEQ']:
            if self._skip(op):
                right = self._parse_comparison()
                op_name = '==' if op == 'EQUALS' else '!='
                left = BinOp(op_name, left, right)
        if self._skip('ASSIGN', '='):
            right = self._parse_comparison()
            left = BinOp('==', left, right)
        return left

    def _parse_comparison(self) -> Expr:
        left = self._parse_membership()
        for op in ['LE', 'GE', 'LT', 'GT']:
            if self._skip(op):
                right = self._parse_membership()
                left = BinOp(op, left, right)
        return left

    def _parse_membership(self) -> Expr:
        left = self._parse_addition()
        if self._skip('KEYWORD', 'in') or self._skip('KEYWORD', 'IN'):
            right = self._parse_addition()
            left = BinOp('in', left, right)
        return left

    def _parse_addition(self) -> Expr:
        left = self._parse_multiplication()
        for op in ['PLUS', 'MINUS']:
            if self._skip(op):
                right = self._parse_multiplication()
                left = BinOp('+' if op == 'PLUS' else '-', left, right)
        return left

    def _parse_multiplication(self) -> Expr:
        left = self._parse_unary()
        for op in ['STAR', 'SLASH', 'PERCENT']:
            if self._skip(op):
                right = self._parse_unary()
                left = BinOp('*' if op == 'STAR' else '/' if op == 'SLASH' else '%', left, right)
        return left

    def _parse_unary(self) -> Expr:
        if self._skip('MINUS'):
            return UnaryOp('-', self._parse_unary())
        if self._skip('KEYWORD', 'not'):
            return UnaryOp('not', self._parse_unary())
        return self._parse_atom()

    def _parse_atom(self) -> Expr:
        t = self._peek()
        if t.kind == 'KEYWORD':
            kw = t.value
            # Pythonic ternary `A if cond else B` is handled in _parse_ifexpr
            if kw == 'match': return self._parse_match()
            if kw == 'lambda': return self._parse_lambda()
            if kw == 'FORALL': return self._parse_quantifier(True)
            if kw == 'EXISTS': return self._parse_quantifier(False)
            if kw == 'None': self._next(); return Var('None')
            if kw == 'Some': self._next(); return Var('Some')
            if kw == 'True': self._next(); return Const(True)
            if kw == 'False': self._next(); return Const(False)
            # nothing removed; use None for void returns
            if kw == 'len': self._next(); return self._parse_fnargs('len')
            if kw == 'array_len': self._next(); return self._parse_fnargs('array_len')
            if kw == 'range':
                self._next()
                if self._peek().kind == 'LPAREN':
                    self._next()
                    args = []
                    while self._peek().kind != 'RPAREN':
                        args.append(self._parse_expr())
                        self._skip('COMMA')
                    self._expect('RPAREN')
                    return App(Var('range'), args)
                return Var('range')
        if t.kind == 'BOOL':
            self._next()
            return Const(t.value in ('True', 'true'))
        if t.kind == 'INT':
            self._next()
            return Const(int(t.value))
        if t.kind == 'FLOAT':
            self._next()
            return Const(float(t.value))
        if t.kind == 'STRING':
            self._next()
            return Const(t.value[1:-1])
        if t.kind == 'LBRACKET':
            self._next()
            if self._peek().kind == 'RBRACKET':
                self._next()
                return Var('Nil')  # empty list
            expr = self._parse_expr()
            items = [expr]
            while self._skip('COMMA'):
                items.append(self._parse_expr())
            self._expect('RBRACKET')
            # Build Cons chain (reverse so first element is at head)
            result = Var('Nil')
            for item in reversed(items):
                result = App(Var('Cons'), [item, result])
            return result

        if t.kind == 'LPAREN':
            self._next()
            expr = self._parse_expr()
            while self._skip('COMMA'):
                items = [expr]
                items.append(self._parse_expr())
                while self._skip('COMMA'):
                    items.append(self._parse_expr())
                self._expect('RPAREN')
                return App(Var('tuple'), items)
            self._expect('RPAREN')
            return expr
        if t.kind == 'IDENT' or t.kind == 'QIDENT':
            name = self._next().value
            if t.kind == 'QIDENT':
                parts = name.split('.')
            else:
                parts = [name]
                while self._peek().kind == 'DOT':
                    self._next()
                    n = self._next().value
                    parts.append(n)
            base = QualifiedVar(QualifiedIdent(parts)) if len(parts) > 1 else Var(parts[0])
            if self._peek().kind == 'LPAREN':
                self._next()
                args = []
                while self._peek().kind != 'RPAREN':
                    args.append(self._parse_expr())
                    self._skip('COMMA')
                self._expect('RPAREN')
                return App(func=base, args=args)
            if self._peek().kind == 'DOT':
                self._next()
                field = self._next().value
                return FieldAccess(expr=base, field=field)
            if self._peek().kind == 'LBRACKET':
                self._next()
                idx = self._parse_expr()
                self._expect('RBRACKET')
                return ArrayIndex(arr=base, index=idx)
            return base
        if t.kind == 'UNDERSCORE':
            self._next()
            return Var('_')
        raise SyntaxError(f'Unexpected in expression: {t}')

    def _parse_fnargs(self, name: str) -> Expr:
        if self._peek().kind == 'LPAREN':
            self._next()
            arg = self._parse_expr()
            self._expect('RPAREN')
            if name == 'len': return Len(expr=arg)
            if name == 'array_len': return ArrayLen(arr=arg)
            return App(Var(name), [arg])
        arg = self._parse_atom()
        if name == 'len': return Len(expr=arg)
        return App(Var(name), [arg])

    def _parse_match(self) -> Expr:
        self._expect('KEYWORD', 'match')
        expr = self._parse_expr()
        self._expect('COLON')
        cases = []
        while self._peek().kind == 'KEYWORD' and self._peek().value == 'case':
            self._next()  # consume 'case'
            pat = self._parse_pattern()
            # Accept both ':' (Pythonic) and '->' (old compat)
            if self._peek().kind == 'ARROW':
                self._next()
            else:
                self._expect('COLON')
            case_expr = self._parse_expr()
            cases.append(MatchCase(pattern=pat, expr=case_expr))
        if isinstance(expr, Var) and expr.name == '_':
            cases = [MatchCase(PatWild(), Const(True))]
        return Match(expr=expr, cases=cases)

    def _parse_pattern(self) -> Pattern:
        if self._skip('UNDERSCORE'): return PatWild()
        if self._skip('KEYWORD', 'None'): return PatApp('None', [])
        if self._skip('KEYWORD', 'Some'):
            if self._peek().kind == 'LPAREN':
                self._next()
                args = []
                while self._peek().kind != 'RPAREN':
                    args.append(self._parse_pattern())
                    self._skip('COMMA')
                self._expect('RPAREN')
                return PatApp('Some', args)
            return PatApp('Some', [PatWild()])
        if self._peek().kind == 'INT':
            return PatConst(int(self._next().value))
        if self._peek().kind == 'LBRACKET':
            self._next()
            if self._skip('RBRACKET'): return PatApp('Nil', [])
            return self._parse_list_pat()
        # Handle `_` wild (may be tokenized as IDENT due to tokenizer order)
        if self._peek().kind == 'IDENT' and self._peek().value == '_':
            self._next()
            return PatWild()
        # Handle tuple patterns: (pat1, pat2, ...)
        if self._peek().kind == 'LPAREN':
            self._next()
            pats = []
            while self._peek().kind != 'RPAREN':
                pats.append(self._parse_pattern())
                self._skip('COMMA')
            self._expect('RPAREN')
            if len(pats) == 1:
                return pats[0]
            return PatTuple(pats)
        name = self._next().value
        # Constructor pattern with payload: `Cons(hd, tl)` or named
        if self._peek().kind == 'LPAREN':
            self._next()
            args = []
            while self._peek().kind != 'RPAREN':
                args.append(self._parse_pattern())
                self._skip('COMMA')
            self._expect('RPAREN')
            return PatApp(name, args)
        return PatVar(name)

    def _parse_list_pat(self) -> Pattern:
        """Parse [hd1, hd2, *tl] pattern."""
        pats = []
        rest_var = None
        while self._peek().kind != 'RBRACKET':
            if self._skip('STAR'):
                rest_var = self._next().value
            else:
                pats.append(self._parse_pattern())
            self._skip('COMMA')
        self._expect('RBRACKET')
        # Build Cons chain: [hd1, hd2, *tl] → hd1 :: hd2 :: tl
        result = PatVar(rest_var) if rest_var else PatApp('Nil', [])
        for p in reversed(pats):
            result = PatApp('Cons', [p, result])
        return result

    def _parse_lambda(self) -> Expr:
        """Parse Python-style lambda: lambda params: body"""
        self._next()  # consume 'lambda'
        params = []
        # Collect param names until ':'
        while self._peek().kind != 'COLON' and self._peek().kind != 'EOF':
            params.append(self._next().value)
            self._skip('COMMA')
        self._expect('COLON')
        body = self._parse_expr()
        return Lambda(params=params, body=body)

    def _parse_skipped_block(self, kind: str) -> PragmaDecl:
        """Skip tokens of an unprocessed block (e.g. CONSTRAINT)."""
        # Consume the block name and colon
        if self._peek().kind == 'IDENT':
            self._next()
        if self._peek().kind == 'COLON':
            self._next()
        # Skip body tokens until next top-level keyword or EOF
        top_level = {'module', 'import', 'class', 'enum', 'variant', 'type', 'def', 'CONSTRAINT', 'IDENT'}
        while self._peek().kind != 'EOF':
            if self._peek().kind == 'KEYWORD' and self._peek().value in top_level:
                break
            if self._peek().kind == 'IDENT' and self._peek().value == '':
                break
            self._next()
        return PragmaDecl(f'{kind} block (skipped)')

    def _parse_quantifier(self, is_forall: bool) -> Expr:
        self._next()  # FORALL/EXISTS
        ident = self._next().value
        self._expect('KEYWORD', 'IN')
        range_expr = self._parse_expr()
        self._expect('COLON')

        # Resolve the binder type BEFORE parsing the body, so that nested
        # quantifiers (FORALL r IN u.requests) can look up the outer binder's type.
        binder_typ: Optional[TypeExpr] = None
        if isinstance(range_expr, FieldAccess):
            collection = self._resolve_field_type(range_expr)
            if collection is not None and isinstance(collection, AppType) and collection.args:
                binder_typ = collection.args[0]
        elif isinstance(range_expr, Var):
            param_typ = self._param_types.get(range_expr.name)
            if param_typ is not None and isinstance(param_typ, AppType) and param_typ.args:
                binder_typ = param_typ.args[0]
        elif isinstance(range_expr, QualifiedVar):
            parts = range_expr.path.parts
            if len(parts) >= 2:
                base_typ = self._param_types.get(parts[0]) or self._quant_binders.get(parts[0])
                if base_typ is not None:
                    base_name = self._type_to_name(base_typ)
                    if base_name is not None:
                        field_map = _global_field_types.get(base_name, {}) or self._field_types.get(base_name, {})
                        field_typ = field_map.get(parts[1])
                        if field_typ is not None and isinstance(field_typ, AppType) and field_typ.args:
                            binder_typ = field_typ.args[0]

        # Save resolved binder type BEFORE parsing body (inner foralls need it)
        b = Binder(name=ident, typ=binder_typ or TypeVar('_'))
        if binder_typ is not None:
            old_val = self._quant_binders.get(ident)
            self._quant_binders[ident] = binder_typ

        body = self._parse_expr()

        # Restore previous quantifier binder if we overwrote
        if binder_typ is not None and old_val is None:
            del self._quant_binders[ident]
        elif binder_typ is not None and old_val is not None:
            self._quant_binders[ident] = old_val

        # Fold the `IN <range>` bound into the body so the quantifier is
        # range-bounded, not type-bounded:
        #   FORALL x IN s: body  ->  forall x :: x in s ==> body
        #   EXISTS x IN s: body  ->  exists x :: x in s && body
        # Dropping the bound was both a soundness bug (quantifying over the whole
        # type instead of the set) and made the quantifier uncompilable in
        # non-ghost functions.
        membership = BinOp('in', Var(ident), range_expr)
        if is_forall:
            return Forall(binders=[b], body=BinOp('==>', membership, body))
        return Exists(binders=[b], body=BinOp('and', membership, body))

    def _record_field_type(self, class_name: str, field_name: str, field_type: TypeExpr) -> None:
        if class_name not in self._field_types:
            self._field_types[class_name] = {}
        self._field_types[class_name][field_name] = field_type
        # Also persist to global registry (shared across block parses)
        if class_name not in _global_field_types:
            _global_field_types[class_name] = {}
        _global_field_types[class_name][field_name] = field_type

    def _resolve_field_type(self, access: FieldAccess) -> Optional[TypeExpr]:
        base_type = None
        if isinstance(access.expr, Var):
            base_type = self._param_types.get(access.expr.name) or self._quant_binders.get(access.expr.name)
        elif isinstance(access.expr, QualifiedVar):
            # e.g. result.users where result is a param → look up users in result's type
            parts = access.expr.path.parts
            if parts and parts[0] in self._param_types:
                base_type = self._param_types[parts[0]]
        elif isinstance(access.expr, FieldAccess):
            base_type = self._resolve_field_type(access.expr)
        if base_type is None:
            return None
        base_name = self._type_to_name(base_type)
        if base_name is None:
            return None
        field_map = _global_field_types.get(base_name, {}) or self._field_types.get(base_name, {})
        return field_map.get(access.field)

    @staticmethod
    def _type_to_name(typ: TypeExpr) -> Optional[str]:
        if isinstance(typ, NamedType):
            return typ.path.parts[0] if typ.path.parts else None
        if isinstance(typ, PrimType):
            return typ.name
        return None

def parse_veri(text: str) -> VeriDslProgram:
    return VeriDslParser(text).parse()
