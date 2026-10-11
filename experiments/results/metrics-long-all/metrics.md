## Runs

| run | group | mode | done | hidden (raw) | hidden unaffected | turns | tokens | interv. | inject total | inject median | inject max | modes | rot | declared | review |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| long-L-1/ledger | L | run | True | pass | - | 2 | 222,700 | 0 | 0.0% | 0.0% | 0.0% | none:2 | not_injected | 5/9 | - |
| long-L-1/minisql | L | run | True | fail | 46/46 | 7 | 1,605,498 | 0 | 0.1% | 0.1% | 0.3% | delta:5 none:1 snapshot:1 | followed | 10/10 | - |
| long-L-1/pipeline | L | run | True | pass | 44/44 | 7 | 2,875,792 | 0 | 0.0% | 0.0% | 0.1% | delta:6 none:1 | followed | 9/11 | - |
| long-L-2/ledger | L | run | True | pass | - | 1 | 186,059 | 0 | 0.0% | 0.0% | 0.0% | none:1 | not_injected | 0/9 | - |
| long-L-3/ledger | L | run | False | fail | 24/25 | 10 | 3,149,427 | 0 | 0.0% | 0.0% | 0.3% | delta:6 none:4 | followed | 6/9 | - |
| long-L-3/minisql | L | run | False | fail | 45/46 | 8 | 4,616,427 | 0 | 0.0% | 0.0% | 0.1% | delta:7 none:1 | followed | 6/10 | - |
| long-L-3/pipeline | L | run | True | pass | 44/44 | 8 | 6,135,841 | 0 | 0.0% | 0.0% | 0.1% | delta:8 | followed | 7/11 | - |
| long-L-mo-1/ledger | L | run | True | fail | 25/25 | 9 | 2,676,777 | 0 | 0.0% | 0.0% | 0.2% | delta:5 none:4 | followed | 6/9 | - |
| long-L-mo-1/minisql | L | run | False | fail | 45/46 | 9 | 4,644,644 | 0 | 0.0% | 0.0% | 0.1% | delta:7 none:2 | followed | 10/10 | - |
| long-L-mo-1/pipeline | L | run | True | pass | 44/44 | 9 | 6,809,349 | 0 | 0.0% | 0.0% | 0.1% | delta:7 none:2 | followed | 9/11 | - |
| long-L-mo-2/ledger | L | run | False | fail | 24/25 | 10 | 2,475,644 | 0 | 0.0% | 0.0% | 0.4% | delta:5 none:5 | followed | 8/9 | - |
| long-L-mo-2/minisql | L | run | False | fail | 45/46 | 10 | 3,202,052 | 0 | 0.0% | 0.0% | 0.2% | delta:7 none:3 | followed | 10/10 | - |
| long-L-mo-2/pipeline | L | run | True | pass | 44/44 | 6 | 3,567,473 | 0 | 0.0% | 0.0% | 0.1% | delta:6 | followed | 9/11 | - |

## Groups

| group | runs | completion | turns | tokens (mean) | interv. | inject total | inject max | rot | declared | detection | false pos. |
|---|---|---|---|---|---|---|---|---|---|---|---|
| L | 13 | 61.5% | 7.38 | 3,243,668 | 0 | 0.0% | 0.4% | followed:11 not_injected:2 | 72.8% | - | - |

## MemoryOS (ops; unattended: proposals are never confirmed)

| run | recall calls | recall ms median | curate calls | curate ms median | failures | usage total | proposals | conflicts |
|---|---|---|---|---|---|---|---|---|
| long-L-mo-1/ledger | 0 | - | 1 | 17634 | 0 | completion_tokens=4660, prompt_tokens=2297, total_tokens=6957 (n=1) | 0 | 0 |
| long-L-mo-1/minisql | 0 | - | 3 | 17634 | 0 | completion_tokens=16638, prompt_tokens=7056, total_tokens=23694 (n=3) | 0 | 0 |
| long-L-mo-1/pipeline | 0 | - | 5 | 17634 | 0 | completion_tokens=22748, prompt_tokens=11881, total_tokens=34629 (n=5) | 0 | 0 |
| long-L-mo-2/ledger | 0 | - | 1 | 59529 | 0 | completion_tokens=11170, prompt_tokens=2212, total_tokens=13382 (n=1) | 4 | 0 |
| long-L-mo-2/minisql | 0 | - | 3 | 27087 | 0 | completion_tokens=17439, prompt_tokens=6909, total_tokens=24348 (n=3) | 1 | 0 |
| long-L-mo-2/pipeline | 0 | - | 4 | 19,523 | 0 | completion_tokens=18173, prompt_tokens=9213, total_tokens=27386 (n=4) | 0 | 0 |
