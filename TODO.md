# Veri DSL DSL — Remaining Work

## Pipeline Complete ✅

```
F* (.fsti) → Veri DSL (.veri) : 47/49 files parse
Veri DSL (.veri) → F* (.fsti) : All DSL examples generate verifiable F*
F* verification       : SortedList ✅, CircularBuffer ✅, FairinfCore ✅
```

## Low-Priority Polish

### Veri DSL Parser

| Issue | Impact |
|---|---|
| `CONSTRAINT` blocks | Fairinf core invariants — parsed as skip |
| `string(128)` size annotations | Width annotations skipped |
| `FORALL` with `IN` clause | Not parsed in constraint blocks |

### F\* Parser

| Issue | Impact |
|---|---|
| `#a: Type` + `let (x,y) = ...` | 2 implementation-heavy files (out of 49) |
| Backtick operators (`a `contains` b`) | Only in heap example ensures clauses |

### F\* Printer

| Issue | Impact |
|---|---|
| Float literal `0.0` | F* 2026.04 doesn't accept — uses `0` |
| `>=` for floats | Mapped to int `>=` since F* lacks native float |
| `[]` list literal patterns | PatApp('Nil') → `[]` (handled) |
