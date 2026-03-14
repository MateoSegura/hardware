# Refactor Plan — Production-Quality Pipeline

> **Goal:** Consolidate duplicated logic, enhance the board parser with full
> pad-level data, and create shared utilities. This is the foundation for
> the connection pattern extraction.

---

## 1. New Module: `src/pipeline/classify.py` (Shared Utilities)

Consolidate all classification logic scattered across modules into one place:

```python
"""Component and net classification utilities.

Single source of truth for: power net detection, component classification
(IC vs passive vs connector vs mechanical), IC family extraction, and
passive type classification.
"""

import re

# ── Power net detection ──────────────────────────────────────────────────

_POWER_NET_PATTERN = re.compile(...)  # one regex, used everywhere

def is_power_net(name: str) -> bool:
    """Check if a net name is a power/ground net."""

# ── Component classification ─────────────────────────────────────────────

class ComponentType:
    IC = "ic"
    PASSIVE = "passive"
    CONNECTOR = "connector"
    MECHANICAL = "mechanical"  # mounting holes, fiducials, test points
    SWITCH = "switch"
    UNKNOWN = "unknown"

def classify_component(
    lib_id: str,
    footprint: str = "",
    ref: str = "",
    pad_count: int = 0,
) -> str:
    """Classify a component into IC, passive, connector, mechanical, etc.

    Uses lib_id patterns, footprint patterns, reference prefix, and pad count.
    Returns a ComponentType string.
    """

def is_passive(lib_id: str, footprint: str = "", ref: str = "") -> bool:
    """Convenience: is this a passive component (R, C, L, FB)?"""

def is_ic(lib_id: str, footprint: str = "", ref: str = "", pad_count: int = 0) -> bool:
    """Convenience: is this an IC (MCU, regulator, driver, etc.)?"""

# ── Passive type classification ──────────────────────────────────────────

def classify_passive_type(lib_id: str, footprint: str = "", ref: str = "") -> str:
    """Return 'R', 'C', 'L', 'FB', or 'passive' for a passive component."""

# ── IC family extraction ────────────────────────────────────────────────

def extract_ic_family(lib_id: str, value: str = "") -> str:
    """Extract IC family from lib_id.

    'MCU_ST:STM32F722RET6' → 'STM32F7'
    'Regulator_Linear:AP2112K-3.3' → 'AP2112'
    """

# ── Footprint reference extraction ──────────────────────────────────────

def get_footprint_ref(fp) -> str:
    """Extract reference designator from a kiutils Footprint object.

    Handles both KiCad 6/7 (graphicItems) and KiCad 8/9 (properties dict).
    """

# ── Version detection ────────────────────────────────────────────────────

def detect_kicad_version(path: Path) -> int | None:
    """Read first 500 bytes, extract (version NNNN) token."""
```

## 2. Enhanced `FootprintInfo` with Pad Data

```python
@dataclass
class PadInfo:
    """A single pad on a footprint with its net assignment."""
    number: str          # pad number/name (e.g., "1", "A4", "GND")
    net_name: str        # assigned net name (e.g., "SPI_MOSI", "+3V3", "")
    net_number: int      # net ordinal (0 = unconnected)
    pad_type: str        # "smd", "thru_hole", "np_thru_hole", "connect"
    position: tuple[float, float]  # x, y relative to footprint origin

@dataclass
class FootprintInfo:
    ref: str
    lib_id: str
    value: str                              # NEW
    layer: str
    position: tuple[float, float, float]    # x, y, angle
    pad_count: int
    path: str                               # hierarchical sheet path
    component_type: str                     # NEW: from classify_component()
    pads: list[PadInfo] = field(default_factory=list)  # NEW: full pad data
```

## 3. Enhanced `parse_board()`

Extract full pad data in one pass so downstream modules don't need to
re-parse the board:

```python
def parse_board(pcb_path: Path) -> ParsedBoard:
    board = Board.from_file(str(pcb_path))

    for fp in board.footprints:
        ref = get_footprint_ref(fp)
        value = get_footprint_value(fp)

        # Extract ALL pad data
        pads = []
        for pad in fp.pads:
            pads.append(PadInfo(
                number=pad.number,
                net_name=pad.net.name if pad.net else "",
                net_number=pad.net.number if pad.net else 0,
                pad_type=pad.type or "",
                position=(pad.position.X, pad.position.Y),
            ))

        component_type = classify_component(
            lib_id=fp.libId or "",
            footprint=fp.entryName or "",
            ref=ref,
            pad_count=len(fp.pads),
        )

        footprints.append(FootprintInfo(
            ref=ref,
            lib_id=fp.libId or "",
            value=value,
            layer=fp.layer or "",
            position=(...),
            pad_count=len(fp.pads),
            path=fp.path or "",
            component_type=component_type,
            pads=pads,
        ))
```

## 4. Refactor Consumers

### subcircuits.py
- Remove `_is_passive()`, `_is_excluded_center()`, `_is_power_net()`,
  `_classify_passive_type()`, `_get_ref_from_footprint()` — use classify.py
- Remove `_build_connectivity()` — use ParsedBoard.footprints with pads
- `detect_subcircuits()` takes `ParsedBoard` instead of `Path`
  (no more re-parsing the board file)

### nets.py
- Remove `_is_power_name()` — use `classify.is_power_net()`
- Keep `_NetBuilder` and `trace_nets()` as-is (clean code)

### hierarchy.py
- Remove `detect_version()` — use `classify.detect_kicad_version()`
- Keep everything else (well-structured)

### board.py
- Remove `detect_version()` — use `classify.detect_kicad_version()`
- Remove `_get_footprint_ref()` — use `classify.get_footprint_ref()`
- Enhance `parse_board()` with full pad extraction

### decoupling.py / decoupling_gen.py
- Remove `_extract_ic_family()` — use `classify.extract_ic_family()`
- Remove `_is_capacitor()` — use `classify.classify_passive_type() == 'C'`

## 5. Migration Strategy

1. Create `classify.py` with all shared functions + comprehensive tests
2. Update `models.py` with `PadInfo` and enhanced `FootprintInfo`
3. Update `board.py` to extract full pad data
4. Update board tests to verify pad extraction
5. Refactor `subcircuits.py` to use classify.py + ParsedBoard
6. Refactor `nets.py` to use classify.py
7. Refactor other consumers
8. Run full test suite — all 564 tests must still pass
9. Delete duplicated functions from all modules

## 6. Tests

### tests/test_classify.py (new)
- test_power_net_patterns: comprehensive power net name list
- test_signal_net_patterns: signal names NOT classified as power
- test_classify_ic: MCUs, regulators, sensors → "ic"
- test_classify_passive: R, C, L → "passive"
- test_classify_connector: USB, RJ45, header → "connector"
- test_classify_mechanical: MountingHole, TestPoint, Fiducial → "mechanical"
- test_classify_switch: Cherry MX, Choc → "switch"
- test_passive_type: R/C/L/FB classification
- test_extract_ic_family: STM32F722 → STM32F7, AP2112K → AP2112
- test_footprint_ref_kicad6: graphicItems extraction
- test_footprint_ref_kicad9: properties dict extraction
- test_version_detection: all KiCad versions

### tests/test_board.py (enhanced)
- test_pad_extraction: verify pads have number, net_name, net_number
- test_pad_net_assignment: specific pads on known components have expected nets
- test_component_type_classification: ICs, passives, connectors classified correctly
- test_footprint_value_extraction: values extracted from footprints
