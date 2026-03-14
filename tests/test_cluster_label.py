"""Tests for cluster_label module."""

import json
import shutil
import pytest
from pathlib import Path

from src.pipeline.cluster_label import label_cluster, label_all_clusters

CLAUDE_CLI = "/home/mateo/.local/bin/claude"
has_claude = shutil.which(CLAUDE_CLI) is not None or Path(CLAUDE_CLI).exists()


@pytest.mark.skipif(not has_claude, reason="Claude CLI not available")
def test_label_cluster_returns_nonempty_string():
    cluster = {
        "canonical_components": ["Package_SO:TSSOP-16_4.4x5mm_P0.65mm", "C", "R"],
        "example_projects": ["U4", "U5"],
    }
    label = label_cluster(cluster)
    assert isinstance(label, str)
    assert len(label) > 0


@pytest.mark.skipif(not has_claude, reason="Claude CLI not available")
def test_label_all_clusters_produces_output(tmp_path):
    clusters = {
        "total_subcircuits": 1,
        "total_clusters": 1,
        "projects_analyzed": 1,
        "top_clusters": [
            {
                "fingerprint": "abc123",
                "count": 5,
                "label": "",
                "canonical_components": ["Package_SO:TSSOP-16_4.4x5mm_P0.65mm", "C"],
                "example_projects": ["U1"],
            }
        ],
    }
    input_path = tmp_path / "clusters.json"
    output_path = tmp_path / "clusters_labeled.json"
    input_path.write_text(json.dumps(clusters))

    result = label_all_clusters(input_path, output_path)

    assert output_path.exists()
    assert result["top_clusters"][0]["label"]
    assert len(result["top_clusters"][0]["label"]) > 0


@pytest.mark.skipif(not has_claude, reason="Claude CLI not available")
def test_label_all_clusters_caches_results(tmp_path):
    """Re-running should use cached labels, not re-query Claude."""
    clusters = {
        "total_subcircuits": 1,
        "total_clusters": 1,
        "projects_analyzed": 1,
        "top_clusters": [
            {
                "fingerprint": "abc123",
                "count": 5,
                "label": "",
                "canonical_components": ["C", "R"],
                "example_projects": ["U1"],
            }
        ],
    }
    input_path = tmp_path / "clusters.json"
    output_path = tmp_path / "clusters_labeled.json"
    input_path.write_text(json.dumps(clusters))

    # First run — calls Claude
    result1 = label_all_clusters(input_path, output_path)
    label1 = result1["top_clusters"][0]["label"]

    # Second run — should use cache
    result2 = label_all_clusters(input_path, output_path)
    label2 = result2["top_clusters"][0]["label"]

    assert label1 == label2
