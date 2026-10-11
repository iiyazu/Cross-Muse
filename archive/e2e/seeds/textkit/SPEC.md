# slugify(text, sep="-", max_len=None) -> str

Turn arbitrary text into a URL slug.

1. Accented Latin letters become their ASCII base letter (`é` → `e`, `Ö` → `o`); `ß` becomes `ss`.
   Other characters that have no ASCII form are treated as separators.
2. The result is lowercase and contains only `a-z`, `0-9` and `sep`.
3. Every run of characters that are not ASCII letters or digits becomes a single `sep`.
   Leading and trailing separators are removed.
4. `max_len` (optional, int ≥ 1): the result is at most `max_len` characters. Cut at a word
   boundary (drop whole trailing words) when possible; only if the first word alone is longer than
   `max_len`, hard-cut that word. The result never ends with `sep`.
5. `sep` must be a non-empty string containing no ASCII letters or digits; otherwise raise
   `ValueError`. `max_len < 1` also raises `ValueError`.
6. Text with nothing usable returns `""`.

Examples: `slugify("Hello, World!") == "hello-world"`, `slugify("Crème brûlée") == "creme-brulee"`,
`slugify("Straße 5") == "strasse-5"`, `slugify("a b c", sep="_") == "a_b_c"`,
`slugify("hello big world", max_len=10) == "hello-big"`.
