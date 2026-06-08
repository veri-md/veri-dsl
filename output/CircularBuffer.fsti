module CircularBuffer

let buffer_size : Prims.nat = 8

type circular_buffer = {
    data: list Prims.int;
    head: Prims.nat;
    tail: Prims.nat;
    count: Prims.nat;
}

let is_valid_buffer (buf: circular_buffer) : Prims.bool =
    buf.head < buffer_size && buf.tail < buffer_size && buf.count <= buffer_size && List.Tot.length buf.data = buffer_size

type valid_buffer = x:circular_buffer{is_valid_buffer x}

val push:  buf:valid_buffer ->  value:Prims.int ->  Pure valid_buffer
  (requires true)
  (ensures (fun result -> is_valid_buffer result && result.count = (if buf.count < buffer_size then buf.count + 1 else buffer_size)))

val pop:  buf:valid_buffer ->  Pure (option (Prims.int * valid_buffer))
  (requires true)
  (ensures (fun result -> match result with
        | None -> buf.count = 0
        | Some (v, new_buf) -> buf.count > 0 && is_valid_buffer new_buf && new_buf.count = buf.count - 1 && new_buf.head = buf.head + 1 % buffer_size))

val peek:  buf:valid_buffer ->  Pure (option Prims.int)
  (requires true)
  (ensures (fun result -> match result with
        | None -> buf.count = 0
        | Some (v) -> buf.count > 0))

