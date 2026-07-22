# Test evidence

Real screenshots captured with [shotlist](https://pypi.org/project/shotlist/)
(`shotlist run` regenerates them). Assertion-level coverage lives in `tests/`
(59 tests: backend contract suite on SQLite and Redis, concurrency race
proofs, FastMCP in-memory integration, CLI).

## CLI

![mcpstate --help showing the serve subcommand](screenshots/01-cli-help.png)

The installed `mcpstate` console script with the `serve` subcommand.

## Test suite

![full pytest suite green](screenshots/02-test-suite.png)

`python3 -m pytest -q` — the full suite green.

## Hand-off sync, demonstrated

![Session 1 mints a research handle and saves state](screenshots/03-session-one-mints.png)

Session 1: a Python process mints a `research` handle and persists state
through the default SQLite backend.

![A separate process lists and resumes the same state - the hand-off](screenshots/04-session-two-resumes.png)

Session 2: a completely separate process lists the user's handles, finds the
research session, and resumes its exact state — the relay-baton hand-off that
is the core promise of the library.
