# GitHub Repository Health Analyzer

A Python command-line tool that gives a quick, readable health overview of any public GitHub repository.

## What it does

- Takes a repository in `owner/repo` form (e.g. `psf/requests`)
- Fetches public repo and contributor data via GitHub's REST API
- Displays:
  - Stars, forks, open issues
  - Primary language
  - Last update time
  - Health warnings
  - Top contributors by commit count
- Supports analyzing multiple repositories in one run, or quitting after a single report

## Health signals

Two intentionally simple, transparent checks:

- **Stale flag** — most recent push is more than 6 months old
- **Low interest flag** — fewer than 10 stars

These are warnings, not quality judgments — a small or quiet project can still be valuable. Missing or malformed timestamps are handled safely instead of crashing the report.

## Design principle: network vs. logic separation

- `fetch_repo_data` and `fetch_contributors` are the **only** functions that call GitHub
- All parsing, health checks, and formatting functions work on plain Python values — no network calls
- This makes the core logic:
  - Deterministic
  - Easy to test with hand-written data
  - Fully independent of GitHub's availability during testing

## Project structure

| File | Purpose |
|---|---|
| `project.py` | CLI entry point, API helpers, validation, parsing, health analysis, report formatting |
| `test_project.py` | Tests for pure functions + mocked HTTP responses for API helpers |
| `preview.html` | Dependency-free interactive dashboard to explore report shape |
| `repo_analyzer_flowchart.mermaid` | Documents the intended user and data flow |
| `requirements.txt` | Runtime and test dependencies |

## Setup

```bash
python -m pip install -r requirements.txt
python project.py
```

**Optional:** set a `GITHUB_TOKEN` environment variable for a higher API rate limit.
Never place a token in source code or commit it to a repository.

## Testing

```bash
pytest -q
```

Covers:
- Normal and incomplete API-shaped data
- Stale vs. healthy repositories
- Low-star warnings
- Invalid dates
- Contributor sorting and malformed entries
- Repository-reference validation
- Successful and not-found API responses

## Key design choices

- **`requests`** for a small, readable HTTP interface
- **Finite timeout** so the CLI never hangs indefinitely
- **`GitHubAPIError`** converts raw API failures into readable CLI messages
- A failed contributor request doesn't discard a successful repo report — it shows a fallback note instead
- Optional token design keeps first-time use simple while offering a path around rate limits

## CS50P final project requirements

- `project.py` is the root-level entry point
- `main()` is present
- More than 3 additional functions have automated tests in the root-level `test_project.py`