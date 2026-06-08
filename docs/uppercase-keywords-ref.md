# Uppercase Keywords Reference

Uppercase SQL-style keywords in Veri DSL separate *contract logic* (what must be true) from *computation* (how to compute). This doc explains each one through a single running example.

| Keyword | Section | Role | Maps to F* | Python Analogy |
|---|---|---|---|---|
| `REQUIRES` | §5 | Precondition | `(requires expr)` | `assert` at function entry |
| `ENSURES` | §5 | Postcondition | `(ensures (fun result -> expr))` | `assert` at function exit |
| `DECREASES` | §5 | Termination metric | `(decreases expr)` | *(no equivalent)* |
| `WHERE` | §3c | Refinement predicate | `t{pred}` | Type narrowing |
| `CONSTRAINT` | §6 | Invariant block | *(documentation)* | DB `CHECK` constraint |
| `FORALL` | §5, §9 | Universal quantifier | `(forall x. p)` | `all(p(x) for x in set)` |
| `EXISTS` | §5, §9 | Existential quantifier | `(exists x. p)` | `any(p(x) for x in set)` |
| `IN` | §9 | Quantifier range | `IN` | `in` (in `for x in set`) |
| `STATE_READ_ONLY` | §10 | Read-only parameter | `Tot` / `Pure` | `@dataclass(frozen=True)` |
| `STATE_WRITE_ONLY` | §10 | Write-only parameter | `ST` / `HST` | *(mutable buffer)* |
| `STATE_READ_WRITE` | §10 | Read+write parameter | `ST` / `HST` | `self` in a method |
| `PURE` | §10 | Explicit pure function | `Tot` / `Pure` | Pure function |
| `GHOST` | §10 | Proof-only function | `GTot` | *(no runtime code)* |
| `LEMMA` | §10 | Lemma function | `Lemma` | *(no runtime code)* |
| `SMTPat` | §5 | SMT solver hint | `[SMTPat expr]` | *(F* internals)* |

---

## Running Example: Token Bucket Rate Limiter

We'll model a token bucket rate limiter — a container that holds tokens, with a max capacity, where tokens refill over time. This needs structure definitions, invariants, a stateful update function, and proof of correctness.

### Step 1: The Data Structure

```veri
class TokenBucket:
    capacity: int       # max tokens the bucket can hold
    tokens:   int       # current token count
    refill_rate: int    # tokens added per refill
    last_refill: int    # timestamp of last refill
```

### Step 2: The Invariant (type-level, `WHERE`)

We need a `WHERE` clause: only buckets where `tokens <= capacity` are valid.

```veri
type ValidBucket = TokenBucket WHERE tokens <= capacity
```

`WHERE` attaches a predicate to a type — values that don't satisfy it can't exist at verified boundaries.

| Veri DSL | F* | Meaning |
|---|---|---|
| `type T = Base WHERE pred` | `type t = x:base{pred x}` | Refinement: only values satisfying `pred` |

---

### Step 3: System-Level Invariants (`CONSTRAINT`)

Let's say all buckets share a global token pool. We document that invariant:

```veri
CONSTRAINT TokenPoolInvariants:
    # Total tokens across all buckets never exceeds total capacity
    total_tokens <= total_capacity

    # No bucket exceeds its individual capacity
    FORALL b IN buckets:
        b.tokens <= b.capacity

    # Refill rate is always positive
    FORALL b IN buckets:
        b.refill_rate > 0
```

`CONSTRAINT` blocks are named collections of conditions that the whole system must satisfy. They act like database `CHECK` constraints — always-true assertions on the global state.

| Veri DSL | Meaning | Python analogy |
|---|---|---|
| `CONSTRAINT Name: ...` | Named block of always-true invariants | Schema-level `CHECK` constraints |
| *lines are `FORALL` or plain expressions* | Each line is an invariant | Assertions checked by the verifier |

---

### Step 4: Quantifiers (`FORALL`, `EXISTS`)

Inside `CONSTRAINT` blocks (and `ENSURES` clauses), we can quantify over data:

```veri
FORALL b IN buckets:
    b.tokens <= b.capacity

EXISTS b IN buckets:
    b.tokens == 0
```

| Veri DSL | Python equivalent | F* |
|---|---|---|
| `FORALL x IN set: p(x)` | `all(p(x) for x in set)` | `(forall x. p(x))` |
| `EXISTS x IN set: p(x)` | `any(p(x) for x in set)` | `(exists x. p(x))` |

`IN` here is part of the quantifier syntax (`FORALL x IN set`), not a direction annotation.

---

### Step 5: A Read-Only Helper (`STATE_READ_ONLY`)

A pure query — takes a bucket, doesn't modify it:

```veri
def can_accept(bucket: STATE_READ_ONLY ValidBucket, count: int) -> bool:
    REQUIRES count > 0
    ENSURES result == (bucket.tokens + count <= bucket.capacity)
```

The `STATE_READ_ONLY` annotation tells F* this parameter is not mutated — the function is pure.

| Annotation | Meaning | F* Effect |
|---|---|---|
| *(none)* | Read-only, no mutation | `Tot` / `Pure` |
| `STATE_READ_ONLY` | Explicitly read-only | `Tot` / `Pure` |
| `STATE_WRITE_ONLY` | Write-only (uninitialized output) | `ST` / `HST` |
| `STATE_READ_WRITE` | Readable and mutable | `ST` / `HST` |
| `PURE` | Explicit pure contract | `Pure` |
| `GHOST` | Proof-only, no runtime effect | `GTot` |
| `LEMMA` | Proof-only function | `Lemma` |

Functions with all `STATE_READ_ONLY` or unannotated params → `Pure` effect.
Any `STATE_WRITE_ONLY` or `STATE_READ_WRITE` → `ST` (stateful) effect.

---

### Step 6: A Stateful Update (`STATE_READ_WRITE`)

Now the core operation — consuming tokens from the bucket:

```veri
def consume(bucket: STATE_READ_WRITE ValidBucket, count: int) -> bool:
    REQUIRES count > 0
    ENSURES match result:
        case True:
            bucket.tokens == (bucket@.tokens - count if bucket@.tokens >= count else bucket@.tokens - 1)
        case False:
            bucket.tokens == bucket@.tokens
```

`STATE_READ_WRITE` means the parameter is both readable and mutable. In `ENSURES`, the old value is accessed via `param@`. The contract guarantees:
- If consumption succeeds (`result == True`), the token count decreases by `count`
- If it fails (`result == False`, not enough tokens), the count stays unchanged

---

### Step 7: Pre/Post Conditions (`REQUIRES`, `ENSURES`)

Every function with a contract uses these:

```veri
def consume(bucket: STATE_READ_WRITE ValidBucket, count: int) -> bool:
    REQUIRES count > 0
    ENSURES match result:
        case True:
            bucket.tokens == bucket@.tokens - count
        case False:
            bucket.tokens == bucket@.tokens
```

| Keyword | Meaning | Python analogy |
|---|---|---|
| `REQUIRES cond` | What must be true before the call | `assert cond` at function entry |
| `ENSURES cond` | What will be true after the call | `assert cond` at function exit |

`result` in `ENSURES` is an implicit variable referring to the return value.

---

### Step 8: Termination (`DECREASES`)

A recursive refill function needs to prove it terminates:

```veri
def refill_until(bucket: STATE_READ_WRITE ValidBucket, target: int) -> None:
    REQUIRES target > bucket.tokens
    DECREASES target - bucket.tokens
    ENSURES bucket.tokens >= target
```

`DECREASES` provides a *termination metric* — a value that strictly decreases on each recursive call. The solver checks it can't go below zero.

| Keyword | Meaning | Python analogy |
|---|---|---|
| `DECREASES expr` | Termination metric | `while expr > 0` — but for recursion |

---

### Step 9: Lemmas and Ghost Code (`LEMMA`, `GHOST`, `SMTPat`)

Sometimes the verifier needs help proving something that isn't obvious from the code alone. You write a **lemma** — a proof-only function that states a fact and explains *why* it's true. Lemmas exist only for the verifier; they produce no runtime code.

**Concrete example:** Our token bucket has `tokens <= capacity` as an invariant (the `WHERE` clause). But what if the verifier needs to know that `tokens >= 0`? That's not in the invariant (capacity could be anything). We prove it as a lemma:

```veri
def token_count_nonnegative(bucket: ValidBucket) -> Lemma:
    ENSURES bucket.tokens >= 0
    SMTPat(bucket.tokens)
```

Breaking this down:

| Keyword | Role | What happens |
|---|---|---|
| `Lemma` | Return type | Tells F* this is a proof, not runtime code. No C code will be generated. |
| `GHOST` | Declaration qualifier | Same effect as `Lemma` — function is erased at compile time. Use whichever reads better. |
| `SMTPat(bucket.tokens)` | SMT trigger | Tells Z3: "apply this lemma whenever you see `bucket.tokens` in a proof goal." |

**How `SMTPat` works:**

Without `SMTPat`, Z3 doesn't know *when* to use the lemma. It could:
- Instantiate it for every single expression → solver explodes (billions of combinations)
- Instantiate it never → proof fails

`SMTPat` gives Z3 a pattern: *whenever `bucket.tokens` appears in the proof, fire this lemma*. It's a performance tuning knob for the solver.

**Why you'd write one:**

```veri
def tokens_additive(b1: ValidBucket, b2: ValidBucket) -> Lemma:
    REQUIRES b1.tokens + b2.tokens <= b1.capacity + b2.capacity
    ENSURES FORALL a IN range(0, b1.tokens + 1):
        FORALL b IN range(0, b2.tokens + 1):
            a + b <= b1.capacity + b2.capacity
    SMTPat(b1.tokens)
    SMTPat(b2.tokens)
```

This lemma says: if two buckets together don't exceed their combined capacity, then any split of their tokens also stays under that limit. Without the triggers, Z3 would have to guess when to apply this — with them, it fires whenever either bucket's token count appears.

**When to use these:**

| Construct | When you'd write it | Runtime cost |
|---|---|---|
| `def f(...) -> Lemma:` | A fact that needs proof but has no runtime computation | Zero — erased |
| `GHOST` | Same as Lemma, different F* encoding | Zero — erased |
| `SMTPat(e)` | When a lemma isn't being applied automatically | Zero — just a hint |
| `PURE` | Explicit marker on a regular (non-lemma) function | Normal codegen |

**In practice:** A C-to-F* pipeline never generates `SMTPat`. It appears when reading existing hand-tuned `.fsti` files, or when a verification engineer profiles proof performance and adds triggers. If you're writing contracts from C headers, you'll use `REQUIRES`/`ENSURES`/`WHERE` — not these.

---
