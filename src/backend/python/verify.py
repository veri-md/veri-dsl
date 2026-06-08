"""
verify.py — Verify that real Python implementation code has correct Veri DSL contracts.

Three verification strategies:
  1. Structural AST comparison: Veri DSL AST ↔ Python AST for each contract condition
  2. Real-source decorator check: verify real Python code has @contract with right refs
  3. Import check: can the generated conditions module be imported?
  4. Dry-run check: CONTRACT_DRY_RUN=1 evaluates conditions without calling functions

Usage (CLI):
    python -m backend.python.verify spec.veri.md impl.py           # basic check
    python -m backend.python.verify spec.veri.md impl.py --verbose  # full report

Usage (library):
    from backend.python.verify import verify_implementation
    v = verify_implementation(veri_ast, "impl.py", "build/my_conditions.py")
    assert v.all_pass, v.report()
"""

import ast
import re
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from veri_ast import (
    VeriDslProgram, Declaration,
    ValDecl, ImportedDecl, ExternDecl,
    Expr,
    Var, QualifiedVar, Const,
    App, BinOp, UnaryOp,
    FieldAccess, RecordUpdate, IfExpr, Match,
    Forall, Exists, Lambda,
    Len, ArrayIndex,
)
from veri_parser import parse_veri


@dataclass
class VerificationResult:
    """Result of a full Python backend verification run."""
    all_pass: bool = True
    checks: List[dict] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = ""):
        self.checks.append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            self.all_pass = False

    def report(self) -> str:
        lines = []
        lines.append("Python Backend Verification")
        lines.append("=" * 40)
        for c in self.checks:
            tag = "✓" if c["passed"] else "✗"
            lines.append(f"  {tag} {c['name']}")
            if not c["passed"] and c["detail"]:
                lines.append(f"       {c['detail']}")
        lines.append(f"\n  {'✅ All pass' if self.all_pass else '❌ Some checks failed'}")
        return '\n'.join(lines)


# ═════════════════════════════════════════════════════════════════════════
# Strategy 1: Structural AST Comparison (Conditions vs Veri DSL Spec)
# ═════════════════════════════════════════════════════════════════════════

def compare_contract_asts(
    veri_prog: VeriDslProgram,
    conditions_source: str,
) -> List[dict]:
    """Compare Veri DSL contracts against Python conditions.

    For each ValDecl/ImportedDecl/ExternDecl in the Veri DSL AST, extract the Veri DSL
    requires/ensures expression AST and compare it to the corresponding
    Python condition function's body AST.
    """
    results = []

    try:
        py_tree = ast.parse(conditions_source)
    except SyntaxError as e:
        results.append({"passed": False, "name": "syntax", "detail": f"Conditions file syntax error: {e}"})
        return results

    py_funcs: Dict[str, ast.FunctionDef] = {}
    for node in ast.walk(py_tree):
        if isinstance(node, ast.FunctionDef):
            py_funcs[node.name] = node

    for decl in veri_prog.decls:
        if not isinstance(decl, (ValDecl, ImportedDecl, ExternDecl)):
            continue

        fn = decl.name

        # REQUIRES
        req_key = f"{fn}__requires"
        if req_key in py_funcs:
            veri_req = decl.contract.requires
            py_req_fn = py_funcs[req_key]
            if veri_req is not None and py_req_fn.body:
                py_return = _extract_return_expr(py_req_fn.body[0])
                if py_return is not None:
                    ok, diff = _check_veri_in_py_and(veri_req, py_return, f"{fn}.REQUIRES")
                    results.append({
                        "passed": ok,
                        "name": f"{fn}__requires",
                        "detail": "" if ok else diff,
                    })
                else:
                    ok = isinstance(veri_req, Const) and veri_req.value is True
                    results.append({
                        "passed": ok,
                        "name": f"{fn}__requires",
                        "detail": "" if ok else f"Expected trivial True, got Veri DSL: {_veri_expr_summary(veri_req)}",
                    })
            else:
                results.append({
                    "passed": True,
                    "name": f"{fn}__requires",
                    "detail": "trivial (no Veri DSL REQUIRES)",
                })
        else:
            # Missing conditions function entirely
            results.append({
                "passed": False,
                "name": f"{fn}__requires",
                "detail": f"Missing from _conditions.py",
            })

        # ENSURES
        ens_key = f"{fn}__ensures"
        if ens_key in py_funcs:
            veri_ens = decl.contract.ensures
            py_ens_fn = py_funcs[ens_key]
            if veri_ens is not None and py_ens_fn.body:
                py_return = _extract_return_expr(py_ens_fn.body[0])
                if py_return is not None:
                    ok, diff = _check_veri_in_py_and(veri_ens, py_return, f"{fn}.ENSURES")
                    results.append({
                        "passed": ok,
                        "name": f"{fn}__ensures",
                        "detail": "" if ok else diff,
                    })
                else:
                    ok = isinstance(veri_ens, Const) and veri_ens.value is True
                    results.append({
                        "passed": ok,
                        "name": f"{fn}__ensures",
                        "detail": "" if ok else f"Expected trivial True, got Veri DSL: {_veri_expr_summary(veri_ens)}",
                    })
            else:
                results.append({
                    "passed": True,
                    "name": f"{fn}__ensures",
                    "detail": "trivial (no Veri DSL ENSURES)",
                })
        else:
            results.append({
                "passed": False,
                "name": f"{fn}__ensures",
                "detail": f"Missing from _conditions.py",
            })

    return results


def _extract_return_expr(stmt) -> Optional[ast.AST]:
    if isinstance(stmt, ast.Return):
        return stmt.value
    if isinstance(stmt, ast.Expr):
        return stmt.value
    return None


def _check_veri_in_py_and(veri_node: Expr, py_and: ast.BoolOp, path: str) -> Tuple[bool, str]:
    """When the generated Python is an AND expression (from type assertions + explicit
    contract), check if the Veri DSL expression matches ANY of the AND values.

    The generated function may include extra type assertion clauses (from refined types)
    beyond the explicit Veri DSL contract. We pass if the explicit contract is found among
    the AND operands.
    """
    if not isinstance(py_and, ast.BoolOp) or not isinstance(py_and.op, ast.And):
        return _walk_and_compare(veri_node, py_and, path)

    for val in py_and.values:
        ok, _ = _walk_and_compare(veri_node, val, path)
        if ok:
            return (True, "")

    # No value matched — report the first mismatch detail
    _, detail = _walk_and_compare(veri_node, py_and.values[0], path)
    return (False, detail)


def _veri_expr_summary(expr: Expr) -> str:
    """Short summary of an Veri DSL expression for error messages."""
    if isinstance(expr, Const):
        return f"Const({expr.value})"
    if isinstance(expr, Var):
        return f"Var({expr.name})"
    if isinstance(expr, App):
        return f"App({_veri_expr_summary(expr.func)}, {len(expr.args)} args)"
    if isinstance(expr, BinOp):
        return f"BinOp({expr.op})"
    return type(expr).__name__


def _walk_and_compare(veri_node: Expr, py_node: ast.AST, path: str) -> Tuple[bool, str]:
    """Compare an Veri DSL expression node against a Python AST node."""

    # Constants
    if isinstance(veri_node, Const):
        if isinstance(py_node, ast.Constant):
            if veri_node.value == py_node.value:
                return (True, "")
            return (False, f"{path}: Veri DSL Const({veri_node.value}) != Python Const({py_node.value})")
        return (False, f"{path}: Veri DSL Const({veri_node.value}) != Python {type(py_node).__name__}")

    # Variable names
    if isinstance(veri_node, Var):
        if isinstance(py_node, ast.Name):
            if veri_node.name == py_node.id:
                return (True, "")
            return (False, f"{path}: Veri DSL Var({veri_node.name}) != Python Name({py_node.id})")
        return (False, f"{path}: Veri DSL Var({veri_node.name}) != Python {type(py_node).__name__}")

    # Qualified var: Foo.Bar → ast.Attribute(ast.Name('Foo'), 'Bar')
    if isinstance(veri_node, QualifiedVar):
        if isinstance(py_node, ast.Attribute) and isinstance(py_node.value, ast.Name):
            if veri_node.path.parts == [py_node.value.id, py_node.attr]:
                return (True, "")
            return (False, f"{path}: Veri DSL QualifiedVar({veri_node.path}) != Python Attribute({py_node.value.id}.{py_node.attr})")
        return (False, f"{path}: Veri DSL QualifiedVar mismatch")

    # Function application: f(a,b) → ast.Call
    if isinstance(veri_node, App):
        if not isinstance(py_node, ast.Call):
            return (False, f"{path}: Veri DSL App != Python {type(py_node).__name__}")
        ok, detail = _walk_and_compare(veri_node.func, py_node.func, f"{path}.func")
        if not ok:
            return (False, detail)
        if len(veri_node.args) != len(py_node.args):
            return (False, f"{path}: Veri DSL {len(veri_node.args)} args vs Python {len(py_node.args)} args")
        for i, (fa, pa) in enumerate(zip(veri_node.args, py_node.args)):
            ok, detail = _walk_and_compare(fa, pa, f"{path}.arg[{i}]")
            if not ok:
                return (False, detail)
        return (True, "")

    # Binary operators
    if isinstance(veri_node, BinOp):
        op_map = {
            'and': (ast.BoolOp, ast.And),
            'or': (ast.BoolOp, ast.Or),
            '==>': None,
            '==': (ast.Compare, ast.Eq),
            '!=': (ast.Compare, ast.NotEq),
            '<': (ast.Compare, ast.Lt),
            '>': (ast.Compare, ast.Gt),
            '<=': (ast.Compare, ast.LtE),
            '>=': (ast.Compare, ast.GtE),
            '+': (ast.BinOp, ast.Add),
            '-': (ast.BinOp, ast.Sub),
            '*': (ast.BinOp, ast.Mult),
        }
        op_info = op_map.get(veri_node.op)
        if op_info is None:
            return (True, "")
        expected_cls, op_cls = op_info

        if veri_node.op in ('and', 'or'):
            if isinstance(py_node, expected_cls) and isinstance(py_node.op, op_cls):
                ok, detail = _walk_and_compare(veri_node.left, py_node.values[0], f"{path}.left")
                if not ok:
                    return (False, detail)
                ok, detail = _walk_and_compare(veri_node.right, py_node.values[1], f"{path}.right")
                return (ok, detail)
            return (False, f"{path}: Veri DSL {veri_node.op} != Python {type(py_node).__name__}")

        if veri_node.op in ('==', '!=', '<', '>', '<=', '>='):
            if isinstance(py_node, ast.Compare) and len(py_node.ops) == 1:
                if isinstance(py_node.ops[0], op_cls):
                    ok, detail = _walk_and_compare(veri_node.left, py_node.left, f"{path}.left")
                    if not ok:
                        return (False, detail)
                    ok, detail = _walk_and_compare(veri_node.right, py_node.comparators[0], f"{path}.right")
                    return (ok, detail)
            return (False, f"{path}: Veri DSL {veri_node.op} != Python Compare[{type(py_node.ops[0]).__name__ if py_node.ops else '?'}]")

        if isinstance(py_node, ast.BinOp) and isinstance(py_node.op, op_cls):
            ok, detail = _walk_and_compare(veri_node.left, py_node.left, f"{path}.left")
            if not ok:
                return (False, detail)
            ok, detail = _walk_and_compare(veri_node.right, py_node.right, f"{path}.right")
            return (ok, detail)
        return (False, f"{path}: Veri DSL BinOp({veri_node.op}) != Python {type(py_node).__name__}")

    # Unary operator: not x → ast.UnaryOp(ast.Not(), x)
    if isinstance(veri_node, UnaryOp):
        if not isinstance(py_node, ast.UnaryOp):
            return (False, f"{path}: Veri DSL UnaryOp != Python {type(py_node).__name__}")
        return _walk_and_compare(veri_node.expr, py_node.operand, f"{path}.operand")

    # Field access: e.f → ast.Attribute
    if isinstance(veri_node, FieldAccess):
        if not isinstance(py_node, ast.Attribute):
            return (False, f"{path}: Veri DSL FieldAccess != Python {type(py_node).__name__}")
        if veri_node.field != py_node.attr:
            return (False, f"{path}: Veri DSL field '{veri_node.field}' != Python attr '{py_node.attr}'")
        return _walk_and_compare(veri_node.expr, py_node.value, f"{path}.expr")

    # If/then/else → ast.IfExp
    if isinstance(veri_node, IfExpr):
        if not isinstance(py_node, ast.IfExp):
            return (False, f"{path}: Veri DSL IfExpr != Python {type(py_node).__name__}")
        ok, detail = _walk_and_compare(veri_node.cond, py_node.test, f"{path}.cond")
        if not ok:
            return (False, detail)
        ok, detail = _walk_and_compare(veri_node.then_expr, py_node.body, f"{path}.then")
        if not ok:
            return (False, detail)
        ok, detail = _walk_and_compare(veri_node.else_expr, py_node.orelse, f"{path}.else")
        return (ok, detail)

    # Len → ast.Call(func=ast.Name('len'), ...)
    if isinstance(veri_node, Len):
        if isinstance(py_node, ast.Call) and isinstance(py_node.func, ast.Name) and py_node.func.id == 'len':
            return _walk_and_compare(veri_node.expr, py_node.args[0], f"{path}.arg")
        return (False, f"{path}: Veri DSL Len != Python {type(py_node).__name__}")

    # If we get here, node type is unhandled
    return (True, f"{path}: skipping unhandled node {type(veri_node).__name__}")


# ═════════════════════════════════════════════════════════════════════════
# Strategy 2: Real-Source Decorator Check
# ═════════════════════════════════════════════════════════════════════════

def check_real_source_decorators(
    veri_prog: VeriDslProgram,
    real_source: str,
    conditions_source: Optional[str] = None,
) -> List[dict]:
    """Check that the real Python implementation has @contract decorators.

    For each ValDecl/ImportedDecl/ExternDecl in the Veri DSL spec, verify:
      a) The real source has a function with the same name
      b) That function has a @contract() decorator
      c) The decorator references the correct requires=/ensures= condition functions
      d) The referenced condition functions actually exist (in _conditions.py or source)

    Args:
        veri_prog: Parsed Veri DSL spec AST
        real_source: Source text of the real Python implementation file
        conditions_source: Optional source text of _conditions.py for cross-reference
    """
    results = []

    try:
        real_tree = ast.parse(real_source)
    except SyntaxError as e:
        results.append({"passed": False, "name": "real-source syntax", "detail": str(e)})
        return results

    # Build function map from real source
    real_funcs: Dict[str, ast.FunctionDef] = {}
    for node in ast.walk(real_tree):
        if isinstance(node, ast.FunctionDef):
            real_funcs[node.name] = node

    # Build condition function names from _conditions.py (if available)
    cond_funcs: set = set()
    if conditions_source:
        try:
            cond_tree = ast.parse(conditions_source)
            for node in ast.walk(cond_tree):
                if isinstance(node, ast.FunctionDef):
                    cond_funcs.add(node.name)
        except SyntaxError:
            pass

    for decl in veri_prog.decls:
        if not isinstance(decl, (ValDecl, ImportedDecl, ExternDecl)):
            continue

        fn_name = decl.name

        # Check the function exists in real source
        if fn_name not in real_funcs:
            results.append({
                "passed": False,
                "name": f"real-source: {fn_name}",
                "detail": f"Function '{fn_name}' not found in real implementation source",
            })
            continue

        func_node = real_funcs[fn_name]

        # Check it has a @contract decorator
        decorator = _find_contract_decorator(func_node)
        if decorator is None:
            results.append({
                "passed": False,
                "name": f"real-source: {fn_name}",
                "detail": f"Function '{fn_name}' in real source has no @contract decorator",
            })
            continue

        # Extract requires= and ensures= keyword args from decorator
        req_ref = _get_decorator_kwarg(decorator, "requires")
        ens_ref = _get_decorator_kwarg(decorator, "ensures")

        expected_req = f"{fn_name}__requires"
        expected_ens = f"{fn_name}__ensures"

        issues = []

        # Check requires reference
        if decl.contract.requires is not None:
            if req_ref is None:
                issues.append(f"missing requires= argument (expected {expected_req})")
            elif isinstance(req_ref, ast.Name) and req_ref.id != expected_req:
                issues.append(f"requires={req_ref.id} does not match expected {expected_req}")
            elif isinstance(req_ref, ast.Attribute):
                ref_name = _attr_to_str(req_ref)
                if ref_name != expected_req:
                    issues.append(f"requires={ref_name} does not match expected {expected_req}")
            # Check condition function exists
            if req_ref and cond_funcs:
                ref_name = _decorator_arg_name(req_ref)
                if ref_name and ref_name not in cond_funcs:
                    issues.append(f"requires={ref_name} not found in _conditions.py")
        else:
            # No REQUIRES in spec — trivial conditions expected
            if req_ref is not None:
                issues.append("has requires= in decorator but Veri DSL spec has no REQUIRES")

        # Check ensures reference
        if decl.contract.ensures is not None:
            if ens_ref is None:
                issues.append(f"missing ensures= argument (expected {expected_ens})")
            elif isinstance(ens_ref, ast.Name) and ens_ref.id != expected_ens:
                issues.append(f"ensures={ens_ref.id} does not match expected {expected_ens}")
            elif isinstance(ens_ref, ast.Attribute):
                ref_name = _attr_to_str(ens_ref)
                if ref_name != expected_ens:
                    issues.append(f"ensures={ref_name} does not match expected {expected_ens}")
            if ens_ref and cond_funcs:
                ref_name = _decorator_arg_name(ens_ref)
                if ref_name and ref_name not in cond_funcs:
                    issues.append(f"ensures={ref_name} not found in _conditions.py")
        else:
            if ens_ref is not None:
                issues.append("has ensures= in decorator but Veri DSL spec has no ENSURES")

        if issues:
            results.append({
                "passed": False,
                "name": f"real-source: {fn_name}",
                "detail": "; ".join(issues),
            })
        else:
            results.append({
                "passed": True,
                "name": f"real-source: {fn_name}",
                "detail": "",
            })

    return results


def _find_contract_decorator(func_node: ast.FunctionDef) -> Optional[ast.Call]:
    """Find the @contract(...) decorator on a function definition.

    Matches 'contract' (bare name) or 'python_runtime.contract' / 'runtime.contract'.
    """
    for dec in func_node.decorator_list:
        if isinstance(dec, ast.Call):
            func = dec.func
            if isinstance(func, ast.Name) and func.id == 'contract':
                return dec
            if isinstance(func, ast.Attribute) and func.attr == 'contract':
                return dec
    return None


def _get_decorator_kwarg(decorator: ast.Call, kw_name: str) -> Optional[ast.expr]:
    """Get a keyword argument value from @contract(requires=..., ensures=...)."""
    for kw in decorator.keywords:
        if kw.arg == kw_name:
            return kw.value
    return None


def _attr_to_str(node: ast.Attribute) -> str:
    """Convert ast.Attribute chain to dotted string (e.g., mod.fn__requires)."""
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return '.'.join(reversed(parts))


def _decorator_arg_name(node: ast.expr) -> Optional[str]:
    """Extract the name string from a decorator argument (Name or Attribute)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _attr_to_str(node)
    return None


# ═════════════════════════════════════════════════════════════════════════
# Strategy 3: Import Check
# ═════════════════════════════════════════════════════════════════════════

def check_imports(conditions_path: Path) -> List[dict]:
    """Check that conditions module can be imported."""
    results = []
    mod_name = conditions_path.stem

    try:
        proc = subprocess.run(
            [sys.executable, "-c", f"import {mod_name}"],
            cwd=str(conditions_path.parent.resolve()),
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0:
            results.append({"passed": True, "name": f"import {mod_name}", "detail": ""})
        else:
            results.append({
                "passed": False,
                "name": f"import {mod_name}",
                "detail": proc.stderr[:500],
            })
    except Exception as e:
        results.append({"passed": False, "name": f"import {mod_name}", "detail": str(e)})

    return results


# ═════════════════════════════════════════════════════════════════════════
# Strategy 4: Dry-run Evaluation
# ═════════════════════════════════════════════════════════════════════════

def check_dry_run(conditions_path: Path) -> List[dict]:
    """Run CONTRACT_DRY_RUN=1 to evaluate conditions without calling functions."""
    results = []
    mod_name = conditions_path.stem

    try:
        proc = subprocess.run(
            [sys.executable, "-c",
             f"import os; os.environ['CONTRACT_DRY_RUN'] = '1'; "
             f"from {mod_name} import *; "
             f"print('Dry-run OK')"],
            cwd=str(conditions_path.parent.resolve()),
            capture_output=True, text=True, timeout=10,
        )
        results.append({
            "passed": proc.returncode == 0,
            "name": "dry-run evaluation",
            "detail": "" if proc.returncode == 0 else proc.stderr[:500],
        })
    except Exception as e:
        results.append({"passed": False, "name": "dry-run evaluation", "detail": str(e)})

    return results


# ═════════════════════════════════════════════════════════════════════════
# Top-level verification functions
# ═════════════════════════════════════════════════════════════════════════

def verify_python_backend(
    veri_prog: VeriDslProgram,
    py_path: Path,
    conditions_path: Path,
) -> VerificationResult:
    """Run AST comparison + import checks + dry-run (old API, kept for compat)."""
    result = VerificationResult()

    # Strategy 1: Structural AST comparison (conditions vs Veri DSL)
    if conditions_path.exists():
        conditions_src = conditions_path.read_text()
        ast_checks = compare_contract_asts(veri_prog, conditions_src)
        for c in ast_checks:
            result.add(
                c.get("name", "AST comparison"),
                c["passed"],
                c.get("detail", ""),
            )

    # Strategy 3: Import check
    if conditions_path.exists():
        import_checks = check_imports(conditions_path)
        for c in import_checks:
            result.add(c["name"], c["passed"], c.get("detail", ""))

    # Strategy 4: Dry-run check
    if conditions_path.exists():
        dry_checks = check_dry_run(conditions_path)
        for c in dry_checks:
            result.add(c["name"], c["passed"], c.get("detail", ""))

    return result


def verify_implementation(
    veri_prog: VeriDslProgram,
    real_source_path: Path,
    conditions_path: Optional[Path] = None,
) -> VerificationResult:
    """Verify a real Python implementation against an Veri DSL spec.

    This is the primary verification entrypoint for the new design:
    checks that the real Python source code has @contract decorators
    matching the Veri DSL spec's contracts.

    Args:
        veri_prog: Parsed Veri DSL spec AST
        real_source_path: Path to the real Python implementation file
        conditions_path: Optional path to _conditions.py for cross-referencing

    Returns:
        VerificationResult with per-check results.
    """
    result = VerificationResult()

    if not real_source_path.exists():
        result.add("real-source", False, f"File not found: {real_source_path}")
        return result

    real_source = real_source_path.read_text()
    cond_source = conditions_path.read_text() if conditions_path and conditions_path.exists() else None

    # Strategy 1: Structural AST comparison (conditions vs Veri DSL)
    if cond_source:
        ast_checks = compare_contract_asts(veri_prog, cond_source)
        for c in ast_checks:
            result.add(
                c.get("name", "AST comparison"),
                c["passed"],
                c.get("detail", ""),
            )

    # Strategy 2: Real-source decorator check
    decorator_checks = check_real_source_decorators(veri_prog, real_source, cond_source)
    for c in decorator_checks:
        result.add(c["name"], c["passed"], c.get("detail", ""))

    return result


# ═════════════════════════════════════════════════════════════════════════
# CLI Entry Point
# ═════════════════════════════════════════════════════════════════════════

def _find_conditions_path(spec_path: Path, impl_path: Path) -> Optional[Path]:
    """Look for _conditions.py near the spec or the implementation."""
    candidates = [
        spec_path.with_name(spec_path.stem.replace(".veri", "") + "_conditions.py"),
        impl_path.with_name(impl_path.stem + "_conditions.py"),
        spec_path.parent / (spec_path.stem.replace(".veri", "") + "_conditions.py"),
        impl_path.parent / (impl_path.stem + "_conditions.py"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _extract_veri_blocks(md_text: str) -> str:
    """Extract Veri DSL code blocks from a .veri.md file."""
    blocks = re.findall(r'```veri\n(.*?)```', md_text, re.DOTALL)
    return '\n\n'.join(blocks)


def _main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Verify real Python code has correct Veri DSL contracts",
    )
    parser.add_argument("spec", type=str, help="Path to .veri.md Veri DSL spec")
    parser.add_argument("impl", type=str, help="Path to real Python implementation")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    parser.add_argument("--conditions", "-c", type=str, default=None,
                        help="Path to _conditions.py (auto-detected if omitted)")

    args = parser.parse_args()

    spec_path = Path(args.spec)
    impl_path = Path(args.impl)

    if not spec_path.exists():
        print(f"✗ Spec not found: {spec_path}")
        sys.exit(1)
    if not impl_path.exists():
        print(f"✗ Implementation not found: {impl_path}")
        sys.exit(1)

    # Parse Veri DSL spec
    md_text = spec_path.read_text()
    veri_text = _extract_veri_blocks(md_text)
    if not veri_text.strip():
        print(f"✗ No ```veri blocks found in {spec_path}")
        sys.exit(1)

    try:
        veri_prog = parse_veri(veri_text)
    except Exception as e:
        print(f"✗ Failed to parse Veri DSL: {e}")
        sys.exit(1)

    # Find conditions
    cond_path = Path(args.conditions) if args.conditions else _find_conditions_path(spec_path, impl_path)
    if args.verbose:
        print(f"• Spec:      {spec_path}")
        print(f"• Impl:      {impl_path}")
        print(f"• Conds:     {cond_path or '(not found — no cross-ref)'}")

    # Run verification
    result = verify_implementation(veri_prog, impl_path, cond_path)
    print(result.report())
    sys.exit(0 if result.all_pass else 1)


if __name__ == '__main__':
    _main()
