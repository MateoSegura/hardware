"""Design composer — generates wired KiCad projects from high-level specs.

Takes a design specification (MCU + peripherals + power) and produces
a complete hierarchical KiCad project using:
- Wiring patterns from data/patterns/wiring_patterns.json
- Decoupling rules from data/patterns/decoupling_rules.json
- Circuit templates from data/patterns/templates/
- Symbol generator for custom chips
- Schematic generator for hierarchical projects
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.pipeline.schematic_gen import (
    ComponentPlacement,
    NetConnection,
    SheetContent,
    generate_hierarchical_project,
)
from src.pipeline.decoupling_gen import generate_decoupling_caps, generate_decoupling_nets
from src.pipeline.classify import extract_ic_family
from src.pipeline.pattern_merge import normalize_ic_family


# ---------------------------------------------------------------------------
# Data paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_PATTERNS_PATH = _REPO_ROOT / "data" / "patterns" / "wiring_patterns.json"
_DEFAULT_RULES_PATH = _REPO_ROOT / "data" / "patterns" / "decoupling_rules.json"

# Layout constants (mm)
_MCU_POS = (100.0, 80.0)
_PERIPHERAL_X_START = 100.0
_PERIPHERAL_Y_START = 80.0
_LABEL_OFFSET_X = 20.0
_LABEL_OFFSET_Y = -5.0
_LABEL_SPACING_Y = 5.0

# MCU library ID templates by family
_MCU_LIB_MAP: dict[str, str] = {
    "ESP32-S3": "RF_Module:ESP32-S3-WROOM-1",
    "ESP32": "RF_Module:ESP32-WROOM-32",
    "STM32F7": "MCU_ST:STM32F722RET6",
    "STM32F4": "MCU_ST:STM32F411CEU6",
    "STM32H7": "MCU_ST:STM32H743VIT6",
    "RP2040": "MCU_RaspberryPi:RP2040",
}

# Common regulator symbols
_REGULATOR_MAP: dict[str, tuple[str, str]] = {
    # (lib_id, footprint)
    "LDO": ("Regulator_Linear:AP2112K-3.3", "Package_TO_SOT_SMD:SOT-23-5"),
    "DCDC": ("Regulator_Switching:TPS563200", "Package_TO_SOT_SMD:SOT-23-6"),
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PeripheralSpec:
    """A peripheral to include in the design."""
    name: str              # human name, e.g., "IMU"
    chip: str              # chip name, e.g., "ICM-42688"
    interface: str         # "SPI", "I2C", "UART", "GPIO"


@dataclass
class PowerSpec:
    """Power supply specification."""
    input_source: str      # "USB-C", "battery", "external"
    voltage: str           # "3.3V"
    regulator: str         # "LDO" or "DCDC"


@dataclass
class DesignSpec:
    """Complete design specification."""
    name: str
    mcu_family: str        # "ESP32-S3", "STM32F7"
    mcu_chip: str          # "ESP32-S3-WROOM-1", "STM32F722RET6"
    peripherals: list[PeripheralSpec]
    power: PowerSpec


@dataclass
class GeneratedProject:
    """Output of the composer."""
    name: str
    files: dict[str, str]  # filename -> content (.kicad_sch, .kicad_sym)
    bom: list[dict]        # bill of materials
    wiring_notes: list[str]  # what patterns were used
    warnings: list[str]     # what couldn't be auto-wired


# ---------------------------------------------------------------------------
# Pattern loading and lookup
# ---------------------------------------------------------------------------

def _load_wiring_patterns(patterns_path: Path) -> dict:
    """Load and index wiring patterns by IC family pair.

    Returns a dict keyed by (ic_a_family_lower, ic_b_family_lower, interface_lower)
    mapping to the pattern entry with canonical_connections.
    """
    if not patterns_path.is_file():
        return {}

    with open(patterns_path) as f:
        data = json.load(f)

    index: dict[tuple[str, str, str], dict] = {}
    for pattern in data.get("patterns", []):
        a = pattern.get("ic_a_family", "").lower()
        b = pattern.get("ic_b_family", "").lower()
        iface = pattern.get("interface_type", "unknown").lower()
        key = (a, b, iface)
        # Keep the one with highest sample_count
        existing = index.get(key)
        if existing is None or pattern.get("sample_count", 0) > existing.get("sample_count", 0):
            index[key] = pattern

    return index


def _find_pattern(
    patterns: dict,
    mcu_family: str,
    peripheral_family: str,
    interface: str,
) -> dict | None:
    """Find the best matching wiring pattern for an MCU<->peripheral pair.

    Tries exact match first, then falls back to partial matches:
    1. Exact (mcu_family, peripheral_family, interface)
    2. Exact families with "unknown" interface
    3. Any entry with matching families regardless of interface
    """
    mcu_low = mcu_family.lower()
    periph_low = peripheral_family.lower()
    iface_low = interface.lower()

    # Exact match
    exact = patterns.get((mcu_low, periph_low, iface_low))
    if exact:
        return exact

    # Try unknown interface
    unknown = patterns.get((mcu_low, periph_low, "unknown"))
    if unknown:
        return unknown

    # Scan for any matching families
    for (a, b, _iface), pattern in patterns.items():
        if a == mcu_low and b == periph_low:
            return pattern

    # Try with normalized IC family names (e.g., "STM32F7" -> "STM32")
    norm_mcu = normalize_ic_family(mcu_family).lower()
    norm_periph = normalize_ic_family(peripheral_family).lower()

    if norm_mcu != mcu_low or norm_periph != periph_low:
        norm_exact = patterns.get((norm_mcu, norm_periph, iface_low))
        if norm_exact:
            return norm_exact

        for (a, b, _iface), pattern in patterns.items():
            if a == norm_mcu and b == norm_periph:
                return pattern

    # Try with shortened MCU family (e.g., "STM32F7" -> "STM32F")
    if len(mcu_low) > 5:
        short_mcu = mcu_low[:-1]  # drop last char
        for (a, b, _iface), pattern in patterns.items():
            if a.startswith(short_mcu) and b == periph_low:
                return pattern

    return None


# ---------------------------------------------------------------------------
# Sheet generators
# ---------------------------------------------------------------------------

def _generate_power_sheet(spec: DesignSpec) -> SheetContent:
    """Generate power supply sub-sheet (LDO/DCDC + caps)."""
    components: list[ComponentPlacement] = []
    nets: list[NetConnection] = []
    hlabels: list[tuple[str, str]] = []

    reg_type = spec.power.regulator.upper()
    reg_lib_id, reg_footprint = _REGULATOR_MAP.get(reg_type, _REGULATOR_MAP["LDO"])

    # Place regulator
    reg_pos = (100.0, 80.0)
    components.append(ComponentPlacement(
        lib_id=reg_lib_id,
        ref="U1",
        value=reg_lib_id.split(":")[-1],
        footprint=reg_footprint,
        position=reg_pos,
    ))

    # Input power net
    input_net = "VIN"
    if spec.power.input_source.upper() == "USB-C":
        input_net = "VBUS"
    elif spec.power.input_source.upper() == "BATTERY":
        input_net = "VBAT"

    nets.append(NetConnection(
        net_name=input_net,
        label_type="global",
        position=(reg_pos[0] - 15.0, reg_pos[1]),
    ))

    # Output voltage net
    voltage_net = f"+{spec.power.voltage}"
    nets.append(NetConnection(
        net_name=voltage_net,
        label_type="global",
        position=(reg_pos[0] + 15.0, reg_pos[1]),
    ))

    # Ground
    nets.append(NetConnection(
        net_name="GND",
        label_type="global",
        position=(reg_pos[0], reg_pos[1] + 15.0),
    ))

    # Input cap
    components.append(ComponentPlacement(
        lib_id="Device:C",
        ref="C1",
        value="10uF",
        footprint="Capacitor_SMD:C_0805_2012Metric",
        position=(reg_pos[0] - 15.0, reg_pos[1] + 10.0),
    ))

    # Output cap
    components.append(ComponentPlacement(
        lib_id="Device:C",
        ref="C2",
        value="10uF",
        footprint="Capacitor_SMD:C_0805_2012Metric",
        position=(reg_pos[0] + 15.0, reg_pos[1] + 10.0),
    ))

    # Power net labels for input/output caps
    nets.append(NetConnection(
        net_name=input_net, label_type="global",
        position=(reg_pos[0] - 15.0, reg_pos[1] + 10.0 - 3.81),
    ))
    nets.append(NetConnection(
        net_name="GND", label_type="global",
        position=(reg_pos[0] - 15.0, reg_pos[1] + 10.0 + 3.81),
    ))
    nets.append(NetConnection(
        net_name=voltage_net, label_type="global",
        position=(reg_pos[0] + 15.0, reg_pos[1] + 10.0 - 3.81),
    ))
    nets.append(NetConnection(
        net_name="GND", label_type="global",
        position=(reg_pos[0] + 15.0, reg_pos[1] + 10.0 + 3.81),
    ))

    # Hierarchical labels for power connections
    hlabels.append((voltage_net, "output"))
    hlabels.append(("GND", "passive"))
    hlabels.append((input_net, "input"))

    return SheetContent(
        title="Power",
        components=components,
        nets=nets,
        hierarchical_labels=hlabels,
    )


def _generate_mcu_sheet(
    spec: DesignSpec,
    patterns: dict,
    ref_counter: list[int],
) -> SheetContent:
    """Generate MCU sub-sheet with decoupling caps.

    Args:
        spec: Full design specification.
        patterns: Loaded wiring patterns index.
        ref_counter: Mutable list [cap_ref_num] for unique cap numbering.
    """
    components: list[ComponentPlacement] = []
    nets: list[NetConnection] = []
    hlabels: list[tuple[str, str]] = []

    # MCU component
    mcu_lib_id = _MCU_LIB_MAP.get(spec.mcu_family, f"Custom:{spec.mcu_chip}")
    mcu_pos = _MCU_POS

    components.append(ComponentPlacement(
        lib_id=mcu_lib_id,
        ref="U1",
        value=spec.mcu_chip,
        footprint="",
        position=mcu_pos,
    ))

    # Decoupling caps for MCU
    voltage_net = f"+{spec.power.voltage}"
    decoupling_caps = generate_decoupling_caps(
        ic_lib_id=mcu_lib_id,
        ic_position=mcu_pos,
        power_nets=[voltage_net],
        ground_net="GND",
        rules_path=_DEFAULT_RULES_PATH,
        ref_start=ref_counter[0],
    )
    ref_counter[0] += len(decoupling_caps)
    components.extend(decoupling_caps)

    # Decoupling cap nets
    decoupling_nets = generate_decoupling_nets(
        caps=decoupling_caps,
        power_nets=[voltage_net],
        ground_net="GND",
    )
    nets.extend(decoupling_nets)

    # Power nets for MCU
    nets.append(NetConnection(
        net_name=voltage_net, label_type="global",
        position=(mcu_pos[0] - 10.0, mcu_pos[1] - 10.0),
    ))
    nets.append(NetConnection(
        net_name="GND", label_type="global",
        position=(mcu_pos[0] - 10.0, mcu_pos[1] + 10.0),
    ))

    # Generate global labels for each peripheral's wiring
    for peripheral in spec.peripherals:
        periph_family = extract_ic_family(peripheral.chip)
        pattern = _find_pattern(
            patterns, spec.mcu_family, periph_family, peripheral.interface,
        )

        if pattern:
            connections = pattern.get("canonical_connections", [])
            for conn in connections:
                net_name = conn["net_name"]
                label_y = mcu_pos[1] + _LABEL_OFFSET_Y
                _LABEL_OFFSET_Y_INCR = 5.0
                nets.append(NetConnection(
                    net_name=net_name,
                    label_type="global",
                    position=(mcu_pos[0] + _LABEL_OFFSET_X, label_y),
                ))
                hlabels.append((net_name, "bidirectional"))
        else:
            # No pattern — generate default net names based on interface
            default_nets = _default_interface_nets(peripheral)
            for net_name in default_nets:
                nets.append(NetConnection(
                    net_name=net_name,
                    label_type="global",
                    position=(mcu_pos[0] + _LABEL_OFFSET_X, mcu_pos[1]),
                ))
                hlabels.append((net_name, "bidirectional"))

    # Power labels as hierarchical
    hlabels.append((voltage_net, "input"))
    hlabels.append(("GND", "passive"))

    # Deduplicate hierarchical labels
    seen_labels: set[str] = set()
    unique_hlabels: list[tuple[str, str]] = []
    for name, direction in hlabels:
        if name not in seen_labels:
            seen_labels.add(name)
            unique_hlabels.append((name, direction))

    return SheetContent(
        title="MCU",
        components=components,
        nets=nets,
        hierarchical_labels=unique_hlabels,
    )


def _generate_peripheral_sheet(
    peripheral: PeripheralSpec,
    pattern: dict | None,
    sheet_index: int,
    ref_counter: list[int],
    voltage_net: str,
) -> SheetContent:
    """Generate a peripheral sub-sheet, wired according to learned patterns.

    Args:
        peripheral: The peripheral specification.
        pattern: Matched wiring pattern (or None if unknown).
        sheet_index: Index for positioning and unique refs.
        ref_counter: Mutable list [cap_ref_num] for unique cap numbering.
        voltage_net: Power voltage net name (e.g., "+3.3V").
    """
    components: list[ComponentPlacement] = []
    nets: list[NetConnection] = []
    hlabels: list[tuple[str, str]] = []

    # Peripheral IC
    periph_pos = (_PERIPHERAL_X_START, _PERIPHERAL_Y_START)
    periph_lib_id = f"Custom:{peripheral.chip}"
    ic_ref = f"U{sheet_index + 2}"  # U1 is MCU, U2+ are peripherals

    components.append(ComponentPlacement(
        lib_id=periph_lib_id,
        ref=ic_ref,
        value=peripheral.chip,
        footprint="",
        position=periph_pos,
    ))

    # Decoupling caps for peripheral
    decoupling_caps = generate_decoupling_caps(
        ic_lib_id=periph_lib_id,
        ic_position=periph_pos,
        power_nets=[voltage_net],
        ground_net="GND",
        rules_path=_DEFAULT_RULES_PATH,
        ref_start=ref_counter[0],
    )
    ref_counter[0] += len(decoupling_caps)
    components.extend(decoupling_caps)

    decoupling_nets = generate_decoupling_nets(
        caps=decoupling_caps,
        power_nets=[voltage_net],
        ground_net="GND",
    )
    nets.extend(decoupling_nets)

    # Power nets
    nets.append(NetConnection(
        net_name=voltage_net, label_type="global",
        position=(periph_pos[0] - 10.0, periph_pos[1] - 10.0),
    ))
    nets.append(NetConnection(
        net_name="GND", label_type="global",
        position=(periph_pos[0] - 10.0, periph_pos[1] + 10.0),
    ))

    # Wire peripheral using pattern or defaults
    if pattern:
        connections = pattern.get("canonical_connections", [])
        for i, conn in enumerate(connections):
            net_name = conn["net_name"]
            label_y = periph_pos[1] + _LABEL_OFFSET_Y + i * _LABEL_SPACING_Y
            nets.append(NetConnection(
                net_name=net_name,
                label_type="global",
                position=(periph_pos[0] + _LABEL_OFFSET_X, label_y),
            ))
            hlabels.append((net_name, "bidirectional"))
    else:
        # No pattern — use default interface nets
        default_nets = _default_interface_nets(peripheral)
        for i, net_name in enumerate(default_nets):
            label_y = periph_pos[1] + _LABEL_OFFSET_Y + i * _LABEL_SPACING_Y
            nets.append(NetConnection(
                net_name=net_name,
                label_type="global",
                position=(periph_pos[0] + _LABEL_OFFSET_X, label_y),
            ))
            hlabels.append((net_name, "bidirectional"))

    # Power hierarchical labels
    hlabels.append((voltage_net, "input"))
    hlabels.append(("GND", "passive"))

    # Deduplicate
    seen: set[str] = set()
    unique_hlabels: list[tuple[str, str]] = []
    for name, direction in hlabels:
        if name not in seen:
            seen.add(name)
            unique_hlabels.append((name, direction))

    return SheetContent(
        title=peripheral.name,
        components=components,
        nets=nets,
        hierarchical_labels=unique_hlabels,
    )


def _default_interface_nets(peripheral: PeripheralSpec) -> list[str]:
    """Generate default net names for a peripheral based on its interface type."""
    prefix = peripheral.name.upper().replace(" ", "_")
    iface = peripheral.interface.upper()

    if iface == "SPI":
        return [
            f"{prefix}_SCK",
            f"{prefix}_MOSI",
            f"{prefix}_MISO",
            f"{prefix}_CS",
        ]
    elif iface == "I2C":
        return [
            f"{prefix}_SDA",
            f"{prefix}_SCL",
        ]
    elif iface == "UART":
        return [
            f"{prefix}_TX",
            f"{prefix}_RX",
        ]
    elif iface == "GPIO":
        return [
            f"{prefix}_IO",
        ]
    else:
        return [f"{prefix}_DATA"]


# ---------------------------------------------------------------------------
# BOM generation
# ---------------------------------------------------------------------------

def _collect_bom(sheets: dict[str, SheetContent]) -> list[dict]:
    """Collect bill of materials from all sheets."""
    bom: list[dict] = []
    for sheet_file, sheet in sheets.items():
        for comp in sheet.components:
            bom.append({
                "ref": comp.ref,
                "value": comp.value,
                "lib_id": comp.lib_id,
                "footprint": comp.footprint,
                "sheet": sheet.title,
            })
    return bom


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compose_design(
    spec: DesignSpec,
    patterns_path: Path | None = None,
) -> GeneratedProject:
    """Generate a complete KiCad project from a design spec.

    Steps:
    1. Load wiring patterns for the MCU family
    2. For each peripheral, look up the wiring pattern for MCU<->peripheral
    3. Generate hierarchical schematic:
       - Root sheet with sub-sheet references
       - Power sheet (regulator + bypass caps from decoupling rules)
       - MCU sheet (MCU symbol + decoupling caps)
       - One sheet per peripheral (peripheral + supporting components)
    4. Wire using patterns: create net labels matching the learned patterns
    5. Add decoupling caps from rules
    6. Return all files + BOM + notes

    Args:
        spec: Complete design specification.
        patterns_path: Path to wiring_patterns.json (defaults to data/patterns/).

    Returns:
        GeneratedProject with all files, BOM, notes, and warnings.
    """
    p_path = patterns_path or _DEFAULT_PATTERNS_PATH
    patterns = _load_wiring_patterns(p_path)

    wiring_notes: list[str] = []
    warnings: list[str] = []

    # Shared cap ref counter to avoid collisions across sheets
    # Start at 10 to leave room for power sheet caps (C1, C2)
    ref_counter = [10]

    # Build sheets dict for hierarchical project
    sheets: dict[str, SheetContent] = {}

    # 1. Power sheet
    power_sheet = _generate_power_sheet(spec)
    sheets["power.kicad_sch"] = power_sheet
    wiring_notes.append(
        f"Power: {spec.power.regulator} regulator from {spec.power.input_source} "
        f"to {spec.power.voltage}"
    )

    # 2. MCU sheet
    mcu_sheet = _generate_mcu_sheet(spec, patterns, ref_counter)
    sheets["mcu.kicad_sch"] = mcu_sheet
    wiring_notes.append(
        f"MCU: {spec.mcu_chip} ({spec.mcu_family}) with decoupling caps"
    )

    # 3. Peripheral sheets
    voltage_net = f"+{spec.power.voltage}"
    for i, peripheral in enumerate(spec.peripherals):
        periph_family = extract_ic_family(peripheral.chip)
        pattern = _find_pattern(
            patterns, spec.mcu_family, periph_family, peripheral.interface,
        )

        if pattern:
            iface = pattern.get("interface_type", "unknown")
            projects = pattern.get("seen_in_projects", [])
            wiring_notes.append(
                f"Peripheral '{peripheral.name}' ({peripheral.chip}): "
                f"wired using {iface} pattern from {projects}"
            )
        else:
            warnings.append(
                f"No wiring pattern found for {spec.mcu_family} <-> "
                f"{peripheral.chip} ({peripheral.interface}). "
                f"Using default {peripheral.interface} net names."
            )

        periph_sheet = _generate_peripheral_sheet(
            peripheral, pattern, i, ref_counter, voltage_net,
        )
        filename = f"{peripheral.name.lower().replace(' ', '_')}.kicad_sch"
        sheets[filename] = periph_sheet

    # Generate hierarchical project files
    project_files = generate_hierarchical_project(sheets, root_title=spec.name)

    # Collect BOM
    bom = _collect_bom(sheets)

    return GeneratedProject(
        name=spec.name,
        files=project_files,
        bom=bom,
        wiring_notes=wiring_notes,
        warnings=warnings,
    )
