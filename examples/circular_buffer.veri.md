# Circular Buffer (N=8)

This example demonstrates a verified circular buffer with fixed size N=8, written in Veri DSL.

## Buffer Size Constant

```veri
buffer_size: nat = 8
```

## Buffer Type and Invariant

```veri
class CircularBuffer:
    data:  list[int]   # fixed-size list, length = buffer_size
    head:  nat         # read position
    tail:  nat         # write position
    count: nat         # number of elements

def is_valid_buffer(buf: CircularBuffer) -> bool:
    return (buf.head < buffer_size
            and buf.tail < buffer_size
            and buf.count <= buffer_size
            and len(buf.data) == buffer_size)

type ValidBuffer = CircularBuffer WHERE is_valid_buffer(buf)
```

## Push Operation

```veri
def push(buf: ValidBuffer, value: int) -> ValidBuffer:
    REQUIRES True
    ENSURES (is_valid_buffer(result)
             and result.count == (buf.count + 1 if buf.count < buffer_size
                                   else buffer_size))
```

## Pop Operation

```veri
def pop(buf: ValidBuffer) -> option[(int, ValidBuffer)]:
    REQUIRES True
    ENSURES match result:
        case None:
            buf.count == 0
        case Some(v, new_buf):
            buf.count > 0
            and is_valid_buffer(new_buf)
            and new_buf.count == buf.count - 1
            and new_buf.head == (buf.head + 1) % buffer_size
```

## Peek Operation

```veri
def peek(buf: ValidBuffer) -> option[int]:
    REQUIRES True
    ENSURES match result:
        case None:
            buf.count == 0
        case Some(v):
            buf.count > 0
```

## Intended Meaning

The circular buffer maintains a fixed-size ring with:
- **push** adds an element at the tail, wrapping around and overwriting the oldest element when full
- **pop** removes an element from the head, returning None if empty
- **peek** reads the head element without removing it
- All operations preserve basic invariants (list length, index bounds)
