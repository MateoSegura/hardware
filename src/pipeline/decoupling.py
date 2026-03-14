"""Decoupling capacitor pattern extractor.

Analyzes all parsed projects to find decoupling cap patterns per MCU/IC family.
Uses sheet co-location and power net membership as a proxy for decoupling
association (since pin-level net connectivity is not yet populated).
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .classify import (
    classify_component,
    classify_passive_type,
    extract_ic_family,
    ComponentType,
)


# Minimum pin count to qualify as an "IC worth analyzing"
IC_MIN_PINS = 20

# Patterns matching capacitor lib_ids
_CAP_LIB_RE = re.compile(r"(?:Device|passive):C(?:_Small|_Polarized)?$", re.IGNORECASE)

# Patterns matching capacitor reference designators
_CAP_REF_RE = re.compile(r"^C\d+$")

# Power net name patterns (matches VCC, GND, +3V3, etc.)
_POWER_NET_RE = re.compile(
    r"^("
    r"[+-]?\d+(\.\d+)?V\d*"
    r"|V(CC|DD|SS|EE|BAT|BUS|IN|OUT|REF|REG)"
    r"|GND|AGND|DGND|PGND|GNDREF|GNDA|GNDD"
    r")$",
    re.IGNORECASE,
)


def _is_capacitor(comp: dict) -> bool:
    """Check if a component is a capacitor."""
    lib_id = comp.get("lib_id", "")
    ref = comp.get("ref", "")
    footprint = comp.get("footprint", "")
    return classify_passive_type(lib_id, footprint, ref) == "C"


def _extract_ic_family(lib_id: str, value: str) -> str:
    """Extract IC family name from lib_id or value.

    Examples:
        "MCU_ST_STM32F7:STM32F722RETx" → "STM32F7"
        "MCU_ST_STM32F4:STM32F411CEU6" → "STM32F4"
        "espressif:ESP32-S3" → "ESP32-S3"
        "RF_Module:ESP32-WROOM-32" → "ESP32"
        "MCU_Microchip_ATmega:ATmega328P-AU" → "ATmega"
        "MCU_NXP_LPC:LPC1768" → "LPC1768"
        "MCU_RaspberryPi:RP2040" → "RP2040"
    """
    # Try to extract from the library name (before colon)
    part = lib_id.split(":")[-1] if ":" in lib_id else lib_id

    # STM32 family: STM32F7, STM32F4, STM32H7, etc.
    m = re.match(r"(STM32[A-Z]\d)", part, re.IGNORECASE)
    if m:
        return m.group(1).upper()

    # ESP32 variants
    m = re.match(r"(ESP32(?:-[A-Z]\d+)?)", part, re.IGNORECASE)
    if m:
        return m.group(1).upper()

    # RP2040, RP2350
    m = re.match(r"(RP\d{4})", part, re.IGNORECASE)
    if m:
        return m.group(1).upper()

    # ATmega, ATtiny
    m = re.match(r"(AT(?:mega|tiny))", part, re.IGNORECASE)
    if m:
        return m.group(1)

    # nRF52, nRF53
    m = re.match(r"(nRF\d{2})", part, re.IGNORECASE)
    if m:
        return m.group(1)

    # LPC family
    m = re.match(r"(LPC\d{4})", part, re.IGNORECASE)
    if m:
        return m.group(1).upper()

    # Generic: use the first word-like token from the part name
    m = re.match(r"([A-Za-z]+\d+[A-Za-z]*)", part)
    if m:
        return m.group(1)

    # Fallback: use the value field
    if value:
        m = re.match(r"([A-Za-z]+\d+[A-Za-z]*)", value)
        if m:
            return m.group(1)

    return part or "Unknown"


def _normalize_cap_value(value: str) -> str:
    """Normalize capacitor value strings to a consistent format.

    "100n" → "100nF", "0.1u" → "100nF", "4u7" → "4.7uF", "10p" → "10pF"
    """
    v = value.strip().lower()

    # Handle "4u7" → "4.7u" style
    m = re.match(r"(\d+)([pnuμm])(\d+)", v)
    if m:
        v = f"{m.group(1)}.{m.group(3)}{m.group(2)}"

    # Extract numeric + unit
    m = re.match(r"([\d.]+)\s*([pnuμm])?f?$", v)
    if not m:
        return value  # Can't parse, return as-is

    num = float(m.group(1))
    unit = m.group(2) or ""

    unit_map = {"p": "pF", "n": "nF", "u": "uF", "μ": "uF", "m": "mF"}

    # Convert 0.1u → 100n
    if unit in ("u", "μ") and num < 1:
        num *= 1000
        unit = "n"

    suffix = unit_map.get(unit, "F")
    # Format nicely: avoid trailing zeros
    if num == int(num):
        return f"{int(num)}{suffix}"
    return f"{num:g}{suffix}"


def _extract_footprint_short(footprint: str) -> str:
    """Extract short footprint name from full KiCad footprint path.

    "Capacitor_SMD:C_0402_1005Metric" → "C_0402"
    "Capacitor_SMD:C_0805_2012Metric" → "C_0805"
    """
    part = footprint.split(":")[-1] if ":" in footprint else footprint
    m = re.match(r"(C_\d{4})", part)
    if m:
        return m.group(1)
    return part


def extract_decoupling_patterns(parsed_dir: Path) -> dict[str, Any]:
    """Extract decoupling capacitor patterns from all parsed projects.

    Args:
        parsed_dir: Path to data/parsed/ directory.

    Returns:
        Dict with "by_ic_family" and "global_stats" keys.
    """
    # ic_family → list of cap records
    family_caps: dict[str, list[dict]] = defaultdict(list)
    # ic_family → set of power net names
    family_power_nets: dict[str, set[str]] = defaultdict(set)
    # ic_family → count of ICs seen
    family_ic_count: dict[str, int] = Counter()

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
                _process_project(proj, family_caps, family_power_nets, family_ic_count)

    return _build_output(family_caps, family_power_nets, family_ic_count)


def _process_project(
    proj: dict,
    family_caps: dict[str, list[dict]],
    family_power_nets: dict[str, set[str]],
    family_ic_count: dict[str, int],
) -> None:
    """Process a single parsed project, collecting decoupling patterns."""
    comps = proj.get("all_components", [])
    if not isinstance(comps, list):
        return

    nets = proj.get("all_nets", {})
    if not isinstance(nets, dict):
        nets = {}

    # Identify power nets
    power_net_names: set[str] = set()
    for net_name, net_info in nets.items():
        if isinstance(net_info, dict) and net_info.get("net_type") == "power":
            power_net_names.add(net_name)

    # Find ICs and caps, grouped by sheet
    ics_by_sheet: dict[str, list[dict]] = defaultdict(list)
    caps_by_sheet: dict[str, list[dict]] = defaultdict(list)

    for comp in comps:
        if not isinstance(comp, dict):
            continue
        sheet = comp.get("sheet_name", "")
        pin_count = comp.get("pin_count", 0)

        comp_type = classify_component(
            lib_id=comp.get("lib_id", ""),
            footprint=comp.get("footprint", ""),
            ref=comp.get("ref", ""),
            pad_count=pin_count,
        )
        if pin_count >= IC_MIN_PINS and comp_type == ComponentType.IC:
            ics_by_sheet[sheet].append(comp)
        elif _is_capacitor(comp):
            caps_by_sheet[sheet].append(comp)

    # For each IC, find caps on the same sheet
    for sheet, ics in ics_by_sheet.items():
        caps = caps_by_sheet.get(sheet, [])
        for ic in ics:
            family = extract_ic_family(ic.get("lib_id", ""), ic.get("value", ""))
            family_ic_count[family] += 1

            for cap in caps:
                cap_value = _normalize_cap_value(cap.get("value", ""))
                cap_fp = _extract_footprint_short(cap.get("footprint", ""))
                family_caps[family].append({
                    "value": cap_value,
                    "footprint": cap_fp,
                })

            # Record power nets this IC's sheet participates in
            for net_name, net_info in nets.items():
                if not isinstance(net_info, dict):
                    continue
                if net_info.get("net_type") == "power":
                    net_sheets = net_info.get("sheets", [])
                    if sheet in net_sheets:
                        family_power_nets[family].add(net_name)


def _build_output(
    family_caps: dict[str, list[dict]],
    family_power_nets: dict[str, set[str]],
    family_ic_count: dict[str, int],
) -> dict[str, Any]:
    """Build final output structure."""
    by_ic_family: dict[str, Any] = {}

    total_caps = 0
    total_ics = 0
    cap_counter: Counter = Counter()

    for family in sorted(family_caps.keys()):
        caps = family_caps[family]
        count = family_ic_count.get(family, 0)
        total_ics += count
        total_caps += len(caps)

        # Count cap value+footprint combos
        combo_counter: Counter = Counter()
        for cap in caps:
            key = f"{cap['value']} {cap['footprint']}"
            combo_counter[key] += 1
            cap_counter[key] += 1

        cap_list = []
        for combo, cnt in combo_counter.most_common():
            parts = combo.split(" ", 1)
            cap_list.append({
                "value": parts[0],
                "footprint": parts[1] if len(parts) > 1 else "",
                "count": cnt,
            })

        by_ic_family[family] = {
            "sample_count": count,
            "caps": cap_list,
            "power_nets": sorted(family_power_nets.get(family, set())),
        }

    # Global stats
    most_common = cap_counter.most_common(1)
    avg_caps = total_caps / total_ics if total_ics > 0 else 0

    return {
        "by_ic_family": by_ic_family,
        "global_stats": {
            "most_common_cap": most_common[0][0] if most_common else "",
            "avg_caps_per_ic": round(avg_caps, 1),
            "total_ics_analyzed": total_ics,
            "total_caps_found": total_caps,
            "families_found": len(by_ic_family),
        },
    }


def run(parsed_dir: Path, output_path: Path) -> dict[str, Any]:
    """Extract patterns and write to JSON file."""
    result = extract_decoupling_patterns(parsed_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2))
    return result
