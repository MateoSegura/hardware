"""Unified pipeline entry point — parses a complete KiCad project directory.

Ties together: discovery -> hierarchy walking -> board parsing -> net tracing.

Usage:
    python3 -m src.pipeline.parse_project data/raw/project_name/
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from .board import parse_board
from .discovery import discover
from .export import export_project
from .hierarchy import walk_hierarchy
from .models import ParsedProject
from .nets import trace_nets

logger = logging.getLogger(__name__)


def parse_project(project_dir: Path) -> list[ParsedProject]:
    """Parse all KiCad design units in a project directory.

    Runs: discovery -> hierarchy walking -> board parsing -> net tracing.

    Args:
        project_dir: Path to a directory containing KiCad files.

    Returns:
        List of ParsedProject objects, one per discovered design unit.
    """
    project_dir = project_dir.resolve()
    units = discover(project_dir)

    if not units:
        logger.warning("No design units found in %s", project_dir)
        return []

    results: list[ParsedProject] = []

    for unit in units:
        sheet_tree = {}
        root_sheet = None
        all_components = []
        all_nets = {}
        board = None

        # Hierarchy walking (if schematic exists)
        if unit.root_schematic and unit.root_schematic.is_file():
            try:
                sheet_tree = walk_hierarchy(unit.root_schematic)
            except Exception as e:
                logger.warning(
                    "Failed to walk hierarchy for %s: %s", unit.name, e
                )
                sheet_tree = {}

            if sheet_tree:
                root_key = str(unit.root_schematic.resolve())
                root_sheet = sheet_tree.get(root_key)

                # Flatten all components
                for sheet in sheet_tree.values():
                    all_components.extend(sheet.components)

                # Trace nets
                try:
                    all_nets = trace_nets(sheet_tree)
                except Exception as e:
                    logger.warning(
                        "Failed to trace nets for %s: %s", unit.name, e
                    )

        # Board parsing (if PCB exists)
        if unit.pcb_file and unit.pcb_file.is_file():
            try:
                board = parse_board(unit.pcb_file)
            except Exception as e:
                logger.warning(
                    "Failed to parse board for %s: %s", unit.name, e
                )

        # Compute stats
        non_power = [c for c in all_components if not c.is_power]
        unique_values = {(c.lib_id, c.value) for c in non_power}
        power_nets = {
            name: info
            for name, info in all_nets.items()
            if info.net_type == "power"
        }

        stats = {
            "total_components": len(all_components),
            "non_power_components": len(non_power),
            "unique_parts": len(unique_values),
            "power_symbols": len(all_components) - len(non_power),
            "total_sheets": len(sheet_tree),
            "has_hierarchy": unit.has_hierarchy,
            "total_nets": len(all_nets),
            "power_nets": len(power_nets),
            "signal_nets": len(all_nets) - len(power_nets),
            "has_pcb": board is not None,
            "pcb_layers": len(board.layers) if board else 0,
            "pcb_footprints": len(board.footprints) if board else 0,
            "pcb_tracks": board.track_count if board else 0,
            "pcb_vias": board.via_count if board else 0,
            "kicad_version": unit.kicad_version,
        }

        results.append(ParsedProject(
            design_unit=unit,
            sheet_tree=sheet_tree,
            root_sheet=root_sheet,
            board=board,
            all_components=all_components,
            all_nets=all_nets,
            stats=stats,
        ))

    return results


def parse_single(project_dir: Path) -> ParsedProject | None:
    """Parse the first (or only) design unit in a project directory.

    Convenience wrapper for projects with a single design unit.
    """
    projects = parse_project(project_dir)
    return projects[0] if projects else None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python3 -m src.pipeline.parse_project <project_dir> [--output <path>]")
        sys.exit(1)

    project_dir = Path(sys.argv[1])
    output_path = None
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_path = Path(sys.argv[idx + 1])

    projects = parse_project(project_dir)

    for proj in projects:
        json_str = export_project(proj)
        if output_path:
            out_file = output_path / f"{proj.design_unit.name}.json"
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(json_str)
            print(f"Wrote {out_file}")
        else:
            print(json_str)
