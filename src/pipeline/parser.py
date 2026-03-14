#!/usr/bin/env python3
"""KiCad project parser — extracts normalized JSON from .kicad_sch + .kicad_pcb files.

Uses kiutils as the primary parsing library. Handles hierarchical schematics,
multi-unit symbols, and net tracing across sheets.

Usage:
    from src.pipeline.parser import parse_project
    result = parse_project(Path("data/raw/hackrf/"))
"""

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from kiutils.board import Board
from kiutils.schematic import Schematic


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class PinInfo:
    name: str = ""
    net: str = ""
    pin_type: str = ""
    number: str = ""


@dataclass
class ComponentInfo:
    ref: str = ""
    lib_id: str = ""
    value: str = ""
    footprint: str = ""
    sheet: str = ""
    mpn: str = ""
    pin_count: int = 0
    pins: dict[str, PinInfo] = field(default_factory=dict)


@dataclass
class SheetInfo:
    name: str = ""
    file: str = ""
    parent: str = ""
    uuid: str = ""


@dataclass
class NetInfo:
    net_type: str = ""  # "power", "signal"
    scope: str = ""  # "global", "local", "hierarchical"
    pins: list[str] = field(default_factory=list)


@dataclass
class BoardInfo:
    layers: int = 0
    layer_names: list[str] = field(default_factory=list)
    footprint_count: int = 0
    track_count: int = 0
    via_count: int = 0
    zone_count: int = 0
    net_classes: list[str] = field(default_factory=list)


@dataclass
class ProjectData:
    meta: dict = field(default_factory=dict)
    hierarchy: dict = field(default_factory=dict)
    components: list[ComponentInfo] = field(default_factory=list)
    nets: dict[str, NetInfo] = field(default_factory=dict)
    board: BoardInfo | None = None
    stats: dict = field(default_factory=dict)


# ── Schematic parsing ────────────────────────────────────────────────────────


def _get_property(symbol, name: str) -> str:
    """Extract a property value from a kiutils symbol."""
    for prop in getattr(symbol, "properties", []):
        if prop.key == name:
            return prop.value or ""
    return ""


def _parse_schematic_sheet(
    sch_path: Path, sheet_name: str, project_dir: Path
) -> tuple[list[ComponentInfo], list[SheetInfo], dict[str, str]]:
    """Parse a single .kicad_sch file, returning components, sub-sheets, and labels."""
    components = []
    sub_sheets = []
    labels = {}  # name → type (local/global/hierarchical)

    try:
        sch = Schematic.from_file(str(sch_path))
    except Exception as e:
        print(f"  Warning: failed to parse {sch_path}: {e}")
        return components, sub_sheets, labels

    # Extract components
    for sym in sch.schematicSymbols:
        ref = _get_property(sym, "Reference")
        lib_id = sym.libId or ""
        value = _get_property(sym, "Value")
        footprint = _get_property(sym, "Footprint")
        mpn = _get_property(sym, "MPN") or _get_property(sym, "Mfr_PN")

        # Count pins
        pin_count = len(getattr(sym, "pins", []))

        comp = ComponentInfo(
            ref=ref,
            lib_id=lib_id,
            value=value,
            footprint=footprint,
            sheet=sheet_name,
            mpn=mpn,
            pin_count=pin_count,
        )
        components.append(comp)

    # Extract sub-sheet references
    for sheet in getattr(sch, "sheets", []):
        sub_name = ""
        sub_file = ""

        # kiutils stores these as Property objects on direct attributes
        sn = getattr(sheet, "sheetName", None)
        fn = getattr(sheet, "fileName", None)
        if sn and hasattr(sn, "value"):
            sub_name = sn.value or ""
        if fn and hasattr(fn, "value"):
            sub_file = fn.value or ""

        # Fallback: check properties list
        if not sub_file:
            for prop in getattr(sheet, "properties", []):
                if prop.key in ("Sheetname", "Sheet name"):
                    sub_name = prop.value or ""
                elif prop.key in ("Sheetfile", "Sheet file"):
                    sub_file = prop.value or ""

        if sub_file:
            sub_sheets.append(
                SheetInfo(
                    name=sub_name or sub_file,
                    file=sub_file,
                    parent=sheet_name,
                    uuid=str(getattr(sheet, "uuid", "")),
                )
            )

    # Extract labels
    for label in getattr(sch, "labels", []):
        labels[label.name] = "local"
    for label in getattr(sch, "globalLabels", []):
        labels[label.name] = "global"
    for label in getattr(sch, "hierarchicalLabels", []):
        labels[label.name] = "hierarchical"

    return components, sub_sheets, labels


def _resolve_hierarchy(
    root_sch: Path, project_dir: Path
) -> tuple[list[ComponentInfo], list[SheetInfo], dict[str, str]]:
    """Walk the hierarchical schematic tree, collecting components and labels."""
    all_components = []
    all_sheets = []
    all_labels = {}

    # BFS through the hierarchy
    to_visit = [(root_sch, "root")]
    visited = set()

    while to_visit:
        sch_path, sheet_name = to_visit.pop(0)

        # Resolve relative path
        if not sch_path.is_absolute():
            sch_path = project_dir / sch_path

        if not sch_path.exists() or str(sch_path) in visited:
            continue
        visited.add(str(sch_path))

        components, sub_sheets, labels = _parse_schematic_sheet(
            sch_path, sheet_name, project_dir
        )

        all_components.extend(components)
        all_sheets.extend(sub_sheets)
        all_labels.update(labels)

        # Queue sub-sheets for parsing
        for sub in sub_sheets:
            sub_path = sch_path.parent / sub.file
            to_visit.append((sub_path, sub.name))

    return all_components, all_sheets, all_labels


# ── PCB parsing ──────────────────────────────────────────────────────────────


def _parse_board(pcb_path: Path) -> BoardInfo:
    """Parse a .kicad_pcb file for board-level metrics."""
    try:
        board = Board.from_file(str(pcb_path))
    except Exception as e:
        print(f"  Warning: failed to parse {pcb_path}: {e}")
        return BoardInfo()

    # Count signal/power layers
    layer_names = []
    for layer_item in getattr(board, "layers", []):
        layer_type = getattr(layer_item, "type", "")
        if layer_type in ("signal", "power", "mixed"):
            layer_names.append(getattr(layer_item, "name", ""))

    # Count tracks, vias, footprints, zones
    track_count = len(getattr(board, "traceItems", []))
    footprint_count = len(getattr(board, "footprints", []))
    zone_count = len(getattr(board, "zones", []))

    # Count vias (they're in traceItems too, check type)
    via_count = 0
    for item in getattr(board, "traceItems", []):
        if hasattr(item, "type") and "via" in str(type(item).__name__).lower():
            via_count += 1

    # Net classes
    net_class_names = []
    for nc in getattr(board, "netClasses", []):
        nc_name = getattr(nc, "name", "")
        if nc_name:
            net_class_names.append(nc_name)

    return BoardInfo(
        layers=len(layer_names),
        layer_names=layer_names,
        footprint_count=footprint_count,
        track_count=track_count,
        via_count=via_count,
        zone_count=zone_count,
        net_classes=net_class_names,
    )


# ── Main parser ──────────────────────────────────────────────────────────────


def parse_project(project_dir: Path) -> dict:
    """Parse a KiCad project directory into a normalized JSON structure.

    Args:
        project_dir: Path to directory containing .kicad_sch and .kicad_pcb files.

    Returns:
        Dictionary with meta, hierarchy, components, nets, board, and stats.
    """
    project_dir = Path(project_dir)

    # Find root schematic (the one referenced by .kicad_pro, or the only one)
    pro_files = list(project_dir.rglob("*.kicad_pro"))
    sch_files = sorted(project_dir.rglob("*.kicad_sch"))
    pcb_files = sorted(project_dir.rglob("*.kicad_pcb"))

    if not sch_files and not pcb_files:
        return {"error": f"No KiCad files found in {project_dir}"}

    # Determine root schematic
    root_sch = None
    if pro_files:
        # Root schematic is usually named same as .kicad_pro
        pro_stem = pro_files[0].stem
        for sch in sch_files:
            if sch.stem == pro_stem:
                root_sch = sch
                break
    if root_sch is None and sch_files:
        root_sch = sch_files[0]

    # Parse schematic hierarchy
    components = []
    sheets = []
    labels = {}
    if root_sch:
        components, sheets, labels = _resolve_hierarchy(root_sch, root_sch.parent)

    # Parse PCB
    board_info = None
    if pcb_files:
        board_info = _parse_board(pcb_files[0])

    # Detect power nets
    power_pattern = re.compile(
        r"^[+-]?\d*V?\d*[._]?\d*(?:VCC|VDD|VSS|GND|VBUS|VBAT|VIN|AVDD|DVDD|VREF|V3V3|3V3|5V|1V8|1V2|12V|AGND|DGND)",
        re.IGNORECASE,
    )

    nets = {}
    for name, scope in labels.items():
        net_type = "power" if power_pattern.match(name) else "signal"
        nets[name] = NetInfo(net_type=net_type, scope=scope)

    # Compute stats
    unique_lib_ids = set(c.lib_id for c in components if c.lib_id)
    power_nets = [n for n, info in nets.items() if info.net_type == "power"]

    # Detect KiCad version from first schematic
    kicad_version = None
    if root_sch and root_sch.exists():
        first_line_text = root_sch.read_text(errors="replace")[:500]
        version_match = re.search(r"\(version (\d+)\)", first_line_text)
        if version_match:
            kicad_version = int(version_match.group(1))

    result = {
        "meta": {
            "project_name": project_dir.name,
            "source_dir": str(project_dir),
            "kicad_version": kicad_version,
            "root_schematic": str(root_sch.relative_to(project_dir)) if root_sch else None,
        },
        "hierarchy": {
            "root": str(root_sch.name) if root_sch else None,
            "sheets": [asdict(s) for s in sheets],
        },
        "components": [asdict(c) for c in components],
        "nets": {name: asdict(info) for name, info in nets.items()},
        "board": asdict(board_info) if board_info else None,
        "stats": {
            "total_components": len(components),
            "unique_parts": len(unique_lib_ids),
            "total_nets": len(nets),
            "power_rails": len(power_nets),
            "hierarchical_sheets": len(sheets),
            "sch_file_count": len(sch_files),
            "pcb_file_count": len(pcb_files),
        },
    }

    return result


def main():
    """CLI entrypoint: parse a project and print JSON."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 -m src.pipeline.parser <project_dir>")
        sys.exit(1)

    project_dir = Path(sys.argv[1])
    if not project_dir.exists():
        print(f"Error: {project_dir} does not exist")
        sys.exit(1)

    result = parse_project(project_dir)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
