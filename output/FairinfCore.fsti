module FairinfCore

type fairinf_req = {
    rid: Prims.string;
    arrival_ts: Prims.int;
    prompt_len: Prims.int;
    real_decode_count: Prims.int;
    prefill_done: Prims.bool;
    is_complete: Prims.bool;
    ant_type: Prims.int;
    ant_end_ts: Prims.int;
    ant_completion: Prims.int;
}

(* Error: Unexpected in type: Token(KEYWORD, 'FORALL') *)
(* Error: Unexpected in type: Token(RBRACKET, ']') *)
val fairinf_isolated_prefill_time:  total_batch_sum:Prims.int ->  max_token_size:Prims.int ->  batch_length:Prims.int ->  fairinf_n:Prims.int ->  Pure Prims.int
  (requires total_batch_sum >= 0 && max_token_size > 0 && batch_length > 0 && fairinf_n > 0)
  (ensures (fun result -> result >= 0))

val fairinf_isolated_decode_time:  total_batch_sum:Prims.int ->  max_token_size:Prims.int ->  batch_length:Prims.int ->  fairinf_n:Prims.int ->  Pure Prims.int
  (requires total_batch_sum >= 0 && max_token_size > 0 && batch_length > 0 && fairinf_n > 0)
  (ensures (fun result -> result >= 0))

