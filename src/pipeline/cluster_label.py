"""Label subcircuit clusters using Claude CLI."""

import json
import subprocess
from pathlib import Path

CLAUDE_CLI = "/home/mateo/.local/bin/claude"


def label_cluster(cluster: dict) -> str:
    """Call Claude CLI to generate a short label for a subcircuit cluster."""
    components = ", ".join(cluster["canonical_components"])
    examples = ", ".join(cluster.get("example_projects", [])[:3])
    prompt = (
        f"Given this circuit subcircuit cluster with components: {components}. "
        f"Example reference designators: {examples}. "
        f"What circuit topology is this? Answer with ONLY a short label "
        f"(3-10 words) like 'LDO voltage regulator with bypass caps' or "
        f"'SPI level shifter'. No explanation."
    )
    result = subprocess.run(
        [CLAUDE_CLI, "--print", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed: {result.stderr}")
    return result.stdout.strip()


def label_all_clusters(
    clusters_path: Path,
    output_path: Path,
    *,
    force: bool = False,
) -> dict:
    """Label all top clusters, caching results in *output_path*.

    If *output_path* already exists, previously labeled clusters are kept
    and only unlabeled ones are sent to Claude (unless *force* is True).
    """
    with open(clusters_path) as f:
        data = json.load(f)

    # Load existing labels for caching
    existing: dict[str, str] = {}
    if not force and output_path.exists():
        with open(output_path) as f:
            prev = json.load(f)
        for c in prev.get("top_clusters", []):
            if c.get("label"):
                existing[c["fingerprint"]] = c["label"]

    for cluster in data["top_clusters"]:
        fp = cluster["fingerprint"]
        if fp in existing:
            cluster["label"] = existing[fp]
            continue
        try:
            cluster["label"] = label_cluster(cluster)
        except Exception as exc:
            cluster["label"] = f"ERROR: {exc}"

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    return data


if __name__ == "__main__":
    base = Path(__file__).resolve().parents[2] / "data" / "patterns"
    result = label_all_clusters(
        base / "subcircuit_clusters.json",
        base / "subcircuit_clusters_labeled.json",
    )
    for c in result["top_clusters"]:
        print(f"  {c['count']:3d}x  {c['label']}")
