# Veri DSL — Multi-Backend Contract Specification Language

A Pythonic DSL for writing formal contract specifications (pre/post conditions,
refined types, invariants) that compiles to one of three verification backends:

```
Veri DSL (.veri / .veri.md) ──► ┌─ F*    (.fsti / .fst)  ──► C    (via Low*/KaRaMeL)
                                ├─ Dafny (.dfy)           ──► Rust (via Dafny)
                                └─ Python (.py)           ──► Runtime @contract enforcement
```

## What is Veri DSL?

Veri DSL is a Pythonic language for writing formal specifications. It looks and
feels like Python (indentation, `class`, `def`, `match`/`case`, `lambda`) but
compiles to F*, Dafny, or runtime Python contracts for verification.

You write the spec once; the pipeline targets the backend of your choice.

```veri
TARGET f-star-c

class TokenBucket:
    capacity: int
    tokens: int

type ValidBucket = TokenBucket WHERE tokens <= capacity

def consume(bucket: STATE_READ_WRITE ValidBucket, count: int) -> bool:
    REQUIRES count > 0
    ENSURES match result:
        case True:
            bucket.tokens >= 0
        case False:
            bucket.tokens >= 0
```

## File format

A `.veri.md` file is a **markdown document**, not a bare DSL file. Write your
specification in natural language prose, and place Veri DSL inside ` ```veri `
fenced code blocks. The first Veri DSL block must declare the target:

````markdown
# Sorted List Specification

Target: F* → C via Low*/KaRaMeL

```veri
TARGET f-star-c
```

## Element type

Each element has a numeric serial and a string data field.

```veri
class Element:
    serial: nat
    data: string
```

## Sorting predicate

A list is sorted if for every adjacent pair, the left element's serial is ≤ the right's.

```veri
def is_sorted(lst: list[Element]) -> bool:
    return match lst:
        case []: True
        case [_]: True
        case [hd1, hd2, *tl]: hd1.serial <= hd2.serial and is_sorted([hd2] + tl)
```
````

## Target declaration

Every `.veri.md` must start with a `TARGET` declaration in the first ` ```veri `
block. This tells the pipeline which backend to use:

| Target | Backend | Output |
|--------|---------|--------|
| `TARGET f-star-c` | F* → Low* → KaRaMeL | Verified C |
| `TARGET dafny-rust` | Dafny | Verified Rust |
| `TARGET python-assert` | Python @contract | Runtime assertion enforcement |

```veri
TARGET f-star-c       # F* → C via Low* / KaRaMeL
TARGET dafny-rust     # Dafny → Rust
TARGET python-assert  # Python runtime @contract enforcement
```

## Backends

| Backend | Parser | Printer | Verifier | Output |
|---------|--------|---------|----------|--------|
| `fstar` | `backend/fstar/parser.py` | `backend/fstar/printer.py` | `fstar.exe` | `.fsti` / `.fst` → C |
| `dafny` | `backend/dafny/parser.py` | `backend/dafny/printer.py` | `dafny` | `.dfy` → Rust |
| `python` | — (uses Veri DSL AST) | `backend/python/conditions.py` | runtime assertions | `_conditions.py` + `@contract` |

Each backend has a parser (backend → Veri DSL AST) and a printer (Veri DSL AST
→ backend), enabling bidirectional conversion:

```
Veri DSL  ──► backend/fstar/printer ──►  .fsti
Veri DSL  ──► backend/dafny/printer ──►  .dfy
Veri DSL  ──► backend/python/printer ──►  _conditions.py

.fsti     ──► backend/fstar/parser  ──►  Veri DSL
.dfy      ──► backend/dafny/parser  ──►  Veri DSL
```

## Syntax at a Glance

| Feature | Veri DSL Syntax |
|---|---|
| Records | `class Name: field: type` |
| Refined types | `type T = Base WHERE predicate` |
| Functions with contracts | `def f(x: T) -> R: REQUIRES ... ENSURES ...` |
| Pythonic match | `match x: case pat: expr` |
| Pythonic lambda | `lambda x: body` |
| Pythonic ternary | `A if cond else B` |
| Quantifiers | `FORALL x IN set: p` / `EXISTS x IN set: p` |
| Direction annotations | `STATE_READ_ONLY`, `STATE_WRITE_ONLY`, `STATE_READ_WRITE` |
| Void return | `-> None:` |
| Invariant blocks | `CONSTRAINT Name: ...` |
| List patterns | `case []:`, `case [_]:`, `case [a, b, *rest]:` |
| Comments | `# line comment` |

## Project Layout

```
dsl/
├── src/
│   ├── veri_ast.py              # Shared AST (Veri DSL + all backends)
│   ├── veri_parser.py           # Veri DSL text → AST
│   ├── veri_printer.py          # AST → Veri DSL text
│   ├── backend/
│   │   ├── base.py              # Abstract backend interface
│   │   ├── completeness.py      # Completeness checker (all targets covered)
│   │   ├── fstar/
│   │   │   ├── parser.py        # F* .fsti → Veri DSL AST
│   │   │   └── printer.py       # Veri DSL AST → F* .fsti
│   │   ├── dafny/
│   │   │   ├── parser.py        # Dafny .dfy → Veri DSL AST
│   │   │   └── printer.py       # Veri DSL AST → Dafny .dfy
│   │   └── python/
│   │       ├── conditions.py    # Veri DSL AST → _conditions.py
│   │       ├── inject.py        # @contract decorator injection
│   │       ├── printer.py       # Veri DSL AST → Python conditions
│   │       ├── runtime.py       # Runtime @contract decorator
│   │       └── verify.py        # Decorator verification
├── tests/                       # Test .veri files
├── examples/                    # Example .veri.md files
└── docs/                        # Grammar, correspondence, reference
```

## Quick Start

```bash
cd dsl
PYTHONPATH=src python3 -c "
from veri_parser import parse_veri
from veri_printer import VeriDslPrinter

text = 'TARGET f-star-c\n\ndef f(x: int) -> int:\n    REQUIRES x > 0\n    ENSURES x + 1 if x > 0 else x\n'

prog = parse_veri(text)
print(VeriDslPrinter().print(prog))
"
```

Convert to F*:
```bash
cd dsl
PYTHONPATH=src python3 -c "
from veri_parser import parse_veri
from backend.fstar.printer import FStarPrinter

prog = parse_veri(text)
print(FStarPrinter().print(prog))
"
```

## Examples

| Example | Backends | Features |
|---------|----------|----------|
| `examples/sorted_list.veri.md` | f-star-c, dafny-rust, python-assert | Records, refined types, predicates, list match patterns |
| `examples/circular_buffer.veri.md` | f-star-c | Constants, invariants, `option` return types, match/case |
| `examples/lru_cache.veri.md` | f-star-c | Quantifiers (`FORALL`/`EXISTS`), `nth_opt`, nested match |
| `examples/fairinf_core.veri.md` | f-star-c | `STATE_*` direction annotations, `CONSTRAINT` blocks, array contracts |

## Uppercase Keywords

Contract-specific keywords use SQL-style UPPERCASE to visually separate *what the code must satisfy* from *how the code computes*:

| Keyword | Purpose |
|---|---|
| `REQUIRES` / `ENSURES` | Pre/post conditions |
| `DECREASES` | Termination metric |
| `WHERE` | Type refinement |
| `FORALL` / `EXISTS` | Quantifiers |
| `CONSTRAINT` | Invariant blocks |
| `STATE_READ_ONLY` / `STATE_WRITE_ONLY` / `STATE_READ_WRITE` | Memory effect annotations |

## Why Veri DSL instead of writing F*/Dafny directly?

- **Single spec, multiple targets.** Write one spec, compile to C (F*), Rust (Dafny), or runtime Python assertions.
- **Ergonomics.** Pythonic syntax for `match`, `lambda`, `if`/`else`, type annotations.
- **Familiar semantics.** `class` for records, `def` for functions, indentation-based blocks.
- **Bidirectional.** Convert existing F* or Dafny contracts into Veri DSL, edit, convert back.
- **No verification language knowledge required.** Write contracts in Pythonic syntax; the toolchain handles backend code generation.

## More info

- **Full pipeline**: [`veri-build`](https://github.com/devbali/veri-build) — lint, fill, verify, and compile `.veri.md` specs to output
- **Python backend docs**: `src/backend/python/README.md`
- **Pipeline API**: [`veri-build/docs/API.md`](https://github.com/devbali/veri-build/blob/main/docs/API.md)

## Versioning

The Veri DSL language version is declared in [`VERSION`](src/VERSION)
(currently **0.0.1**). Specs may optionally declare their version:

```veri
VERI_VERSION 0.0.1
```

The lint step checks that the spec's `VERI_VERSION` matches the DSL
version. Every commit that changes the Veri DSL language should update
`VERSION` and create a corresponding git tag:

```bash
git tag v$(cat VERSION)
git push --tags
```
