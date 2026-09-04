"""Command-line GitHub repository health analyzer."""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests


GITHUB_API_BASE = "https://api.github.com"
REQUEST_TIMEOUT = 10
STALE_AFTER_DAYS = 180
LOW_STAR_THRESHOLD = 10
TOP_CONTRIBUTORS = 5
REPORT_WIDTH = 50
REPOSITORY_PART_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class GitHubAPIError(RuntimeError):
    """An actionable error raised while communicating with GitHub."""


def _repository_path(owner: str, repo: str) -> tuple[str, str]:
    """Validate and normalize repository path components."""

    owner = owner.strip()
    repo = repo.strip()
    if not owner or not repo:
        raise ValueError("Both an owner and repository name are required.")
    if not REPOSITORY_PART_PATTERN.fullmatch(owner) or not REPOSITORY_PART_PATTERN.fullmatch(repo):
        raise ValueError("Owner and repository names may only contain letters, numbers, '.', '_' and '-'.")
    return owner, repo


def parse_repo_reference(value: str) -> tuple[str, str]:
    """Parse an ``owner/repo`` value or a GitHub repository URL."""

    reference = value.strip()
    if reference.startswith("https://github.com/") or reference.startswith("http://github.com/"):
        reference = reference.split("github.com/", 1)[1]
    reference = reference.strip("/")
    parts = reference.split("/")
    if len(parts) != 2:
        raise ValueError("Enter a repository as owner/repo, for example psf/requests.")
    return _repository_path(parts[0], parts[1])


def _request_headers() -> dict[str, str]:
    """Build headers, adding an optional GitHub token when configured."""

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-repository-health-analyzer",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    return headers


def _get_json(endpoint: str):
    """Fetch and decode one GitHub API response with user-friendly errors."""

    try:
        response = requests.get(
            f"{GITHUB_API_BASE}{endpoint}",
            headers=_request_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.HTTPError as error:
        status_code = getattr(error.response, "status_code", None) or getattr(response, "status_code", None)
        if status_code == 404:
            message = "Repository not found. Check the owner/repository name and try again."
        elif status_code == 403:
            message = "GitHub rate limit reached. Set GITHUB_TOKEN and try again later."
        else:
            message = f"GitHub returned HTTP {status_code or 'an error'}."
        raise GitHubAPIError(message) from error
    except requests.Timeout as error:
        raise GitHubAPIError("The GitHub request timed out. Check your connection and try again.") from error
    except requests.RequestException as error:
        raise GitHubAPIError("Unable to reach GitHub. Check your connection and try again.") from error

    try:
        return response.json()
    except ValueError as error:
        raise GitHubAPIError("GitHub returned an invalid JSON response.") from error


def fetch_repo_data(owner: str, repo: str) -> dict:
    """Return raw repository data from GitHub's repository endpoint."""

    owner, repo = _repository_path(owner, repo)
    data = _get_json(f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}")
    if not isinstance(data, dict):
        raise GitHubAPIError("GitHub returned an unexpected repository response.")
    return data


def _nonnegative_int(value, default: int = 0) -> int:
    """Convert a count to a non-negative integer, using a safe default."""

    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(number, 0)


def parse_repo_stats(raw_data: dict) -> dict:
    """Extract stable, display-ready statistics from a GitHub response."""

    if not isinstance(raw_data, dict):
        raise ValueError("Repository data must be a dictionary.")
    return {
        "name": raw_data.get("name") or "Unknown repository",
        "stars": _nonnegative_int(raw_data.get("stargazers_count")),
        "forks": _nonnegative_int(raw_data.get("forks_count")),
        "open_issues": _nonnegative_int(raw_data.get("open_issues_count")),
        "language": raw_data.get("language") or "Unknown",
        "last_updated": raw_data.get("pushed_at") or raw_data.get("updated_at"),
    }


def _parse_github_datetime(value: str | None) -> datetime | None:
    """Parse an ISO-8601 GitHub timestamp as an aware UTC datetime."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def check_repo_health(stats: dict) -> list[str]:
    """Return warnings for stale activity or unusually low star counts."""

    if not isinstance(stats, dict):
        raise ValueError("Repository stats must be a dictionary.")

    warnings = []
    last_updated = _parse_github_datetime(stats.get("last_updated"))
    if last_updated and datetime.now(timezone.utc) - last_updated > timedelta(days=STALE_AFTER_DAYS):
        warnings.append("No commits in 6+ months")

    stars = _nonnegative_int(stats.get("stars"))
    if stars < LOW_STAR_THRESHOLD:
        warnings.append("Low community interest (few stars)")
    return warnings


def fetch_contributors(owner: str, repo: str) -> list[dict]:
    """Return raw contributor data from GitHub's contributors endpoint."""

    owner, repo = _repository_path(owner, repo)
    data = _get_json(f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/contributors")
    if not isinstance(data, list):
        raise GitHubAPIError("GitHub returned an unexpected contributors response.")
    return data


def format_contributor_list(contributors_raw: list[dict]) -> list[tuple[str, int]]:
    """Return valid contributors as login/count tuples sorted by contributions."""

    if not isinstance(contributors_raw, list):
        return []

    formatted = []
    for contributor in contributors_raw:
        if not isinstance(contributor, dict):
            continue
        login = contributor.get("login")
        contributions = contributor.get("contributions")
        if not isinstance(login, str) or not login.strip() or isinstance(contributions, bool):
            continue
        try:
            contributions = int(contributions)
        except (TypeError, ValueError):
            continue
        if contributions < 0:
            continue
        formatted.append((login.strip(), contributions))

    return sorted(formatted, key=lambda item: (-item[1], item[0].casefold()))


def _format_report(stats: dict, warnings: list[str], contributors: list[tuple[str, int]]) -> str:
    """Build the human-readable repository report."""

    lines = [
        "\n" + "=" * REPORT_WIDTH,
        f"Repository: {stats['name']}",
        "=" * REPORT_WIDTH,
        f"Stars:       {stats['stars']:,}",
        f"Forks:       {stats['forks']:,}",
        f"Open issues: {stats['open_issues']:,}",
        f"Language:    {stats['language']}",
        f"Last update: {stats['last_updated'] or 'Unknown'}",
        "",
        "Health: " + ("Healthy" if not warnings else "Warnings"),
    ]
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- No immediate warning signs detected.")

    lines.extend(["", "Top contributors:"])
    if contributors:
        lines.extend(f"{index}. {login} ({count:,} contributions)" for index, (login, count) in enumerate(contributors[:TOP_CONTRIBUTORS], 1))
    else:
        lines.append("- No contributor data available.")
    return "\n".join(lines)


def main() -> None:
    """Run the interactive repository analyzer."""

    print("GitHub Repository Health Analyzer")
    print("Enter a public repository as owner/repo (or type q to quit).")

    while True:
        try:
            reference = input("\nRepository: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            return

        if reference.lower() in {"q", "quit", "exit"}:
            print("come back soon!")
            return

        try:
            owner, repo = parse_repo_reference(reference)
            raw_data = fetch_repo_data(owner, repo)
        except ValueError as error:
            print(f"Input error: {error}")
            continue
        except GitHubAPIError as error:
            print(f"API error: {error}")
            continue

        stats = parse_repo_stats(raw_data)
        warnings = check_repo_health(stats)
        contributor_note = None
        try:
            contributors_raw = fetch_contributors(owner, repo)
            contributors = format_contributor_list(contributors_raw)
        except GitHubAPIError as error:
            contributors = []
            contributor_note = str(error)

        print(_format_report(stats, warnings, contributors))
        if contributor_note:
            print(f"\nContributor note: {contributor_note}")

        try:
            again = input("\nCheck another repository? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nThat's a wrap. Now go build something great.")
            return
        if again not in {"y", "yes"}:
            print("That's a wrap. Now go build something great.")
            return


if __name__ == "__main__":
    main()