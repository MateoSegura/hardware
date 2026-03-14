"""Inter-IC connection pattern extraction.

Analyzes PCB pad-level net assignments to discover how ICs are wired
to each other. Extracts empirical wiring patterns from real designs.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))

from src.pipeline.board import parse_board
from src.pipeline.classify import (
    classify_component,
    ComponentType,
    extract_ic_family,
    is_power_net,
)
from src.pipeline.models import ParsedBoard


# ── Data classes ────────────────────────────────────────────────────────


@dataclass
class PadConnection:
    """A single pad-to-pad connection between two ICs via a shared net."""

    ic_a_pad: str  # pad number/name on IC A
    ic_b_pad: str  # pad number/name on IC B
    net_name: str  # the net connecting them


@dataclass
class ICPairPattern:
    """Wiring pattern between two IC families."""

    ic_a_family: str  # e.g., "STM32F7"
    ic_b_family: str  # e.g., "ICM-42688"
    ic_a_lib_id: str  # full lib_id example
    ic_b_lib_id: str  # full lib_id example
    interface_type: str  # "SPI", "I2C", "UART", "RMII", "USB", "GPIO", "unknown"
    connections: list[PadConnection]
    project_name: str  # which project this was found in
    confidence: str  # "high" (3+ projects), "medium" (2), "low" (1)


@dataclass
class AggregatedPattern:
    """A wiring pattern aggregated across multiple projects."""

    ic_a_family: str
    ic_b_family: str
    interface_type: str
    canonical_connections: list[PadConnection]  # most common pad mapping
    seen_in_projects: list[str]
    sample_count: int
    confidence: str


# ── Known MCU families (for ordering: MCU first in pair) ────────────────

_MCU_FAMILIES = frozenset([
    "STM32", "ESP32", "RP2040", "RP2350", "ATmega", "ATtiny",
    "nRF52", "nRF53", "LPC", "PIC", "SAMD", "EFM32",
])


def _is_mcu_family(family: str) -> bool:
    """Check if a family string starts with a known MCU prefix."""
    return any(family.upper().startswith(m) for m in _MCU_FAMILIES)


def _order_pair(
    family_a: str, family_b: str
) -> tuple[str, str]:
    """Order IC pair: MCU first, then alphabetical."""
    a_is_mcu = _is_mcu_family(family_a)
    b_is_mcu = _is_mcu_family(family_b)

    if a_is_mcu and not b_is_mcu:
        return family_a, family_b
    if b_is_mcu and not a_is_mcu:
        return family_b, family_a
    # Both MCU or both non-MCU: alphabetical
    if family_a <= family_b:
        return family_a, family_b
    return family_b, family_a


# ── Interface classification ────────────────────────────────────────────


def classify_interface(connections: list[PadConnection]) -> str:
    """Classify the interface type from connection net/pad names.

    SPI: nets matching *SCK*/*MOSI*/*MISO*/*CS* (3-4 signals)
    I2C: nets matching *SDA*/*SCL* (exactly 2 signals)
    UART: nets matching *TX*/*RX* (exactly 2 signals)
    RMII: nets matching *MDC*/*MDIO*/*TXD*/*RXD*/*TX_EN*/*REF_CLK*
    USB: nets matching *D+*/*D-*/*DP*/*DM*
    """
    net_names = {c.net_name.upper() for c in connections}

    # SPI: needs SCK + at least MOSI or MISO
    if any("SCK" in n or "SCLK" in n for n in net_names):
        if any(
            "MOSI" in n or "MISO" in n or "SDI" in n or "SDO" in n
            for n in net_names
        ):
            return "SPI"

    # I2C: needs SDA + SCL
    if any("SDA" in n for n in net_names) and any("SCL" in n for n in net_names):
        return "I2C"

    # UART: TX + RX
    if any("TX" in n for n in net_names) and any("RX" in n for n in net_names):
        return "UART"

    # RMII Ethernet
    if any("RMII" in n or "MDIO" in n or "MDC" in n for n in net_names):
        return "RMII"

    # USB
    if any(
        "USB" in n or "D+" in n or "D-" in n or "DP" in n or "DM" in n
        for n in net_names
    ):
        return "USB"

    # GPIO (single signal connections)
    if len(connections) <= 2:
        return "GPIO"

    return "unknown"


# ── Single-board extraction ─────────────────────────────────────────────


def extract_connections(board: ParsedBoard) -> list[ICPairPattern]:
    """Extract IC-to-IC connections from a single parsed board.

    Algorithm:
    1. Build net_map: {net_name: [(ref, pad_number, lib_id, family), ...]}
       - Only include non-power nets
       - Only include ICs (not passives, connectors, mechanical)
    2. For each signal net with 2+ IC endpoints:
       - Record the pad-to-pad connection between each IC pair
    3. Group connections by IC pair
    4. Classify interface type from net/pad naming patterns
    """
    # Step 1: identify ICs and build net map
    ic_info: dict[str, tuple[str, str, str]] = {}  # ref -> (lib_id, family, value)
    for fp in board.footprints:
        comp_type = classify_component(
            fp.lib_id, footprint="", ref=fp.ref, pad_count=fp.pad_count
        )
        if comp_type != ComponentType.IC:
            continue
        family = extract_ic_family(fp.lib_id, fp.value)
        ic_info[fp.ref] = (fp.lib_id, family, fp.value)

    # Build net map: net_name -> [(ref, pad_number)]
    net_map: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for fp in board.footprints:
        if fp.ref not in ic_info:
            continue
        for pad in fp.pads:
            # Skip power/ground nets and unconnected pads
            if not pad.net_name or pad.net_number == 0:
                continue
            if is_power_net(pad.net_name):
                continue
            net_map[pad.net_name].append((fp.ref, pad.number))

    # Step 2: for each net with 2+ IC endpoints, record connections
    # Group by IC pair (ref_a, ref_b)
    pair_connections: dict[tuple[str, str], list[PadConnection]] = defaultdict(list)

    for net_name, endpoints in net_map.items():
        # Get unique IC refs on this net
        unique_refs = list(dict.fromkeys(ep[0] for ep in endpoints))
        if len(unique_refs) < 2:
            continue

        # For each pair of ICs on this net
        for i in range(len(unique_refs)):
            for j in range(i + 1, len(unique_refs)):
                ref_a, ref_b = unique_refs[i], unique_refs[j]
                # Normalize order by ref
                if ref_a > ref_b:
                    ref_a, ref_b = ref_b, ref_a

                # Find pad numbers for each ref on this net
                pads_a = [ep[1] for ep in endpoints if ep[0] == ref_a]
                pads_b = [ep[1] for ep in endpoints if ep[0] == ref_b]

                # Use first pad from each (typically one pad per IC per net)
                pair_connections[(ref_a, ref_b)].append(
                    PadConnection(
                        ic_a_pad=pads_a[0],
                        ic_b_pad=pads_b[0],
                        net_name=net_name,
                    )
                )

    # Step 3: build ICPairPattern for each pair
    project_name = board.file_path.parent.name
    # Try to get the repo-style name from path
    for part in board.file_path.parts:
        if "__" in part:
            project_name = part
            break

    patterns = []
    for (ref_a, ref_b), conns in pair_connections.items():
        lib_id_a, family_a, _ = ic_info[ref_a]
        lib_id_b, family_b, _ = ic_info[ref_b]

        # Order: MCU first, then alphabetical
        ordered_a, ordered_b = _order_pair(family_a, family_b)
        if ordered_a == family_b:
            # Swap everything
            ref_a, ref_b = ref_b, ref_a
            lib_id_a, lib_id_b = lib_id_b, lib_id_a
            family_a, family_b = family_b, family_a
            conns = [
                PadConnection(
                    ic_a_pad=c.ic_b_pad,
                    ic_b_pad=c.ic_a_pad,
                    net_name=c.net_name,
                )
                for c in conns
            ]

        iface = classify_interface(conns)

        patterns.append(
            ICPairPattern(
                ic_a_family=ordered_a,
                ic_b_family=ordered_b,
                ic_a_lib_id=lib_id_a,
                ic_b_lib_id=lib_id_b,
                interface_type=iface,
                connections=conns,
                project_name=project_name,
                confidence="low",  # single project, set during aggregation
            )
        )

    return patterns


# ── Multi-project extraction ────────────────────────────────────────────


def _find_pcb_files(raw_dir: Path) -> list[tuple[str, Path]]:
    """Find all .kicad_pcb files grouped by project directory."""
    results = []
    for project_dir in sorted(raw_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        for pcb_file in sorted(project_dir.rglob("*.kicad_pcb")):
            results.append((project_dir.name, pcb_file))
    return results


def _board_has_target_family(
    board: ParsedBoard, target_families: list[str]
) -> bool:
    """Check if a board contains any IC from the target families."""
    for fp in board.footprints:
        comp_type = classify_component(
            fp.lib_id, footprint="", ref=fp.ref, pad_count=fp.pad_count
        )
        if comp_type != ComponentType.IC:
            continue
        family = extract_ic_family(fp.lib_id, fp.value)
        for target in target_families:
            if family.upper().startswith(target.upper()):
                return True
    return False


def extract_all_connections(
    raw_dir: Path,
    target_families: list[str] | None = None,
) -> list[ICPairPattern]:
    """Extract connections from all projects, optionally filtered by MCU family.

    If target_families is provided (e.g., ["STM32", "ESP32"]),
    only process projects containing those MCU families.
    """
    all_patterns = []
    pcb_files = _find_pcb_files(raw_dir)

    for project_name, pcb_path in pcb_files:
        try:
            board = parse_board(pcb_path)
        except Exception:
            continue

        # Filter by target families if specified
        if target_families and not _board_has_target_family(board, target_families):
            continue

        try:
            patterns = extract_connections(board)
            all_patterns.extend(patterns)
        except Exception:
            continue

    return all_patterns


# ── Aggregation ─────────────────────────────────────────────────────────


def aggregate_patterns(patterns: list[ICPairPattern]) -> list[AggregatedPattern]:
    """Aggregate IC pair patterns across projects.

    Groups by (ic_a_family, ic_b_family, interface_type), finds canonical
    connections, counts occurrences, assigns confidence levels.
    """
    # Group by (family_a, family_b, interface)
    groups: dict[tuple[str, str, str], list[ICPairPattern]] = defaultdict(list)
    for p in patterns:
        key = (p.ic_a_family, p.ic_b_family, p.interface_type)
        groups[key].append(p)

    aggregated = []
    for (fam_a, fam_b, iface), group in groups.items():
        projects = list(dict.fromkeys(p.project_name for p in group))
        count = len(group)

        # Confidence based on number of distinct projects
        if len(projects) >= 3:
            confidence = "high"
        elif len(projects) >= 2:
            confidence = "medium"
        else:
            confidence = "low"

        # Canonical connections: use the instance with the most connections
        best = max(group, key=lambda p: len(p.connections))
        canonical = best.connections

        aggregated.append(
            AggregatedPattern(
                ic_a_family=fam_a,
                ic_b_family=fam_b,
                interface_type=iface,
                canonical_connections=canonical,
                seen_in_projects=projects,
                sample_count=count,
                confidence=confidence,
            )
        )

    # Sort by confidence (high first), then sample count descending
    confidence_order = {"high": 0, "medium": 1, "low": 2}
    aggregated.sort(key=lambda a: (confidence_order.get(a.confidence, 3), -a.sample_count))

    return aggregated


# ── Serialization ───────────────────────────────────────────────────────


def _pattern_to_dict(p: AggregatedPattern) -> dict:
    """Convert an AggregatedPattern to a JSON-serializable dict."""
    return {
        "ic_a_family": p.ic_a_family,
        "ic_b_family": p.ic_b_family,
        "interface_type": p.interface_type,
        "canonical_connections": [
            {"ic_a_pad": c.ic_a_pad, "ic_b_pad": c.ic_b_pad, "net_name": c.net_name}
            for c in p.canonical_connections
        ],
        "seen_in_projects": p.seen_in_projects,
        "sample_count": p.sample_count,
        "confidence": p.confidence,
    }


def save_patterns(patterns: list[AggregatedPattern], output_path: Path) -> None:
    """Save aggregated patterns to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "pattern_count": len(patterns),
        "patterns": [_pattern_to_dict(p) for p in patterns],
    }
    output_path.write_text(json.dumps(data, indent=2) + "\n")


def load_patterns(path: Path) -> list[AggregatedPattern]:
    """Load aggregated patterns from JSON."""
    data = json.loads(path.read_text())
    patterns = []
    for p in data["patterns"]:
        conns = [
            PadConnection(
                ic_a_pad=c["ic_a_pad"],
                ic_b_pad=c["ic_b_pad"],
                net_name=c["net_name"],
            )
            for c in p["canonical_connections"]
        ]
        patterns.append(
            AggregatedPattern(
                ic_a_family=p["ic_a_family"],
                ic_b_family=p["ic_b_family"],
                interface_type=p["interface_type"],
                canonical_connections=conns,
                seen_in_projects=p["seen_in_projects"],
                sample_count=p["sample_count"],
                confidence=p["confidence"],
            )
        )
    return patterns
