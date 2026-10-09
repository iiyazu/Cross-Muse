#!/usr/bin/env bash
# Run scenario/run pairs sequentially: e2e/batch.sh s1-slugify:1 s1-slugify:2 ...
E2E="$(cd "$(dirname "$0")" && pwd)"
for x in "$@"; do
  sc=${x%:*} n=${x#*:}
  echo "=== $sc $n $(date +%T)"
  mkdir -p "$E2E/results"
  bash "$E2E/run.sh" "$sc" "$n" > "$E2E/results/$sc-$n.out" 2>&1 && echo "ok $sc $n" || echo "FAILED $sc $n"
done
echo "=== batch done $(date +%T)"
