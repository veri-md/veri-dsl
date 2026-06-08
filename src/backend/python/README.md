# Python Asserts Backend

## What It Is

The Python asserts backend translates Veri DSL contracts (`REQUIRES`/`ENSURES` + refined type constraints) into runtime `@contract` decorators that enforce those contracts on **real Python implementation code**.

**Flow:**
1. Write an Veri DSL spec (`.veri.md`) with contracts
2. Run `compile_veri` → generates `_conditions.py` (pre/post predicates)
3. Run `backend.python.inject` → adds `@contract(...)` decorators to your real code
4. Production: decorators are zero-overhead pass-through (`CONTRACT_ASSERT_ENABLED=0`)
5. CI/Fuzz: enable assertions (`CONTRACT_ASSERT_ENABLED=1`) — contracts are checked at runtime

## What We Control vs. What We Don't

### ✅ We Control (the only changes to your real code)

1. **The `@contract` decorator** — placed on functions that have contracts in the Veri DSL spec
   ```python
   @contract(requires=fn__requires, ensures=fn__ensures)
   def fn(...):
       ...  # your implementation, untouched
   ```

2. **Two import lines** at the top of the file:
   ```python
   from backend.python.runtime import contract
   from my_spec_conditions import fn__requires, fn__ensures
   ```

3. **Stub functions** (optional) — if the Veri DSL spec describes a function not found in real code, we may add:
   ```python
   def missing_fn(...):
       # TODO: implement from spec.veri.md
       pass
   ```

### ❌ We Never Touch

- **Function bodies** — your implementation logic is never modified
- **Class definitions** — types, fields, methods are left as-is
- **Imports** beyond the two contract imports above
- **Variable names, comments, whitespace, formatting**
- **Existing decorators** — only `@contract` is added; all other decorators are preserved

The injector (`backend.python.inject`) is surgically precise: it only adds lines, never removes or edits existing lines. Every change is a net insertion.

## What the Decorator Checks

### Explicit contracts (from Veri DSL `REQUIRES`/`ENSURES`)

Generated as `fn__requires(args) -> bool` and `fn__ensures(result, args) -> bool`.

### Implicit type assertions (from Veri DSL refined types)

If a parameter or return value uses a **refined type** like:
```veri
type ValidSortedList = SortedList WHERE is_sorted(lst)

def add_element(existing: ValidSortedList, ...) -> ValidSortedList:
```

The generated conditions also check the type invariant:
```python
def add_element__requires(existing, new_elem):
    return is_sorted(existing)  # ← implicit: ValidSortedList invariant

def add_element__ensures(result, existing, new_elem):
    return (is_sorted(result)    # ← implicit: return type ValidSortedList
            and len(result) == len(existing) + 1)  # ← explicit ENSURES
```

This ensures the same level of type-safety that F* and Dafny provide statically — enforced at runtime for the Python target.

## Runtime Behavior

| Mode | Env Var | Behavior |
|---|---|---|
| **Production** (default) | `CONTRACT_ASSERT_ENABLED=0` | Zero-overhead pass-through. `@contract` calls the function directly, no checks. |
| **Assert** (CI/fuzz) | `CONTRACT_ASSERT_ENABLED=1` | Evaluates `requires` before call, `ensures` after. Raises `PreconditionError` / `PostconditionError` on violation. |
| **Dry-run** (CI verify) | `CONTRACT_DRY_RUN=1` | Evaluates conditions only, raises `ContractDryRun` instead of calling the function. Used by the verify CLI. |

Programmatic toggle (for pytest fixtures, etc.):
```python
from backend.python.runtime import ContractSettings
ContractSettings.enable()   # turn on assertions
ContractSettings.disable()  # turn off (pass-through)
```

## CLI Commands

```bash
# 1. Generate conditions from Veri DSL spec
python -m backend.python.conditions spec.veri.md > spec_conditions.py

# 2. Check decorators match spec
python -m backend.python.verify spec.veri.md real_impl.py

# 3. Inject decorators into real code
python -m backend.python.inject spec.veri.md real_impl.py           # dry-run
python -m backend.python.inject spec.veri.md real_impl.py --write   # apply
python -m backend.python.inject spec.veri.md real_impl.py -o decorated.py

# 4. Run with assertions
CONTRACT_ASSERT_ENABLED=1 CONTRACT_DRY_RUN=1 python real_impl.py
```

## Testing

```bash
cd ~/project/verification/veri-build
PYTHONPATH=src:src/veri_build/dsl/src:tests python3 tests/test_python.py
```

Tests cover:
- Conditions generation from Veri DSL specs
- AST structural comparison (conditions ↔ Veri DSL spec)
- Decorator verification on real source code
- Dry-run, assert, and pass-through runtime modes
- Decorator injection (dry-run, write, skip-existing)
- End-to-end: inject → verify → match
