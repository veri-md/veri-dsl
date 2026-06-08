# Sorted List Example

This example demonstrates a verified data structure: a list of elements that must remain sorted by serial number. Written in Veri DSL.

## Element Type

```veri
class Element:
    serial: nat        # unique serial number
    data: string       # associated data
```

## Sorted List Type

```veri
type SortedList = list[Element]

def is_sorted(lst: SortedList) -> bool:
    return match lst:
        case []:
            True
        case [_]:
            True
        case [hd1, hd2, *tl]:
            hd1.serial <= hd2.serial and is_sorted([hd2] + tl)

type ValidSortedList = SortedList WHERE is_sorted(lst)
```

## Adding an Element

```veri
def add_element(existing: ValidSortedList, new_elem: Element) -> ValidSortedList:
    REQUIRES True
    ENSURES is_sorted(result)
        and len(result) == len(existing) + 1
```

## Intended Meaning

The implementation should insert the new element in sorted order by `serial`, preserve the sortedness invariant, and increase the list length by exactly one.
