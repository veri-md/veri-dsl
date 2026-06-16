"""
dafny_printer.py — Pretty-print VeriDslProgram AST to Dafny syntax.
"""

import re
from typing import List
from veri_ast import *


def _to_dafny_type(name: str) -> str:
    """Map Veri DSL/F* type names to Dafny types."""
    _TYPE_MAP = {
        'Prims.nat': 'nat',
        'Prims.bool': 'bool',
        'Prims.int': 'int',
        'Prims.string': 'string',
        'float64': 'int',
        'float32': 'int',
        'int32': 'int',
        'int64': 'int',
        'uint32': 'int',
        'uint64': 'int',
        'string': 'string',
        'bool': 'bool',
        'byte': 'int',
        'None': '()',
        'int': 'int',
        'nat': 'nat',
        'unit': '()',
        'Type': 'type',
        'Type0': 'type',
    }
    return _TYPE_MAP.get(name, name)


class DafnyPrinter:
    def __init__(self):
        self.lines: List[str] = []
        self.indent = 0
        self._imported_modules: set = set()  # track imported modules to deduplicate

    def _line(self, text: str = ''):
        if text:
            self.lines.append('    ' * self.indent + text)
        else:
            self.lines.append('')

    def print(self, program: VeriDslProgram) -> str:
        if program.module:
            mod_name = program.module.name.parts[-1] if program.module.name.parts else 'Module'
            self._line(f"module {mod_name} {{")
            self.indent += 1
            self._line()

        for decl in program.decls:
            self._print_decl(decl)

        if program.module:
            self.indent -= 1
            self._line("}")

        return '\n'.join(self.lines)

    def _print_decl(self, decl: Declaration):
        if isinstance(decl, OpenDecl):
            self._print_open(decl)
        elif isinstance(decl, ModuleDecl):
            mod_name = decl.name.parts[-1] if decl.name.parts else 'Module'
            self._line(f"module {mod_name} {{")
            self.indent += 1
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
            if decl.module_path:
                # Import from another Veri DSL module — emit import opened
                # Deduplicate: multiple imports from same module → one import
                if decl.module_path not in self._imported_modules:
                    self._imported_modules.add(decl.module_path)
                    self._line(f"import opened {decl.module_path}")
            else:
                # Bare import — emit {:extern} as fallback
                self._print_extern_or_import(decl, keyword='{:extern}')
        elif isinstance(decl, ExternDecl):
            self._print_extern_or_import(decl, keyword='{:extern}')
        elif isinstance(decl, PragmaDecl):
            self._line(decl.text)
        # TargetDecl — not part of Dafny, skip
        self._line()

    def _print_open(self, d: OpenDecl):
        """Print a module-level import in Dafny.

        Dafny only supports `import opened ModuleName` (single module).
        For Veri DSL imports with multi-part paths (e.g. "ConfigStore.config_entry"
        type import), only the first part (the module name) is used.
        """
        parts = d.path.parts
        mod_name = parts[0] if parts else ''
        if mod_name and mod_name not in self._imported_modules:
            self._imported_modules.add(mod_name)
            self._line(f"import opened {mod_name}")

    def _print_abs(self, d: TypeAbstract):
        parts = [f"type {d.name}"]
        if d.params:
            params_str = ', '.join(_to_dafny_type(p.name) for p in d.params)
            if params_str:
                parts.append(f"({params_str})")
        self._line(' '.join(parts))

    def _print_alias(self, d: TypeAlias):
        if d.typ is None:
            self._line(f"type {d.name}")
            return
        if isinstance(d.typ, RefinedType):
            r = d.typ
            n = r.binder.name or 'x'
            base = self._type(r.binder.typ)
            pred = self._expr(r.predicate)
            # Substitute common variable names with the Dafny binder name
            import re
            for old_name in ['buf', 'lst', 'cache', 'req', 'existing', 'new_elem']:
                pred = re.sub(rf'\b{old_name}\b', n, pred)
            self._line(f"type {d.name} = {n}: {base} | {pred}")
        else:
            type_str = self._type(d.typ)
            self._line(f"type {d.name} = {type_str}")

    def _print_record(self, d: TypeRecord):
        field_strs = [f"{f.name}: {self._type(f.typ)}" for f in d.fields]
        fields_inner = ', '.join(field_strs)
        self._line(f"datatype {d.name} = {d.name}({fields_inner})")

    def _print_variant(self, d: TypeVariant):
        self._line(f"datatype {d.name} =")
        self.indent += 1
        for i, c in enumerate(d.constructors):
            prefix = "| "
            if c.args:
                arg_strs = [f"{a.name}: {self._type(a.typ)}" for a in c.args]
                self._line(f"{prefix}{c.name}({', '.join(arg_strs)})")
            else:
                self._line(f"{prefix}{c.name}")
        self.indent -= 1

    def _named_return(self, ret: str, ensures_str) -> str:
        """Bind the return value to `result` when a postcondition refers to it.

        The Veri DSL reserves `result` to name a function's return value inside
        ENSURES, but Dafny only puts that name in scope if the signature
        declares it: `function f(...): (result: T)`. When the lowered ensures
        mentions `result`, emit the named form so the identifier resolves.
        """
        if ensures_str is not None and re.search(r'\bresult\b', ensures_str):
            return f"(result: {ret})"
        return ret

    def _print_let(self, d: LetDecl):
        if d.body is not None:
            if not d.params:
                # Ghost constant
                ret = f": {self._type(d.typ)}" if d.typ else ""
                body_str = self._expr(d.body)
                self._line(f"const {d.name}{ret} :=")
                self.indent += 1
                self._line(body_str)
                self.indent -= 1
                return
            # Function with params
            params_str = ', '.join(f"{p.name}: {self._type(p.typ)}" for p in d.params)
            ret = f": {self._type(d.typ)}" if d.typ else ""
            body_str = self._expr(d.body)
            self._line(f"function {d.name}({params_str}){ret}")
            self._line("{")
            self.indent += 1
            self._line(body_str)
            self.indent -= 1
            self._line("}")
            return
        # Declaration without body
        params = ', '.join(f"{p.name}: {self._type(p.typ)}" for p in d.params)
        ret = f": {self._type(d.typ)}" if d.typ else ""
        if params:
            self._line(f"function {d.name}({params}){ret}")
        else:
            self._line(f"function {d.name}{ret}")

    def _print_extern_or_import(self, d, keyword: str):
        """Print an imported or external function declaration in Dafny.

        Both imported and external functions are declared with {:extern}:
          - function {:extern} fn_name(params): ret
            requires ... ensures ...
          - method {:extern} fn_name(params)
            requires ... ensures ...
        """
        params_str = ', '.join(f"{p.name}: {self._type(p.typ)}" for p in d.params)
        ens = self._expr(d.contract.ensures) if d.contract.ensures is not None else None
        if d.return_type:
            ret = self._named_return(self._type(d.return_type), ens)
            self._line(f"function {keyword} {d.name}({params_str}): {ret}")
        else:
            self._line(f"method {keyword} {d.name}({params_str})")
        if d.contract.requires:
            self._line(f"  requires {self._expr(d.contract.requires)}")
        if ens is not None:
            self._line(f"  ensures {ens}")
        if d.contract.decreases:
            self._line(f"  decreases {self._expr(d.contract.decreases)}")

    def _print_val(self, d: ValDecl):
        params_str = ', '.join(f"{p.name}: {self._type(p.typ)}" for p in d.params)
        ens = self._expr(d.contract.ensures) if d.contract.ensures is not None else None
        if d.return_type:
            ret = self._named_return(self._type(d.return_type), ens)
            self._line(f"function {d.name}({params_str}): {ret}")
        else:
            self._line(f"method {d.name}({params_str})")
        if d.contract.requires:
            self._line(f"  requires {self._expr(d.contract.requires)}")
        if ens is not None:
            self._line(f"  ensures {ens}")
        if d.contract.decreases:
            self._line(f"  decreases {self._expr(d.contract.decreases)}")
        if d.body is not None:
            self._line("{")
            self.indent += 1
            self._line(self._expr(d.body))
            self.indent -= 1
            self._line("}")

    def _type(self, typ: TypeExpr) -> str:
        if isinstance(typ, PrimType):
            return _to_dafny_type(typ.name)
        if isinstance(typ, TypeVar):
            return typ.name
        if isinstance(typ, NamedType):
            path_str = '.'.join(typ.path.parts)
            return _to_dafny_type(path_str)
        if isinstance(typ, AppType):
            func_type = typ.func
            if isinstance(func_type, NamedType):
                name = '.'.join(func_type.path.parts)
                if name == 'list' or name == 'FStar.List':
                    return f"seq<{self._type(typ.args[0])}>"
                if name == 'option' or name == 'FStar.Option':
                    return f"Option<{self._type(typ.args[0])}>"
            func_str = self._type(func_type)
            args_str = ', '.join(self._type(a) for a in typ.args)
            return f"{func_str}<{args_str}>"
        if isinstance(typ, RefinedType):
            n = typ.binder.name or 'x'
            base = self._type(typ.binder.typ)
            pred = self._expr(typ.predicate)
            return f"{n}: {base} | {pred}"
        if isinstance(typ, TupleType):
            return '(' + ', '.join(self._type(t) for t in typ.items) + ')'
        if isinstance(typ, ArrowType):
            param_strs = [self._type(p.typ) for p in typ.params]
            result_str = self._type(typ.result)
            return ' -> '.join(param_strs + [result_str])
        if isinstance(typ, ListType):
            return f"seq<{self._type(typ.elem)}>"
        if isinstance(typ, OptionType):
            return f"Option<{self._type(typ.elem)}>"
        if isinstance(typ, BufferType):
            return f"seq<{self._type(typ.elem)}>"
        return str(typ)

    def _expr(self, expr: Expr) -> str:
        if isinstance(expr, Const):
            if expr.value is None:
                return '()'
            if isinstance(expr.value, bool):
                return 'true' if expr.value else 'false'
            if isinstance(expr.value, str):
                return f'"{expr.value}"'
            return str(expr.value)
        if isinstance(expr, Var):
            if expr.name == 'None':
                return 'None'
            if expr.name == 'Nil':
                return '[]'
            return expr.name
        if isinstance(expr, QualifiedVar):
            return str(expr.path)
        if isinstance(expr, App):
            # Handle Cons: flatten to [hd1, hd2] + tl when possible
            if isinstance(expr.func, Var) and expr.func.name == 'Cons' and len(expr.args) == 2:
                h = self._expr(expr.args[0])
                t = self._expr(expr.args[1])
                # Check if tail is [] (Nil) — then just [h]
                if t == '[]':
                    return f"[{h}]"
                # Check if tail is also a cons — flatten into list literal
                if isinstance(expr.args[1], App) and isinstance(expr.args[1].func, Var) and expr.args[1].func.name == 'Cons':
                    # Already flattened by recursive call
                    pass
                return f"[{h}] + {t}"
            func = self._expr(expr.func)
            args = ', '.join(self._expr(a) for a in expr.args)
            if isinstance(expr.func, Var) and expr.func.name == 'tuple':
                return '(' + args + ')'
            if expr.args:
                return f"{func}({args})"
            return func
        if isinstance(expr, BinOp):
            op = expr.op
            if op == 'and':
                op_str = '&&'
            elif op == 'or':
                op_str = '||'
            elif op == 'not':
                op_str = '!'
            elif op == '==>':
                op_str = '==>'
            elif op in ('=', '=='):
                op_str = '=='
            elif op == '!=':
                op_str = '!='
            elif op == 'LE':
                op_str = '<='
            elif op == 'GE':
                op_str = '>='
            elif op == 'LT':
                op_str = '<'
            elif op == 'GT':
                op_str = '>'
            else:
                op_str = op
            return f"{self._expr(expr.left)} {op_str} {self._expr(expr.right)}"
        if isinstance(expr, UnaryOp):
            op = expr.op
            if op == 'not':
                return f"!{self._expr(expr.expr)}"
            return f"{op}{self._expr(expr.expr)}"
        if isinstance(expr, FieldAccess):
            return f"{self._expr(expr.expr)}.{expr.field}"
        if isinstance(expr, IfExpr):
            return f"if {self._expr(expr.cond)} then {self._expr(expr.then_expr)} else {self._expr(expr.else_expr)}"
        if isinstance(expr, Match):
            body = str(expr.expr)
            cases_lines = []
            for c in expr.cases:
                pat = self._pattern(c.pattern)
                e = self._expr(c.expr)
                cases_lines.append(f"case {pat} => {e}")
            indent1 = '    ' * (self.indent + 1)
            cases_str = '\n' + indent1 + ('\n' + indent1).join(cases_lines)
            return f"match {self._expr(expr.expr)} {{{cases_str}\n{'    ' * self.indent}}}"
        if isinstance(expr, Forall):
            binders = ', '.join(f"{b.name}: {self._type(b.typ)}" for b in expr.binders)
            body = self._expr(expr.body)
            return f"(forall {binders} :: {body})"
        if isinstance(expr, Exists):
            binders = ', '.join(f"{b.name}: {self._type(b.typ)}" for b in expr.binders)
            body = self._expr(expr.body)
            return f"(exists {binders} :: {body})"
        if isinstance(expr, Lambda):
            params = ', '.join(expr.params)
            body = self._expr(expr.body)
            return f"({params}) => {body}"
        if isinstance(expr, Len):
            return f"|{self._expr(expr.expr)}|"
        if isinstance(expr, ArrayLen):
            return f"{self._expr(expr.arr)}.Length"
        if isinstance(expr, ArrayIndex):
            return f"{self._expr(expr.arr)}[{self._expr(expr.index)}]"
        if isinstance(expr, BufferLength):
            return f"{self._expr(expr.expr)}.Length"
        if isinstance(expr, BufferGet):
            return f"{self._expr(expr.buf)}[{self._expr(expr.index)}]"
        if isinstance(expr, Contains):
            return f"Contains({self._expr(expr.heap)}, {self._expr(expr.ref)})"
        if isinstance(expr, Sel):
            return f"Sel({self._expr(expr.heap)}, {self._expr(expr.ref)})"
        if isinstance(expr, Live):
            return f"Live({self._expr(expr.heap)}, {self._expr(expr.buffer)})"
        if isinstance(expr, Modifies):
            return f"Modifies({self._expr(expr.locs)}, {self._expr(expr.h0)}, {self._expr(expr.h1)})"
        if isinstance(expr, RecordUpdate):
            updates = '; '.join(f"{f} := {self._expr(v)}" for f, v in expr.updates)
            return f"{self._expr(expr.expr)}.({updates})"
        return f"<{type(expr).__name__}>"

    def _pattern(self, pat: Pattern) -> str:
        if isinstance(pat, PatWild):
            return '_'
        if isinstance(pat, PatVar):
            return pat.name
        if isinstance(pat, PatConst):
            if pat.value is None:
                return '()'
            if isinstance(pat.value, bool):
                return 'true' if pat.value else 'false'
            return str(pat.value)
        if isinstance(pat, PatApp):
            if pat.name == 'None':
                return 'None'
            if pat.name == 'Some':
                inner = ', '.join(self._pattern(a) for a in pat.args)
                return f"Some({inner})"
            if pat.name == 'Cons':
                if len(pat.args) == 2:
                    h = self._pattern(pat.args[0])
                    t = self._pattern(pat.args[1])
                    # Single element: [x]
                    if t == '[]':
                        return f"[{h}]"
                    # Head + rest: [h, ..rest]
                    return f"[{h}, ..{t}]"
                return f"Cons({', '.join(self._pattern(a) for a in pat.args)})"
            if pat.name == 'Nil':
                return '[]'
            return f"{pat.name}({', '.join(self._pattern(a) for a in pat.args)})"
        if isinstance(pat, PatCons):
            return f"[{self._pattern(pat.head)}, ..{self._pattern(pat.tail)}]"
        if isinstance(pat, PatTuple):
            return '(' + ', '.join(self._pattern(p) for p in pat.items) + ')'
        if isinstance(pat, PatRecord):
            return '(' + ', '.join(f"{f}: {self._pattern(p)}" for f, p in pat.fields) + ')'
        if isinstance(pat, PatOr):
            return ' | '.join(self._pattern(p) for p in pat.patterns)
        return str(pat)
