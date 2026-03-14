#!/usr/bin/env python3
"""Run subcircuit detection on all parsed projects."""
import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "tools"))

from src.pipeline.subcircuits import detect_subcircuits, cluster_subcircuits


def main():
    raw_dir = project_root / "data" / "raw"
    patterns_dir = project_root / "data" / "patterns"
    patterns_dir.mkdir(exist_ok=True)

    all_subcircuits = []
    project_stats = []

    projects = sorted(p for p in raw_dir.iterdir() if p.is_dir())

    for i, project_dir in enumerate(projects, 1):
        name = project_dir.name
        print(f"[{i}/{len(projects)}] {name}...", end=" ", flush=True)

        try:
            # detect_subcircuits takes a Path to a .kicad_pcb file
            pcb_files = sorted(project_dir.rglob("*.kicad_pcb"))
            if not pcb_files:
                print("no PCB files")
                project_stats.append({"name": name, "subcircuits": 0, "note": "no PCB"})
                continue

            project_subs = []
            for pcb_file in pcb_files:
                try:
                    subs = detect_subcircuits(pcb_file)
                    project_subs.extend(subs)
                except Exception as e:
                    print(f"(pcb error: {pcb_file.name}: {e})", end=" ")

            all_subcircuits.extend(project_subs)
            print(f"{len(project_subs)} subcircuits")
            project_stats.append({"name": name, "subcircuits": len(project_subs)})

        except Exception as e:
            print(f"FAILED: {e}")
            project_stats.append({"name": name, "error": str(e)[:200]})

    # Cluster all subcircuits
    clusters = cluster_subcircuits(all_subcircuits)

    # Save results
    summary = {
        "total_subcircuits": len(all_subcircuits),
        "total_clusters": len(clusters),
        "projects_analyzed": len(project_stats),
        "top_clusters": [],
    }

    # Sort clusters by size
    clusters.sort(key=lambda c: c.count, reverse=True)
    for cluster in clusters[:30]:
        summary["top_clusters"].append({
            "fingerprint": cluster.fingerprint,
            "count": cluster.count,
            "label": cluster.label,
            "canonical_components": cluster.canonical_components,
            "example_projects": [s.center_ref for s in cluster.instances[:3]],
        })

    with open(patterns_dir / "subcircuit_clusters.json", "w") as f:
        json.dump(summary, f, indent=2)

    # Save per-project stats
    with open(patterns_dir / "subcircuit_stats.json", "w") as f:
        json.dump(project_stats, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Total: {len(all_subcircuits)} subcircuits in {len(clusters)} clusters")
    print("\nTop 10 clusters:")
    for c in clusters[:10]:
        print(f"  [{c.count}x] {c.label or 'unlabeled'} — {', '.join(c.canonical_components[:5])}")


if __name__ == "__main__":
    main()
