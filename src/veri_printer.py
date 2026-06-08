"""
veri_printer.py — Pretty-print VeriDslProgram AST to Veri DSL format.

Output: Python-like syntax with SQL contract keywords.
"""

from typing import List, Optional, Set
from veri_ast import *


# Sugar: expressions that should be mapped to shorter DSL forms
_LEN_SUGAR = {'List.Tot.length', 'FStar.List.Tot.length', 'length'}
_ARR_LEN_SUGAR = {'Buffer.length', 'FStar.Buffer.length', 'Array.length'}

class VeriDslPrinter:
    """Convert VeriDslProgram AST to Veri DSL text."""

    def __init__(self, indent: int = 4):
        self.indent = indent
        self.level = 0
        self.lines: List[str] = []

    def print(self, program: VeriDslProgram) -> str:
        self.lines = []
        if program.module:
            self._line(f"module {program.module.name}")
            self._blank()

        for decl in program.decls:
            self._print_decl(decl)
        return '\n'.join(self.lines)

    def _line(self, text: str = ''):
        if text:
            self.lines.append(' ' * (self.level * self.indent) + text)
        else:
            self.lines.append('')

    def _blank(self):
        self.lines.append('')

    # ── Declaration dispatch ────────────────────────────────────────────────

    def _print_decl(self, decl: Declaration):
        if isinstance(decl, ModuleDecl):
            self._line(f"module {decl.name}")
            self._blank()
        elif isinstance(decl, OpenDecl):
            self._print_open(decl)
        elif isinstance(decl, IncludeDecl):
            self._line(f"import {decl.path}")
        elif isinstance(decl, FriendDecl):
            self._line(f"import {decl.path}  # friend")
        elif isinstance(decl, TypeAbstract):
            self._print_type_abstract(decl)
        elif isinstance(decl, TypeAlias):
            self._print_type_alias(decl)
        elif isinstance(decl, TypeRecord):
            self._print_type_record(decl)
        elif isinstance(decl, TypeVariant):
            self._print_type_variant(decl)
        elif isinstance(decl, LetDecl):
            self._print_let(decl)
        elif isinstance(decl, ValDecl):
            self._print_val(decl)
        elif isinstance(decl, PragmaDecl):
            self._line(f"{decl.text}")

    def _print_open(self, decl: OpenDecl):
        # `open FStar.List.Tot` -> `import FStar.List.Tot`
        self._line(f"import {decl.path}")

    # ── Type declarations ───────────────────────────────────────────────────

    def _print_type_abstract(self, decl: TypeAbstract):
        parts = ["type", decl.name]
        if decl.params:
            param_strs = []
            for p in decl.params:
                if p.kind:
                    param_strs.append(f"{p.name}: {self._type_str(p.kind)}")
                else:
                    param_strs.append(p.name)
            parts.append(f"[{', '.join(param_strs)}]")
        if decl.kind:
            parts.append(f": {self._type_str(decl.kind)}")
        self._line(' '.join(parts))
        self._blank()

    def _print_type_alias(self, decl: TypeAlias):
        parts = ["type", decl.name]
        if decl.params:
            param_strs = [self._type_param_str(p) for p in decl.params]
            parts.append(f"[{', '.join(param_strs)}]")
        if decl.typ:
            type_str = self._type_str(decl.typ)
            # Check if it's a refined type
            if isinstance(decl.typ, RefinedType):
                ref = decl.typ
                base_str = self._type_str(ref.binder.typ)
                pred_str = self._expr_str(ref.predicate)
                parts.append(f"= {base_str} WHERE {pred_str}")
            else:
                parts.append(f"= {type_str}")
        self._line(' '.join(parts))
        self._blank()

    def _print_type_record(self, decl: TypeRecord):
        parts = ["class", decl.name]
        if decl.params:
            param_strs = [self._type_param_str(p) for p in decl.params]
            parts.append(f"[{', '.join(param_strs)}]")
        parts.append(':')
        self._line(' '.join(parts))
        self.level += 1
        for f in decl.fields:
            ftype = self._type_str(f.typ)
            comment = f"  # {f.name}" if f.name else ''
            self._line(f"{f.name}: {ftype}{comment}")
        self.level -= 1
        self._blank()

    def _print_type_variant(self, decl: TypeVariant):
        if all(not c.args for c in decl.constructors):
            # Enum-style
            parts = ["enum", decl.name]
            if decl.params:
                param_strs = [self._type_param_str(p) for p in decl.params]
                parts.append(f"[{', '.join(param_strs)}]")
            parts.append(':')
            self._line(' '.join(parts))
            self.level += 1
            for i, c in enumerate(decl.constructors):
                tag = f"    {c.name}" if i == 0 else f"    {c.name}"
                self._line(tag)
            self.level -= 1
        else:
            # Variant with payload
            parts = ["variant", decl.name]
            if decl.params:
                param_strs = [self._type_param_str(p) for p in decl.params]
                parts.append(f"[{', '.join(param_strs)}]")
            parts.append(':')
            self._line(' '.join(parts))
            self.level += 1
            for c in decl.constructors:
                if c.args:
                    arg_strs = [f"{a.name}: {self._type_str(a.typ)}" for a in c.args]
                    self._line(f"| {c.name}({', '.join(arg_strs)})")
                else:
                    self._line(f"| {c.name}()")
            self.level -= 1
        self._blank()

    def _type_param_str(self, p: TypeVar) -> str:
        if p.kind:
            return f"{p.name}: {self._type_str(p.kind)}"
        return p.name

    # ── Let declarations ────────────────────────────────────────────────────

    def _print_let(self, decl: LetDecl):
        if decl.body is None:
            parts = [decl.name]
            if decl.typ:
                parts.append(f": {self._type_str(decl.typ)}")
            self._line(' '.join(parts))
        elif not decl.params:
            # Simple constant
            body_str = self._expr_str(decl.body)
            parts = [decl.name]
            if decl.typ:
                parts.append(f": {self._type_str(decl.typ)}")
            parts.append(f"= {body_str}")
            self._line(' '.join(parts))
        else:
            # Function/predicate
            params_str = ', '.join(self._binder_str(p, include_type=True) for p in decl.params)
            parts = ["def", f"{decl.name}({params_str})"]
            if decl.typ:
                parts.append(f"-> {self._type_str(decl.typ)}")
            parts.append(':')
            self._line(' '.join(parts))
            self.level += 1
            if decl.body:
                body_str = self._expr_str(decl.body)
                self._line(f"return {body_str}")
            self.level -= 1
        self._blank()

    # ── Val declarations ────────────────────────────────────────────────────

    def _print_val(self, decl: ValDecl):
        params_str = ', '.join(self._param_str(p) for p in decl.params)
        ret_str = self._type_str(decl.return_type) if decl.return_type else 'None'

        parts = ["def", f"{decl.name}({params_str})"]
        parts.append(f"-> {ret_str}:")
        self._line(' '.join(parts))

        self.level += 1
        if decl.contract.requires:
            req_str = self._expr_str(decl.contract.requires)
            self._line(f"REQUIRES {req_str}")
        if decl.contract.ensures:
            ens_str = self._expr_str(decl.contract.ensures)
            self._line(f"ENSURES {ens_str}")
        if decl.contract.decreases:
            dec_str = self._expr_str(decl.contract.decreases)
            self._line(f"DECREASES {dec_str}")
        if decl.contract.smt_pats:
            for pats in decl.contract.smt_pats:
                pat_strs = [self._expr_str(p) for p in pats]
                self._line(f"[SMTPat({', '.join(pat_strs)})]")
        if decl.effect != 'Pure' and decl.contract.requires is None and decl.contract.ensures is None:
            self._line(f"# effect: {decl.effect}")
        self.level -= 1
        self._blank()

    # ── Binder/param formatting ─────────────────────────────────────────────

    def _binder_str(self, b: Binder, include_type: bool = True) -> str:
        if b.name is None:
            if include_type:
                return f': {self._type_str(b.typ)}'
            return '_'
        if include_type:
            return f'{b.name}: {self._type_str(b.typ)}'
        return b.name

    def _param_str(self, p: Binder) -> str:
        """Format a binder as a parameter: name: type or name: DIR type."""
        if p.direction:
            return f'{p.name}: {p.direction} {self._type_str(p.typ)}'
        return f'{p.name}: {self._type_str(p.typ)}'

    # ── Type → string ──────────────────────────────────────────────────────

    def _type_str(self, typ: TypeExpr) -> str:
        if isinstance(typ, PrimType):
            return typ.name
        elif isinstance(typ, TypeVar):
            return typ.name
        elif isinstance(typ, NamedType):
            return str(typ.path)
        elif isinstance(typ, AppType):
            args_str = ', '.join(self._type_str(a) for a in typ.args)
            base_str = self._type_str(typ.func)
            return f'{base_str}[{args_str}]'
        elif isinstance(typ, RefinedType):
            base = self._type_str(typ.binder.typ)
            pred = self._expr_str(typ.predicate)
            return f'{base} WHERE {pred}'
        elif isinstance(typ, ArrowType):
            param_strs = [self._binder_str(p) for p in typ.params]
            ret = self._type_str(typ.result)
            eff = f' {typ.effect}' if typ.effect else ''
            params = ' -> '.join(param_strs)
            return f'{params} ->{eff} {ret}'
        elif isinstance(typ, TupleType):
            items = ', '.join(self._type_str(t) for t in typ.items)
            return f'({items})'
        elif isinstance(typ, ListType):
            return f'list {self._type_str(typ.elem)}'
        elif isinstance(typ, OptionType):
            return f'option {self._type_str(typ.elem)}'
        elif isinstance(typ, BufferType):
            return f'buffer {self._type_str(typ.elem)}'
        elif isinstance(typ, Const):
            return str(typ.value) if typ.value is not None else 'unit'
        else:
            return str(typ)

    # ── Expression → string ─────────────────────────────────────────────────

    def _expr_str(self, expr: Expr, parent_prec: int = 0) -> str:
        if isinstance(expr, Const):
            if expr.value is None:
                return 'None'
            elif isinstance(expr.value, bool):
                return 'True' if expr.value else 'False'
            elif isinstance(expr.value, int):
                return str(expr.value)
            elif isinstance(expr.value, float):
                return str(expr.value)
            elif isinstance(expr.value, str):
                return f'"{expr.value}"'
            return str(expr.value)

        elif isinstance(expr, Var):
            if expr.name == 'None':
                return 'None'
            if expr.name == 'Some':
                return 'Some'
            return expr.name

        elif isinstance(expr, QualifiedVar):
            path_str = str(expr.path)
            return path_str

        elif isinstance(expr, App):
            func_str = self._expr_str(expr.func)
            args_str = ', '.join(self._expr_str(a) for a in expr.args)
            # Special cases
            if isinstance(expr.func, Var) and expr.func.name == 'tuple':
                return f'({args_str})'
            if isinstance(expr.func, Var) and expr.func.name == 'Some':
                return f'Some({args_str})'
            if isinstance(expr.func, Var) and expr.func.name == 'Cons':
                # Flatten Cons chain to [..., *rest] syntax
                return self._expr_cons_chain(expr)
            return f'{func_str}({args_str})'

        elif isinstance(expr, BinOp):
            op = expr.op
            left = self._expr_str(expr.left, 1)
            right = self._expr_str(expr.right, 1)
            # Map F* operators to DSL
            if op == '/' or (isinstance(op, str) and op == '/\\'):
                op_str = 'and'
            elif op == '\\/' or op == 'or':
                op_str = 'or'
            elif op == '~' or op == 'not':
                op_str = 'not'
            elif op == '==>':
                op_str = '==>'
            elif op == '<==>':
                op_str = '<==>'
            elif op == '=' or op == '==':
                op_str = '=='
            elif op in ('<', '>', 'LT', 'GT'):
                if op in ('LT', 'GT'):
                    op_str = '<' if op == 'LT' else '>'
                else:
                    op_str = op
            elif op in ('<=', '>=', 'LE', 'GE'):
                if op in ('LE', 'GE'):
                    op_str = '<=' if op == 'LE' else '>='
                else:
                    op_str = op
            elif op == '+':
                op_str = '+'
            elif op == '-':
                op_str = '-'
            elif op == '*':
                op_str = '*'
            elif op == '/':
                op_str = '/'
            elif op == '%':
                op_str = '%'
            elif op == '!=':
                op_str = '!='
            elif op == ':=':
                op_str = ':='
            elif op == '::':
                op_str = '::'
            else:
                op_str = str(op)

            # Pretty-print
            if op_str in ('and', 'or', '==>', '<==>'):
                # SQL-style operators
                return f'{left} {op_str} {right}'
            else:
                return f'{left} {op_str} {right}'

        elif isinstance(expr, UnaryOp):
            inner = self._expr_str(expr.expr)
            if expr.op == 'not':
                return f'not {inner}'
            elif expr.op == '~':
                return f'not {inner}'
            elif expr.op == '!':
                return f'!{inner}'
            return f'{expr.op}{inner}'

        elif isinstance(expr, FieldAccess):
            base = self._expr_str(expr.expr)
            return f'{base}.{expr.field}'

        elif isinstance(expr, RecordUpdate):
            base = self._expr_str(expr.expr)
            updates_str = ', '.join(
                f'{f} = {self._expr_str(v)}' for f, v in expr.updates
            )
            return f'{{{base} with {updates_str}}}'

        elif isinstance(expr, IfExpr):
            then_e = self._expr_str(expr.then_expr)
            cond = self._expr_str(expr.cond)
            else_e = self._expr_str(expr.else_expr)
            return f'{then_e} if {cond} else {else_e}'

        elif isinstance(expr, Match):
            match_e = self._expr_str(expr.expr)
            self.level += 1
            case_indent = ' ' * (self.level * self.indent)
            body_indent = ' ' * ((self.level + 1) * self.indent)
            case_parts = []
            for c in expr.cases:
                pat_str = self._pattern_str(c.pattern)
                val_str = self._expr_str(c.expr)
                val_lines = val_str.split('\n')
                val_body = '\n'.join(body_indent + l for l in val_lines)
                case_parts.append(f'{case_indent}case {pat_str}:')
                case_parts.append(val_body)
            result = f'match {match_e}:\n' + '\n'.join(case_parts)
            self.level -= 1
            return result

        elif isinstance(expr, Forall):
            binders_str = ', '.join(self._binder_str(b) for b in expr.binders)
            body_str = self._expr_str(expr.body)
            return f'FORALL {binders_str}: {body_str}'

        elif isinstance(expr, Exists):
            binders_str = ', '.join(self._binder_str(b) for b in expr.binders)
            body_str = self._expr_str(expr.body)
            return f'EXISTS {binders_str}: {body_str}'

        elif isinstance(expr, Lambda):
            params_str = ', '.join(expr.params)
            body_str = self._expr_str(expr.body)
            return f'lambda {params_str}: {body_str}'

        elif isinstance(expr, ArrayIndex):
            arr_str = self._expr_str(expr.arr)
            idx_str = self._expr_str(expr.index)
            return f'{arr_str}[{idx_str}]'

        elif isinstance(expr, Len):
            inner = self._expr_str(expr.expr)
            return f'len({inner})'

        elif isinstance(expr, ArrayLen):
            inner = self._expr_str(expr.expr)
            return f'array_len({inner})'

        elif isinstance(expr, Contains):
            h = self._expr_str(expr.heap)
            r = self._expr_str(expr.ref)
            return f'{h} `contains` {r}'

        elif isinstance(expr, Sel):
            h = self._expr_str(expr.heap)
            r = self._expr_str(expr.ref)
            return f'sel {h} {r}'

        elif isinstance(expr, Live):
            h = self._expr_str(expr.heap)
            b = self._expr_str(expr.buffer)
            return f'live {h} {b}'

        elif isinstance(expr, Modifies):
            locs = self._expr_str(expr.locs)
            h0 = self._expr_str(expr.h0)
            h1 = self._expr_str(expr.h1)
            return f'modifies {locs} {h0} {h1}'

        elif isinstance(expr, BufferGet):
            h = self._expr_str(expr.heap)
            b = self._expr_str(expr.buf)
            i = self._expr_str(expr.index)
            return f'Buffer.get {h} {b} {i}'

        elif isinstance(expr, BufferLength):
            inner = self._expr_str(expr.expr)
            return f'Buffer.length({inner})'

        else:
            return f'<{type(expr).__name__}>'

    # ── Pattern → string ────────────────────────────────────────────────────

    def _pattern_str(self, pat: Pattern) -> str:
        if isinstance(pat, PatWild):
            return '_'
        elif isinstance(pat, PatVar):
            return pat.name
        elif isinstance(pat, PatConst):
            return str(pat.value)
        elif isinstance(pat, PatCons):
            h = self._pattern_str(pat.head)
            t = self._pattern_str(pat.tail)
            return f'{h} :: {t}'
        elif isinstance(pat, PatApp):
            args_str = ', '.join(self._pattern_str(a) for a in pat.args)
            if pat.name == 'None':
                return 'None'
            if pat.name == 'Some':
                return f'Some({args_str})' if args_str else 'Some(_)'
            if pat.name == 'Cons':
                return self._pattern_cons_chain(pat)
            if pat.name == 'Nil':
                return '[]'
            return f'{pat.name}({args_str})'
        elif isinstance(pat, PatTuple):
            items = ', '.join(self._pattern_str(p) for p in pat.items)
            return f'({items})'
        elif isinstance(pat, PatOr):
            return ' | '.join(self._pattern_str(p) for p in pat.patterns)
        elif isinstance(pat, PatRecord):
            fields = ', '.join(f'{f}={self._pattern_str(p)}' for f, p in pat.fields)
            return f'{{{fields}}}'
        else:
            return f'<{type(pat).__name__}>'

    def _pattern_cons_chain(self, pat: Pattern) -> str:
        """Convert nested Cons chain to [a, b, *rest] syntax."""
        items = []
        rest = None
        current = pat
        while isinstance(current, PatApp) and current.name == 'Cons' and len(current.args) == 2:
            items.append(self._pattern_str(current.args[0]))
            current = current.args[1]
        if isinstance(current, PatApp) and current.name == 'Nil':
            pass
        elif isinstance(current, PatWild):
            rest = '_'
        elif isinstance(current, PatVar):
            rest = current.name
        else:
            rest = self._pattern_str(current)

        if not items and rest is None:
            return '[]'
        elif rest is None:
            return f'[{", ".join(items)}]'
        elif not items:
            return f'[*{rest}]'
        else:
            return f'[{", ".join(items)}, *{rest}]'
    def _expr_cons_chain(self, expr: Expr) -> str:
        """Convert nested Cons chain in expressions to [a, b, *rest] syntax."""
        items = []
        rest = None
        current = expr
        while isinstance(current, App) and isinstance(current.func, Var) and current.func.name == 'Cons' and len(current.args) == 2:
            items.append(self._expr_str(current.args[0]))
            current = current.args[1]
        if isinstance(current, Var) and current.name == 'Nil':
            pass
        elif isinstance(current, Var):
            rest = current.name
        else:
            rest = self._expr_str(current)

        if not items and rest is None:
            return '[]'
        elif rest is None:
            return f'[{", ".join(items)}]'
        elif not items:
            return f'[*{rest}]'
        else:
            return f'[{", ".join(items)}, *{rest}]'

