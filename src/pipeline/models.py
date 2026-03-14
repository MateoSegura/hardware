from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DesignUnit:
    """A single PCB design within a repo."""
    name: str
    root_dir: Path
    root_schematic: Path | None
    pcb_file: Path | None
    project_file: Path | None
    kicad_version: int | None
    has_hierarchy: bool
    has_local_libs: bool


@dataclass
class SheetPinInfo:
    """A connection point on a hierarchical sheet symbol."""
    name: str
    direction: str


@dataclass
class SubSheetRef:
    """A reference to a sub-sheet from a parent sheet."""
    sheet_name: str
    file_name: str
    resolved_path: Path | None
    uuid: str
    pins: list[SheetPinInfo] = field(default_factory=list)
    exists: bool = True


@dataclass
class LabelInfo:
    """A net label on a schematic sheet."""
    name: str
    label_type: str
    shape: str
    position: tuple[float, float] = (0.0, 0.0)
    uuid: str = ""


@dataclass
class ParsedComponent:
    """A placed component instance on a schematic sheet."""
    ref: str
    lib_id: str
    value: str
    footprint: str
    mpn: str
    sheet_path: str
    sheet_name: str
    unit: int
    pin_count: int
    is_power: bool
    is_in_bom: bool
    is_on_board: bool
    dnp: bool
    properties: dict[str, str] = field(default_factory=dict)


@dataclass
class Position:
    """A simple x,y position."""
    x: float
    y: float


@dataclass
class ParsedSheet:
    """A single parsed .kicad_sch file with extracted data."""
    file_path: Path
    sheet_name: str
    sheet_uuid: str
    parent_path: Path | None
    kicad_version: int | None
    components: list[ParsedComponent] = field(default_factory=list)
    local_labels: list[LabelInfo] = field(default_factory=list)
    global_labels: list[LabelInfo] = field(default_factory=list)
    hierarchical_labels: list[LabelInfo] = field(default_factory=list)
    sub_sheet_refs: list[SubSheetRef] = field(default_factory=list)
    power_symbols: list[ParsedComponent] = field(default_factory=list)
    no_connects: list[Position] = field(default_factory=list)
    junctions: list[Position] = field(default_factory=list)


@dataclass
class LayerInfo:
    ordinal: int
    name: str
    layer_type: str  # "signal", "power", "mixed"


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
    layer: str
    position: tuple[float, float, float]  # x, y, angle
    pad_count: int
    path: str  # hierarchical sheet path
    value: str = ""
    pads: list[PadInfo] = field(default_factory=list)


@dataclass
class ParsedBoard:
    """Extracted data from a .kicad_pcb file."""
    file_path: Path
    kicad_version: int | None
    layers: list[LayerInfo]
    footprints: list[FootprintInfo]
    track_count: int
    via_count: int
    zone_count: int
    net_count: int
    net_classes: list[str] = field(default_factory=list)
    nets: dict[int, str] = field(default_factory=dict)


@dataclass
class NetInfo:
    """A resolved net with all connected pins across the hierarchy."""
    name: str
    net_type: str  # "power", "signal"
    scope: str  # "global", "local", "hierarchical"
    connected_pins: list[str] = field(default_factory=list)
    sheets: list[str] = field(default_factory=list)


@dataclass
class ParsedProject:
    """Complete parsed output for a single design unit."""
    design_unit: DesignUnit
    sheet_tree: dict[str, ParsedSheet] = field(default_factory=dict)
    root_sheet: ParsedSheet | None = None
    board: ParsedBoard | None = None
    all_components: list[ParsedComponent] = field(default_factory=list)
    all_nets: dict[str, NetInfo] = field(default_factory=dict)
    stats: dict = field(default_factory=dict)


@dataclass
class Subcircuit:
    """An IC and its supporting passive components."""
    center_ref: str              # e.g., "U1"
    center_lib_id: str           # e.g., "Regulator_Linear:MCP1700"
    center_value: str
    supporting_components: list[str] = field(default_factory=list)  # refs of connected passives
    connected_nets: list[str] = field(default_factory=list)         # nets involved
    fingerprint: str = ""        # hash of topology
    sheet: str = ""              # which sheet this is on


@dataclass
class SubcircuitCluster:
    """A group of subcircuits sharing the same topology fingerprint."""
    fingerprint: str
    count: int
    label: str = ""              # human-readable name (e.g., "LDO circuit")
    instances: list[Subcircuit] = field(default_factory=list)
    canonical_components: list[str] = field(default_factory=list)  # component types in this topology


@dataclass
class TemplatePassive:
    """A passive component slot in a circuit template."""
    ref_prefix: str              # "C" or "R" or "L"
    typical_value: str           # "100nF"
    typical_footprint: str       # "C_0402"
    connection_type: str         # "power_bypass", "signal_filter", "pullup", etc.
    count_in_template: int       # how many of this passive per instance


@dataclass
class CircuitTemplate:
    """A reusable circuit pattern extracted from clustered subcircuits."""
    name: str                    # e.g., "LDO_SOT23-5_bypass"
    description: str
    center_ic_lib_id: str
    center_ic_footprint: str
    passives: list[TemplatePassive] = field(default_factory=list)
    source_count: int = 0
    source_projects: list[str] = field(default_factory=list)
    fingerprint: str = ""
