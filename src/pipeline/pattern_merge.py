"""Pattern merging and normalization for wiring patterns.

Merges near-duplicate wiring patterns that differ only in net naming
conventions. The key insight: "SPI1_MOSI", "HSPI_MOSI", "GYRO_MOSI",
and "MOSI" all represent the same logical signal.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

# ── Signal name normalization ──────────────────────────────────────────


# Prefixes to strip (order matters: longer/more-specific first)
_STRIP_PREFIXES = [
    # Numbered bus prefixes
    "SPI1_",
    "SPI2_",
    "SPI3_",
    "SPI4_",
    "I2C1_",
    "I2C2_",
    "I2C3_",
    "UART1_",
    "UART2_",
    "UART3_",
    "USART1_",
    "USART2_",
    "USART3_",
    # Generic bus prefixes
    "HSPI_",
    "VSPI_",
    "SPI_",
    "I2C_",
    "UART_",
    "USART_",
    # Voltage prefixes
    "3V3_SPI_",
    "3V3_",
    "5V_",
    "1V8_",
    # Peripheral-specific prefixes
    "FLASH_",
    "ETH_",
    "WIFI_",
    "BMS_",
    "GYRO_",
    "BARO_",
    "ADC_",
    "AFE_",
    "INA_",
    "AUDIO_",
    "CODEC_",
    "PICO_",
    "BMC_",
    "MCU_",
    "MCU-",
    "FTDI_",
    "FPDI_",
    "GPDI_",
    "CAM_",
    "CAM.",
    "UC_",
    "CANBUS_",
    "E_",
]

# Canonical signal name mappings
_SIGNAL_ALIASES = {
    # SPI
    "SCLK": "SCK",
    "SPI_SCLK": "SCK",
    "SDI": "MOSI",
    "SPI_SDI": "MOSI",
    "DIN": "MOSI",
    "SDO": "MISO",
    "SPI_SDO": "MISO",
    "DOUT": "MISO",
    "NCS": "CS",
    "CSN": "CS",
    "SS": "CS",
    "NSS": "CS",
    # I2C
    "IO8_SCL": "SCL",
    "IO10_SDA": "SDA",
    # UART
    "TXD": "TX",
    "RXD": "RX",
}

# Recognized signal types for structural fingerprinting
_KNOWN_SIGNALS = frozenset(
    {
        # SPI
        "SCK",
        "MOSI",
        "MISO",
        "CS",
        # I2C
        "SDA",
        "SCL",
        # UART
        "TX",
        "RX",
        # Common auxiliary
        "INT",
        "INT1",
        "INT2",
        "RST",
        "RESET",
        "EN",
        "WP",
        "HOLD",
        "NHOLD",
        "NWP",
        "NRESET",
        "NRST",
        # USB
        "DP",
        "DM",
        "D+",
        "D-",
        "VBUS",
        "ID",
        # Ethernet
        "MDC",
        "MDIO",
        "TXD0",
        "TXD1",
        "RXD0",
        "RXD1",
        "TX_EN",
        "REF_CLK",
        "CRS_DV",
        # Audio codec
        "MCLK",
        "BCLK",
        "WCLK",
        "LRCLK",
        "DPLAY",
        "DREC",
        "ADC_DATA",
        "DAC_DAT",
        "BIT_CLK",
        "ADC_LR",
    }
)


def normalize_net_name(name: str) -> str:
    """Normalize a net name for comparison.

    Strips project-specific prefixes, hierarchical paths, and maps
    aliases to canonical names.

    Examples:
        SPI1_MOSI -> MOSI
        HSPI_MOSI -> MOSI
        /audio/codec.sda -> SDA
        GYRO_SCK -> SCK
        3V3_SPI_SCLK -> SCK
        FLASH_CS -> CS
        SCLK -> SCK
        SDI -> MOSI
        SDO -> MISO
    """
    result = name.strip().upper()

    # Strip hierarchical path prefixes: /audio/codec.sda -> codec.sda
    if "/" in result:
        result = result.rsplit("/", 1)[-1]

    # Strip dot-separated prefixes: codec.sda -> SDA
    if "." in result:
        result = result.rsplit(".", 1)[-1]

    # Strip tilde markup: ~{reset} -> RESET
    result = re.sub(r"~\{(\w+)\}", r"\1", result)

    # Strip known prefixes repeatedly (a name like BARO_I2C_SDA needs
    # two passes: BARO_ -> I2C_SDA, then I2C_ -> SDA)
    changed = True
    while changed:
        changed = False
        for prefix in _STRIP_PREFIXES:
            if result.startswith(prefix):
                result = result[len(prefix) :]
                changed = True
                break

    # Strip USB_ prefix for USB signal names
    if result.startswith("USB_"):
        result = result[4:]

    # Apply alias mappings
    if result in _SIGNAL_ALIASES:
        result = _SIGNAL_ALIASES[result]

    return result


def _classify_signal(normalized_name: str) -> str:
    """Classify a normalized signal name into a signal type category.

    Returns the signal type (e.g., 'SCK', 'MOSI') if recognized,
    or 'other' for unrecognized signals.
    """
    if normalized_name in _KNOWN_SIGNALS:
        return normalized_name
    return "other"


def _structural_fingerprint(connections: list[dict], interface_type: str) -> str:
    """Create a structural fingerprint from connections.

    The fingerprint captures the interface-defining signals present, not
    the specific net names. For known interfaces (SPI, I2C, UART, USB,
    RMII), only the recognized bus signals contribute to the fingerprint.
    Auxiliary signals (interrupts, resets, GPIOs) are counted but not
    individually distinguished, so patterns with different auxiliary
    wiring but the same bus structure merge together.

    For unknown/GPIO interfaces, we use connection count as the
    fingerprint since there are no bus signals to match on.
    """
    known_signals = []
    other_count = 0

    for conn in connections:
        sig = normalize_net_name(conn["net_name"])
        category = _classify_signal(sig)
        if category == "other":
            other_count += 1
        else:
            known_signals.append(category)

    # For known bus interfaces, fingerprint on CORE bus signals only.
    # Auxiliary signals (interrupts, resets, WP, HOLD, etc.) are ignored
    # so that patterns with the same bus structure but different
    # auxiliary wiring merge together.
    _CORE_BUS_SIGNALS: dict[str, frozenset[str]] = {
        "SPI": frozenset({"SCK", "MOSI", "MISO", "CS"}),
        "I2C": frozenset({"SDA", "SCL"}),
        "UART": frozenset({"TX", "RX"}),
        "USB": frozenset({"DP", "DM", "D+", "D-", "VBUS", "ID"}),
        "RMII": frozenset(
            {
                "MDC",
                "MDIO",
                "TXD0",
                "TXD1",
                "RXD0",
                "RXD1",
                "TX_EN",
                "REF_CLK",
                "CRS_DV",
            }
        ),
    }
    if interface_type in _CORE_BUS_SIGNALS:
        core = _CORE_BUS_SIGNALS[interface_type]
        bus_sigs = sorted(s for s in set(known_signals) if s in core)
        return f"{interface_type}:{'+'.join(bus_sigs) if bus_sigs else 'bare'}"

    # For GPIO/unknown: just use total connection count
    total = len(connections)
    return f"{interface_type}:n{total}"


# ── IC family normalization ────────────────────────────────────────────


# Map of specific families to normalized base families
_FAMILY_NORMALIZATIONS = {
    # STM32 subfamilies
    "STM32F": "STM32",
    "STM32G": "STM32",
    "STM32H": "STM32",
    "STM32L": "STM32",
    "STM32U": "STM32",
    "STM32W": "STM32",
    # ESP32 subfamilies
    "ESP32-S2": "ESP32",
    "ESP32-S3": "ESP32",
    "ESP32-C3": "ESP32",
    "ESP32-C6": "ESP32",
    "ESP32-H2": "ESP32",
    # Winbond flash
    "W25Q": "W25x_FLASH",
    "W25N": "W25x_FLASH",
    # TI current/power monitors
    "INA180A": "INAx",
    "INA229": "INAx",
    "INA237": "INAx",
    "INA260": "INAx",
    # InvenSense IMUs
    "ICP-42688-P": "ICM_IMU",
    "IC_ICM-42670-P": "ICM_IMU",
    # USB-UART bridges
    "CP2102N": "CP21x",
    "CH341": "USB_UART",
    "FT231X": "USB_UART",
    # USB protection
    "USBLC6": "USB_PROT",
    "TPD4E": "USB_PROT",
    "IP4220CZ": "USB_PROT",
    # ESD protection
    "SRV05": "ESD_PROT",
    "SP720": "ESD_PROT",
    # LDOs
    "AP2112K": "AP21xx_LDO",
    "AP2125K": "AP21xx_LDO",
    "AP2127K": "AP21xx_LDO",
    # Battery chargers
    "MCP73831": "MCP738x",
    "MCP73831T": "MCP738x",
    # TI buck converters
    "TPS62A": "TPS62x",
    "TLV62569DBV": "TPS62x",
    # SPI flash (generic SOIC packages often used for flash/EEPROM)
    "SOA008": "SPI_FLASH",
    # DRAM
    "W958D": "DRAM",
    "W9825G": "DRAM",
    # Audio codecs
    "TLV320AIC": "AUDIO_CODEC",
    "PCM3060": "AUDIO_CODEC",
    "PCM5102A": "AUDIO_CODEC",
    # RTC
    "PCF8563T": "RTC",
    "DS1307Z": "RTC",
    # Barometer/pressure
    "BMP388": "BARO",
    # Level shifters / buffers
    "TXB0104": "LEVEL_SHIFT",
    "TXS0102DCU": "LEVEL_SHIFT",
    "SN74LVC": "LEVEL_SHIFT",
    "SN74AHC": "LEVEL_SHIFT",
    # USB mux/switch
    "TS3USB": "USB_MUX",
    "FSUSB42MUX": "USB_MUX",
    # Motor driver
    "TMC2209": "MOTOR_DRV",
    # CAN transceiver
    "MCP2562": "CAN_XCVR",
    "SN65HVD": "CAN_XCVR",
    # USB-C PD controller
    "FUSB302BMPX": "USB_PD",
    # Power switch
    "SY6280": "POWER_SW",
    "AP2552FDC": "POWER_SW",
    # LDO - additional
    "MCP1824T": "LDO",
    "RT9080": "LDO",
    "LP2985": "LDO",
    # Buck additional
    "TPS54335ADRCR": "BUCK",
    "TPS40305": "BUCK",
    "SY7200A": "BUCK",
    "SY8088": "BUCK",
    "AP1511B": "BUCK",
    "AP2502": "BUCK",
    # Boost/buck-boost
    "TPS63001": "BOOST",
    # Magnetic encoder
    "AS5600": "MAG_ENCODER",
    # IO expander
    "MCP23S": "IO_EXPANDER",
    "TCA6416APWR": "IO_EXPANDER",
}


def normalize_ic_family(family: str) -> str:
    """Normalize an IC family name for merge grouping.

    Maps specific subfamilies to their base family for broader matching.
    Tries exact match first, then longest prefix match.
    """
    # Direct lookup
    if family in _FAMILY_NORMALIZATIONS:
        return _FAMILY_NORMALIZATIONS[family]

    # Prefix match: try longest matching prefix first
    best_prefix = ""
    best_value = ""
    for key, value in _FAMILY_NORMALIZATIONS.items():
        if family.startswith(key) and len(key) > len(best_prefix):
            best_prefix = key
            best_value = value
    if best_prefix:
        return best_value

    return family


def _order_pair(family_a: str, family_b: str) -> tuple[str, str]:
    """Order IC pair alphabetically for consistent keys."""
    if family_a <= family_b:
        return family_a, family_b
    return family_b, family_a


# ── Pattern merging ────────────────────────────────────────────────────


def _confidence_from_projects(project_count: int) -> str:
    """Assign confidence based on number of distinct projects."""
    if project_count >= 3:
        return "high"
    elif project_count >= 2:
        return "medium"
    return "low"


def merge_similar_patterns(patterns: list[dict]) -> list[dict]:
    """Merge patterns with same IC families and interface but different net names.

    Grouping key: (normalized_ic_a_family, normalized_ic_b_family,
                    interface_type, structural_fingerprint)

    When patterns merge:
    - sample_count is summed
    - seen_in_projects is unioned
    - confidence is recalculated from unique project count
    - canonical_connections kept from the pattern with most connections
    - All original IC family names are preserved in ic_a_variants / ic_b_variants

    Returns merged patterns sorted by confidence (high first),
    then sample_count descending.
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)

    for p in patterns:
        norm_a = normalize_ic_family(p["ic_a_family"])
        norm_b = normalize_ic_family(p["ic_b_family"])
        ordered_a, ordered_b = _order_pair(norm_a, norm_b)

        fingerprint = _structural_fingerprint(
            p["canonical_connections"], p["interface_type"]
        )

        key = (ordered_a, ordered_b, p["interface_type"], fingerprint)
        groups[key].append(p)

    merged = []
    for (norm_a, norm_b, iface, _fp), group in groups.items():
        # Collect all projects
        all_projects = []
        seen = set()
        for p in group:
            for proj in p["seen_in_projects"]:
                if proj not in seen:
                    all_projects.append(proj)
                    seen.add(proj)

        # Sum sample counts
        total_samples = sum(p["sample_count"] for p in group)

        # Confidence from unique projects
        confidence = _confidence_from_projects(len(all_projects))

        # Canonical connections from the best example (most connections)
        best = max(group, key=lambda p: len(p["canonical_connections"]))

        # Collect IC family variants
        a_variants = sorted(set(p["ic_a_family"] for p in group))
        b_variants = sorted(set(p["ic_b_family"] for p in group))

        merged_pattern = {
            "ic_a_family": norm_a,
            "ic_b_family": norm_b,
            "interface_type": iface,
            "canonical_connections": best["canonical_connections"],
            "seen_in_projects": all_projects,
            "sample_count": total_samples,
            "confidence": confidence,
        }

        # Only add variant fields if there are actual variants
        if len(a_variants) > 1 or a_variants[0] != norm_a:
            merged_pattern["ic_a_variants"] = a_variants
        if len(b_variants) > 1 or b_variants[0] != norm_b:
            merged_pattern["ic_b_variants"] = b_variants

        merged.append(merged_pattern)

    # Sort: high confidence first, then by sample_count descending
    confidence_order = {"high": 0, "medium": 1, "low": 2}
    merged.sort(
        key=lambda p: (confidence_order.get(p["confidence"], 3), -p["sample_count"])
    )

    return merged


# ── Reindexing ─────────────────────────────────────────────────────────


def reindex_patterns(patterns_path: Path, output_path: Path) -> dict:
    """Reload patterns, merge similar ones, recalculate confidence, save.

    Returns a summary dict with before/after counts and confidence breakdown.
    """
    data = json.loads(patterns_path.read_text())
    original_patterns = data["patterns"]

    merged = merge_similar_patterns(original_patterns)

    # Confidence breakdown
    before_conf = defaultdict(int)
    for p in original_patterns:
        before_conf[p["confidence"]] += 1

    after_conf = defaultdict(int)
    for p in merged:
        after_conf[p["confidence"]] += 1

    # Save
    output_data = {
        "pattern_count": len(merged),
        "merge_metadata": {
            "original_count": len(original_patterns),
            "merged_count": len(merged),
            "reduction": len(original_patterns) - len(merged),
        },
        "patterns": merged,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output_data, indent=2) + "\n")

    return {
        "before_count": len(original_patterns),
        "after_count": len(merged),
        "reduction": len(original_patterns) - len(merged),
        "before_confidence": dict(before_conf),
        "after_confidence": dict(after_conf),
    }


if __name__ == "__main__":
    import sys

    patterns_path = Path("data/patterns/wiring_patterns.json")
    output_path = Path("data/patterns/wiring_patterns_merged.json")

    if len(sys.argv) > 1:
        patterns_path = Path(sys.argv[1])
    if len(sys.argv) > 2:
        output_path = Path(sys.argv[2])

    summary = reindex_patterns(patterns_path, output_path)

    print(f"Before: {summary['before_count']} patterns")
    print(f"  Confidence: {summary['before_confidence']}")
    print(f"After:  {summary['after_count']} patterns")
    print(f"  Confidence: {summary['after_confidence']}")
    print(f"Reduction: {summary['reduction']} patterns merged")
    print(f"Output: {output_path}")
