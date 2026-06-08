"""
inject.py — Write Veri DSL contract conditions into real Python code as @contract decorators.

Takes an Veri DSL spec (.veri.md) and a real Python implementation file, and injects
the @contract(requires=..., ensures=...) decorators onto matching functions.

The injection is non-destructive: it only adds decorators and import lines.
It never removes or changes existing code. The user can review the diff.

Module mapping (same concept as TARGET for other backends):
    TARGET python-assert

    # Map imported Veri DSL modules to their real Python implementation files.
    # Without this, imported functions are assumed to already have decorators.
    python.file SortedListSpec = ../sorted_list/impl.py

Usage (CLI):
    # Dry-run (show what would change, no write)
    python -m backend.python.inject spec.veri.md real_impl.py

    # Write decorators in-place
    python -m backend.python.inject spec.veri.md real_impl.py --write

    # Write to a different output file
    python -m backend.python.inject spec.veri.md real_impl.py -o decorated_impl.py

Usage (library):
    from backend.python.inject import inject_decorators

    changes = inject_decorators(
        spec_path="path/to/spec.veri.md",
        impl_path="path/to/real_impl.py",
        dry_run=True,
    )
    for fn, action in changes:
        print(f"  {action}: {fn}")
"""

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class InjectChange:
    """A single change that would be made to the real code."""
    action: str            # "add_decorator", "add_import", "add_stub", "import_other_module"
    function: str          # Function name affected
    decorator_text: str = ""   # The decorator text being added
    detail: str = ""


@dataclass
class InjectResult:
    """Result of an injection operation."""
    changes: List[InjectChange] = field(default_factory=list)
    output_source: str = ""
    spec_path: str = ""
    impl_path: str = ""

    @property
    def has_changes(self) -> bool:
        return len(self.changes) > 0

    def summary(self) -> str:
        if not self.changes:
            return "No changes needed — all decorators already correct."
        lines = [f"{len(self.changes)} change(s) needed:"]
        for c in self.changes:
            lines.append(f"  [{c.action}] {c.function}")
            if c.detail:
                lines.append(f"           {c.detail}")
        return '\n'.join(lines)


# ──── Veri DSL Spec Parsing ─────────────────────────────────────────────────

@dataclass
class SpecFunction:
    name: str
    params: List[str]
    has_requires: bool
    has_ensures: bool
    module_path: Optional[str] = None  # Set for cross-spec imports (e.g. "SortedListSpec")

    @property
    def conditions_module(self) -> Optional[str]:
        """The conditions module to import from (lowercased last segment)."""
        if self.module_path:
            return self.module_path.split('.')[-1].lower()
        return None


def _parse_module_mappings(veri_text: str) -> Dict[str, str]:
    """Parse python.file directives from the spec.

    Format (in the .veri.md source):
        python.file ModuleName = path/to/impl.py

    Returns:
        {module_name: file_path_string}
    """
    mappings = {}
    for match in re.finditer(
        r'python\.file\s+(\S+)\s*=\s*(\S+(?:\.py)?)',
        veri_text,
    ):
        module_name = match.group(1)
        file_path = match.group(2)
        mappings[module_name] = file_path
    return mappings


def _parse_spec(veri_text: str) -> Tuple[str, List[SpecFunction], Dict[str, str]]:
    """Parse an Veri DSL spec and return (module_name, functions, module_file_mappings).

    Also extracts python.file directives for module-to-file mapping.
    """
    from veri_parser import parse_veri

    # Extract module file mappings from spec text
    module_file_map = _parse_module_mappings(veri_text)

    # Extract ```veri blocks
    blocks = re.findall(r'```veri\n(.*?)```', veri_text, re.DOTALL)
    # Also handle inline veri blocks (outside code fences)
    veri_blocks = re.findall(r'```veri\n(.*?)```', veri_text, re.DOTALL)
    veri_text = '\n\n'.join(blocks) if blocks else veri_text

    if not veri_text.strip():
        raise ValueError("No ```veri blocks found in spec file")

    prog = parse_veri(veri_text)

    module_name = "generated"
    if prog.module and prog.module.name.parts:
        module_name = prog.module.name.parts[-1].lower()

    functions = []
    for decl in prog.decls:
        from veri_ast import ValDecl, ImportedDecl, ExternDecl
        if isinstance(decl, (ValDecl, ImportedDecl, ExternDecl)):
            module_path = getattr(decl, 'module_path', None)
            functions.append(SpecFunction(
                name=decl.name,
                params=[p.name for p in decl.params],
                has_requires=decl.contract.requires is not None,
                has_ensures=decl.contract.ensures is not None,
                module_path=module_path,
            ))

    return module_name, functions, module_file_map


# ──── Real Code Injection ──────────────────────────────────────────────

def _find_function_node(tree: ast.Module, func_name: str) -> Optional[ast.FunctionDef]:
    """Find a FunctionDef node by name in a Python AST."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return node
    return None


def _has_contract_decorator(node: ast.FunctionDef) -> Tuple[bool, Optional[str], Optional[str]]:
    """Check if a function already has @contract decorator with requires/ensures.

    Returns (has_decorator, requires_ref, ensures_ref).
    """
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            func = dec.func
            dec_name = None
            if isinstance(func, ast.Name):
                dec_name = func.id
            elif isinstance(func, ast.Attribute):
                dec_name = func.attr
            if dec_name == 'contract':
                req = None
                ens = None
                for kw in dec.keywords:
                    if kw.arg == 'requires':
                        req = _node_to_str(kw.value)
                    elif kw.arg == 'ensures':
                        ens = _node_to_str(kw.value)
                return True, req, ens
    return False, None, None


def _node_to_str(node: ast.expr) -> str:
    """Convert a small AST expression to a string for comparison."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _node_to_str(node.value) + '.' + node.attr
    if isinstance(node, ast.Constant):
        return repr(node.value)
    return ast.unparse(node)


def _has_import(tree: ast.Module, module_name: str, names: List[str]) -> bool:
    """Check if the AST already has an import for given names from a module."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module == module_name:
                imported = {alias.name for alias in node.names}
                if all(n in imported for n in names):
                    return True
    return False


def _generate_decorator_source(func_name: str, spec_fn: SpecFunction,
                                conditions_module: str) -> str:
    """Generate the @contract decorator source line for a function."""
    req_name = f"{func_name}__requires" if spec_fn.has_requires else None
    ens_name = f"{func_name}__ensures" if spec_fn.has_ensures else None
    parts = []
    if req_name:
        parts.append(f"requires={req_name}")
    if ens_name:
        parts.append(f"ensures={ens_name}")
    args = ", ".join(parts)
    return f"@contract({args})"


def inject_decorators(
    spec_path: Path,
    impl_path: Path,
    conditions_module: Optional[str] = None,
    dry_run: bool = True,
    module_file_map: Optional[Dict[str, str]] = None,
) -> InjectResult:
    """Inject @contract decorators from an Veri DSL spec into real Python code.

    Args:
        spec_path: Path to the .veri.md Veri DSL spec file
        impl_path: Path to the real Python implementation file
        conditions_module: Module name for conditions (defaults to spec module name)
        dry_run: If True, only report changes without modifying (default True)
        module_file_map: Optional {module_name: file_path} mapping for cross-spec imports

    Returns:
        InjectResult with changes list and generated output source.
    """
    result = InjectResult(
        spec_path=str(spec_path),
        impl_path=str(impl_path),
    )

    if not spec_path.exists():
        raise FileNotFoundError(f"Spec not found: {spec_path}")
    if not impl_path.exists():
        raise FileNotFoundError(f"Implementation not found: {impl_path}")

    # Parse Veri DSL spec
    veri_text = spec_path.read_text()
    module_name, spec_fns, spec_mappings = _parse_spec(veri_text)
    if conditions_module is None:
        conditions_module = module_name

    # Merge spec-level mappings with caller-provided mappings
    all_mappings = dict(spec_mappings)
    if module_file_map:
        all_mappings.update(module_file_map)

    # Resolve mapping paths relative to spec directory
    resolved_mappings = {}
    spec_dir = spec_path.parent
    for mod_name, file_path in all_mappings.items():
        resolved_mappings[mod_name] = (spec_dir / file_path).resolve()

    # Parse real implementation
    impl_source = impl_path.read_text()
    try:
        impl_tree = ast.parse(impl_source)
    except SyntaxError as e:
        raise ValueError(f"Syntax error in implementation file: {e}")

    source_lines = impl_source.split('\n')

    # Collect all changes
    needed_imports_by_mod: Dict[str, set] = {}
    needs_contract_import = False
    changes_by_line: Dict[int, str] = {}
    stubs_to_append: List[str] = []

    def _add_needed_import(spec_fn: SpecFunction):
        cond_mod = spec_fn.conditions_module or conditions_module
        if cond_mod not in needed_imports_by_mod:
            needed_imports_by_mod[cond_mod] = set()
        if spec_fn.has_requires:
            needed_imports_by_mod[cond_mod].add(f"{spec_fn.name}__requires")
        if spec_fn.has_ensures:
            needed_imports_by_mod[cond_mod].add(f"{spec_fn.name}__ensures")

    for spec_fn in spec_fns:
        func_node = _find_function_node(impl_tree, spec_fn.name)

        # ── Cross-spec import: function belongs to another module ──
        if spec_fn.module_path is not None:
            _add_needed_import(spec_fn)
            needs_contract_import = True

            if func_node is None:
                # Check if we know where this module's real code lives
                mapped_path = resolved_mappings.get(spec_fn.module_path)
                if mapped_path and mapped_path.exists():
                    result.changes.append(InjectChange(
                        action="import_other_module",
                        function=spec_fn.name,
                        detail=(f"Function from {spec_fn.module_path} — "
                                f"decorator belongs in {mapped_path}"),
                    ))
                    # We don't inject into other files; we just note it
                else:
                    result.changes.append(InjectChange(
                        action="import_other_module",
                        function=spec_fn.name,
                        detail=(f"Function from {spec_fn.module_path} — "
                                f"ensure it has @contract in its implementation. "
                                f"Add python.file {spec_fn.module_path} = <path> to spec "
                                f"to resolve automatically."),
                    ))
            continue

        # ── Local function: belongs to this file ──
        if func_node is None:
            decorator_source = _generate_decorator_source(
                spec_fn.name, spec_fn, conditions_module
            )
            stub_lines = ["", ""]
            stub_lines.append(decorator_source)
            params_str = ', '.join(spec_fn.params)
            stub_lines.append(f"def {spec_fn.name}({params_str}):")
            stub_lines.append(f"    # TODO: implement from {spec_path.name}")
            stub_lines.append(f"    pass")
            stubs_to_append.extend(stub_lines)
            _add_needed_import(spec_fn)
            needs_contract_import = True
            result.changes.append(InjectChange(
                action="add_stub",
                function=spec_fn.name,
                decorator_text=decorator_source,
                detail=f"Function not found — stub added at end of file",
            ))
            continue

        has_dec, req_ref, ens_ref = _has_contract_decorator(func_node)

        expected_req = f"{spec_fn.name}__requires" if spec_fn.has_requires else None
        expected_ens = f"{spec_fn.name}__ensures" if spec_fn.has_ensures else None

        if has_dec:
            issues = []
            if expected_req and req_ref != expected_req:
                issues.append(f"requires={req_ref} should be {expected_req}")
            if not expected_req and req_ref:
                issues.append("has requires= but spec has no REQUIRES")
            if expected_ens and ens_ref != expected_ens:
                issues.append(f"ensures={ens_ref} should be {expected_ens}")
            if not expected_ens and ens_ref:
                issues.append("has ensures= but spec has no ENSURES")
            if issues:
                result.changes.append(InjectChange(
                    action="fix_decorator",
                    function=spec_fn.name,
                    detail="; ".join(issues),
                ))
                decorator_source = _generate_decorator_source(
                    spec_fn.name, spec_fn, conditions_module
                )
                changes_by_line[func_node.lineno - 1] = decorator_source
                _add_needed_import(spec_fn)
                needs_contract_import = True
            else:
                result.changes.append(InjectChange(
                    action="ok", function=spec_fn.name,
                    detail="decorator already correct",
                ))
        else:
            cond_mod = spec_fn.conditions_module or conditions_module
            decorator_source = _generate_decorator_source(
                spec_fn.name, spec_fn, cond_mod
            )
            changes_by_line[func_node.lineno - 1] = decorator_source
            _add_needed_import(spec_fn)
            needs_contract_import = True
            result.changes.append(InjectChange(
                action="add_decorator", function=spec_fn.name,
                decorator_text=decorator_source,
            ))

    # Generate modified source
    if changes_by_line or stubs_to_append or needs_contract_import or needed_imports_by_mod:
        output_lines = []

        new_imports = []
        if needs_contract_import and not _has_import(impl_tree, "backend.python.runtime", ["contract"]):
            new_imports.append("from backend.python.runtime import contract")
        for mod, needs in sorted(needed_imports_by_mod.items()):
            mod_file = f"{mod}_conditions"
            if not _has_import(impl_tree, mod_file, list(needs)):
                sorted_needs = sorted(needs)
                new_imports.append(f"from {mod_file} import {', '.join(sorted_needs)}")

        inserted_imports = False
        for i, line in enumerate(source_lines):
            if not inserted_imports and new_imports:
                stripped = line.strip()
                if (stripped and not stripped.startswith('import')
                        and not stripped.startswith('from')
                        and not stripped.startswith('"""')
                        and not stripped.startswith("'''")
                        and not stripped.startswith('#')):
                    for imp in new_imports:
                        output_lines.append(imp)
                    inserted_imports = True
            if i in changes_by_line:
                output_lines.append(changes_by_line[i])
            output_lines.append(line)

        if not inserted_imports and new_imports:
            last_import_idx = -1
            for i, line in enumerate(source_lines):
                if line.strip().startswith('import') or line.strip().startswith('from'):
                    last_import_idx = i
            insert_pos = last_import_idx + 1 if last_import_idx >= 0 else 0
            output_lines = []
            for i, line in enumerate(source_lines):
                if i == insert_pos:
                    for imp in new_imports:
                        output_lines.append(imp)
                if i in changes_by_line:
                    output_lines.append(changes_by_line[i])
                output_lines.append(line)
            if insert_pos >= len(source_lines):
                for imp in new_imports:
                    output_lines.append(imp)

        if stubs_to_append:
            output_lines.extend(stubs_to_append)

        result.output_source = '\n'.join(output_lines)
    else:
        result.output_source = impl_source

    return result


# ──── CLI Entry Point ──────────────────────────────────────────────────

def _main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Inject Veri DSL @contract decorators into real Python code",
    )
    parser.add_argument("spec", type=str, help="Path to .veri.md Veri DSL spec")
    parser.add_argument("impl", type=str, help="Path to real Python implementation")
    parser.add_argument("--write", "-w", action="store_true",
                        help="Write changes in-place (default: dry-run)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output path (default: overwrite impl with --write)")
    args = parser.parse_args()

    spec_path = Path(args.spec)
    impl_path = Path(args.impl)
    dry_run = not args.write

    try:
        result = inject_decorators(spec_path=spec_path, impl_path=impl_path, dry_run=dry_run)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"Spec: {spec_path}")
    print(f"Impl: {impl_path}")
    print()
    print(result.summary())
    print()

    if result.output_source and (args.output or args.write):
        output_path = Path(args.output) if args.output else impl_path
        output_path.write_text(result.output_source)
        print(f"Wrote: {output_path}")
    elif dry_run and result.changes:
        print("Dry-run (no changes written). Use --write to apply.")
        print()
        print("--- Preview ---")
        print(result.output_source)


if __name__ == '__main__':
    _main()
