"""Hierarchical sheet organization pattern extractor.

Analyzes all parsed projects to extract patterns about how KiCad designers
organize their schematics into hierarchical sheets — naming conventions,
component density per sheet, hierarchy depth, and functional domains.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


# Common functional domain keywords mapped to domain names
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "power": ["power", "psu", "supply", "regulator", "ldo", "dcdc", "dc-dc",
              "buck", "boost", "battery", "charge", "vreg", "voltage"],
    "mcu": ["mcu", "processor", "cpu", "micro", "stm32", "esp32", "rp2040",
            "atmega", "nrf", "controller"],
    "communication": ["comms", "comm", "uart", "spi", "i2c", "usb", "can",
                      "ethernet", "wifi", "bluetooth", "ble", "radio", "rf",
                      "serial", "interface"],
    "motor": ["motor", "stepper", "bldc", "hbridge", "h-bridge",
              "mosfet"],
    "sensor": ["sensor", "imu", "accel", "gyro", "temp", "adc", "analog",
               "input"],
    "display": ["display", "lcd", "oled", "led", "screen", "tft", "epaper",
               "driver"],
    "connector": ["connector", "header", "gpio", "expansion", "debug",
                  "jtag", "swd", "breakout"],
    "memory": ["memory", "flash", "eeprom", "sdcard", "sd", "emmc", "ram",
               "storage"],
    "audio": ["audio", "codec", "dac", "amplifier", "speaker", "microphone"],
    "data_bus": ["data", "bus", "transceiver", "buffer", "level"],
}


def _classify_sheet_domain(sheet_name: str) -> str:
    """Classify a sheet name into a functional domain.

    Returns the best-matching domain or "other".
    """
    name_lower = sheet_name.lower().replace("_", " ").replace("-", " ")

    for domain, keywords in _DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                return domain

    return "other"


def _compute_hierarchy_depth(
    sheet_tree: dict[str, dict],
) -> int:
    """Compute maximum hierarchy depth from sheet_tree.

    Root sheet has depth 0. Each sub-sheet adds 1.
    """
    if not sheet_tree:
        return 0

    # Build parent→children map
    parent_map: dict[str, list[str]] = defaultdict(list)
    root_path = None

    for path, sheet in sheet_tree.items():
        parent = sheet.get("parent_path")
        if parent:
            parent_map[parent].append(path)
        else:
            root_path = path

    if root_path is None:
        # No explicit root found — single sheet
        return 0

    # BFS to find max depth
    max_depth = 0
    queue = [(root_path, 0)]
    while queue:
        current, depth = queue.pop(0)
        max_depth = max(max_depth, depth)
        for child in parent_map.get(current, []):
            queue.append((child, depth + 1))

    return max_depth


def extract_sheet_patterns(parsed_dir: Path) -> dict[str, Any]:
    """Extract sheet organization patterns from all parsed projects.

    Args:
        parsed_dir: Path to data/parsed/ directory.

    Returns:
        Dict with sheet naming patterns, component density, hierarchy stats.
    """
    # Accumulators
    sheet_names: list[str] = []
    domain_counter: Counter = Counter()
    components_per_sheet: list[int] = []
    sheets_per_project: list[int] = []
    hierarchy_depths: list[int] = []
    hierarchical_project_count = 0
    flat_project_count = 0
    total_projects = 0

    # Per-domain component counts
    domain_component_counts: dict[str, list[int]] = defaultdict(list)

    for proj_dir in sorted(parsed_dir.iterdir()):
        if not proj_dir.is_dir():
            continue
        for jf in proj_dir.glob("*.json"):
            try:
                raw = json.loads(jf.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            projects = raw if isinstance(raw, list) else [raw]
            for proj in projects:
                if not isinstance(proj, dict):
                    continue

                sheet_tree = proj.get("sheet_tree", {})
                if not isinstance(sheet_tree, dict):
                    continue

                total_projects += 1
                num_sheets = len(sheet_tree)
                sheets_per_project.append(num_sheets)

                depth = _compute_hierarchy_depth(sheet_tree)
                hierarchy_depths.append(depth)

                if depth > 0:
                    hierarchical_project_count += 1
                else:
                    flat_project_count += 1

                for _path, sheet in sheet_tree.items():
                    if not isinstance(sheet, dict):
                        continue

                    name = sheet.get("sheet_name", "")
                    if not name or name == "root":
                        continue

                    sheet_names.append(name)
                    domain = _classify_sheet_domain(name)
                    domain_counter[domain] += 1

                    comp_count = len(sheet.get("components", []))
                    components_per_sheet.append(comp_count)
                    domain_component_counts[domain].append(comp_count)

    return _build_output(
        sheet_names=sheet_names,
        domain_counter=domain_counter,
        components_per_sheet=components_per_sheet,
        sheets_per_project=sheets_per_project,
        hierarchy_depths=hierarchy_depths,
        hierarchical_project_count=hierarchical_project_count,
        flat_project_count=flat_project_count,
        total_projects=total_projects,
        domain_component_counts=domain_component_counts,
    )


def _build_output(
    *,
    sheet_names: list[str],
    domain_counter: Counter,
    components_per_sheet: list[int],
    sheets_per_project: list[int],
    hierarchy_depths: list[int],
    hierarchical_project_count: int,
    flat_project_count: int,
    total_projects: int,
    domain_component_counts: dict[str, list[int]],
) -> dict[str, Any]:
    """Build final output structure."""
    # Name frequency
    name_counter = Counter(sheet_names)
    top_names = [
        {"name": name, "count": cnt}
        for name, cnt in name_counter.most_common(30)
    ]

    # Domain stats
    domain_stats = {}
    for domain, count in domain_counter.most_common():
        comp_counts = domain_component_counts.get(domain, [])
        avg_comps = sum(comp_counts) / len(comp_counts) if comp_counts else 0
        domain_stats[domain] = {
            "sheet_count": count,
            "avg_components": round(avg_comps, 1),
        }

    # Averages
    avg_sheets = (
        sum(sheets_per_project) / len(sheets_per_project)
        if sheets_per_project
        else 0
    )
    avg_comps = (
        sum(components_per_sheet) / len(components_per_sheet)
        if components_per_sheet
        else 0
    )
    avg_depth = (
        sum(hierarchy_depths) / len(hierarchy_depths)
        if hierarchy_depths
        else 0
    )
    max_depth = max(hierarchy_depths) if hierarchy_depths else 0

    return {
        "top_sheet_names": top_names,
        "domain_distribution": domain_stats,
        "global_stats": {
            "total_projects_analyzed": total_projects,
            "hierarchical_projects": hierarchical_project_count,
            "flat_projects": flat_project_count,
            "avg_sheets_per_project": round(avg_sheets, 1),
            "avg_components_per_sheet": round(avg_comps, 1),
            "avg_hierarchy_depth": round(avg_depth, 2),
            "max_hierarchy_depth": max_depth,
            "total_sheets_analyzed": len(sheet_names),
        },
    }


def run(parsed_dir: Path, output_path: Path) -> dict[str, Any]:
    """Extract patterns and write to JSON file."""
    result = extract_sheet_patterns(parsed_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2))
    return result
