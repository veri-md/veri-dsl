#!/usr/bin/env python3
"""
convert.py — Convert .veri.md files to Veri DSL format.

Usage:
    python3 convert.py path/to/file.veri.md
    python3 convert.py path/to/file.fsti

Output is written to stdout by default.
Use --output or -o to write to file.
"""

import argparse
import re
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from veri_ast import *
from fsti_parser import parse_fstar
from veri_printer import VeriDslPrinter


def extract_veri_blocks(md_path: str) -> list[str]:
    """Extract veri code blocks from a .veri.md file."""
    content = Path(md_path).read_text()
    blocks = re.findall(r'```veri\n(.*?)```', content, re.DOTALL)
    return [b.strip() for b in blocks if b.strip()]


def convert_veri_md(md_path: str) -> str:
    """Convert a .veri.md file to Veri DSL format."""
    blocks = extract_veri_blocks(md_path)
    if not blocks:
        return "# No veri blocks found.\n"

    results = []
    for i, block in enumerate(blocks):
        try:
            program = parse_fstar(block)
            printer = VeriDslPrinter()
            veri_text = printer.print(program)
            if i > 0:
                results.append('')  # separator
            results.append(veri_text.strip())
        except Exception as e:
            results.append(f"# Error parsing block {i+1}: {e}")
            results.append(f"# Block {i+1}:\n# {block[:80]}...\n")

    return '\n'.join(results)


def convert_fsti(fsti_path: str) -> str:
    """Convert a .fsti file to Veri DSL format."""
    content = Path(fsti_path).read_text()
    try:
        program = parse_fstar(content)
        printer = VeriDslPrinter()
        return printer.print(program)
    except Exception as e:
        return f"# Error parsing {fsti_path}: {e}\n"


def main():
    parser = argparse.ArgumentParser(
        description='Convert .veri.md or .fsti files to Veri DSL format.'
    )
    parser.add_argument('input', help='Input .veri.md or .fsti file')
    parser.add_argument('-o', '--output', help='Output file (default: stdout)')
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)

    if path.suffix == '.fsti':
        result = convert_fsti(str(path))
    else:
        result = convert_veri_md(str(path))

    if args.output:
        Path(args.output).write_text(result)
        print(f"Written to {args.output}")
    else:
        print(result)


if __name__ == '__main__':
    main()
