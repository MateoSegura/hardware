"""Hierarchy walker for KiCad schematic designs.

Recursively loads all sheets in a hierarchical KiCad schematic,
building a complete sheet tree with components, labels, and sub-sheet references.
"""

from __future__ import annotations

import logging
import re
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools"))

from kiutils.schematic import Schematic

from .models import (
    LabelInfo,
    ParsedComponent,
    ParsedSheet,
    Position,
    SheetPinInfo,
    SubSheetRef,
)

logger = logging.getLogger(__name__)


def detect_version(path: Path) -> int | None:
    """Read first 500 bytes, extract (version NNNN) token."""
    try:
        text = path.read_text(errors="replace")[:500]
    except OSError:
        return None
    match = re.search(r"\(version\s+(\d+)\)", text)
    return int(match.group(1)) if match else None


def _get_sheet_filename(sheet) -> str:
    fn = getattr(sheet, "fileName", None)
    if fn and hasattr(fn, "value"):
        return fn.value
    return ""


def _get_sheet_name(sheet) -> str:
    sn = getattr(sheet, "sheetName", None)
    if sn and hasattr(sn, "value"):
        return sn.value
    return ""


def _is_power_symbol(sym, lib_symbols: list) -> bool:
    for lib_sym in lib_symbols:
        if lib_sym.libId == sym.libId or lib_sym.entryName == sym.entryName:
            return getattr(lib_sym, "isPower", False)
    return False


def _get_pin_count(sym, lib_symbols: list) -> int:
    for lib_sym in lib_symbols:
        if lib_sym.libId == sym.libId or lib_sym.entryName == sym.entryName:
            total = 0
            for u in lib_sym.units:
                total += len(u.pins)
            return total
    return 0


def _get_ref(sym, sch: Schematic, sheet_path: str) -> str:
    """Get reference designator, handling v6 and v7+ formats."""
    # v7+: check sym.instances
    if sym.instances:
        for inst in sym.instances:
            for path in inst.paths:
                if path.sheetInstancePath == sheet_path:
                    return path.reference
        # Fallback: return first instance's reference
        for inst in sym.instances:
            if inst.paths:
                return inst.paths[0].reference

    # v6: check root schematic's symbolInstances
    if sch.symbolInstances:
        for si in sch.symbolInstances:
            if si.path.endswith(str(sym.uuid)):
                return si.reference

    # Last resort: Reference property
    for prop in sym.properties:
        if prop.key == "Reference":
            return prop.value

    return "?"


def _get_property(sym, key: str, default: str = "") -> str:
    for prop in sym.properties:
        if prop.key == key:
            return prop.value
    return default


def _extract_components(
    sch: Schematic,
    root_sch: Schematic,
    lib_symbols: list,
    sheet_path: str,
    sheet_name: str,
) -> tuple[list[ParsedComponent], list[ParsedComponent]]:
    """Extract components and power symbols from a schematic."""
    components = []
    power_symbols = []

    for sym in sch.schematicSymbols:
        is_power = _is_power_symbol(sym, lib_symbols)
        ref = _get_ref(sym, root_sch, sheet_path)
        props = {p.key: p.value for p in sym.properties}

        comp = ParsedComponent(
            ref=ref,
            lib_id=sym.libId,
            value=_get_property(sym, "Value"),
            footprint=_get_property(sym, "Footprint"),
            mpn=_get_property(sym, "MPN") or _get_property(sym, "Manufacturer_Part_Number"),
            sheet_path=sheet_path,
            sheet_name=sheet_name,
            unit=sym.unit,
            pin_count=_get_pin_count(sym, lib_symbols),
            is_power=is_power,
            is_in_bom=getattr(sym, "inBom", True),
            is_on_board=getattr(sym, "onBoard", True),
            dnp=getattr(sym, "dnp", False) or False,
            properties=props,
        )
        components.append(comp)
        if is_power:
            power_symbols.append(comp)

    return components, power_symbols


def _extract_labels(sch: Schematic) -> tuple[list[LabelInfo], list[LabelInfo], list[LabelInfo]]:
    """Extract local, global, and hierarchical labels."""
    local_labels = []
    for label in getattr(sch, "labels", []):
        local_labels.append(LabelInfo(
            name=label.text,
            label_type="local",
            shape=getattr(label, "shape", ""),
            position=(label.position.X, label.position.Y),
            uuid=str(label.uuid),
        ))

    global_labels = []
    for label in sch.globalLabels:
        global_labels.append(LabelInfo(
            name=label.text,
            label_type="global",
            shape=getattr(label, "shape", ""),
            position=(label.position.X, label.position.Y),
            uuid=str(label.uuid),
        ))

    hier_labels = []
    for label in sch.hierarchicalLabels:
        hier_labels.append(LabelInfo(
            name=label.text,
            label_type="hierarchical",
            shape=getattr(label, "shape", ""),
            position=(label.position.X, label.position.Y),
            uuid=str(label.uuid),
        ))

    return local_labels, global_labels, hier_labels


def _extract_sub_sheet_refs(sch: Schematic, parent_dir: Path) -> list[SubSheetRef]:
    """Extract sub-sheet references with resolved paths."""
    refs = []
    for sheet in sch.sheets:
        file_name = _get_sheet_filename(sheet)
        sheet_name = _get_sheet_name(sheet)
        if not file_name:
            continue

        resolved = (parent_dir / file_name).resolve()
        exists = resolved.is_file()

        pins = []
        for pin in sheet.pins:
            pins.append(SheetPinInfo(
                name=pin.name,
                direction=getattr(pin, "connectionType", ""),
            ))

        refs.append(SubSheetRef(
            sheet_name=sheet_name,
            file_name=file_name,
            resolved_path=resolved if exists else None,
            uuid=str(sheet.uuid),
            pins=pins,
            exists=exists,
        ))

    return refs


def walk_hierarchy(root_path: Path) -> dict[str, ParsedSheet]:
    """Walk a KiCad schematic hierarchy breadth-first.

    Args:
        root_path: Absolute path to the root .kicad_sch file.

    Returns:
        Dictionary mapping absolute file path strings to ParsedSheet objects.
    """
    root_path = root_path.resolve()
    if not root_path.is_file():
        raise FileNotFoundError(f"Root schematic not found: {root_path}")

    # Load root schematic to access symbolInstances (v6)
    root_sch = Schematic.from_file(str(root_path))
    root_uuid = str(root_sch.uuid) if hasattr(root_sch, "uuid") and root_sch.uuid else ""

    # Cache loaded schematics by absolute path
    _cache: dict[str, Schematic] = {str(root_path): root_sch}

    # BFS queue: (sch_path, sheet_name, parent_path, sheet_uuid, sheet_path_for_instances)
    queue: deque[tuple[Path, str, Path | None, str, str]] = deque()
    queue.append((root_path, "root", None, root_uuid, f"/{root_uuid}"))

    visited: set[str] = set()
    sheet_tree: dict[str, ParsedSheet] = {}

    while queue:
        sch_path, sheet_name, parent_path, sheet_uuid, sheet_path = queue.popleft()
        abs_path = str(sch_path.resolve())

        if abs_path in visited:
            continue
        visited.add(abs_path)

        # Load schematic (cached)
        if abs_path in _cache:
            sch = _cache[abs_path]
        else:
            try:
                sch = Schematic.from_file(abs_path)
                _cache[abs_path] = sch
            except Exception as e:
                logger.warning("Failed to load schematic %s: %s", abs_path, e)
                continue

        version = detect_version(sch_path)

        # Use root_sch for symbolInstances resolution in v6
        # (root_sch has the global symbolInstances list)
        lib_symbols = sch.libSymbols

        components, power_symbols = _extract_components(
            sch, root_sch, lib_symbols, sheet_path, sheet_name
        )
        local_labels, global_labels, hier_labels = _extract_labels(sch)
        sub_sheet_refs = _extract_sub_sheet_refs(sch, sch_path.parent)

        no_connects = [
            Position(x=nc.position.X, y=nc.position.Y)
            for nc in sch.noConnects
        ]
        junctions = [
            Position(x=j.position.X, y=j.position.Y)
            for j in sch.junctions
        ]

        parsed = ParsedSheet(
            file_path=sch_path.resolve(),
            sheet_name=sheet_name,
            sheet_uuid=sheet_uuid,
            parent_path=parent_path,
            kicad_version=version,
            components=components,
            local_labels=local_labels,
            global_labels=global_labels,
            hierarchical_labels=hier_labels,
            sub_sheet_refs=sub_sheet_refs,
            power_symbols=power_symbols,
            no_connects=no_connects,
            junctions=junctions,
        )
        sheet_tree[abs_path] = parsed

        # Enqueue sub-sheets
        for ref in sub_sheet_refs:
            if not ref.exists:
                logger.warning(
                    "Sub-sheet not found: %s (referenced from %s)",
                    ref.file_name, abs_path,
                )
                continue
            sub_path = ref.resolved_path
            sub_sheet_path = f"{sheet_path}/{ref.uuid}"
            queue.append((sub_path, ref.sheet_name, sch_path.resolve(), ref.uuid, sub_sheet_path))

    return sheet_tree
