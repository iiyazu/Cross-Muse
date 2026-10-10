## Runs

| run | group | mode | done | hidden (raw) | hidden unaffected | turns | tokens | interv. | inject total | inject median | inject max | modes | rot | declared | review |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| review-ledger-bug2-1/ledger | C | review | - | - | - | 1 | 395,987 | 0 | 0.0% | 0.0% | 0.0% | none:1 | no_rot | 0/9 | hit (fp 1) |
| review-minisql-bug1-1/minisql | C | review | - | - | - | 1 | 350,723 | 0 | 0.0% | 0.0% | 0.0% | none:1 | no_rot | 0/10 | hit (fp 0) |
| review-minisql-bug2-1/minisql | C | review | - | - | - | 1 | 395,614 | 0 | 0.0% | 0.0% | 0.0% | none:1 | no_rot | 0/10 | hit (fp 1) |
| review-pipeline-bug1-1/pipeline | C | review | - | - | - | 1 | 878,187 | 0 | 0.0% | 0.0% | 0.0% | none:1 | no_rot | 0/11 | hit (fp 0) |
| review-pipeline-bug2-1/pipeline | C | review | - | - | - | 1 | 293,552 | 0 | 0.0% | 0.0% | 0.0% | none:1 | no_rot | 0/11 | hit (fp 0) |
| pipeline-C-2/pipeline | C | run | True | pass | 44/44 | 6 | 1,971,498 | 0 | 0.0% | 0.0% | 0.2% | delta:4 none:2 | followed | 10/11 | - |
| ledger-B-2/ledger | B | run | True | fail | 25/25 | 11 | 2,314,934 | 0 | 0.0% | 0.0% | 0.0% | none:11 | followed | 0/9 | - |
| minisql-C-2/minisql | C | run | True | fail | 46/46 | 5 | 1,603,171 | 0 | 0.0% | 0.0% | 0.0% | delta:2 none:3 | followed | 0/10 | - |
| pipeline-A-2/pipeline | A | run | True | pass | 44/44 | 10 | 2,124,328 | 0 | 0.0% | 0.0% | 0.0% | none:10 | followed | 0/11 | - |
| ledger-A-3/ledger | A | run | False | fail | 24/25 | 10 | 2,440,492 | 0 | 0.0% | 0.0% | 0.0% | none:10 | followed | 6/9 | - |

## Groups

| group | runs | completion | turns | tokens (mean) | interv. | inject total | inject max | rot | declared | detection | false pos. |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 2 | 50.0% | 10 | 2282410 | 0 | 0.0% | 0.0% | followed:2 | 33.3% | - | - |
| B | 1 | 100.0% | 11 | 2314934 | 0 | 0.0% | 0.0% | followed:1 | 0.0% | - | - |
| C | 2 | 100.0% | 5.5 | 1,787,334 | 0 | 0.0% | 0.2% | followed:2 | 45.5% | - | - |
| review-C | 5 | - | 1 | 462,813 | 0 | 0.0% | 0.0% | no_rot:5 | 0.0% | 100.0% | 20.0% |
