"""KiCad symbol generator — creates .kicad_sym files from structured pin data.

Generates multi-unit symbols where each unit corresponds to a functional
pin group (Power, GPIO_A, UART, etc.). Uses vendored kiutils for output.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))

from kiutils.items.common import Effects, Fill, Font, Position, Property, Stroke
from kiutils.items.syitems import SyRect
from kiutils.symbol import Symbol, SymbolLib, SymbolPin

# KiCad pin electrical types
VALID_PIN_TYPES = {
    "input", "output", "bidirectional", "tri_state", "passive",
    "free", "unspecified", "power_in", "power_out", "open_collector",
    "open_emitter", "no_connect",
}

# Layout constants (in mm, KiCad default grid)
PIN_LENGTH = 2.54
PIN_SPACING = 2.54
BODY_MARGIN = 2.54  # margin between pin end and body edge
TEXT_SIZE = 1.27


@dataclass
class PinDef:
    """Definition of a single pin."""
    number: str
    name: str
    electrical_type: str  # must be in VALID_PIN_TYPES
    group: str


@dataclass
class ChipDef:
    """Definition of a chip to generate a symbol for."""
    name: str
    library: str
    description: str
    footprint: str
    datasheet_url: str
    pins: list[PinDef] = field(default_factory=list)


def _normalize_pin_type(pin_type: str) -> str:
    """Normalize a pin electrical type to a valid KiCad type."""
    pin_type = pin_type.lower().strip()
    if pin_type in VALID_PIN_TYPES:
        return pin_type
    # Common aliases
    aliases = {
        "power": "power_in",
        "pwr_in": "power_in",
        "pwr_out": "power_out",
        "bidi": "bidirectional",
        "bidir": "bidirectional",
        "tristate": "tri_state",
        "tri-state": "tri_state",
        "open_drain": "open_collector",
        "nc": "no_connect",
    }
    return aliases.get(pin_type, "unspecified")


def _group_pins(pins: list[PinDef]) -> dict[str, list[PinDef]]:
    """Group pins by their functional group, preserving order."""
    groups: dict[str, list[PinDef]] = defaultdict(list)
    for pin in pins:
        groups[pin.group].append(pin)
    return dict(groups)


def _compute_body_size(pin_count: int) -> tuple[float, float]:
    """Compute rectangle body size for a unit with N pins.

    Pins go on the left side. Returns (width, height).
    """
    # Height: enough for all pins with spacing, plus margin
    height = max((pin_count + 1) * PIN_SPACING, 5.08)
    # Width: fixed reasonable width for pin name display
    width = 15.24  # 6 grid units
    return width, height


def _make_unit(
    parent_name: str,
    unit_id: int,
    group_name: str,
    pins: list[PinDef],
) -> Symbol:
    """Create a single unit (sub-symbol) for a pin group."""
    unit = Symbol()
    unit.entryName = parent_name
    unit.libId = parent_name
    unit.unitId = unit_id
    unit.styleId = 1

    width, height = _compute_body_size(len(pins))
    half_h = height / 2

    # Create body rectangle
    rect = SyRect()
    rect.start = Position(X=-width / 2, Y=half_h)
    rect.end = Position(X=width / 2, Y=-half_h)
    rect.stroke = Stroke(width=0.254, type="default")
    rect.fill = Fill(type="background")
    unit.graphicItems = [rect]

    # Place pins on the left side, evenly spaced
    sym_pins = []
    start_y = half_h - PIN_SPACING  # first pin position
    for i, pin_def in enumerate(pins):
        pin = SymbolPin()
        pin.electricalType = _normalize_pin_type(pin_def.electrical_type)
        pin.graphicalStyle = "line"
        pin.name = pin_def.name
        pin.number = str(pin_def.number)
        pin.length = PIN_LENGTH

        y = start_y - i * PIN_SPACING
        # Pins on the left, pointing right (angle=0)
        pin.position = Position(
            X=-(width / 2) - PIN_LENGTH,
            Y=y,
            angle=0,
        )
        sym_pins.append(pin)

    unit.pins = sym_pins
    return unit


def generate_symbol(chip: ChipDef) -> SymbolLib:
    """Generate a KiCad symbol library from a ChipDef.

    Creates a multi-unit symbol with one unit per pin group.
    Each unit has a rectangular body with pins on the left side.

    Args:
        chip: The chip definition with pins grouped by function.

    Returns:
        A kiutils SymbolLib ready to write with to_file().
    """
    lib = SymbolLib()
    lib.version = 20231120
    lib.generator = "symbol_gen"

    # Create parent symbol
    sym = Symbol()
    sym.entryName = chip.name
    sym.libId = chip.name
    sym.inBom = True
    sym.onBoard = True

    # Standard properties
    sym.properties = [
        Property(
            key="Reference", value="U", id=0,
            effects=Effects(font=Font(width=TEXT_SIZE, height=TEXT_SIZE)),
        ),
        Property(
            key="Value", value=chip.name, id=1,
            effects=Effects(font=Font(width=TEXT_SIZE, height=TEXT_SIZE)),
        ),
        Property(
            key="Footprint", value=chip.footprint, id=2,
            effects=Effects(font=Font(width=TEXT_SIZE, height=TEXT_SIZE), hide=True),
        ),
        Property(
            key="Datasheet", value=chip.datasheet_url or "", id=3,
            effects=Effects(font=Font(width=TEXT_SIZE, height=TEXT_SIZE), hide=True),
        ),
    ]

    if chip.description:
        sym.properties.append(Property(
            key="Description", value=chip.description, id=4,
            effects=Effects(font=Font(width=TEXT_SIZE, height=TEXT_SIZE), hide=True),
        ))

    # Group pins and create units
    groups = _group_pins(chip.pins)
    units = []
    for unit_id, (group_name, group_pins) in enumerate(groups.items(), start=1):
        unit = _make_unit(chip.name, unit_id, group_name, group_pins)
        units.append(unit)

    sym.units = units
    lib.symbols = [sym]
    return lib


def generate_symbol_file(chip: ChipDef, output_path: Path) -> Path:
    """Generate a .kicad_sym file from a ChipDef.

    Args:
        chip: The chip definition.
        output_path: Where to write the .kicad_sym file.

    Returns:
        The output path.
    """
    lib = generate_symbol(chip)
    lib.to_file(str(output_path))
    return output_path
