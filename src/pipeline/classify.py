"""Component and net classification utilities.

Single source of truth for: power net detection, component classification
(IC vs passive vs connector vs mechanical vs switch), IC family extraction,
passive type classification, footprint reference extraction, and KiCad
version detection.
"""

from __future__ import annotations

import re
from pathlib import Path


# ── Power net detection ──────────────────────────────────────────────────

_POWER_NET_PATTERN = re.compile(
    r"^("
    r"[+-]?\d+(\.\d+)?V\d*"           # +3V3, +5V, -12V, 3V3, 1V8
    r"|V(CC|DD|SS|EE|BAT|BUS|IN|OUT|REF|REG)"  # VCC, VDD, VSS, etc.
    r"|GND|AGND|DGND|PGND|GNDREF|GNDA|GNDD"    # ground variants
    r"|PWR_FLAG"
    r"|unconnected-.*"                 # unconnected pads (from subcircuits.py)
    r")$",
    re.IGNORECASE,
)


def is_power_net(name: str) -> bool:
    """Check if a net name is a power/ground net.

    Also returns True for empty net names (unconnected pads).
    """
    return name == "" or bool(_POWER_NET_PATTERN.match(name))


# ── Component classification ─────────────────────────────────────────────

class ComponentType:
    """String constants for component classification."""
    IC = "ic"
    PASSIVE = "passive"
    CONNECTOR = "connector"
    MECHANICAL = "mechanical"
    SWITCH = "switch"
    UNKNOWN = "unknown"


# Patterns for passive detection via lib_id
_PASSIVE_LIB_RE = re.compile(
    r"Device:(R|C|L|R_Small|C_Small|L_Small|C_Polarized|R_Pack|C_Pack|Ferrite_Bead)",
    re.IGNORECASE,
)

# Patterns for passive detection via footprint name
_PASSIVE_FP_RE = re.compile(
    r"R_\d|C_\d|L_\d|R_Pack|C_Pack|R_Array|C_Array",
    re.IGNORECASE,
)

# Reference designator prefixes for passives
_PASSIVE_REF_RE = re.compile(r"^(R|C|L|FB)\d+$")

# Connector patterns
_CONNECTOR_LIB_RE = re.compile(
    r"Connector:|Connector_Generic:|Connector_USB:|Connector_RJ:"
    r"|Connector_Generic_MountingPin:",
    re.IGNORECASE,
)
_CONNECTOR_FP_RE = re.compile(
    r"Conn_|USB_|RJ45|PinHeader|PinSocket|Jack_|Barrel_Jack",
    re.IGNORECASE,
)
_CONNECTOR_REF_RE = re.compile(r"^J\d+$")

# Additional connector detection: part name (after colon) contains connector keywords
_CONNECTOR_PART_RE = re.compile(
    r"(?:^|:)(?:Conn_|CONN_|Connector_|JAMMA|Arduino_.*Shield|.*_Connector$|.*_conn)",
    re.IGNORECASE,
)

# Mechanical patterns (mounting holes, test points, fiducials)
_MECHANICAL_LIB_RE = re.compile(
    r"MountingHole|TestPoint|Fiducial",
    re.IGNORECASE,
)
_MECHANICAL_FP_RE = re.compile(
    r"MountingHole|TestPoint|Fiducial",
    re.IGNORECASE,
)
_MECHANICAL_REF_RE = re.compile(r"^(H|TP|FID|MH)\d+$", re.IGNORECASE)

# Switch patterns (keyboard switches, general switches)
_SWITCH_LIB_RE = re.compile(
    r"Switch:|Key:|MX|Choc|Cherry",
    re.IGNORECASE,
)
_SWITCH_FP_RE = re.compile(
    r"SW_|Key_|MX[-_]|Choc|Cherry",
    re.IGNORECASE,
)
_SWITCH_REF_RE = re.compile(r"^(SW|K)\d+$", re.IGNORECASE)


def classify_component(
    lib_id: str,
    footprint: str = "",
    ref: str = "",
    pad_count: int = 0,
) -> str:
    """Classify a component into IC, passive, connector, mechanical, or switch.

    Uses lib_id patterns, footprint patterns, reference prefix, and pad count.
    Returns a ComponentType string.
    """
    # Mechanical first — these should never be classified as anything else
    if _MECHANICAL_LIB_RE.search(lib_id):
        return ComponentType.MECHANICAL
    if _MECHANICAL_FP_RE.search(footprint):
        return ComponentType.MECHANICAL
    if ref and _MECHANICAL_REF_RE.match(ref):
        return ComponentType.MECHANICAL

    # Switches
    if _SWITCH_LIB_RE.search(lib_id):
        return ComponentType.SWITCH
    if _SWITCH_FP_RE.search(footprint):
        return ComponentType.SWITCH
    if ref and _SWITCH_REF_RE.match(ref):
        return ComponentType.SWITCH

    # Connectors
    if _CONNECTOR_LIB_RE.search(lib_id):
        return ComponentType.CONNECTOR
    if _CONNECTOR_PART_RE.search(lib_id):
        return ComponentType.CONNECTOR
    if _CONNECTOR_FP_RE.search(footprint):
        return ComponentType.CONNECTOR
    if ref and _CONNECTOR_REF_RE.match(ref):
        return ComponentType.CONNECTOR

    # Passives
    if _PASSIVE_LIB_RE.search(lib_id):
        return ComponentType.PASSIVE
    if _PASSIVE_FP_RE.search(footprint):
        return ComponentType.PASSIVE
    if ref and _PASSIVE_REF_RE.match(ref):
        return ComponentType.PASSIVE

    # IC: anything with enough pins that isn't one of the above
    # Also check for common IC lib_id patterns
    if _is_ic_lib_id(lib_id):
        return ComponentType.IC
    if pad_count > 4 and ref and re.match(r"^U\d+$", ref):
        return ComponentType.IC

    # Heuristic: components with many pads are likely ICs
    if pad_count > 8:
        return ComponentType.IC

    return ComponentType.UNKNOWN


# IC lib_id patterns
_IC_LIB_RE = re.compile(
    r"MCU_|Regulator_|Driver_|Sensor_|Interface_|Timer_|Amplifier_|Comparator_"
    r"|Memory_|FPGA_|DSP_|CPU_|RF_Module:|Power_Management:",
    re.IGNORECASE,
)


def _is_ic_lib_id(lib_id: str) -> bool:
    """Check if a lib_id indicates an IC."""
    return bool(_IC_LIB_RE.search(lib_id))


def is_passive(lib_id: str, footprint: str = "", ref: str = "") -> bool:
    """Convenience: is this a passive component (R, C, L, FB)?"""
    return classify_component(lib_id, footprint, ref) == ComponentType.PASSIVE


def is_ic(
    lib_id: str, footprint: str = "", ref: str = "", pad_count: int = 0
) -> bool:
    """Convenience: is this an IC (MCU, regulator, driver, etc.)?"""
    return classify_component(lib_id, footprint, ref, pad_count) == ComponentType.IC


# ── Passive type classification ──────────────────────────────────────────

def classify_passive_type(
    lib_id: str, footprint: str = "", ref: str = ""
) -> str:
    """Return 'R', 'C', 'L', 'FB', or 'passive' for a passive component."""
    lib_lower = lib_id.lower()
    fp_lower = footprint.lower()

    # Check lib_id — require the letter to be followed by _ or end-of-string
    # to avoid "Device:Crystal" matching as capacitor.
    # Match both "Device:" and "passive:" library prefixes.
    if re.search(r"(?:device|passive):ferrite_bead", lib_lower):
        return "FB"
    if re.search(r"(?:device|passive):r(?:_|$)", lib_lower):
        return "R"
    if re.search(r"(?:device|passive):c(?:_|$)", lib_lower):
        return "C"
    if re.search(r"(?:device|passive):l(?:_|$)", lib_lower):
        return "L"

    # Check footprint
    if "r_" in fp_lower or "r_pack" in fp_lower or "r_array" in fp_lower:
        return "R"
    if "c_" in fp_lower or "c_pack" in fp_lower or "c_array" in fp_lower:
        return "C"
    if "l_" in fp_lower:
        return "L"

    # Fall back to reference designator prefix
    if ref:
        m = re.match(r"^(R|C|L|FB)", ref)
        if m:
            return m.group(1)

    return "passive"


# ── IC family extraction ────────────────────────────────────────────────

def extract_ic_family(lib_id: str, value: str = "") -> str:
    """Extract IC family from lib_id.

    Examples:
        'MCU_ST_STM32F7:STM32F722RETx' -> 'STM32F7'
        'MCU_ST_STM32F4:STM32F411CEU6' -> 'STM32F4'
        'espressif:ESP32-S3' -> 'ESP32-S3'
        'RF_Module:ESP32-WROOM-32' -> 'ESP32'
        'MCU_Microchip_ATmega:ATmega328P-AU' -> 'ATmega'
        'MCU_NXP_LPC:LPC1768' -> 'LPC1768'
        'MCU_RaspberryPi:RP2040' -> 'RP2040'
        'Regulator_Linear:AP2112K-3.3' -> 'AP2112'
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


# ── Footprint reference extraction ──────────────────────────────────────

def get_footprint_ref(fp) -> str:
    """Extract reference designator from a kiutils Footprint object.

    Handles both KiCad 8/9 (properties dict) and KiCad 6/7 (graphicItems).
    """
    # KiCad 8/9: properties is a dict with "Reference" key
    if isinstance(fp.properties, dict) and "Reference" in fp.properties:
        return fp.properties["Reference"]

    # KiCad 6/7: graphicItems contains FpText with type='reference'
    for gi in getattr(fp, "graphicItems", []):
        if getattr(gi, "type", None) == "reference":
            return getattr(gi, "text", "")

    return ""


# ── Version detection ────────────────────────────────────────────────────

def detect_kicad_version(path: Path) -> int | None:
    """Read first 500 bytes, extract (version NNNN) token.

    Works with both .kicad_sch and .kicad_pcb files.
    """
    try:
        text = path.read_text(errors="replace")[:500]
        match = re.search(r"\(version\s+(\d+)\)", text)
        return int(match.group(1)) if match else None
    except OSError:
        return None
