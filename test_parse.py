#!/usr/bin/env python3
"""Test parser against veri.md files."""
import sys
sys.path.insert(0, 'src')
import re
from fsti_parser import parse_fstar
from veri_printer import VeriDslPrinter
import traceback

def extract_blocks(filepath):
    with open(filepath) as f:
        text = f.read()
    blocks = re.findall(r'```veri\n(.*?)```', text, re.DOTALL)
    return blocks

def parse_blocks(filepath):
    blocks = extract_blocks(filepath)
    for i, block in enumerate(blocks):
        print(f'=== Block {i} ({len(block)} chars) ===')
        try:
            prog = parse_fstar(block.strip())
            printer = VeriDslPrinter()
            output = printer.print(prog)
            print(output)
        except Exception as e:
            print(f'ERROR: {e}')
            traceback.print_exc()
            print()

if __name__ == '__main__':
    filepath = sys.argv[1]
    parse_blocks(filepath)
