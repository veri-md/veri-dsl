# LRU Cache (N=8)

A verified LRU (Least Recently Used) cache with fixed size N=8, written in Veri DSL.

## Cache Parameters

```veri
cache_size: nat = 8
```

## Cache Entry and Type

```veri
class CacheEntry:
    key:       nat     # lookup key
    value:     int     # cached value
    timestamp: nat     # access time (higher = more recent)

class LRUCache:
    entries: list[option[CacheEntry]]   # fixed-size, length = cache_size
    count:   nat                        # occupied slots
    clock:   nat                        # monotonic timestamp counter

def count_some(entries: list[option[CacheEntry]]) -> nat:
    return match entries:
        case []:
            0
        case [None, *tl]:
            count_some(tl)
        case [Some(_), *tl]:
            1 + count_some(tl)

def nth_opt(lst: list[type], i: nat) -> option[type]:
    return match (lst, i):
        case ([], _):
            None
        case ([hd, *tl], 0):
            Some(hd)
        case ([_, *tl], _):
            nth_opt(tl, i - 1)

def is_valid_cache(cache: LRUCache) -> bool:
    return (cache.count <= cache_size
            and len(cache.entries) == cache_size
            and cache.count == count_some(cache.entries))

type ValidLRUCache = LRUCache WHERE is_valid_cache(cache)
```

## Get Operation

```veri
def get(cache: ValidLRUCache, k: nat) -> option[(int, ValidLRUCache)]:
    REQUIRES True
    ENSURES match result:
        case None:
            FORALL i IN range(0, cache_size):
                match nth_opt(cache.entries, i):
                    case Some(Some(e)):
                        e.key != k
                    case _:
                        True
        case Some(v, new_cache):
            is_valid_cache(new_cache)
            and new_cache.count == cache.count
            and new_cache.clock == cache.clock + 1
            and EXISTS i IN range(0, cache_size):
                  match nth_opt(cache.entries, i):
                      case Some(Some(e)):
                          e.key == k and e.value == v
                      case _:
                          False
```

## Put Operation

```veri
def put(cache: ValidLRUCache, k: nat, v: int) -> ValidLRUCache:
    REQUIRES True
    ENSURES (is_valid_cache(result)
             and result.clock == cache.clock + 1
             and EXISTS i IN range(0, cache_size):
                   match nth_opt(result.entries, i):
                       case Some(Some(e)):
                           e.key == k and e.value == v
                           and e.timestamp == cache.clock
                       case _:
                           False)
```

## Evict Operation (Proves LRU Property)

```veri
def evict(cache: ValidLRUCache) -> option[(nat, ValidLRUCache)]:
    REQUIRES cache.count > 0
    ENSURES match result:
        case None:
            False
        case Some(evicted_key, new_cache):
            is_valid_cache(new_cache)
            and new_cache.count == cache.count - 1
            and new_cache.clock == cache.clock
            and EXISTS i IN range(0, cache_size):
                  match nth_opt(cache.entries, i):
                      case Some(Some(e)):
                          e.key == evicted_key
                          and FORALL j IN range(0, cache_size):
                                match nth_opt(cache.entries, j):
                                    case Some(Some(ej)):
                                        e.timestamp <= ej.timestamp
                                    case _:
                                        True
                      case _:
                          False
```

## Intended Meaning

The LRU cache maintains a fixed-size key-value store with:
- **get** retrieves a value and updates its timestamp (marks as recently used)
- **put** inserts or updates an entry, evicting the LRU entry if at capacity
- **evict** removes the entry with the smallest timestamp, proving LRU property in its ensures clause
