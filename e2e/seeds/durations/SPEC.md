# parse_duration(text) -> int and format_duration(seconds) -> str

`parse_duration` converts a duration string to whole seconds.

1. A duration is one or more components `<number><unit>`. Units: `d` (86400 s), `h` (3600),
   `m` (60), `s` (1). Units are case-insensitive.
2. Spaces between components are allowed (`"1h 30m"`); leading/trailing whitespace is ignored.
   No space is allowed between a number and its unit.
3. Numbers are non-negative integers, or decimals with a fractional part (`"1.5h"`). The total is
   rounded to the nearest second (half up).
4. Units must appear in descending order (`d`, `h`, `m`, `s`) and at most once each:
   `"1m1h"` and `"1h1h"` are invalid.
5. Anything else (empty string, unknown unit, missing unit, signs, `"h"` alone) raises `ValueError`
   with a message that includes the offending input.

`format_duration(seconds)` is the inverse for non-negative ints: the canonical form uses the
largest units first and omits zero components (`5400` → `"1h30m"`, `90061` → `"1d1h1m1s"`);
`0` → `"0s"`. Negative or non-int input raises `ValueError` (bools are not ints here).
For every int `n >= 0`, `parse_duration(format_duration(n)) == n`.
