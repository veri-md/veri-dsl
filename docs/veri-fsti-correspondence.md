# Veri DSL ↔ F* .fsti Correspondence

Complete reference mapping Veri DSL (F*Veri DSL) constructs to their F* `.fsti` equivalents, organized by concept.

## 1. Module Structure

### Module Declaration

```
Veri:  module FairinfCore
F*:   module FairinfCore
```

### Imports / Opens

```
Veri:  import FStar.List.Tot
      import FStar.Mul

F*:   open FStar.List.Tot
      open FStar.Mul
```

---

## 2. Type Declarations

### 2a. Abstract Type

No body = abstract type whose representation is hidden.

```
Veri:  type Key: eqtype
      type FairinfToken

F*:   type key : eqtype
      type fairinf_token
```

### 2b. Type Alias

Simple name for an existing type.

```
Veri:  type SortedList = list[int]

F*:   type sorted_list = list int
```

### 2c. Refined Type

Type with an invariant predicate attached via `WHERE`.

```
Veri:  type ValidBuffer = CircularBuffer WHERE is_valid_buffer(buf)
      type FinN = int WHERE 0 <= n and n < N

F*:   type valid_circular_buffer = buf:circular_buffer{is_valid_buffer buf}
      type fin_n = n:int{0 <= n /\ n < N}
```

### 2d. Record / Struct (class)

```
Veri:  class CircularBuffer:
          data:  list[int]      # fixed-size list
          head:  nat            # read position
          tail:  nat            # write position
          count: nat            # number of elements

F*:   type circular_buffer = {
        data: list int;
        head: nat;
        tail: nat;
        count: nat;
      }
```

Fields are `name: type` (one per line, indented). Inline comments via `#`.

### 2e. Enum (Unit Constructors)

```
Veri:  enum AntType:
          NONE
          PREFILL
          DECODE

F*:   type ant_type_t =
        | None_t : ant_type_t
        | Prefill : ant_type_t
        | Decode : ant_type_t
```

With numeric values (for C interop) — these become derived lemmas:

```
Veri:  enum AntType:
          NONE    = -1
          PREFILL = 0
          DECODE  = 1
```

### 2f. Variant (Constructors with Payload)

```
Veri:  variant Outcome:
          | Success(result: int64, msg: string)
          | Failure(error: string)
          | Timeout(duration: float64)

F*:   type outcome =
        | Success : result:int64 -> msg:Prims.string -> outcome
        | Failure : error:Prims.string -> outcome
        | Timeout : duration:Prims.float -> outcome
```

---

## 3. Type Applications

### Parenthesized Application

```
Veri:  option[int]
      option[(int, ValidBuffer)]
      list[option[CacheEntry]]
      buffer[CacheEntry]

F*:   option int
      option (int * valid_circular_buffer)
      list (option cache_entry)
      Buffer.buffer cache_entry
```

Type constructors (`option`, `list`, `buffer`, etc.) are followed by their argument in brackets.

### Tuples

```
Veri:  (int, ValidBuffer)
      (nat * nat * nat)           # F* uses * for tuple types

F*:   (int * valid_circular_buffer)
      (nat * nat * nat)
```

Tuple elements are comma-separated in Veri DSL, `*`-separated in F*.

---

## 4. Predicates / Invariants (let definitions)

### Simple Constant

```
Veri:  buffer_size: nat = 8
      max_int_val: int = 2 ** 31 - 1

F*:   let buffer_size : nat = 8
      let max_int_val : int = 2 ** 31 - 1
```

### Boolean Predicate

```
Veri:  def is_valid_buffer(buf: CircularBuffer) -> bool:
          return (buf.head < buffer_size
                  and buf.tail < buffer_size
                  and buf.count <= buffer_size
                  and len(buf.data) == buffer_size)

F*:   let is_valid_buffer (buf: circular_buffer) : bool =
        buf.head < buffer_size &&
        buf.tail < buffer_size &&
        buf.count <= buffer_size &&
        List.Tot.length buf.data = buffer_size
```

`def` with a `return` body → F* `let` definition.
Parameters are comma-separated in Veri DSL, space-separated in F*.

---

## 5. Function Signatures (val declarations)

### Pure Function (Tot effect)

```
Veri:  def nth_opt(lst: list[type], i: nat) -> option[type]:
          REQUIRES True
          ENSURES ...

F*:   val nth_opt: lst:list 'a -> i:nat -> Tot (option 'a)
```

### Pure Function with Requires/Ensures

```
Veri:  def push(buf: ValidBuffer, value: int) -> ValidBuffer:
          REQUIRES True
          ENSURES (is_valid_buffer(result)
                   and result.count == (buf.count + 1 if buf.count < buffer_size
                                         else buffer_size))

F*:   val push: buf:valid_circular_buffer -> value:int
          -> Pure valid_circular_buffer
            (requires True)
            (ensures (fun result ->
              is_valid_buffer result /\
              result.count = (if buf.count < buffer_size
                              then buf.count + 1
                              else buffer_size)))
```

### Stateful Function (ST effect)

```
Veri:  def fairinf_run_rebuild_kernel(
          reqs:         IN OUT FairinfReq[],
          n:            IN     int32,
          max_kv_tokens: IN    int32,
      ) -> None:
          REQUIRES n > 0 and array_len(reqs) >= n
          ENSURES ...

F*:   val fairinf_run_rebuild_kernel:
          reqs:         Buffer.buffer fairinf_c_req ->
          n:            int ->
          max_kv_tokens: int ->
          ST unit
            (requires (fun h -> n > 0 /\ length reqs >= n))
            (ensures (fun h0 r h1 -> ...))
```

### Lemma

```
Veri:  def uv_inv(x: Int8):
          ENSURES int_to_t(v(x)) == x
          [SMTPat(v(x))]

F*:   val uv_inv (x : Int8.t) : Lemma
          (ensures (Int8.int_to_t (Int8.v x) == x))
          [SMTPat (Int8.v x)]
```

Lemma has no return type — the contract clauses follow directly.

### Direction Annotations → F* Effects

| Veri DSL | F* Effect | Meaning |
|---|---|---|
| (no direction) | `Tot` | Read-only, total |
| `IN` | `Tot` | Input, no mutation |
| `OUT` | `ST` | Writes to heap |
| `IN OUT` | `ST` | Reads and writes |
| `PURE` | `Pure` | Explicit contract |
| `GHOST` | `GTot` | Ghost/proof-only |
| `LEMMA` | `Lemma` | Lemma with ensures |

---

## 6. Contract Clauses (Pre/Post Conditions)

### Keywords

| Veri DSL | F* | Meaning |
|---|---|---|
| `REQUIRES expr` | `(requires expr)` | Precondition |
| `ENSURES expr` | `(ensures (fun result -> expr))` | Postcondition |
| `DECREASES expr` | `(decreases expr)` | Termination metric |

In Veri DSL, `result` is an implicit variable in `ENSURES` referring to the return value.

### Logical Operators

| Veri DSL | F* | Meaning |
|---|---|---|
| `and` | `/\` | Conjunction |
| `or` | `\/` | Disjunction |
| `not` | `~` | Negation |
| `==>` | `==>` | Implication |
| `<==>` | `<==>` | If and only if |
| `==` | `=` | Propositional equality |
| `!=` | `<>` | Inequality |
| `< / > / <= / >=` | `< / > / <= / >=` | Comparison |
| `+ / - / * / / %` | `+ / - / * / / %` | Arithmetic |

### Quantifiers

```
Veri:  FORALL i IN range(0, n): reqs[i].ant_type != -1
      EXISTS i IN range(0, n): reqs[i].is_complete == 1

F*:   (forall (i: nat). i < n ==> reqs.[i].ant_type <> -1)
      (exists (i: nat). i < n /\ reqs.[i].is_complete = 1)
```

### Match Expressions (Pythonic)

```
Veri:  match result:
          case None:
              buf.count == 0
          case Some(v, new_buf):
              buf.count > 0 and is_valid_buffer(new_buf)

F*:   match result with
        | None -> buf.count = 0
        | Some (v, new_buf) ->
            buf.count > 0 /\ is_valid_buffer new_buf
```

### List Patterns

```
Veri:  case [] -> True
      case [_] -> True
      case [hd1, hd2, *tl] ->
          hd1.serial <= hd2.serial and is_sorted([hd2] + tl)

F*:   | [] -> true
      | [_] -> true
      | hd1 :: hd2 :: tl ->
          hd1.serial <= hd2.serial && is_sorted (hd2 :: tl)
```

---

## 7. Expression Sugar

| Veri DSL | F* | Notes |
|---|---|---|
| `len(x)` | `List.Tot.length x` | List length |
| `array_len(x)` | `Buffer.length x` | Buffer length |
| `x[i]` | `Seq.index x i` | Indexing |
| `x.f` | `x.f` | Field access |
| `True` / `False` | `true` / `false` | Booleans |
| `None` | `()` | Unit/void return |
| `if A then B else C` | `if A then B else C` | Conditional |
| `[hd] + tl` | `hd :: tl` | List cons (expression-level) |
| `f(x, y, z)` | `f x y z` | Function application |
| `# comment` | `// comment` | Line comment |

---

## 8. Constraint Blocks (Table-level Invariants)

```
Veri:  CONSTRAINT FairinfReqInvariants:
          FORALL req IN reqs:
              req.ant_type != -1
          FORALL req IN reqs:
              req.is_complete == 1 ==> req.ant_type == -1

F*:   (* Documented invariants from _fairinf_core.h:
        - Every request gets a prediction
        - Completed requests get no anticipated event *)
      (* These become lemmas or refinement constraints *)
```

Constraint blocks are documentation-level — they compile to comments or lemma declarations in F*.

---

## 9. Attributes / Annotations

### SMT Patterns

```
Veri:  [SMTPat(v(x))]
      [SMTPatOr([[SMTPat(p x)], [SMTPat(q x)]])]

F*:   [SMTPat (v x)]
      [SMTPatOr [[SMTPat (p x)]; [SMTPat (q x)]]]
```

### Extraction Attributes

```
Veri:  ADMITTED
      INLINE_FOR_EXTRACTION

F*:   [@@ (admitted)]
      inline_for_extraction
```

---

## 10. C Type Mappings (for `_fairinf_core.h`-style headers)

| C Type | Veri DSL Type | F* Type |
|---|---|---|
| `int` | `int32` | `Prims.int` |
| `double` | `float64` | `Prims.float` |
| `char *` / `char[N]` | `string(N)` | `Prims.string` |
| `bool` / `_Bool` | `bool` | `Prims.bool` |
| `uint32_t` | `uint32` | `FStar.UInt32.t` |
| `void` | `None` | `unit` |
| `T *` (mutable) | `IN OUT T[]` | `Buffer.buffer t` |
| `T *` (immutable) | `IN T[]` | `Seq.seq t` |

---

## 11. Complete Example Round-trip

**F* `.fsti`:**
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

let is_valid_buffer (buf: circular_buffer) : bool =
  buf.head < buffer_size &&
  buf.tail < buffer_size &&
  buf.count <= buffer_size

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

**Veri DSL `.veri`:**
```veri
import FStar.List.Tot

buffer_size: nat = 8

class CircularBuffer:
    data:  list[int]    # fixed-size list
    head:  nat          # read position
    tail:  nat          # write position
    count: nat          # number of elements

def is_valid_buffer(buf: CircularBuffer) -> bool:
    return (buf.head < buffer_size
            and buf.tail < buffer_size
            and buf.count <= buffer_size)

type ValidBuffer = CircularBuffer WHERE is_valid_buffer(buf)

def push(buf: ValidBuffer, value: int) -> ValidBuffer:
    REQUIRES True
    ENSURES (is_valid_buffer(result)
             and result.count == (buf.count + 1 if buf.count < buffer_size
                                   else buffer_size))
```
