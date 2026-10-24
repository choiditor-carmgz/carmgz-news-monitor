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
