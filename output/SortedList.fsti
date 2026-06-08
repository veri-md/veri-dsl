module SortedList

type element = {
    serial: Prims.nat;
    data: Prims.string;
}

type sorted_list = list element

let rec is_sorted (lst: sorted_list) : Prims.bool =
    match lst with
        | [] -> true
        | _ :: [] -> true
        | hd1 :: hd2 :: tl -> hd1.serial <= hd2.serial && is_sorted (hd2 :: tl)

type valid_sorted_list = x:sorted_list{is_sorted x}

val add_element:  existing:valid_sorted_list ->  new_elem:element ->  Pure valid_sorted_list
  (requires true)
  (ensures (fun result -> is_sorted result && List.Tot.length result = List.Tot.length existing + 1))

