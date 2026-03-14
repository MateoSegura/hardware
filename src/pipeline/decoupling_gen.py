"""Decoupling capacitor auto-generation — decoupled from templates.

Generates ComponentPlacement and NetConnection objects for decoupling
capacitors based on IC family rules from decoupling_rules.json. Works
directly with the schematic generator without going through the template
system.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .schematic_gen import ComponentPlacement, NetConnection

# Default data paths
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_RULES_PATH = _REPO_ROOT / "data" / "patterns" / "decoupling_rules.json"

# Cap placement layout: offset from IC, spacing between caps
_CAP_X_OFFSET = 15.0  # mm to the right of IC
_CAP_Y_START_OFFSET = -5.0  # mm above IC center
_CAP_Y_SPACING = 5.0  # mm between caps vertically

# Default footprint mappings
_DEFAULT_FOOTPRINT_MAP = {
    "C_0201": "Capacitor_SMD:C_0201_0603Metric",
    "C_0402": "Capacitor_SMD:C_0402_1005Metric",
    "C_0603": "Capacitor_SMD:C_0603_1608Metric",
    "C_0805": "Capacitor_SMD:C_0805_2012Metric",
    "C_1206": "Capacitor_SMD:C_1206_3216Metric",
}


def _extract_ic_family(lib_id: str) -> str:
    """Extract IC family from a library ID.

    Examples:
        "MCU_ST:STM32F722RET6" -> "STM32F7"
        "MCU_ST:STM32F411CEU6" -> "STM32F4"
        "RF_Module:ESP32-WROOM-32" -> "ESP32"
        "MCU_RaspberryPi:RP2040" -> "RP2040"
    """
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

    # Generic: first alphanumeric token
    m = re.match(r"([A-Za-z]+\d+[A-Za-z]*)", part)
    if m:
        return m.group(1)

    return part or "Unknown"


def _expand_footprint(short: str) -> str:
    """Expand short footprint name to full KiCad path.

    "C_0402" -> "Capacitor_SMD:C_0402_1005Metric"
    """
    if ":" in short:
        return short  # Already a full footprint path
    return _DEFAULT_FOOTPRINT_MAP.get(short, f"Capacitor_SMD:{short}")


def _load_rules(rules_path: Path | None) -> dict:
    """Load decoupling_rules.json."""
    path = rules_path or _DEFAULT_RULES_PATH
    if not path.is_file():
        return {}
    with open(path) as f:
        return json.load(f)


def generate_decoupling_caps(
    ic_lib_id: str,
    ic_position: tuple[float, float],
    power_nets: list[str],
    ground_net: str = "GND",
    rules_path: Path | None = None,
    ref_start: int = 1,
) -> list[ComponentPlacement]:
    """Generate decoupling capacitor placements for a given IC.

    Looks up the IC family in decoupling_rules.json, finds the most common
    cap values/footprints, and generates ComponentPlacement objects positioned
    near the IC.

    Args:
        ic_lib_id: Library ID of the IC (e.g., "MCU_ST:STM32F722RET6")
        ic_position: X, Y position of the IC on the schematic
        power_nets: List of power net names this IC uses
        ground_net: Ground net name
        rules_path: Path to decoupling_rules.json (defaults to data/patterns/)
        ref_start: Starting reference number for cap designators

    Returns:
        List of ComponentPlacement objects for decoupling caps
    """
    rules = _load_rules(rules_path)
    family = _extract_ic_family(ic_lib_id)

    families = rules.get("by_ic_family", {})
    family_data = families.get(family)

    if family_data is not None:
        caps_spec = _caps_from_rules(family_data, len(power_nets))
    else:
        caps_spec = _default_caps(power_nets)

    # Generate ComponentPlacement objects
    placements: list[ComponentPlacement] = []
    ix, iy = ic_position
    ref_num = ref_start

    for i, (value, footprint_short) in enumerate(caps_spec):
        full_footprint = _expand_footprint(footprint_short)
        x = ix + _CAP_X_OFFSET
        y = iy + _CAP_Y_START_OFFSET + i * _CAP_Y_SPACING

        placements.append(ComponentPlacement(
            lib_id="Device:C",
            ref=f"C{ref_num}",
            value=value,
            footprint=full_footprint,
            position=(x, y),
        ))
        ref_num += 1

    return placements


def _caps_from_rules(
    family_data: dict,
    num_power_nets: int,
) -> list[tuple[str, str]]:
    """Extract cap value/footprint pairs from rules data.

    Takes the top cap entries from the family. Uses at most 5 entries
    (the most common caps for this family).

    Returns:
        List of (value, footprint_short) tuples
    """
    caps = family_data.get("caps", [])
    result: list[tuple[str, str]] = []

    for cap in caps[:5]:
        value = cap.get("value", "")
        footprint = cap.get("footprint", "")

        if not value:
            continue

        # Use default footprint if none specified in rules
        if not footprint:
            footprint = "C_0402"

        result.append((value, footprint))

    # Ensure at least one cap per power net if rules have fewer
    if not result:
        result = [("100nF", "C_0402")] * max(num_power_nets, 1)

    return result


def _default_caps(power_nets: list[str]) -> list[tuple[str, str]]:
    """Generate default cap specs when IC family is not in rules.

    100nF C_0402 per power net + one 10uF C_0805 bulk cap.

    Returns:
        List of (value, footprint_short) tuples
    """
    result: list[tuple[str, str]] = []

    # 100nF per power net
    for _ in power_nets:
        result.append(("100nF", "C_0402"))

    # One 10uF bulk cap
    result.append(("10uF", "C_0805"))

    return result


def generate_decoupling_nets(
    caps: list[ComponentPlacement],
    power_nets: list[str],
    ground_net: str = "GND",
) -> list[NetConnection]:
    """Generate power/ground net connections for decoupling caps.

    Places net labels near each capacitor: pin 1 (top) gets the power net,
    pin 2 (bottom) gets the ground net. Power nets are assigned round-robin
    across caps.

    Args:
        caps: List of decoupling cap ComponentPlacement objects
        power_nets: List of power net names
        ground_net: Ground net name

    Returns:
        List of NetConnection objects for power and ground nets
    """
    if not caps or not power_nets:
        return []

    nets: list[NetConnection] = []

    for i, cap in enumerate(caps):
        cx, cy = cap.position

        # Assign power net round-robin
        power_net = power_nets[i % len(power_nets)]

        # Power label at pin 1 (above cap)
        nets.append(NetConnection(
            net_name=power_net,
            label_type="global",
            position=(cx, cy - 3.81),
        ))

        # Ground label at pin 2 (below cap)
        nets.append(NetConnection(
            net_name=ground_net,
            label_type="global",
            position=(cx, cy + 3.81),
        ))

    return nets
