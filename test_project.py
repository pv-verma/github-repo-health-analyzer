from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
import requests

from project import (
    GitHubAPIError,
    check_repo_health,
    fetch_contributors,
    fetch_repo_data,
    format_contributor_list,
    parse_repo_reference,
    parse_repo_stats,
)


def test_parse_repo_stats():
    raw_data = {
        "name": "requests",
        "stargazers_count": 50000,
        "forks_count": 9000,
        "open_issues_count": 100,
        "language": "Python",
        "pushed_at": "2026-08-01T12:00:00Z",
    }

    stats = parse_repo_stats(raw_data)

    assert stats == {
        "name": "requests",
        "stars": 50000,
        "forks": 9000,
        "open_issues": 100,
        "language": "Python",
        "last_updated": "2026-08-01T12:00:00Z",
    }


def test_parse_repo_stats_missing_fields():
    stats = parse_repo_stats({"name": "small-project", "stargazers_count": None})

    assert stats["name"] == "small-project"
    assert stats["stars"] == 0
    assert stats["forks"] == 0
    assert stats["open_issues"] == 0
    assert stats["language"] == "Unknown"
    assert stats["last_updated"] is None


def test_parse_repo_stats_converts_invalid_counts_to_zero():
    stats = parse_repo_stats(
        {
            "name": "repo",
            "stargazers_count": "not a number",
            "forks_count": -3,
            "open_issues_count": True,
        }
    )

    assert stats["stars"] == 0
    assert stats["forks"] == 0
    assert stats["open_issues"] == 0


def test_check_repo_health_flags_stale_repo():
    stats = {
        "stars": 100,
        "last_updated": "2020-01-01T12:00:00Z",
    }

    assert "No commits in 6+ months" in check_repo_health(stats)


def test_check_repo_health_flags_low_stars():
    stats = {
        "stars": 0,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }

    assert check_repo_health(stats) == ["Low community interest (few stars)"]


def test_check_repo_health_no_warnings_for_healthy_repo():
    stats = {
        "stars": 100,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }

    assert check_repo_health(stats) == []


def test_check_repo_health_ignores_invalid_date_without_crashing():
    stats = {"stars": 100, "last_updated": "not-a-date"}

    assert check_repo_health(stats) == []


def test_format_contributor_list_sorts_by_commits():
    raw = [
        {"login": "alice", "contributions": 10},
        {"login": "bob", "contributions": 50},
        {"login": "carol", "contributions": 20},
    ]

    assert format_contributor_list(raw) == [("bob", 50), ("carol", 20), ("alice", 10)]


def test_format_contributor_list_uses_deterministic_tie_breaking():
    raw = [
        {"login": "zoe", "contributions": 10},
        {"login": "Alice", "contributions": 10},
    ]

    assert format_contributor_list(raw) == [("Alice", 10), ("zoe", 10)]


def test_format_contributor_list_skips_malformed_records():
    raw = [
        {"login": "valid", "contributions": 3},
        {"login": "missing-count"},
        {"contributions": 8},
        {"login": "negative", "contributions": -1},
        "not a dictionary",
    ]

    assert format_contributor_list(raw) == [("valid", 3)]


def test_format_contributor_list_empty():
    assert format_contributor_list([]) == []
    assert format_contributor_list(None) == []


@pytest.mark.parametrize(
    "value, expected",
    [
        ("psf/requests", ("psf", "requests")),
        ("https://github.com/psf/requests/", ("psf", "requests")),
    ],
)
def test_parse_repo_reference(value, expected):
    assert parse_repo_reference(value) == expected


def test_parse_repo_reference_rejects_invalid_value():
    with pytest.raises(ValueError, match="owner/repo"):
        parse_repo_reference("requests")


def test_fetch_repo_data_returns_json_and_uses_timeout():
    response = Mock()
    response.json.return_value = {"name": "requests"}

    with patch("project.requests.get", return_value=response) as get:
        assert fetch_repo_data("psf", "requests") == {"name": "requests"}

    get.assert_called_once()
    assert get.call_args.kwargs["timeout"] == 10
    assert get.call_args.kwargs["headers"]["User-Agent"] == "github-repository-health-analyzer"


def test_fetch_repo_data_translates_not_found_error():
    response = Mock(status_code=404)
    response.raise_for_status.side_effect = requests.HTTPError(response=response)

    with patch("project.requests.get", return_value=response):
        with pytest.raises(GitHubAPIError, match="Repository not found"):
            fetch_repo_data("psf", "missing")


def test_fetch_contributors_returns_list():
    response = Mock()
    response.json.return_value = [{"login": "alice", "contributions": 4}]

    with patch("project.requests.get", return_value=response):
        assert fetch_contributors("psf", "requests") == [{"login": "alice", "contributions": 4}]