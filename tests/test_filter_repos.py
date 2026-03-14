"""Tests for the RepoRecon repository filtering pipeline.

Run: cd ~/hardware && python3 -m pytest tests/test_filter_repos.py -v
"""

import json
import sys
from pathlib import Path

import pytest

# Ensure scripts are importable
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from filter_repos import (
    filter_repos,
    repo_dir_name,
    existing_repos,
    load_index,
    DATA_DIR,
    INDEX_PATH,
)


# ---------------------------------------------------------------------------
# Unit tests (no external data needed)
# ---------------------------------------------------------------------------


class TestRepoHelpers:
    """Test helper functions."""

    def test_repo_dir_name(self):
        assert repo_dir_name("owner", "repo") == "owner__repo"

    def test_repo_dir_name_with_hyphens(self):
        assert repo_dir_name("my-org", "my-repo") == "my-org__my-repo"

    def test_existing_repos_empty_dir(self, tmp_path):
        assert existing_repos(tmp_path) == set()

    def test_existing_repos_nonexistent_dir(self, tmp_path):
        missing = tmp_path / "nonexistent"
        assert existing_repos(missing) == set()

    def test_existing_repos_with_dirs(self, tmp_path):
        (tmp_path / "owner1__repo1").mkdir()
        (tmp_path / "owner2__repo2").mkdir()
        (tmp_path / "somefile.txt").touch()  # should be ignored
        result = existing_repos(tmp_path)
        assert result == {"owner1__repo1", "owner2__repo2"}


class TestFilterLogic:
    """Test filter_repos with synthetic data."""

    SAMPLE_REPOS = [
        {
            "repo": "high-stars-recent",
            "owner": "alice",
            "stars": 100,
            "pushed": "2025-06-01T00:00:00Z",
            "url": "https://github.com/alice/high-stars-recent",
            "description": "Popular project",
        },
        {
            "repo": "low-stars",
            "owner": "bob",
            "stars": 1,
            "pushed": "2025-06-01T00:00:00Z",
            "url": "https://github.com/bob/low-stars",
            "description": "Unpopular project",
        },
        {
            "repo": "old-push",
            "owner": "carol",
            "stars": 50,
            "pushed": "2018-01-01T00:00:00Z",
            "url": "https://github.com/carol/old-push",
            "description": "Stale project",
        },
        {
            "repo": "medium-stars",
            "owner": "dave",
            "stars": 10,
            "pushed": "2025-01-01T00:00:00Z",
            "url": "https://github.com/dave/medium-stars",
            "description": "Decent project",
        },
        {
            "repo": "existing-repo",
            "owner": "eve",
            "stars": 200,
            "pushed": "2025-06-01T00:00:00Z",
            "url": "https://github.com/eve/existing-repo",
            "description": "Already cloned",
        },
    ]

    def test_min_stars_filter(self):
        result = filter_repos(self.SAMPLE_REPOS, min_stars=3, max_age_years=10)
        names = {c["full_name"] for c in result}
        assert "bob/low-stars" not in names, "1-star repo should be filtered"
        assert "alice/high-stars-recent" in names

    def test_pushed_age_filter(self):
        result = filter_repos(self.SAMPLE_REPOS, min_stars=1, max_age_years=3)
        names = {c["full_name"] for c in result}
        assert "carol/old-push" not in names, "Old repo should be filtered"
        assert "alice/high-stars-recent" in names

    def test_skip_existing(self):
        skip = {"eve__existing-repo"}
        result = filter_repos(
            self.SAMPLE_REPOS, min_stars=1, max_age_years=10, skip_existing=skip
        )
        names = {c["full_name"] for c in result}
        assert "eve/existing-repo" not in names, "Existing repo should be skipped"

    def test_sorted_by_stars_descending(self):
        result = filter_repos(self.SAMPLE_REPOS, min_stars=3, max_age_years=10)
        stars = [c["stars"] for c in result]
        assert stars == sorted(stars, reverse=True)

    def test_output_fields(self):
        result = filter_repos(self.SAMPLE_REPOS, min_stars=3, max_age_years=10)
        assert len(result) > 0
        c = result[0]
        assert "full_name" in c
        assert "html_url" in c
        assert "stars" in c
        assert "pushed_at" in c
        assert "description" in c

    def test_empty_input(self):
        result = filter_repos([], min_stars=3, max_age_years=3)
        assert result == []

    def test_all_filtered_out(self):
        result = filter_repos(self.SAMPLE_REPOS, min_stars=1000, max_age_years=3)
        assert result == []

    def test_default_filters(self):
        """Default filters: stars >= 3, max_age 3 years."""
        result = filter_repos(self.SAMPLE_REPOS)
        names = {c["full_name"] for c in result}
        # bob/low-stars (1 star) and carol/old-push (2018) should be gone
        assert "bob/low-stars" not in names
        assert "carol/old-push" not in names
        # alice and dave and eve should pass
        assert "alice/high-stars-recent" in names
        assert "dave/medium-stars" in names


# ---------------------------------------------------------------------------
# Integration tests (require real RepoRecon data)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not INDEX_PATH.exists(),
    reason="reporecon_index.json not found",
)
class TestWithRealData:
    """Tests against the actual RepoRecon KiCad index."""

    @pytest.fixture(autouse=True)
    def _load_data(self):
        self.repos = load_index(INDEX_PATH)

    def test_index_loads(self):
        assert len(self.repos) > 40000, (
            f"Expected 40K+ repos, got {len(self.repos)}"
        )

    def test_index_has_required_fields(self):
        r = self.repos[0]
        for field in ("repo", "owner", "stars", "pushed", "url"):
            assert field in r, f"Missing field: {field}"

    def test_filter_produces_candidates(self):
        result = filter_repos(self.repos, min_stars=3, max_age_years=3)
        assert len(result) > 1000, (
            f"Expected 1000+ candidates with stars>=3, got {len(result)}"
        )

    def test_filter_star_threshold(self):
        result = filter_repos(self.repos, min_stars=100, max_age_years=10)
        for c in result:
            assert c["stars"] >= 100

    def test_candidates_sorted(self):
        result = filter_repos(self.repos, min_stars=3, max_age_years=3)
        stars = [c["stars"] for c in result]
        assert stars == sorted(stars, reverse=True)

    def test_candidates_json_written(self):
        """Verify candidates.json exists and is valid JSON."""
        candidates_path = DATA_DIR / "candidates.json"
        if not candidates_path.exists():
            pytest.skip("candidates.json not generated yet")
        with open(candidates_path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) > 0
