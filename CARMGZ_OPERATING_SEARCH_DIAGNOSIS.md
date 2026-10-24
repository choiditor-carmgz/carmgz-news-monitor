# Operating CARMGZ search diagnosis — 2026-10-24

## Finding and limit

The failure was reproduced in the real `operations.run(..., mode='refresh')`
path using a disposable copy of #26's SQLite artifact. No RSS, production state
upload/rotation, or deployment was executed. The copied DB and generated dashboard
are not diagnostic artifacts.

Failing responses were HTTP 200 `text/html`, with `section-list` and
`params['total']`, but without `params['sc_word']` or the requested phrase.
An instrumented failure returned total **19,995**, the archive total, rather than
the **0** returned by the same query in a correctly filtered response.
This is an unfiltered list response, not a successfully searched empty result.
The existing validator correctly rejects it. HTTP 200 must not bypass validation.

The precise upstream reason for dropping the query is **not established**.
There is no evidence sufficient to attribute it to a particular cache, backend,
IP restriction, or preceding RSS collection. In fact, it also happened without RSS.
No URL workaround, retry loop, validation relaxation, or query rewriting is
introduced on the strength of those unproven explanations.

## Code and request comparison

Both paths use `coverage.Checker`, `PolicyClient`/`HttpClient`, `own_url`, and
`parse_search`. The request is GET `/news/articleList.html` with URL-encoded
`sc_area=A`, `view_type=sm`, and `sc_word=<query>`; no date filter or login cookie.
The shared headers are User-Agent `CARMGZNewsMonitor/0.1` and Accept
`application/rss+xml, application/xml, text/plain`.

Direct validation starts from five known phrases. Operations generates phrases
from issue titles and may reuse six-hour DB results. The old validation also
primed search caches before exercising `Checker.check`. Validation now clears
those caches and additionally tests six exact phrases from #25/#26 and the
refresh replay, including the longer quoted phrase containing `우주·의료`.

Known and operating-phrase direct validation responses had Content-Type
`text/html`, unchanged final URLs, no HTTP redirects, a matching query echo,
the main results element and total. Each of the six operating phrases correctly
returned zero at measurement time. Zero is not evidence of noncoverage.

Historical #26 did not retain content type, redirect chain, or structural facts;
these cannot be retroactively recovered from its SQLite artifact. Its two
recorded final URLs retain the intended query and its error is `query_echo_missing`.

## Measurements (no functional request/parser changes between replays)

| Experiment | Issue attempts | Successful issues | Other evidence |
| --- | ---: | ---: | --- |
| Production #26, commit 2173d86 | 1 | 0 | Two query-echo failures, circuit opened |
| GitHub replay 40066973565 | 1 | 0 | Both responses had 67,184 bytes and no query echo |
| GitHub replay 40067164215 | 2 | 1 | First issue passed; next issue returned unfiltered total 19,995 twice |
| GitHub replay 40067363644 | 20 | 20 | 40 queries; 12 empty issues, 8 issues with results, 8 stored match-evidence records |
| Local disposable replay | 20 | 20 | 40 queries; 12 empty issues, 8 issues with results, 8 match-evidence records |

GitHub direct validation 40067164215 and 40067363644: five known articles found,
five generated-query checks matched the expected articles, six operating phrases
validated, and one explicit empty-search control validated. The latter direct
validation took 58.79 seconds. These runs do **not** prove that production's
intermittent failure is resolved, nor that eight evidence records are eight
independently editorially confirmed identical events.

## Changes and safety

- Preserve search URLs, parser rules, queue order, six-hour cache, 20-issue/180-second
  limits, two-error circuit breaker, collection schedule, and all Access code.
- Persist only response length/hash, structural booleans/total, Content-Type,
  explicitly allowed request headers, and redacted redirect metadata per new search.
  Do not persist response HTML, cookies, authorization, unexpected echo text, or
  unexpected redirect values.
- Add a manual diagnostic workflow that downloads a chosen main run's existing
  artifact and calls refresh on a temporary copy. Diagnostics have no write
  permissions, production state artifact name, production state rotation, or deploy.
  Source run ID defaults to #26 for this investigation; select a recent run when
  that original one-day artifact has expired. Re-runs after it expires cannot
  reconstruct the original snapshot from GitHub.
- Controlled original/page=1/percent-space/default-list probes run only in the
  diagnostic script following a failure, with a separate 180-second diagnostic
  checker. They are not production retries or a circuit-breaker bypass.

Local verification: 101 Python tests and 13 Node tests passed. No changes were
made to main, the production DB, scoring, collection, Access, or deployment.

## Follow-up: spacing, repetition, and cache controls

All times below are UTC on 2026-10-24 (add nine hours for Korea). These are
explicit diagnostic requests, not RSS collection or operational retries.

| Experiment | Search responses | HTTP requests including robots | Duration |
| --- | --- | ---: | ---: |
| Local spacing/revalidation, 05:59:50–06:00:48 | 14 valid, 0 invalid | 15 | 60.08 s |
| [GitHub known-first 40068524773](https://github.com/choiditor-carmgz/carmgz-news-monitor/actions/runs/40068524773), 06:01:17–06:01:32 | 4 valid, 3 invalid | 8 | 19.52 s |
| Local exact failed query, 06:03:44–06:03:55 | 3 valid, 0 invalid | 4 | 18.06 s |
| [GitHub exact failed query 40068754705](https://github.com/choiditor-carmgz/carmgz-news-monitor/actions/runs/40068754705), 06:04:45–06:05:09 | 5 valid, 0 invalid (3 probe, 2 known controls) | 6 | 31.55 s |
| [GitHub fresh-first 40068921167](https://github.com/choiditor-carmgz/carmgz-news-monitor/actions/runs/40068921167), 06:07:15–06:07:39 | 2 valid known controls, 3 invalid probes | 6 | 31.79 s |

The local spacing study used six 2-second requests and eight 6-second requests.
Four requests used standard `Cache-Control: no-cache` revalidation; the rest
used normal headers. All query echoes/layouts/totals validated; known article
22736 was found in every known control. Fresh timestamp phrases are zero-result
controls, not claimed editorial candidate searches.

In the GitHub known-first study, the first four requests succeeded. A fresh
phrase then returned the unfiltered list twice, at measured 2-second spacing.
One exact retry after a measured 6 seconds failed too. The study stopped rather
than spend its remaining budget. That same URL subsequently validated locally
and in a new GitHub job, under normal/revalidation/normal headers. The first
normal request was already valid, so revalidation did not cause that recovery.

The final study counterbalanced order: fresh / known / same fresh / known /
same fresh with revalidation, all at measured 6-second spacing. The FIRST search
already failed, both interleaved known controls found article 22736, and all
three fresh-phrase responses failed, including the revalidation control. This
does not support an explanation based solely on a fifth-request threshold or
two-second bursts. It does not establish that every unseen query fails either.

### Cache/proxy evidence versus hypotheses

- All measured responses were HTTP 200 `text/html` with unchanged final URLs
  and zero redirects. Invalid responses were 67,184 bytes, total 19,995, and
  lacked both query echo and requested text; they are never valid search results.
- Every invalid response advertised `no-cache, no-store, must-revalidate`.
  Normal responses lacked those Cache-Control directives. Invalid response
  body hashes and Date values changed between repeats; this was not simple
  byte-for-byte replay of one body by Checker's query cache (which was bypassed).
- Age, Via, ETag, cache HIT/MISS markers, cache keys and backend/server identifiers
  were absent. Vary was `accept-encoding`. No configured http/https/all proxy
  was reported, but that does not exclude transparent intermediaries.
- These facts neither prove an HTTP cache fault nor exclude an intermediary,
  an application cache or different backend behavior. A compliant HTTP cache
  should respect no-store. An absent Age is not proof of origin contact:
  see [RFC 9111 §5.1](https://www.rfc-editor.org/rfc/rfc9111.html#section-5.1).
  No origin/backend trace identifiers or server logs are available to localize
  the fault. Different jobs also differ in time and potentially egress routing;
  those variables were not independently controlled.

### Retry decision and safeguards

A one-time delayed identical GET can fit inside the existing remaining budget,
but the measured six-second retry failed and revalidation also failed during
an actively failing episode. There is no evidence to recommend enabling either
as an operational fix. Production request/parser rules and its two-error circuit
remain unchanged; a future retry would have to consume an existing request slot,
respect the same deadline/robots delay, and not reset or bypass the circuit.

The opt-in study hard-caps ALL HTTP requests, including robots and redirects, at
20 and caps network time at 180 seconds, with no transport retries. Access/server
errors, Retry-After, robots denial, or budget exhaustion stop it. Two consecutive
invalid responses allow only one delayed diagnostic retry; another failure stops
the study. No IP/UA rotation, cookie acquisition, proxy disabling, or access
restriction bypass is used. Only allowlisted header facts and structural hashes
are saved. The new workflow is now manual-only to avoid repeated site probes
on future commits.

The first fresh-first experiment completed its plan and its initial CLI exit
status did not flag invalid rows, although all three rows were correctly marked
`valid:false`. The CLI now returns failure for ANY invalid row, with a regression
test, so a completed diagnostic plan cannot be mistaken for healthy search.
This changes diagnostic reporting only, not the production parser.
