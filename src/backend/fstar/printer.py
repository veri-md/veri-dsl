"""
fsti_printer.py — Pretty-print VeriDslProgram AST to F* .fst format.
"""

from typing import List, Set
from veri_ast import *


# F* reserved keywords that cannot be used as record field names or identifiers
_FSTAR_KEYWORDS: Set[str] = {
    'val', 'let', 'type', 'match', 'fun', 'if', 'then', 'else', 'with',
    'for', 'function', 'open', 'module', 'when', 'and', 'or', 'in',
    'true', 'false', 'instance', 'inline_for_extraction', 'effect',
    'assume', 'noeq', 'new', 'effect', 'kind',
}


def _escape_fstar_name(name: str) -> str:
    """Escape a name if it conflicts with F* reserved keywords."""
    if name in _FSTAR_KEYWORDS:
        return name + '_'
    return name


def _to_fstar_name(name: str) -> str:
    """Convert CamelCase to snake_case for F* type names."""
    # Map custom C types to F* primitives
    _TYPE_MAP = {
        'float64': 'Prims.int',    # F* has no built-in float type
        'float32': 'Prims.int',
        'int32': 'Prims.int',
        'int64': 'Prims.int',
        'uint32': 'FStar.UInt32.t',
        'uint64': 'FStar.UInt64.t',
        'string': 'Prims.string',
        'bool': 'Prims.bool',
        'byte': 'FStar.UInt8.t',
        'None': 'unit',
        'int': 'Prims.int',
        'nat': 'Prims.nat',
    }
    if name in _TYPE_MAP:
        return _TYPE_MAP[name]
    if name == name.upper():
        return name.lower()  # ALLCAPS → lowercase
    result = []
    for i, c in enumerate(name):
        if c.isupper() and i > 0:
            result.append('_')
            result.append(c.lower())
        else:
            result.append(c.lower())
    return ''.join(result)

class FStarPrinter:
    def __init__(self):
        self.lines: List[str] = []
        self.indent = 0
        self._binder_name = 'x'
        self._opened_modules: set = set()  # track opened modules to deduplicate

    def _line(self, text: str = ''):
        if text:
            self.lines.append('    ' * self.indent + text)
        else:
            self.lines.append('')

    def print(self, program: VeriDslProgram) -> str:
        if program.module:
            mod = program.module.name
            name_str = str(mod)
            # Capitalize module name for F*
            parts = name_str.split('.')
            parts = [p[0].upper() + p[1:] if p else p for p in parts]
            self._line(f"module {'.'.join(parts)}")
            self._line()

        for decl in program.decls:
            self._print_decl(decl)
        return '\n'.join(self.lines)

    def _print_decl(self, decl: Declaration):
        if isinstance(decl, OpenDecl):
            # Deduplicate: same module opened from ImportedDecl or multiple OpenDecls
            path_str = str(decl.path)
            if path_str not in self._opened_modules:
                self._opened_modules.add(path_str)
                self._line(f"open {decl.path}")
        elif isinstance(decl, ModuleDecl):
            self._line(f"module {decl.name}")
        elif isinstance(decl, TypeAbstract):
            self._print_abs(decl)
        elif isinstance(decl, TypeAlias):
            self._print_alias(decl)
        elif isinstance(decl, TypeRecord):
            self._print_record(decl)
        elif isinstance(decl, TypeVariant):
            self._print_variant(decl)
        elif isinstance(decl, LetDecl):
            self._print_let(decl)
        elif isinstance(decl, ValDecl):
            self._print_val(decl)
        elif isinstance(decl, ImportedDecl):
            self._print_imported(decl)
        elif isinstance(decl, ExternDecl):
            self._print_extern(decl)  # ExternDecl prints as val in F*
        # TargetDecl — not part of F*, skip
        self._line()

    def _print_abs(self, d: TypeAbstract):
        parts = [f"type {_to_fstar_name(d.name)}"]
        if d.params:
            parts.append(str(d.params))
        if d.kind:
            parts.append(f": {self._type(d.kind)}")
        self._line(' '.join(parts))

    def _print_alias(self, d: TypeAlias):
        parts = [f"type {_to_fstar_name(d.name)}"]
        if d.typ:
            type_str = self._type(d.typ)
            if isinstance(d.typ, RefinedType):
                r = d.typ
                n = r.binder.name or 'x'
                base = self._type(r.binder.typ)
                pred = self._expr(r.predicate)
                # Substitute common DSL variable names with the F* binder name
                import re
                for old_name in ['buf', 'lst', 'cache', 'req']:
                    pred = re.sub(rf'\b{old_name}\b', n, pred)
                type_str = f"{n}:{base}{{{pred}}}"
            parts.append(f" = {type_str}")
        self._line(''.join(parts))

    def _print_record(self, d: TypeRecord):
        # F* 2026.05+ requires `noeq` and does not allow newlines inside { }
        # Field names are escaped if they conflict with F* reserved keywords
        fields = "; ".join(f"{_escape_fstar_name(f.name)}: {self._type(f.typ)}" for f in d.fields)
        self._line(f"noeq type {_to_fstar_name(d.name)} = {{ {fields} }}")

    def _print_variant(self, d: TypeVariant):
        self._line(f"type {_to_fstar_name(d.name)} =")
        self.indent += 1
        for c in d.constructors:
            if c.args:
                arg_strs = [f"{a.name}:{self._type(a.typ)}" for a in c.args]
                self._line(f"| {c.name}: {' -> '.join(arg_strs)} -> {d.name}")
            elif c.typ:
                self._line(f"| {c.name}: {self._type(c.typ)}")
            else:
                self._line(f"| {c.name}: {d.name}")
        self.indent -= 1

    def _print_let(self, d: LetDecl):
        parts = ["let"]
        if d.recursive:
            parts.append("rec")
        parts.append(_to_fstar_name(d.name))
        for p in d.params:
            parts.append(f"({p.name}: {self._type(p.typ)})")
        if d.typ:
            # F* 2026.05: let rec with pattern matching and comparisons (<= etc.)
            # requires GTot effect because integer comparisons use GHOST/decode.
            if d.recursive:
                parts.append(f": GTot {self._type(d.typ)}")
            else:
                parts.append(f": {self._type(d.typ)}")
        if d.body is not None:
            body_str = self._expr(d.body)
            if len(parts) <= 3 and '\n' not in body_str:
                # Simple one-liner
                self._line(' '.join(parts) + f" = {body_str}")
            else:
                self._line(' '.join(parts) + " =")
                self.indent += 1
                self._line(body_str)
                self.indent -= 1
        else:
            self._line(' '.join(parts))

    def _print_imported(self, d: ImportedDecl):
        """Print an imported function declaration.

        When module_path is set (import Module.fn_name), emit `open Module`
        so the function comes from the other spec's declarations.
        When bare (import fn_name), emit `assume val` as a fallback.
        """
        if d.module_path:
            # Import from another Veri DSL module — emit open, not assume val
            # Deduplicate: multiple imports from same module → one open
            if d.module_path not in self._opened_modules:
                self._opened_modules.add(d.module_path)
                self._line(f"open {d.module_path}")
            return
        parts = ["assume val", f"{_to_fstar_name(d.name)}:"]
        for p in d.params:
            ptype = self._type(p.typ)
            parts.append(f" {p.name}:{ptype} ->")
        has_contract = d.contract.requires is not None or d.contract.ensures is not None
        eff = 'Pure' if has_contract else 'Tot'
        ret = self._type(d.return_type) if d.return_type else 'unit'
        if d.return_type and isinstance(d.return_type, (AppType, TupleType, RefinedType)):
            ret = f"({ret})"
        parts.append(f" {eff} {ret}")
        self._line(' '.join(parts))
        if d.contract.requires:
            self._line(f"  (requires {self._expr(d.contract.requires)})")
        if d.contract.ensures:
            ens = self._expr(d.contract.ensures)
            # F* 2026: ensures expects prop. Wrap bool expressions with b2t.
            if ens != 'True' and ens != 'False':
                ens = f"Prims.b2t ({ens})"
            self._line(f"  (ensures (fun result -> {ens}))")
        if d.contract.decreases:
            self._line(f"  (decreases {self._expr(d.contract.decreases)})")

    def _print_extern(self, d: ExternDecl):
        """ExternDecl → F* val with Pure/Tot."""
        parts = ["val", f"{_to_fstar_name(d.name)}:"]
        for p in d.params:
            ptype = self._type(p.typ)
            parts.append(f" {p.name}:{ptype} ->")
        has_contract = d.contract.requires is not None or d.contract.ensures is not None
        eff = 'Pure' if has_contract else 'Tot'
        ret = self._type(d.return_type) if d.return_type else 'unit'
        if d.return_type and isinstance(d.return_type, (AppType, TupleType, RefinedType)):
            ret = f"({ret})"
        parts.append(f" {eff} {ret}")
        self._line(' '.join(parts))
        if d.contract.requires:
            self._line(f"  (requires {self._expr(d.contract.requires)})")
        if d.contract.ensures:
            ens = self._expr(d.contract.ensures)
            # F* 2026: ensures expects prop. Wrap bool expressions with b2t.
            if ens != 'True' and ens != 'False':
                ens = f"Prims.b2t ({ens})"
            self._line(f"  (ensures (fun result -> {ens}))")

    def _print_val(self, d: ValDecl):
        # In .fst files, val declarations without let definitions must use
        # `assume val`. Since we now generate .fst files (F* 2026.05+ can't
        # parse records in .fsti), we use assume for body-less TODO functions.
        has_let_body = d.body is not None
        parts = ["assume val" if not has_let_body else "val", f"{_to_fstar_name(d.name)}:"]
        for p in d.params:
            parts.append(f" {p.name}:{self._type(p.typ)} ->")
        has_contract = d.contract.requires is not None or d.contract.ensures is not None
        ret = self._type(d.return_type) if d.return_type else 'unit'
        if d.return_type and isinstance(d.return_type, (AppType, TupleType, RefinedType)):
            ret = f"({ret})"
        if has_contract:
            # F* 2026: inline Pure syntax: Pure ret (pre) (fun result -> post)
            pre = self._expr(d.contract.requires) if d.contract.requires else 'True'
            if pre != 'True' and pre != 'False':
                pre = f"Prims.b2t ({pre})"
            pre = f"({pre})"
            if d.contract.ensures:
                post = self._expr(d.contract.ensures)
                if post != 'True' and post != 'False':
                    post = f"Prims.b2t ({post})"
            else:
                post = 'True'
            parts.append(f" Pure {ret} {pre} (fun result -> {post})")
        else:
            parts.append(f" Pure {ret}")
        self._line(' '.join(parts))

        # When the ValDecl has a body (from Veri DSL `def` with implementation),
        # also emit the corresponding `let` definition so F* has an implementation
        # to go with the `val` signature.
        if has_let_body and d.body is not None:
            body_str = self._expr(d.body)
            let_parts = ["let"]
            # Detect self-recursive functions by checking if the body references
            # the function's own name
            fn_name_fstar = _to_fstar_name(d.name)
            if fn_name_fstar in body_str:
                let_parts.append("rec")
            let_parts.append(fn_name_fstar)
            for p in d.params:
                let_parts.append(f"({p.name}: {self._type(p.typ)})")
            if d.return_type:
                let_parts.append(f": {ret}")

            if '\n' in body_str:
                self._line(' '.join(let_parts) + " =")
                self.indent += 1
                self._line(body_str)
                self.indent -= 1
            else:
                self._line(' '.join(let_parts) + f" = {body_str}")

    def _type(self, typ: TypeExpr) -> str:
        if isinstance(typ, PrimType):
            return _to_fstar_name(typ.name)
        if isinstance(typ, TypeVar):
            return typ.name
        if isinstance(typ, NamedType):
            parts = typ.path.parts
            if len(parts) == 1:
                parts = [_to_fstar_name(p) for p in parts]
            # Multi-part paths (e.g. FStar.Seq.seq) are module-qualified → keep casing
            return '.'.join(parts)
        if isinstance(typ, AppType):
            if typ.args:
                arg_str = self._type(typ.args[0])
                if isinstance(typ.args[0], TupleType):
                    arg_str = f"({arg_str})"
                return f"{self._type(typ.func)} {arg_str}"
            return self._type(typ.func)
        if isinstance(typ, RefinedType):
            return f"{self._type(typ.binder.typ)}{{{self._expr(typ.predicate)}}}"
        if isinstance(typ, TupleType):
            return ' * '.join(self._type(t) for t in typ.items)
        if isinstance(typ, ArrowType):
            return ' -> '.join([self._type(p.typ) for p in typ.params] + [self._type(typ.result)])
        return str(typ)

    def _expr(self, expr: Expr) -> str:
        if isinstance(expr, Const):
            if expr.value is None: return '()'
            if isinstance(expr.value, bool): return 'True' if expr.value else 'False'
            if isinstance(expr.value, float): return '0'
            if isinstance(expr.value, str) and expr.value: return f'"{expr.value}"'
            if isinstance(expr.value, str): return '""'
            return str(expr.value)
        if isinstance(expr, Var):
            if expr.name == 'None': return 'None'
            if expr.name == 'Nil': return '[]'
            return expr.name
        if isinstance(expr, QualifiedVar):
            return str(expr.path)
        if isinstance(expr, App):
            # Handle Cons as infix ::
            if isinstance(expr.func, Var) and expr.func.name == 'Cons' and len(expr.args) == 2:
                h = self._expr(expr.args[0])
                t = self._expr(expr.args[1])
                return f"{h} :: {t}"
            func = self._expr(expr.func)
            args = ' '.join(
                f"({self._expr(a)})" if not isinstance(a, (Var, Const, QualifiedVar, FieldAccess)) and (isinstance(a, App) or isinstance(a, BinOp))
                else self._expr(a)
                for a in expr.args
            )
            if isinstance(expr.func, Var) and expr.func.name == 'tuple':
                return '(' + ', '.join(self._expr(a) for a in expr.args) + ')'
            return f"{func} {args}"
        if isinstance(expr, BinOp):
            op = expr.op
            # [hd2] + tl → hd2 :: tl (list cons)
            if op == '+':
                # [hd2] + tl → hd2 :: tl (list cons), else arithmetic add
                if isinstance(expr.left, App) and isinstance(expr.left.func, Var) and expr.left.func.name == 'Cons':
                    h = self._expr(expr.left.args[0])
                    t = self._expr(expr.right)
                    return f"{h} :: {t}"
                return f"Prims.op_Addition ({self._expr(expr.left)}) ({self._expr(expr.right)})"
            if op == '-':
                return f"Prims.op_Subtraction ({self._expr(expr.left)}) ({self._expr(expr.right)})"
            if op == '*':
                # F* 2026.05.17: Prims.op_Star (NOT op_Multiply — that was 2026.04)
                return f"Prims.op_Star ({self._expr(expr.left)}) ({self._expr(expr.right)})"
            if op == '==':
                # result == True → just result (True is prop, can't compare with bool)
                if isinstance(expr.right, Const) and expr.right.value is True:
                    return self._expr(expr.left)
                if isinstance(expr.left, Const) and expr.left.value is True:
                    return self._expr(expr.right)
                if isinstance(expr.right, Const) and expr.right.value is False:
                    return f"~{self._expr(expr.left)}"
                if isinstance(expr.left, Const) and expr.left.value is False:
                    return f"~{self._expr(expr.right)}"
                # F* 2026: = returns Prims.logical; op_Equality returns Prims.bool
                # Parenthesize both sides to handle complex expressions (e.g. len(xs) == 6)
                return f"Prims.op_Equality ({self._expr(expr.left)}) ({self._expr(expr.right)})"
            if op == '!=':
                # F* 2026: <> returns Prims.logical; op_disEquality returns Prims.bool
                return f"Prims.op_disEquality ({self._expr(expr.left)}) ({self._expr(expr.right)})"
            if op == 'and':
                # F* 2026: && can resolve as l_and (logical).
                # Use explicit op_AmpAmp for bool, always paren for safety.
                return f"Prims.op_AmpAmp ({self._expr(expr.left)}) ({self._expr(expr.right)})"
            if op == 'or':
                # F* 2026: \/ resolves as l_or (logical).
                # Use explicit op_BarBar for bool, always paren for safety.
                return f"Prims.op_BarBar ({self._expr(expr.left)}) ({self._expr(expr.right)})"

            elif op == 'LE': op_str = '<='
            elif op == 'GE': op_str = '>='
            elif op == 'LT': op_str = '<'
            elif op == 'GT': op_str = '>'
            elif op == '<': op_str = '<'
            elif op == '>': op_str = '>'
            elif op == '<=': op_str = '<='
            elif op == '>=': op_str = '>='
            else: op_str = op
            left_s = self._expr(expr.left)
            right_s = self._expr(expr.right)
            if isinstance(expr.left, BinOp):
                left_s = f"({left_s})"
            if isinstance(expr.right, BinOp):
                right_s = f"({right_s})"
            return f"{left_s} {op_str} {right_s}"
        if isinstance(expr, UnaryOp):
            # F* 2026: ~ resolves as l_not (logical). Use op_Negation for bool.
            return f"Prims.op_Negation ({self._expr(expr.expr)})" if expr.op == 'not' else f"{expr.op}{self._expr(expr.expr)}"
        if isinstance(expr, FieldAccess):
            return f"{self._expr(expr.expr)}.{expr.field}"
        if isinstance(expr, IfExpr):
            return f"(if {self._expr(expr.cond)} then {self._expr(expr.then_expr)} else {self._expr(expr.else_expr)})"
        if isinstance(expr, Match):
            def _fmt_case_body(e):
                body = self._expr(e)
                if isinstance(e, Match):
                    return '(' + body + ')'
                return body
            cases = '\n        | '.join(
                f"{self._pattern(c.pattern)} -> {_fmt_case_body(c.expr)}" for c in expr.cases)
            return f"match {self._expr(expr.expr)} with\n        | {cases}"
        if isinstance(expr, Forall):
            binders = ', '.join(f"({b.name}:{self._type(b.typ)})" for b in expr.binders)
            body = self._expr(expr.body)
            return f"(forall {binders}. {body})"
        if isinstance(expr, Exists):
            binders = ', '.join(f"({b.name}:{self._type(b.typ)})" for b in expr.binders)
            body = self._expr(expr.body)
            return f"(exists {binders}. {body})"
        if isinstance(expr, Len):
            return f"List.Tot.length {self._expr(expr.expr)}"
        if isinstance(expr, ArrayLen):
            return f"FStar.Seq.length {self._expr(expr.arr)}"
        if isinstance(expr, ArrayIndex):
            return f"Seq.index {self._expr(expr.arr)} {self._expr(expr.index)}"
        if isinstance(expr, RecordUpdate):
            updates = '; '.join(f"{f}={self._expr(v)}" for f, v in expr.updates)
            return f"{{{self._expr(expr.expr)} with {updates}}}"
        return f"<{type(expr).__name__}>"

    def _pattern(self, pat: Pattern) -> str:
        if isinstance(pat, PatWild): return '_'
        if isinstance(pat, PatVar): return pat.name
        if isinstance(pat, PatConst): return str(pat.value)
        if isinstance(pat, PatApp):
            if pat.name == 'None': return 'None'
            if pat.name == 'Some':
                if len(pat.args) > 1:
                    inner = ', '.join(self._pattern(a) for a in pat.args)
                    return f"Some ({inner})"
                if len(pat.args) == 1:
                    return f"Some ({', '.join(self._pattern(a) for a in pat.args)})"
                return "Some _"
            if pat.name == 'Cons':
                if len(pat.args) >= 2:
                    return f"{self._pattern(pat.args[0])} :: {self._pattern(pat.args[1])}"
                return str(pat.name)
            if pat.name == 'Nil':
                return '[]'
            return f"{pat.name} {' '.join(self._pattern(a) for a in pat.args)}"
        if isinstance(pat, PatTuple):
            return ', '.join(self._pattern(p) for p in pat.items)
        if isinstance(pat, PatCons):
            return f"{self._pattern(pat.head)} :: {self._pattern(pat.tail)}"
        if isinstance(pat, PatOr):
            return ' | '.join(self._pattern(p) for p in pat.patterns)
        return str(pat)
