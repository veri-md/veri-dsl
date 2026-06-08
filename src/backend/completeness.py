"""
Completeness checker — ensures both backends support the same Veri DSL constructs.

A "gap" is any AST node type or Veri DSL keyword that is handled by one backend
but not the other. This module detects and reports such gaps.

Usage:
    from backend.completeness import check_all_backends, CompletenessChecker

    gaps = check_all_backends()
    if gaps:
        for gap in gaps:
            print(gap)
    else:
        print("All backends are complete ✓")
"""

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Set, Type

from backend.base import (
    Backend, BackendParser, BackendPrinter,
    _ALL_DECLARATION_TYPES, _ALL_TYPE_TYPES, _ALL_EXPR_TYPES, _ALL_PATTERN_TYPES,
    _ALL_KEYWORDS,
)

from backend.fstar import FStarBackend
from backend.dafny import DafnyBackend
from backend.python import PythonBackend


# ── All registered backends ──────────────────────────────────────────────

ALL_BACKENDS: Dict[str, Backend] = {
    'fstar': FStarBackend(),
    'dafny': DafnyBackend(),
    'python': PythonBackend(),
}


@dataclass
class CompletenessGap:
    """A single gap between backend support for an Veri DSL construct."""
    category: str           # 'declaration', 'type', 'expression', 'pattern', 'keyword'
    node_type: str          # AST class name or keyword
    present_in: List[str]   # backend names that support it
    missing_in: List[str]   # backend names that don't
    severity: str = 'warning'  # 'error' | 'warning'

    def __str__(self) -> str:
        if self.severity == 'error':
            tag = '❌ GAP'
        else:
            tag = '⚠️  WARNING'
        have = ', '.join(self.present_in)
        missing = ', '.join(self.missing_in)
        return f"{tag} [{self.category}] {self.node_type}: supported by {have}, missing from {missing}"


@dataclass
class CompletenessReport:
    """Result of a completeness check across backends."""
    backends: List[str] = field(default_factory=list)
    gaps: List[CompletenessGap] = field(default_factory=list)
    declarations_total: int = 0
    declarations_covered: int = 0
    types_total: int = 0
    types_covered: int = 0
    expressions_total: int = 0
    expressions_covered: int = 0
    patterns_total: int = 0
    patterns_covered: int = 0
    keywords_total: int = 0
    keywords_covered: int = 0

    @property
    def is_complete(self) -> bool:
        return len(self.gaps) == 0

    @property
    def error_gaps(self) -> List[CompletenessGap]:
        return [g for g in self.gaps if g.severity == 'error']

    @property
    def warning_gaps(self) -> List[CompletenessGap]:
        return [g for g in self.gaps if g.severity == 'warning']

    def summary(self) -> str:
        lines = []
        lines.append("=" * 60)
        lines.append(f"Completeness Check — {len(self.backends)} backends: {', '.join(self.backends)}")
        lines.append("=" * 60)
        lines.append(f"  Declarations:  {self.declarations_covered}/{self.declarations_total} covered")
        lines.append(f"  Types:         {self.types_covered}/{self.types_total} covered")
        lines.append(f"  Expressions:   {self.expressions_covered}/{self.expressions_total} covered")
        lines.append(f"  Patterns:      {self.patterns_covered}/{self.patterns_total} covered")

        if self.gaps:
            lines.append("")
            lines.append(f"  Gaps found: {len(self.gaps)}")
            for gap in self.gaps:
                lines.append(f"    {gap}")
        else:
            lines.append("")
            lines.append("  ✅ All backends cover the same constructs. No gaps.")
        return '\n'.join(lines)


class CompletenessChecker:
    """Check that all registered backends cover the same Veri DSL constructs."""

    def __init__(self, backends: Dict[str, Backend] = None):
        self.backends = backends or ALL_BACKENDS

    def check_all(self) -> CompletenessReport:
        """Run full completeness check across all categories."""
        backend_names = sorted(self.backends.keys())
        report = CompletenessReport(backends=backend_names)

        # Check declarations
        self._check_category(
            'declaration', _ALL_DECLARATION_TYPES,
            lambda b: b.supported_declarations,
            report,
        )

        # Check types
        self._check_category(
            'type', _ALL_TYPE_TYPES,
            lambda b: b.supported_types,
            report,
        )

        # Check expressions
        self._check_category(
            'expression', _ALL_EXPR_TYPES,
            lambda b: b.supported_expressions,
            report,
        )

        # Check patterns
        self._check_category(
            'pattern', _ALL_PATTERN_TYPES,
            lambda b: b.supported_patterns,
            report,
        )

        return report

    def _check_category(
        self,
        category: str,
        all_types: FrozenSet[Type],
        get_supported,
        report: CompletenessReport,
    ):
        """Check one category (declarations, types, etc.) across all backends."""
        total = len(all_types)
        backend_sets = {
            name: get_supported(backend)
            for name, backend in self.backends.items()
        }

        # Union of all supported
        all_supported: Set[Type] = set()
        for s in backend_sets.values():
            all_supported.update(s)

        covered = len(all_supported)

        # Update report counters
        if category == 'declaration':
            report.declarations_total = total
            report.declarations_covered = covered
        elif category == 'type':
            report.types_total = total
            report.types_covered = covered
        elif category == 'expression':
            report.expressions_total = total
            report.expressions_covered = covered
        elif category == 'pattern':
            report.patterns_total = total
            report.patterns_covered = covered

        # Find gaps: nodes supported by some but not all backends
        for nt in sorted(all_types, key=lambda t: t.__name__):
            present = []
            missing = []
            for name in sorted(self.backends.keys()):
                if nt in backend_sets[name]:
                    present.append(name)
                else:
                    missing.append(name)

            if missing and present:
                # Determine severity: if at least 2 backends support it, it's an error
                severity = 'error' if len(present) >= 2 else 'warning'
                report.gaps.append(CompletenessGap(
                    category=category,
                    node_type=nt.__name__,
                    present_in=present,
                    missing_in=missing,
                    severity=severity,
                ))

    def check_keywords(self) -> List[CompletenessGap]:
        """Check that all Veri DSL keywords are handled by all backend printers.

        This is a coarser check: verifies that backend printer source code
        references each keyword.
        """
        gaps = []
        import inspect

        for backend_name, backend in self.backends.items():
            src = inspect.getsource(backend.printer.__class__)
            for kw in sorted(_ALL_KEYWORDS):
                if kw not in src:
                    # Check other backends
                    present_in = []
                    for bn, b in self.backends.items():
                        if bn == backend_name:
                            continue
                        other_src = inspect.getsource(b.printer.__class__)
                        if kw in other_src:
                            present_in.append(bn)
                    if present_in:
                        gaps.append(CompletenessGap(
                            category='keyword',
                            node_type=kw,
                            present_in=present_in,
                            missing_in=[backend_name],
                            severity='warning',
                        ))
        return gaps


def check_all_backends() -> CompletenessReport:
    """Convenience: check everything and print summary."""
    checker = CompletenessChecker()
    report = checker.check_all()
    keyword_gaps = checker.check_keywords()
    report.gaps.extend(keyword_gaps)
    return report
