"""Net connectivity tracer across the schematic hierarchy.

Takes the output of the hierarchy walker (a dict of ParsedSheet objects keyed
by file path) and produces a unified net map connecting labels, power symbols,
and hierarchical pins across all sheets.
"""

from __future__ import annotations

import re

from .models import (
    NetInfo,
    ParsedSheet,
    SubSheetRef,
)

# Patterns that indicate a power net name.
_POWER_PATTERNS = re.compile(
    r"^("
    r"[+-]?\d+(\.\d+)?V\d*"   # +3V3, +5V, -12V, 3V3, 1V8
    r"|V(CC|DD|SS|EE|BAT|BUS|IN|OUT|REF|REG)"  # VCC, VDD, VSS, etc.
    r"|GND|AGND|DGND|PGND|GNDREF|GNDA|GNDD"    # ground variants
    r"|PWR_FLAG"
    r")$",
    re.IGNORECASE,
)


def _is_power_name(name: str) -> bool:
    """Check if a net name matches common power net patterns."""
    return bool(_POWER_PATTERNS.match(name))


def _classify_net(
    name: str,
    has_global: bool,
    has_hierarchical: bool,
    has_power_symbol: bool,
) -> tuple[str, str]:
    """Return (net_type, scope) for a net.

    net_type: "power" or "signal"
    scope: "global", "hierarchical", or "local"
    """
    is_power = has_power_symbol or _is_power_name(name)
    net_type = "power" if is_power else "signal"

    if has_global or has_power_symbol:
        scope = "global"
    elif has_hierarchical:
        scope = "hierarchical"
    else:
        scope = "local"

    return net_type, scope


class _NetBuilder:
    """Accumulates net information during tracing."""

    def __init__(self) -> None:
        # net_name -> set of sheet names where it appears
        self._sheets: dict[str, set[str]] = {}
        # net_name -> flags
        self._has_global: dict[str, bool] = {}
        self._has_hierarchical: dict[str, bool] = {}
        self._has_power_symbol: dict[str, bool] = {}

    def add(
        self,
        net_name: str,
        sheet_name: str,
        *,
        is_global: bool = False,
        is_hierarchical: bool = False,
        is_power_symbol: bool = False,
    ) -> None:
        if net_name not in self._sheets:
            self._sheets[net_name] = set()
            self._has_global[net_name] = False
            self._has_hierarchical[net_name] = False
            self._has_power_symbol[net_name] = False

        self._sheets[net_name].add(sheet_name)
        if is_global:
            self._has_global[net_name] = True
        if is_hierarchical:
            self._has_hierarchical[net_name] = True
        if is_power_symbol:
            self._has_power_symbol[net_name] = True

    def merge(self, from_name: str, into_name: str) -> None:
        """Merge from_name net into into_name net (hierarchical connection)."""
        if from_name not in self._sheets:
            return
        if into_name not in self._sheets:
            self._sheets[into_name] = set()
            self._has_global[into_name] = False
            self._has_hierarchical[into_name] = False
            self._has_power_symbol[into_name] = False

        self._sheets[into_name] |= self._sheets[from_name]
        self._has_global[into_name] |= self._has_global[from_name]
        self._has_hierarchical[into_name] |= self._has_hierarchical[from_name]
        self._has_power_symbol[into_name] |= self._has_power_symbol[from_name]

    def build(self) -> dict[str, NetInfo]:
        result: dict[str, NetInfo] = {}
        for name, sheets in self._sheets.items():
            net_type, scope = _classify_net(
                name,
                self._has_global[name],
                self._has_hierarchical[name],
                self._has_power_symbol[name],
            )
            result[name] = NetInfo(
                name=name,
                net_type=net_type,
                scope=scope,
                sheets=sorted(sheets),
            )
        return result


def _resolve_child_sheet(
    parent_sheet: ParsedSheet,
    sub_ref: SubSheetRef,
    sheets_by_path: dict[str, ParsedSheet],
) -> ParsedSheet | None:
    """Find the child ParsedSheet for a SubSheetRef."""
    if sub_ref.resolved_path is not None:
        key = str(sub_ref.resolved_path)
        if key in sheets_by_path:
            return sheets_by_path[key]

    # Fallback: resolve relative to parent directory
    parent_dir = parent_sheet.file_path.parent
    child_path = parent_dir / sub_ref.file_name
    child_resolved = str(child_path.resolve())
    return sheets_by_path.get(child_resolved)


def trace_nets(sheet_tree: dict[str, ParsedSheet]) -> dict[str, NetInfo]:
    """Build net connectivity map across the entire schematic hierarchy.

    Args:
        sheet_tree: Dict mapping absolute file path (as string) to ParsedSheet.
                    This is the output of the hierarchy walker.

    Returns:
        Dict mapping net name to NetInfo with type, scope, and sheet membership.
    """
    builder = _NetBuilder()

    # Phase 1+2: Collect all labels and power symbols from every sheet.
    for sheet in sheet_tree.values():
        sname = sheet.sheet_name

        # Global labels → global scope
        for label in sheet.global_labels:
            builder.add(label.name, sname, is_global=True)

        # Local labels → local scope (unless merged later)
        for label in sheet.local_labels:
            builder.add(label.name, sname)

        # Hierarchical labels → hierarchical scope
        for label in sheet.hierarchical_labels:
            builder.add(label.name, sname, is_hierarchical=True)

        # Power symbols create implicit global nets
        for comp in sheet.power_symbols:
            # Power symbol's value is the net name (e.g., "VCC", "+3V3")
            builder.add(comp.value, sname, is_power_symbol=True, is_global=True)

    # Phase 3: Resolve hierarchical connections.
    # For each parent sheet's sub_sheet_ref, connect parent-side nets to child-side nets.
    for sheet in sheet_tree.values():
        for sub_ref in sheet.sub_sheet_refs:
            child = _resolve_child_sheet(sheet, sub_ref, sheet_tree)
            if child is None:
                continue

            # Build a lookup of hierarchical labels in the child sheet
            child_hlabels = {hl.name: hl for hl in child.hierarchical_labels}

            for pin in sub_ref.pins:
                if pin.name in child_hlabels:
                    # The pin on the parent side connects the parent's net
                    # to the child's hierarchical label net. They're the same net.
                    # Mark both sides as hierarchical.
                    builder.add(
                        pin.name, sheet.sheet_name, is_hierarchical=True
                    )
                    builder.add(
                        pin.name, child.sheet_name, is_hierarchical=True
                    )

    # Phase 4: Classification happens inside builder.build()
    return builder.build()
