# FairInf Core — Scheduling Kernel

Translated from `_fairinf_core.h` using Veri DSL. This module models the isolated scheduling simulation for fair inference.

## Request State

```veri
class FairinfReq:
    rid:               string(128)    # request ID
    arrival_ts:        float64        # when request arrived
    prompt_len:        int32          # number of prompt tokens
    real_decode_count: int32          # decode steps completed
    prefill_done:      bool           # prefill completed?
    is_complete:       bool           # request fully complete?
    ant_type:          int32          # -1=none, 0=prefill, 1=decode
    ant_end_ts:        float64        # predicted end timestamp
    ant_completion:    int32          # decode step number
```

## Documented Invariants

```veri
CONSTRAINT FairinfReqInvariants:
    FORALL req IN reqs:
        # Every request gets a prediction
        req.ant_type != -1

    FORALL req IN reqs:
        # Completed requests get no anticipated event
        req.is_complete == 1 ==> req.ant_type == -1

    FORALL req IN reqs:
        # Anticipation never goes backward in time
        req.ant_type >= 0 ==> req.ant_end_ts > req.arrival_ts

    FORALL req IN reqs:
        # Active KV memory does not exceed budget
        active_kv_memory <= max_kv_tokens
```

## Kernel Function

```veri
def fairinf_run_rebuild_kernel(
    reqs:         STATE_READ_WRITE FairinfReq[],
    n:            STATE_READ_ONLY     int32,
    max_kv_tokens: STATE_READ_ONLY    int32,
    fairinf_n:    STATE_READ_ONLY     int32,
    until_ts:     STATE_READ_ONLY     float64,
) -> None:
    REQUIRES (n > 0
              and array_len(reqs) >= n
              and max_kv_tokens >= -1
              and until_ts >= -1.0)
    ENSURES (FORALL i IN range(0, n):
                 reqs[i].ant_type != -1
             and FORALL i IN range(0, n):
                 (reqs[i].is_complete == 1 ==>
                  reqs[i].ant_type == -1)
             and FORALL i IN range(0, n):
                 (reqs[i].ant_type >= 0 ==>
                  reqs[i].ant_end_ts > reqs[i].arrival_ts))
    DECREASES n
```

## Time Estimation (Pure Functions)

```veri
def fairinf_isolated_prefill_time(
    total_batch_sum: float64,
    max_token_size:  float64,
    batch_length:    float64,
    fairinf_n:       float64,
) -> float64:
    REQUIRES (total_batch_sum >= 0.0
              and max_token_size > 0.0
              and batch_length > 0.0
              and fairinf_n > 0.0)
    ENSURES result >= 0.0

def fairinf_isolated_decode_time(
    total_batch_sum: float64,
    max_token_size:  float64,
    batch_length:    float64,
    fairinf_n:       float64,
) -> float64:
    REQUIRES (total_batch_sum >= 0.0
              and max_token_size > 0.0
              and batch_length > 0.0
              and fairinf_n > 0.0)
    ENSURES result >= 0.0
```

## Intended Meaning

- `fairinf_run_rebuild_kernel` drives the scheduler: given real-world state, it predicts the next scheduling event for every request.
- Time estimation functions are exact translations of Python implementations in `time_estimation.py`.
- Invariants guarantee soundness: no spurious anticipation for completed requests, no backward time jumps.
