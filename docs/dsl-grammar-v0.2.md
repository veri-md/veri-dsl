# Veri DSL Grammar v0.2 — Python + SQL Hybrid

*2026-05-15: match/case updated to Pythonic colon syntax (`case pat:` instead of `case pat ->`); lambda uses Python `lambda x: body` syntax.*

Hybrid syntax: Python-like for structure (`class`, `def`, `import`, `:`, `->`, `#`),
SQL-like uppercase keywords for contract-specific concepts (`REQUIRES`, `ENSURES`, `WHERE`, `CONSTRAINT`, `FORALL`).

---

## 1. Module & Imports

```veri
# Module declaration
module FairinfCore

# Imports (maps to F* `open`)
import FStar.List.Tot
import FStar.Mul
```

## 2. Let Bindings (Constants / Named Terms)

```veri
# Simple constant
buffer_size: nat = 8

# Named function/predicate
max_int_val: int = 2 ** 31 - 1
```

Maps to F*:
```fstar
let buffer_size : nat = 8
let max_int_val : int = 2 ** 31 - 1
```

## 3. Type Declarations

### 3a. Abstract Type

```veri
# No body = abstract
type Key: eqtype
type FairinfToken
```

Maps to F*:
```fstar
type key : eqtype
type fairinf_token
```

### 3b. Type Alias

```veri
type SortedList = list Element
```

Maps to F*:
```fstar
type sorted_list = list element
```

### 3c. Refined Type

```veri
type ValidBuffer = CircularBuffer WHERE is_valid_buffer(buf)
```

Maps to F*:
```fstar
type valid_circular_buffer = buf:circular_buffer{is_valid_buffer buf}
```

### 3d. Record / Struct (Python `class`)

```veri
# C struct → F* record → DSL class
class FairinfCReq:
    rid:               string(128)     # request ID
    arrival_ts:        float64         # arrival timestamp
    prompt_len:        int32           # prompt token count
    real_decode_count: int32           # completed decode steps
    prefill_done:      bool            # prefill done?
    is_complete:       bool            # request complete?
    ant_type:          int32           # -1=none, 0=prefill, 1=decode
    ant_end_ts:        float64         # predicted end time
    ant_completion:    int32           # decode step number
```

Maps to F*:
```fstar
type fairinf_c_req = {
  rid:               Prims.string;
  arrival_ts:        Prims.float;
  prompt_len:        Prims.int;
  real_decode_count: Prims.int;
  prefill_done:      Prims.bool;
  is_complete:       Prims.bool;
  ant_type:          Prims.int;
  ant_end_ts:        Prims.float;
  ant_completion:    Prims.int;
}
```

### 3e. Enum (Unit Variants)

```veri
# C enum → F* inductive → DSL enum
enum AntType:
    NONE    = -1       # no event
    PREFILL = 0        # prefill event
    DECODE  = 1        # decode event
```

Maps to F*:
```fstar
type ant_type_t =
  | None_t : ant_type_t
  | Prefill : ant_type_t
  | Decode : ant_type_t
```

### 3f. Tagged Union (Constructors with Payload)

```veri
# Tagged union / variant
variant Outcome:
    | Success(result: int64, msg: string)
    | Failure(error: string)
    | Timeout(duration: float64)
```

Maps to F*:
```fstar
type outcome =
  | Success : result:int64 -> msg:Prims.string -> outcome
  | Failure : error:Prims.string -> outcome
  | Timeout : duration:Prims.float -> outcome
```

---

## 4. Predicates (Let-bound invariants)

Python `def` with `return` body = F* `let`:

```veri
def is_valid_buffer(buf: CircularBuffer) -> bool:
    return (buf.head < buffer_size
            and buf.tail < buffer_size
            and buf.count <= buffer_size
            and len(buf.data) == buffer_size)
```

Maps to F*:
```fstar
let is_valid_buffer (buf: circular_buffer) : bool =
  buf.head < buffer_size &&
  buf.tail < buffer_size &&
  buf.count <= buffer_size &&
  List.Tot.length buf.data = buffer_size
```

---

## 5. Function Signatures (The core contract construct)

Python `def` with `REQUIRES` / `ENSURES` / `DECREASES` = F* `val`:

```veri
def push(buf: ValidBuffer, value: int32) -> ValidBuffer:
    REQUIRES True
    ENSURES (is_valid_buffer(result)
             and result.count == (buf.count + 1 if buf.count < buffer_size
                                   else buffer_size))
```

Maps to F*:
```fstar
val push: buf:valid_circular_buffer -> value:int
  -> Pure valid_circular_buffer
    (requires True)
    (ensures (fun result ->
      is_valid_buffer result /\
      result.count = (if buf.count < buffer_size
                      then buf.count + 1
                      else buffer_size)))
```

### With state/mutation effects:

```veri
def fairinf_run_rebuild_kernel(
    reqs:         STATE_READ_WRITE FairinfCReq[],
    n:            STATE_READ_ONLY     int32,
    max_kv_tokens: STATE_READ_ONLY    int32,
    fairinf_n:    STATE_READ_ONLY     int32,
    until_ts:     STATE_READ_ONLY     float64,
) -> None:
    REQUIRES n > 0 and array_len(reqs) >= n
    ENSURES (FORALL i IN range(0, n):
                 reqs[i].ant_type != -1
             and FORALL i IN range(0, n):
                 (reqs[i].is_complete == 1 ==> reqs[i].ant_type == -1))
    DECREASES n
```

Maps to F* (ST effect for mutation):
```fstar
val fairinf_run_rebuild_kernel:
  reqs:        Buffer.buffer fairinf_c_req ->
  n:           int ->
  max_kv_tokens: int ->
  fairinf_n:   int ->
  until_ts:    float ->
  ST unit
    (requires (fun h -> n > 0 /\ length reqs >= n))
    (ensures (fun h0 r h1 ->
      (forall (i: nat{(i < n)}).
        live h1 reqs /\
        as_seq h1 reqs).[i].ant_type <> -1) /\
      ...))
```

### Pure function with pre/post:

```veri
def add(a: Int32, b: Int32) -> Int32:
    REQUIRES fits(a + b, 32)
    ENSURES result == a + b
```

### Lemma:

```veri
def uv_inv(x: Int8):
    ENSURES int_to_t(v(x)) == x
    SMTPat(v(x))
```

Maps to F*:
```fstar
val uv_inv (x : Int8.t) : Lemma
  (ensures (Int8.int_to_t (Int8.v x) == x))
  [SMTPat (Int8.v x)]
```

---

## 6. Constraint Blocks (Table-level invariants)

```veri
# Documented invariants from _fairinf_core.h
CONSTRAINT FairinfReqInvariants:
    # Every request gets some prediction
    FORALL req IN reqs:
        req.ant_type != -1

    # Completed requests get no event
    FORALL req IN reqs:
        req.is_complete == 1 ==> req.ant_type == -1

    # Anticipation never goes backward
    FORALL req IN reqs:
        req.ant_type >= 0 ==> req.ant_end_ts > req.arrival_ts

    # Memory limit
    active_kv_memory <= max_kv_tokens
```

---

## 7. Lambda Expressions

Python `lambda` syntax for anonymous functions:

```veri
def apply(f: lambda int: bool, x: int) -> bool:
    ENSURES lambda result: f(x) == result
```

Maps to F*:
```fstar
let apply (f: int -> bool) (x: int) : bool = f x
```

In ENSURES/REQUIRES clauses the `result` variable is implicit, so the lambda wrapper is typically not needed:

```veri
ENSURES is_valid(result)       # result is implicit
ENSURES lambda r: is_valid(r)  # explicit, also valid
```

## 8. Match / Case (Pythonic)

Python-style `match`/`case` with colon after pattern:

```veri
def is_sorted(lst: list[int]) -> bool:
    return match lst:
        case []:
            True
        case [_]:
            True
        case [hd1, hd2, *tl]:
            hd1.serial <= hd2.serial and is_sorted([hd2] + tl)
```

Maps to F*:
```fstar
match lst with
| [] -> true
| [_] -> true
| hd1 :: hd2 :: tl -> hd1.serial <= hd2.serial && is_sorted (hd2 :: tl)
```

For single-line case bodies:

```veri
match result:
    case None:
        buf.count == 0
    case Some(v):
        buf.count > 0
```

## 9. Expression / Operator Mapping

| Python/DSL | F* Translation | Notes |
|---|---|---|
| `x and y` | `x /\ y` | |
| `x or y` | `x \/ y` | |
| `not x` | `~ x` | |
| `x == y` | `x = y` | propositional equality |
| `x != y` | `~(x = y)` | inequality |
| `x ==> y` | `x ==> y` | same keyword, kept as-is |
| `x < y` | `x < y` | preserved |
| `A if cond else B` | `A if cond else B` | same |
| `cond ? A : B` | not supported | use if/else |
| `FORALL x IN set: p` | `(forall (x: ...). p)` | |
| `EXISTS x IN set: p` | `(exists (x: ...). p)` | |
| `match x: ...` | `match x with ...` | Python-style match/case — see §4d |
| `len(x)` | `List.Tot.length x` | sugared |
| `array_len(x)` | `length x` | for buffers |
| `x[i]` | `Seq.index x i` | indexing |
| `x.f` | `x.f` | field access |
| `True` | `True` | |
| `False` | `False` | |
| `None` | `unit` | void return |
| `# comment` | `// comment` | line comment |

---

## 10. Direction Annotations → F* Effects

| DSL Parameter | Meaning | F* Effect |
|---|---|---|
| `(none)` | Read-only, no mutation | `Tot` / `Pure` |
| `STATE_READ_ONLY` | Input (read-only) parameter | `Tot` / `Pure` |
| `STATE_WRITE_ONLY` | Output (write-only) parameter | `ST` / `HST` |
| `STATE_READ_WRITE` | Input/output (mutable) parameter | `ST` / `HST` |
| `PURE` | Explicit pure contract | `Pure` |
| `GHOST` | Ghost/proof-only | `GTot` |
| `LEMMA` | Lemma | `Lemma` |

Functions with **all `STATE_READ_ONLY` or unannotated** parameters → `Pure`.
Functions with **any `STATE_WRITE_ONLY` or `STATE_READ_WRITE`** → `ST`.

---

## 11. File Structure (Grammar)

```
.veri  ≡
    module_stmt
    import_stmt*
    declaration*

module_stmt  ::= "module" IDENTIFIER
import_stmt  ::= "import" QIDENTIFIER

declaration ::=
    type_decl
    | class_decl
    | enum_decl
    | variant_decl
    | predicate_def        # def with body (return)
    | function_sig         # def with REQUIRES/ENSURES (no body)
    | let_binding          # ident: type = expr
    | constraint_block
    | pragma

class_decl ::= "class" IDENTIFIER ":" NEWLINE INDENT
    field_decl+
    DEDENT

field_decl ::= IDENTIFIER ":" type

enum_decl ::= "enum" IDENTIFIER ":" NEWLINE INDENT
    enum_member+
    DEDENT

enum_member ::= IDENTIFIER ["=" int_literal]

variant_decl ::= "variant" IDENTIFIER ":" NEWLINE INDENT
    "|" IDENTIFIER "(" field_decl ("," field_decl)* ")" NEWLINE
    DEDENT

predicate_def ::= "def" IDENTIFIER "(" params ")" "->" type ":" NEWLINE INDENT
    "return" expr NEWLINE
    DEDENT

function_sig ::= "def" IDENTIFIER "(" params ")" "->" type ":" NEWLINE INDENT
    [ "REQUIRES" expr NEWLINE ]
    [ "ENSURES" expr NEWLINE ]
    [ "DECREASES" expr NEWLINE ]
    DEDENT

let_binding ::= IDENTIFIER ":" type "=" expr

constraint_block ::= "CONSTRAINT" IDENTIFIER ":" NEWLINE INDENT
    constraint_clause+
    DEDENT

constraint_clause ::= [ "FORALL" ... ":" ] expr
```

---

## 12. Full Example: `_fairinf_core.h` → Veri DSL → F*

### C Header (source)

```c
typedef struct { ... } FairinfCReq;

void fairinf_run_rebuild_kernel(
    FairinfCReq *reqs, int n,
    int max_kv_tokens, int fairinf_n,
    double until_ts
);
```

### Veri DSL DSL

```veri
module FairinfCore

class FairinfCReq:
    rid:               string(128)
    arrival_ts:        float64
    prompt_len:        int32
    real_decode_count: int32
    prefill_done:      bool
    is_complete:       bool
    ant_type:          int32
    ant_end_ts:        float64
    ant_completion:    int32

CONSTRAINT FairinfReqInvariants:
    FORALL req IN reqs:
        req.ant_type != -1
    FORALL req IN reqs:
        req.is_complete == 1 ==> req.ant_type == -1
    FORALL req IN reqs:
        req.ant_type >= 0 ==> req.ant_end_ts > req.arrival_ts

def fairinf_run_rebuild_kernel(
    reqs:         IN OUT FairinfCReq[],
    n:            IN     int32,
    max_kv_tokens: IN    int32,
    fairinf_n:    IN     int32,
    until_ts:     IN     float64,
) -> None:
    REQUIRES n > 0 and array_len(reqs) >= n
    ENSURES FORALL i IN range(0, n):
                reqs[i].ant_type != -1
            and FORALL i IN range(0, n):
                (reqs[i].is_complete == 1 ==> reqs[i].ant_type == -1)
```

### Generated F* `.fsti`

```fstar
module FairinfCore

type fairinf_c_req = {
  rid:               Prims.string;
  arrival_ts:        Prims.float;
  prompt_len:        Prims.int;
  real_decode_count: Prims.int;
  prefill_done:      Prims.bool;
  is_complete:       Prims.bool;
  ant_type:          Prims.int;
  ant_end_ts:        Prims.float;
  ant_completion:    Prims.int;
}

val fairinf_run_rebuild_kernel:
  reqs:         Buffer.buffer fairinf_c_req ->
  n:            int ->
  max_kv_tokens: int ->
  fairinf_n:    int ->
  until_ts:     float ->
  ST unit
    (requires (fun h -> n > 0 /\ Buffer.length reqs >= n))
    (ensures (fun h0 _ h1 ->
      (forall (i: nat). i < n ==>
        Seq.index (Buffer.as_seq h1 reqs) i).ant_type <> -1) /\
      (forall (i: nat). i < n ==>
        ... )))
```

---

## Appendix A: F* Naming Conventions

FCL uses F* names for operators and functions — no renaming:

| FCL construct | F* equivalent | Notes |
|---------------|---------------|-------|
| `@` | `@` | List append (NOT `+`) |
| `rev` | `rev` (from `FStar.List.Tot`) | List reverse (NOT `reverse`) |
| `len(x)` | `List.Tot.length x` | List length |
| `x in lst` | `List.mem x lst` | List membership |
| `nth(x, i)` | `List.nth x i` | List index |
| `int`, `nat`, `bool` | `Prims.int`, etc. | Same as F* (auto-opened) |
| `op_Multiply` | `op_Multiply` | Int multiplication (F* 2026) |
| `import M` | `open M` | Module import |
| `FORALL x IN s: p` | `(forall x. List.mem x s ==> p)` | Quantification |
| `EXISTS x IN s: p` | `(exists x. List.mem x s /\ p)` | Quantification |

**Rule:** FCL does not rename F* function/operator names. If F* calls it `rev`,
FCL calls it `rev`. If F* calls it `@`, FCL calls it `@`. This keeps the
FCL ↔ F* mapping lossless and predictable for both humans and models.
