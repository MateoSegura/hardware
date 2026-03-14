"""Board parser — extracts structured data from .kicad_pcb files.

Uses vendored kiutils for parsing. Handles KiCad 6-9 format differences
for footprint reference extraction.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))

from kiutils.board import Board
from kiutils.items.brditems import Arc, Segment, Via

from src.pipeline.models import FootprintInfo, LayerInfo, PadInfo, ParsedBoard


def detect_version(path: Path) -> int | None:
    """Read first 500 bytes, extract (version NNNN) token."""
    try:
        text = path.read_text(errors="replace")[:500]
        match = re.search(r"\(version\s+(\d+)\)", text)
        return int(match.group(1)) if match else None
    except OSError:
        return None


def _get_footprint_ref(fp) -> str:
    """Extract reference designator from a footprint.

    KiCad 8/9: Reference is in fp.properties dict.
    KiCad 6/7: Reference is in fp.graphicItems as an FpText with type='reference'.
    """
    # Try properties dict first (KiCad 8/9)
    if isinstance(fp.properties, dict) and "Reference" in fp.properties:
        return fp.properties["Reference"]

    # Fall back to graphicItems (KiCad 6/7)
    for gi in getattr(fp, "graphicItems", []):
        if getattr(gi, "type", None) == "reference":
            return getattr(gi, "text", "")

    return ""


def _get_footprint_value(fp) -> str:
    """Extract value from a footprint.

    KiCad 8/9: Value is in fp.properties dict.
    KiCad 6/7: Value is in fp.graphicItems as an FpText with type='value'.
    """
    if isinstance(fp.properties, dict) and "Value" in fp.properties:
        return fp.properties["Value"]

    for gi in getattr(fp, "graphicItems", []):
        if getattr(gi, "type", None) == "value":
            return getattr(gi, "text", "")

    return ""


def parse_board(pcb_path: Path) -> ParsedBoard:
    """Parse a .kicad_pcb file and return structured board data."""
    board = Board.from_file(str(pcb_path))

    # Layers — signal/power/mixed only
    layers = []
    for layer in board.layers:
        if layer.type in ("signal", "power", "mixed"):
            layers.append(LayerInfo(
                ordinal=layer.ordinal,
                name=layer.name,
                layer_type=layer.type,
            ))

    # Track/via counts — traceItems is a flat list of Segment, Via, Arc
    track_count = 0
    via_count = 0
    for item in board.traceItems:
        if isinstance(item, (Segment, Arc)):
            track_count += 1
        elif isinstance(item, Via):
            via_count += 1

    zone_count = len(board.zones)

    # Nets
    nets = {n.number: n.name for n in board.nets}

    # Footprints
    footprints = []
    for fp in board.footprints:
        ref = _get_footprint_ref(fp)
        value = _get_footprint_value(fp)

        # Extract pad data
        pads = []
        for pad in fp.pads:
            net = getattr(pad, "net", None)
            pads.append(PadInfo(
                number=pad.number or "",
                net_name=net.name if net else "",
                net_number=net.number if net else 0,
                pad_type=getattr(pad, "type", "") or "",
                position=(
                    pad.position.X if hasattr(pad, "position") else 0.0,
                    pad.position.Y if hasattr(pad, "position") else 0.0,
                ),
            ))

        footprints.append(FootprintInfo(
            ref=ref,
            lib_id=fp.libId or "",
            layer=fp.layer or "",
            position=(
                fp.position.X,
                fp.position.Y,
                fp.position.angle if fp.position.angle is not None else 0.0,
            ),
            pad_count=len(fp.pads),
            path=fp.path or "",
            value=value,
            pads=pads,
        ))

    # Net classes
    net_classes = []
    for nc in getattr(board, "netClasses", []):
        name = getattr(nc, "name", "")
        if name:
            net_classes.append(name)

    return ParsedBoard(
        file_path=pcb_path.resolve(),
        kicad_version=detect_version(pcb_path),
        layers=layers,
        footprints=footprints,
        track_count=track_count,
        via_count=via_count,
        zone_count=zone_count,
        net_count=len(nets),
        net_classes=net_classes,
        nets=nets,
    )
