# Test evidence

Real screenshots captured with [shotlist](https://pypi.org/project/shotlist/)
(`shotlist run` regenerates them). Assertion-level coverage lives in `tests/`
(97 tests: backend contract suite on SQLite and Redis, concurrency race
proofs, input-hardening regressions, FastMCP integration, CLI).

## The use case, end to end

The headline demonstration — a research assistant that remembers across
conversations, and safely merges concurrent edits — has its own captioned
walkthrough in **[use-case.md](use-case.md)**. Every step there runs through
the real MCP tools in a separate process.

## CLI

![mcpstate --help showing the serve subcommand](screenshots/01-cli-help.png)

The installed `mcpstate` console script with the `serve` subcommand.

## Test suite

![full pytest suite green](screenshots/02-test-suite.png)

`python3 -m pytest -q` — the full suite green.
