"""Subcircuit detection — identifies IC + passive groupings from PCB net connectivity.

A subcircuit is an IC (pin_count > 8) plus all passives connected to it
within 1 net hop. Uses PCB pad-level net assignments for exact connectivity.
"""

from __future__ import annotations

import hashlib
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))

from kiutils.board import Board

from .models import Subcircuit, SubcircuitCluster

# Minimum pin count to qualify as an IC (center of a subcircuit).
IC_PIN_THRESHOLD = 8

# Patterns that identify passive component lib_ids or footprints.
_PASSIVE_LIB_PATTERNS = re.compile(
    r"Device:(R|C|L|R_Small|C_Small|L_Small|C_Polarized|R_Pack|C_Pack)"
    r"|Connector:|TestPoint:|MountingHole:",
    re.IGNORECASE,
)

_PASSIVE_FP_PATTERNS = re.compile(
    r"R_\d|C_\d|L_\d|R_Pack|C_Pack|R_Array|C_Array",
    re.IGNORECASE,
)

# Components that should never be subcircuit centers (mechanical, non-electrical).
_EXCLUDED_CENTER_LIB = re.compile(
    r"MountingHole|TestPoint|Fiducial"
    r"|Switch|Key|MX|Choc|Cherry",
    re.IGNORECASE,
)
_EXCLUDED_CENTER_FP = re.compile(
    r"MountingHole|TestPoint|Fiducial"
    r"|SW_|Key_|MX[-_]|Choc|Cherry",
    re.IGNORECASE,
)
_EXCLUDED_CENTER_REF = re.compile(
    r"^(H|TP|FID|MH)\d",
    re.IGNORECASE,
)

# Net names to exclude (power/ground nets connect everything).
_POWER_NET_PATTERN = re.compile(
    r"^("
    r"[+-]?\d+(\.\d+)?V\d*"
    r"|V(CC|DD|SS|EE|BAT|BUS|IN|OUT|REF|REG)"
    r"|GND|AGND|DGND|PGND|GNDREF|GNDA|GNDD"
    r"|PWR_FLAG"
    r"|unconnected-.*"
    r")$",
    re.IGNORECASE,
)


def _get_ref_from_footprint(fp) -> str:
    """Extract reference designator from a kiutils Footprint object."""
    if isinstance(fp.properties, dict) and "Reference" in fp.properties:
        return fp.properties["Reference"]
    for gi in getattr(fp, "graphicItems", []):
        if getattr(gi, "type", None) == "reference":
            return getattr(gi, "text", "")
    return ""


def _is_passive(lib_id: str, footprint_name: str, ref: str = "") -> bool:
    """Check if a component is a passive (R, C, L).

    Uses lib_id, footprint name, and reference designator prefix as signals.
    """
    if _PASSIVE_LIB_PATTERNS.search(lib_id):
        # Connectors, test points, and mounting holes are not passives
        if re.search(r"Connector:|TestPoint:|MountingHole:", lib_id, re.IGNORECASE):
            return False
        return True
    if _PASSIVE_FP_PATTERNS.search(footprint_name):
        return True
    # Fall back to reference designator prefix (R1, C42, L3, FB1)
    if ref and re.match(r"^(R|C|L|FB)\d+$", ref):
        return True
    return False


def _is_excluded_center(lib_id: str, fp_name: str, ref: str) -> bool:
    """Check if a component should be excluded as a subcircuit center.

    Excludes mounting holes, test points, fiducials, keyboard switches,
    and other mechanical/non-electrical components.
    """
    if _EXCLUDED_CENTER_LIB.search(lib_id):
        return True
    if _EXCLUDED_CENTER_FP.search(fp_name):
        return True
    if ref and _EXCLUDED_CENTER_REF.match(ref):
        return True
    return False


def _is_power_net(name: str) -> bool:
    return bool(_POWER_NET_PATTERN.match(name)) or name == ""


def _build_connectivity(board: Board) -> tuple[
    dict[str, list[str]],   # ref -> list of net names
    dict[str, list[str]],   # net_name -> list of refs
    dict[str, str],          # ref -> lib_id
    dict[str, str],          # ref -> footprint entry name
    dict[str, int],          # ref -> pad_count
    dict[str, str],          # ref -> value (from properties or graphicItems)
]:
    """Build component-to-net and net-to-component maps from PCB pad data."""
    ref_to_nets: dict[str, list[str]] = defaultdict(list)
    net_to_refs: dict[str, list[str]] = defaultdict(list)
    ref_to_lib_id: dict[str, str] = {}
    ref_to_fp_name: dict[str, str] = {}
    ref_to_pad_count: dict[str, int] = {}
    ref_to_value: dict[str, str] = {}

    for fp in board.footprints:
        ref = _get_ref_from_footprint(fp)
        if not ref:
            continue

        ref_to_lib_id[ref] = fp.libId or ""
        ref_to_fp_name[ref] = fp.entryName or ""
        ref_to_pad_count[ref] = len(fp.pads)

        # Get value
        if isinstance(fp.properties, dict):
            ref_to_value[ref] = fp.properties.get("Value", "")
        else:
            # Fall back to graphicItems
            for gi in getattr(fp, "graphicItems", []):
                if getattr(gi, "type", None) == "value":
                    ref_to_value[ref] = getattr(gi, "text", "")
                    break

        seen_nets = set()
        for pad in fp.pads:
            net = getattr(pad, "net", None)
            if net and net.name and net.name not in seen_nets:
                seen_nets.add(net.name)
                ref_to_nets[ref].append(net.name)
                net_to_refs[net.name].append(ref)

    return ref_to_nets, net_to_refs, ref_to_lib_id, ref_to_fp_name, ref_to_pad_count, ref_to_value


def _compute_fingerprint(
    center_lib_id: str,
    supporting: list[tuple[str, str]],  # list of (passive_type, passive_value)
) -> str:
    """Compute a deterministic fingerprint for a subcircuit topology.

    The fingerprint is based on the center IC's lib_id and a sorted count
    of passive component types (ignoring specific values, so that e.g.
    100nF vs 10uF caps produce the same fingerprint).
    """
    # Count passive types (e.g., 3xC, 2xR, 1xL) instead of listing each value
    type_counts: dict[str, int] = defaultdict(int)
    for ptype, _pvalue in supporting:
        type_counts[ptype] += 1

    parts = [center_lib_id]
    for ptype in sorted(type_counts):
        parts.append(f"{type_counts[ptype]}x{ptype}")
    fingerprint_str = "|".join(parts)
    return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]


def _classify_passive_type(lib_id: str, fp_name: str, ref: str = "") -> str:
    """Classify a passive into R, C, L, or FB."""
    lib_lower = lib_id.lower()
    fp_lower = fp_name.lower()
    if "device:r" in lib_lower or "r_" in fp_lower or "r_pack" in fp_lower:
        return "R"
    if "device:c" in lib_lower or "c_" in fp_lower or "c_pack" in fp_lower:
        return "C"
    if "device:l" in lib_lower or "l_" in fp_lower:
        return "L"
    # Fall back to ref prefix
    if ref:
        m = re.match(r"^(R|C|L|FB)", ref)
        if m:
            return m.group(1)
    return "passive"


def detect_subcircuits(pcb_path: Path) -> list[Subcircuit]:
    """Detect subcircuits in a PCB file.

    A subcircuit is an IC (pad_count > IC_PIN_THRESHOLD) plus all passive
    components connected to it via shared signal nets (excluding power/ground).

    Args:
        pcb_path: Path to a .kicad_pcb file.

    Returns:
        List of detected Subcircuit objects.
    """
    board = Board.from_file(str(pcb_path))
    ref_to_nets, net_to_refs, ref_to_lib_id, ref_to_fp_name, ref_to_pad_count, ref_to_value = (
        _build_connectivity(board)
    )

    subcircuits = []
    seen_ic_refs = set()

    for ref, pad_count in ref_to_pad_count.items():
        if pad_count <= IC_PIN_THRESHOLD:
            continue

        lib_id = ref_to_lib_id.get(ref, "")
        fp_name = ref_to_fp_name.get(ref, "")
        # Skip if this is actually a passive (some passives have many pads, e.g., R_Pack)
        if _is_passive(lib_id, fp_name, ref):
            continue
        # Skip mechanical/non-electrical components (mounting holes, switches, etc.)
        if _is_excluded_center(lib_id, fp_name, ref):
            continue

        if ref in seen_ic_refs:
            continue
        seen_ic_refs.add(ref)

        # Find all signal nets this IC connects to
        ic_nets = ref_to_nets.get(ref, [])
        signal_nets = [n for n in ic_nets if not _is_power_net(n)]

        # Find all passives on those signal nets
        supporting_refs = set()
        for net_name in signal_nets:
            for other_ref in net_to_refs.get(net_name, []):
                if other_ref == ref:
                    continue
                other_lib_id = ref_to_lib_id.get(other_ref, "")
                other_fp = ref_to_fp_name.get(other_ref, "")
                if _is_passive(other_lib_id, other_fp, other_ref):
                    supporting_refs.add(other_ref)

        # Also include passives on power nets that ONLY connect to this IC
        # (decoupling caps) — they connect to a power net and to this IC's power pin
        for net_name in ic_nets:
            if _is_power_net(net_name):
                for other_ref in net_to_refs.get(net_name, []):
                    if other_ref == ref:
                        continue
                    other_lib_id = ref_to_lib_id.get(other_ref, "")
                    other_fp = ref_to_fp_name.get(other_ref, "")
                    if not _is_passive(other_lib_id, other_fp, other_ref):
                        continue
                    # Check if this passive shares a non-power net with ANY IC
                    # If it only connects to power nets + this IC's power net, it's a decoupling cap
                    other_nets = ref_to_nets.get(other_ref, [])
                    all_power = all(_is_power_net(n) for n in other_nets)
                    if all_power:
                        # Pure decoupling cap — only power/ground nets
                        supporting_refs.add(other_ref)

        if not supporting_refs:
            continue

        # Build fingerprint
        supporting_info = []
        for s_ref in sorted(supporting_refs):
            s_lib_id = ref_to_lib_id.get(s_ref, "")
            s_fp = ref_to_fp_name.get(s_ref, "")
            s_value = ref_to_value.get(s_ref, "")
            ptype = _classify_passive_type(s_lib_id, s_fp, s_ref)
            supporting_info.append((ptype, s_value))

        fingerprint = _compute_fingerprint(lib_id, supporting_info)

        # Collect all nets involved (signal nets only for the subcircuit view)
        all_involved_nets = set(signal_nets)
        for s_ref in supporting_refs:
            for n in ref_to_nets.get(s_ref, []):
                if not _is_power_net(n):
                    all_involved_nets.add(n)

        subcircuits.append(Subcircuit(
            center_ref=ref,
            center_lib_id=lib_id,
            center_value=ref_to_value.get(ref, ""),
            supporting_components=sorted(supporting_refs),
            connected_nets=sorted(all_involved_nets),
            fingerprint=fingerprint,
            sheet="",  # Sheet info not available from PCB alone
        ))

    return subcircuits


def cluster_subcircuits(subcircuits: list[Subcircuit]) -> list[SubcircuitCluster]:
    """Group subcircuits by fingerprint into clusters.

    Subcircuits with identical fingerprints share the same topology
    (same IC type + same passive configuration).
    """
    by_fingerprint: dict[str, list[Subcircuit]] = defaultdict(list)
    for sc in subcircuits:
        by_fingerprint[sc.fingerprint].append(sc)

    clusters = []
    for fp, instances in sorted(by_fingerprint.items(), key=lambda x: -len(x[1])):
        # Build canonical component list from first instance
        first = instances[0]
        canonical = [first.center_lib_id]
        # Collect passive types from supporting components
        seen_types = set()
        for s_ref in first.supporting_components:
            # We don't have lib_id here, but can infer from ref prefix
            prefix = re.match(r"^([A-Z]+)", s_ref)
            if prefix:
                seen_types.add(prefix.group(1))
        canonical.extend(sorted(seen_types))

        clusters.append(SubcircuitCluster(
            fingerprint=fp,
            count=len(instances),
            label="",  # To be filled by Claude labeling
            instances=instances,
            canonical_components=canonical,
        ))

    return clusters
