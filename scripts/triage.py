#!/usr/bin/env python3
"""Triage scorer for KiCad projects.

Scores projects by complexity using fast regex on raw S-expression text.
No full parse needed — runs in <1 second per project.

Usage:
    python3 scripts/triage.py data/raw/
    python3 scripts/triage.py data/raw/antmicro__jetson-nano-baseboard/
"""

import json
import re
import sys
from pathlib import Path


def find_kicad_files(project_dir: Path) -> tuple[list[Path], list[Path]]:
    """Find all .kicad_sch and .kicad_pcb files in a project."""
    sch_files = sorted(project_dir.rglob("*.kicad_sch"))
    pcb_files = sorted(project_dir.rglob("*.kicad_pcb"))
    return sch_files, pcb_files


def score_project(project_dir: Path) -> dict:
    """Score a project's complexity from raw file content."""
    sch_files, pcb_files = find_kicad_files(project_dir)

    if not sch_files and not pcb_files:
        return {"project": project_dir.name, "error": "no KiCad files found"}

    result = {
        "project": project_dir.name,
        "sch_file_count": len(sch_files),
        "pcb_file_count": len(pcb_files),
    }

    # ── Schematic analysis ───────────────────────────────────────────────────
    all_sch_text = ""
    for f in sch_files:
        try:
            all_sch_text += f.read_text(errors="replace")
        except Exception:
            pass

    if all_sch_text:
        # Component instances
        result["component_count"] = all_sch_text.count('(symbol (lib_id')

        # Unique lib_ids (unique part types)
        lib_ids = set(re.findall(r'\(lib_id "([^"]+)"\)', all_sch_text))
        result["unique_parts"] = len(lib_ids)

        # Hierarchical sheets
        result["hier_sheets"] = all_sch_text.count("(sheet (at")

        # Net labels (all types)
        local_labels = set(re.findall(r'\(label "([^"]+)"', all_sch_text))
        global_labels = set(re.findall(r'\(global_label "([^"]+)"', all_sch_text))
        hier_labels = set(re.findall(r'\(hierarchical_label "([^"]+)"', all_sch_text))
        all_nets = local_labels | global_labels | hier_labels
        result["unique_nets"] = len(all_nets)
        result["global_labels"] = len(global_labels)
        result["hier_labels"] = len(hier_labels)

        # Power rail detection
        power_pattern = re.compile(
            r'"([+-]?\d*V?\d*[._]?\d*(?:VCC|VDD|VSS|GND|VBUS|VBAT|VIN|AVDD|DVDD|VREF|V3V3|3V3|5V|1V8|1V2|12V|AGND|DGND)[^"]*)"',
            re.IGNORECASE,
        )
        power_nets = set(power_pattern.findall(all_sch_text))
        result["power_rails"] = len(power_nets)
        result["power_rail_names"] = sorted(power_nets)[:20]  # cap at 20 for readability

        # Differential pairs
        diff_patterns = [
            r'"[A-Z_]+_[PN]"',          # SIGNAL_P / SIGNAL_N
            r'"[A-Z_]+[DP][+-]"',        # D+ / D-
            r'"USB_D[PM]"',              # USB_DP / USB_DM
            r'"ETH_TX[PN]"',             # Ethernet TX+/TX-
        ]
        result["has_diff_pairs"] = any(
            re.search(p, all_sch_text) for p in diff_patterns
        )

        # MPN presence
        result["has_mpn"] = bool(
            re.search(r'"(?:MPN|Manufacturer_Part|Mfr_PN)"', all_sch_text)
        )

        # Custom local library
        sym_lib_table = project_dir / "sym-lib-table"
        result["has_custom_lib"] = (
            sym_lib_table.exists()
            and "${KIPRJMOD}" in sym_lib_table.read_text(errors="replace")
        )

        # KiCad version from first file
        version_match = re.search(r'\(version (\d+)\)', all_sch_text)
        result["kicad_version"] = int(version_match.group(1)) if version_match else None

    # ── PCB analysis ─────────────────────────────────────────────────────────
    if pcb_files:
        pcb_text = ""
        try:
            pcb_text = pcb_files[0].read_text(errors="replace")
        except Exception:
            pass

        if pcb_text:
            # Layer count (signal + power layers)
            layers = re.findall(r'\(\d+ "([^"]+)" (signal|power)', pcb_text)
            result["layer_count"] = len(layers)
            result["layer_names"] = [l[0] for l in layers]

            # Track and via counts
            result["track_count"] = pcb_text.count("(segment ")
            result["via_count"] = pcb_text.count("(via ")

            # Footprint count
            result["footprint_count"] = pcb_text.count("(footprint ")

            # Net class count
            net_classes = set(re.findall(r'\(netclass "([^"]+)"', pcb_text))
            result["net_classes"] = len(net_classes)
            result["net_class_names"] = sorted(net_classes)

            # Zone count (copper pours)
            result["zone_count"] = pcb_text.count("(zone ")

    # ── Composite score ──────────────────────────────────────────────────────
    score = 0.0
    nets = result.get("unique_nets", 0)
    score += min(nets / 50, 5.0)                                    # 0-5 pts

    rails = result.get("power_rails", 0)
    score += min(rails / 2, 3.0)                                    # 0-3 pts

    layers = result.get("layer_count", 2)
    score += min((layers - 2) / 2, 2.0)                             # 0-2 pts

    sheets = result.get("hier_sheets", 0)
    score += min(sheets / 2, 2.0)                                   # 0-2 pts

    unique = result.get("unique_parts", 0)
    score += min(unique / 10, 3.0)                                  # 0-3 pts

    score += 1.0 if result.get("has_diff_pairs") else 0.0           # 0-1 pts
    score += 1.0 if result.get("has_custom_lib") else 0.0           # 0-1 pts
    score += 1.0 if result.get("has_mpn") else 0.0                  # 0-1 pts
    score += 1.0 if result.get("net_classes", 0) > 1 else 0.0      # 0-1 pts
    score += 1.0 if result.get("component_count", 0) > 100 else 0.0  # 0-1 pts

    result["complexity_score"] = round(score, 1)
    result["max_possible_score"] = 22.0

    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/triage.py <project_dir_or_parent_dir>")
        sys.exit(1)

    target = Path(sys.argv[1])

    if not target.exists():
        print(f"Error: {target} does not exist")
        sys.exit(1)

    # Check if target is a single project or a directory of projects
    sch_files, pcb_files = find_kicad_files(target)
    if sch_files or pcb_files:
        # Single project
        result = score_project(target)
        print(json.dumps(result, indent=2))
    else:
        # Directory of projects
        results = []
        for child in sorted(target.iterdir()):
            if child.is_dir():
                result = score_project(child)
                results.append(result)

        # Sort by complexity score
        results.sort(key=lambda r: r.get("complexity_score", 0), reverse=True)

        print(json.dumps(results, indent=2))

        # Summary table
        print("\n--- COMPLEXITY RANKING ---")
        print(f"{'#':<3} {'Score':<7} {'Nets':<6} {'Parts':<6} {'Layers':<7} {'Sheets':<7} {'Project'}")
        print("-" * 80)
        for i, r in enumerate(results, 1):
            if "error" in r:
                print(f"{i:<3} {'ERR':<7} {'-':<6} {'-':<6} {'-':<7} {'-':<7} {r['project']}")
            else:
                print(
                    f"{i:<3} "
                    f"{r.get('complexity_score', 0):<7.1f} "
                    f"{r.get('unique_nets', 0):<6} "
                    f"{r.get('unique_parts', 0):<6} "
                    f"{r.get('layer_count', '?'):<7} "
                    f"{r.get('hier_sheets', 0):<7} "
                    f"{r['project']}"
                )


if __name__ == "__main__":
    main()
