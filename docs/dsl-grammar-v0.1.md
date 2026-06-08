# DSL Design v0.1 — "F*Veri DSL" (Veri DSL)

Bidirectional mapping: `.fsti` ↔ `.veri` (our DSL).

## Design Principles

1. **SQL-like declarative syntax** — clear schema, constraints, function contracts
2. **Bidirectional** — lossless round-trip between F* `.fsti` and `.veri`
3. **C-programmer friendly** — reads naturally alongside `_fairinf_core.h`
4. **Subset-first** — we only need what `.fsti` files use for C header contracts

## Mapped Grammar

### Module Declaration

```
.fsti:  module FairinfCore
.veri:   MODULE FairinfCore
```

### Opens / Imports

```
.fsti:  open FStar.List.Tot
.veri:   IMPORT FStar.List.Tot
```

### 1. Schema (Types)

#### 1a. Abstract Types

```
.fsti:  type key : eqtype
.veri:   TYPE key : eqtype;
```

#### 1b. Type Aliases

```
.fsti:  type sorted_list = list element
.veri:   TYPE sorted_list = list element;

.fsti:  type valid_circular_buffer = buf:circular_buffer{is_valid_buffer buf}
.veri:   TYPE valid_circular_buffer = circular_buffer WHERE is_valid_buffer(buf);
```

Refinement syntax: `TYPE name = base_type WHERE predicate`

#### 1c. Record Types (C struct → F* record)

_C header:_
```c
typedef struct {
    int    ant_type;
    double ant_end_ts;
    int    ant_completion;
} FairinfCReq;
```

_F* .fsti:_
```fstar
type fairinf_c_req = {
  ant_type:    int;
  ant_end_ts:  float;
  ant_completion: int;
}
```

_Veri DSL:_
```veri
TABLE FairinfCReq {
  ant_type:        int32,     -- -1=none, 0=prefill, 1=decode
  ant_end_ts:      float64,   -- predicted end timestamp
  ant_completion:  int32      -- decode step number
};
```

**Record field rules:**
- Fields separated by commas or semicolons
- Inline comments via `--`
- F* record type maps to `TABLE name { ... }`
- C type mapping: `int` → `int32`, `double` → `float64`, `char` → `int8`, etc.

#### 1d. Inductive Types (Enums / Tagged Unions)

```fstar
type ant_type_t =
  | None_t   : ant_type_t
  | Prefill  : ant_type_t
  | Decode   : ant_type_t
```

_Veri:_
```veri
ENUM AntType {
  NONE    = -1,   -- no event
  PREFILL = 0,    -- prefill event
  DECODE  = 1     -- decode event
};
```

With payload:
```veri
VARIANT Outcome {
  | Success(result: int32),
  | Failure(error: string),
  | Timeout(duration: float64)
};
```

### 2. Constraints (Invariants / Predicates)

F* let-predicates and refinement constraints.

```
.fsti:  let is_valid_buffer (buf: circular_buffer) : bool = ...
.veri:   PREDICATE is_valid_buffer (buf: circular_buffer) -> bool =
          buf.head < buffer_size
          AND buf.tail < buffer_size
          AND buf.count <= buffer_size;

.fsti:  type valid_circular_buffer = buf:circular_buffer{is_valid_buffer buf}
.veri:   TYPE valid_circular_buffer = circular_buffer WHERE is_valid_buffer(buf);
```

**Table-level invariants** (from C header documented invariants):

```veri
CONSTRAINT FairinfCReq {
  -- Every request gets some prediction
  FORALL req IN reqs:
    req.ant_type != -1,
  -- Completed requests get no event
  FORALL req IN reqs:
    req.is_complete = 1  ==>  req.ant_type = -1,
  -- Anticipation never goes backward
  FORALL req IN reqs:
    req.ant_type >= 0 ==> req.ant_end_ts > req.arrival_ts
};
```

### 3. Function Signatures (Procedures)

The core translation target:

_C header:_
```c
void fairinf_run_rebuild_kernel(
    FairinfCReq *reqs,
    int          n,
    int          max_kv_tokens,
    int          fairinf_n,
    double       until_ts
);
```

_F* .fsti:_
```fstar
val fairinf_run_rebuild_kernel:
  reqs:        fairinf_c_req ->
  n:           int ->
  max_kv_tokens: int ->
  fairinf_n:   int ->
  until_ts:    float ->
  ST unit
    (requires (fun h -> n > 0 /\ ...))
    (ensures  (fun h0 r h1 -> ...))
```

_Veri:_
```veri
PROCEDURE fairinf_run_rebuild_kernel(
  reqs:         IN OUT FairinfCReq[],   -- array, read-write
  n:            IN     int32,            -- number of requests
  max_kv_tokens: IN    int32,            -- KV budget; -1 = unlimited
  fairinf_n:    IN     int32,            -- concurrent users
  until_ts:     IN     float64           -- time limit; -1 = unlimited
)
RETURNS nothing
PRE  n > 0
  AND array_len(reqs) >= n
POST FORALL i IN 0..n-1
  reqs[i].ant_type != -1
  AND (reqs[i].is_complete = 1 ==>
       reqs[i].ant_type = -1)
  AND (reqs[i].ant_type >= 0 ==>
       reqs[i].ant_end_ts > reqs[i].arrival_ts)
DECREASES n;
```

#### Mode Annotations

The `IN` / `OUT` / `IN OUT` maps to F* effects:

| DSL Direction | F* Effect | Meaning |
|---|---|---|
| (none) | `Tot` | Pure, no side effects, total |
| `PURE` | `Pure` | Pure with pre/post (default) |
| `MUT` | `ST` | Stateful (heap mutation) |
| `GHOST` | `GTot` | Ghost/proof-only |
| `LEMMA` | `Lemma` | Lemma with ensures |
| `DIV` | `Dv` | Possibly divergent |

### 4. Full Round-trip Example

**F* `.fsti` → Veri DSL `.veri` → F* `.fsti`**

_Input F*:_
```fstar
module CircularBuffer

open FStar.List.Tot

let buffer_size : nat = 8

type circular_buffer = {
  data: list int;
  head: nat;
  tail: nat;
  count: nat;
}

val is_valid_buffer: buf: circular_buffer -> Tot bool

type valid_circular_buffer = buf:circular_buffer{is_valid_buffer buf}

val push: buf:valid_circular_buffer -> value:int
  -> Pure valid_circular_buffer
    (requires True)
    (ensures (fun result ->
      is_valid_buffer result /\
      result.count = (if buf.count < buffer_size
                      then buf.count + 1
                      else buffer_size)))
```

_DSL output:_
```veri
MODULE CircularBuffer;
IMPORT FStar.List.Tot;

LET buffer_size: nat = 8;

TABLE CircularBuffer {
  data:  list int,   -- fixed-size list
  head:  nat,        -- read position
  tail:  nat,        -- write position
  count: nat         -- number of elements
};

PREDICATE is_valid_buffer (buf: CircularBuffer) -> bool =
  buf.head < buffer_size
  AND buf.tail < buffer_size
  AND buf.count <= buffer_size
  AND len(buf.data) = buffer_size
  AND buf.count = IF buf.tail >= buf.head
                  THEN buf.tail - buf.head
                  ELSE buffer_size - buf.head + buf.tail;

TYPE valid_circular_buffer = CircularBuffer WHERE is_valid_buffer(buf);

PROCEDURE push(
  buf:   IN OUT valid_circular_buffer,
  value: IN     int32
)
RETURNS valid_circular_buffer
PRE  TRUE
POST is_valid_buffer(result)
  AND result.count = IF buf.count < buffer_size
                     THEN buf.count + 1
                     ELSE buffer_size
  AND (buf.count = buffer_size ==>
       result.head = (buf.head + 1) % buffer_size);
```

### 5. Expression Mapping

| F* | DSL | Notes |
|---|---|---|
| `True` | `TRUE` | |
| `False` | `FALSE` | |
| `x /\ y` | `x AND y` | |
| `x \/ y` | `x OR y` | |
| `x ==> y` | `x ==> y` or `IF x THEN y` | either form |
| `~x` | `NOT x` | |
| `x = y` | `x = y` | |
| `forall x. p` | `FORALL x IN set: p` | with explicit domain |
| `exists x. p` | `EXISTS x IN set: p` | |
| `match x with ...` | `MATCH x ...` | |
| `List.Tot.length l` | `len(l)` | sugared |
| `array_len(a)` | `array_len(a)` | DSL built-in |
| `x + 1` | `x + 1` | arithmetic preserved |
| `fun result -> ...` | `result` | implicit in POST |

### 6. File Structure

```
.veri  ≡  module_header import* declaration*
decl  ≡  type_decl
        | constraint_decl
        | predicate_decl
        | procedure_decl
        | let_decl
        | pragma

type_decl ::=
  | "TYPE" name ":" kind ";"                                           -- abstract
  | "TYPE" name "=" type_expr ";"                                       -- abbrev
  | "TYPE" name "=" base_type "WHERE" predicate ";"                     -- refined
  | "TABLE" name "{" field ("," field)* "}" ";"                         -- record
  | "ENUM" name "{" variant ("," variant)* "}" ";"                      -- unit enum
  | "VARIANT" name "{" "|" variant_payload ("," "|" variant_payload)* "}" ";"  -- tagged union

field ::= name ":" type [comment]
variant ::= name ["=" int_const] [comment]
variant_payload ::= name "(" field ("," field)* ")"

constraint_decl ::=
  "CONSTRAINT" name "{" constraint_clause ("," constraint_clause)* "}" ";"
constraint_clause ::= [FORALL ...] predicate

predicate_decl ::=
  "PREDICATE" name "(" binder ("," binder)* ")" "->" type "=" expr ";"

procedure_decl ::=
  "PROCEDURE" name "(" param ("," param)* ")"
  "RETURNS" type
  [ "PRE" formula ]
  [ "POST" formula ]
  [ "DECREASES" term ]
  ";" ";"

param ::= name ":" direction type

direction ::= "IN" | "OUT" | "IN OUT" | (empty)

let_decl ::=
  "LET" name "=" expr ";"                       -- simple constant
  "LET" name "(" binder ")" "=" expr ";"         -- named predicate macro
```

### 7. Bidirectional Mapping Schema

```
             ┌──────────────────────┐
             │     F* .fsti         │
             └────────┬─────────────┘
                      │ fsti → veri
                      ▼
             ┌──────────────────────┐
             │   .veri (DSL)         │
             └────────┬─────────────┘
                      │ veri → fsti
                      ▼
             ┌──────────────────────┐
             │   F* .fsti           │
             └──────────────────────┘
```

The mapping must be **lossless**: round-tripping should produce syntactically
equivalent (modulo whitespace/comments) F*.

**Verification strategy:**
1. Take any existing `.fsti` from the scaffold pipeline
2. Convert to `.veri` (parsing F* to our AST)
3. Convert back to `.fsti` (pretty-printing)
4. Diff the original and round-tripped F*
5. Both must type-check with `fstar.exe`
