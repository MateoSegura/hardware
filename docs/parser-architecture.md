# Parser Architecture Spec

> **Status:** Ready for implementation
> **Date:** 2026-03-14
> **Based on:** kiutils source code analysis, KiBot/kicad-sch-api pattern study,
> pilot project reconnaissance (10 projects, KiCad 3-9)

---

## 1. Design Principles

1. **Two-phase loading**: Parse individual files first, then resolve hierarchy and connectivity
2. **Version-aware**: Detect KiCad version from `(version YYYYMMDD)` and branch behavior
3. **Path resolution**: Always relative to parent schematic's directory via `os.path.dirname()` + `os.path.join()`
4. **Sheet caching**: Cache parsed schematics by absolute path (shared sheets load once)
5. **Fail gracefully**: Missing sub-sheets, broken library paths, PCB-only projects — warn, don't crash
6. **Multi-project repos**: Discover ALL design units in a repo, not just the first
7. **Real data tested**: Must parse all 10 pilot projects cleanly

## 2. Module Structure

```
src/pipeline/
├── __init__.py
├── discovery.py        # Find all design units in a repo
├── loader.py           # Load + cache individual KiCad files via kiutils
├── hierarchy.py        # Walk hierarchical schematic trees
├── nets.py             # Net connectivity tracing across sheets
├── models.py           # Our data model (dataclasses)
├── version.py          # KiCad version detection + normalization
└── export.py           # Export parsed project to normalized JSON
```

## 3. Data Model (`models.py`)

```python
@dataclass
class DesignUnit:
    """A single PCB design within a repo. A repo may contain many."""
    name: str                           # e.g., "hackrf-one"
    root_dir: Path                      # absolute path to directory containing root files
    root_schematic: Path | None         # absolute path to root .kicad_sch
    pcb_file: Path | None               # absolute path to .kicad_pcb
    project_file: Path | None           # absolute path to .kicad_pro (may be None)
    kicad_version: int | None           # YYYYMMDD version number
    has_hierarchy: bool
    has_local_libs: bool

@dataclass
class ParsedSheet:
    """A single parsed .kicad_sch file with extracted data."""
    file_path: Path                     # absolute path
    sheet_name: str                     # display name (from parent's sheet reference)
    sheet_uuid: str                     # UUID of the sheet reference in parent
    parent_path: Path | None            # absolute path of parent sheet (None for root)
    kicad_version: int | None

    components: list[ParsedComponent]
    local_labels: list[LabelInfo]
    global_labels: list[LabelInfo]
    hierarchical_labels: list[LabelInfo]
    sub_sheet_refs: list[SubSheetRef]
    power_symbols: list[ParsedComponent]  # subset of components where is_power=True
    no_connects: list[Position]
    junctions: list[Position]

@dataclass
class ParsedComponent:
    """A placed component instance on a schematic sheet."""
    ref: str                            # reference designator (e.g., "R1")
    lib_id: str                         # library:name (e.g., "Device:R")
    value: str
    footprint: str
    mpn: str                            # manufacturer part number (empty if not set)
    sheet_path: str                     # UUID path (e.g., "/root-uuid/sheet-uuid")
    sheet_name: str                     # human-readable sheet name
    unit: int                           # unit number (1-based, for multi-unit symbols)
    pin_count: int
    is_power: bool                      # True for power symbols (VCC, GND, etc.)
    is_in_bom: bool
    is_on_board: bool
    dnp: bool                           # do-not-populate
    properties: dict[str, str]          # all properties as key-value pairs

@dataclass
class LabelInfo:
    """A net label on a schematic sheet."""
    name: str
    label_type: str                     # "local", "global", "hierarchical"
    shape: str                          # "input", "output", "bidirectional", etc.
    position: tuple[float, float]
    uuid: str

@dataclass
class SubSheetRef:
    """A reference to a sub-sheet from a parent sheet."""
    sheet_name: str                     # display name
    file_name: str                      # filename (e.g., "power.kicad_sch")
    resolved_path: Path | None          # absolute path after resolution
    uuid: str                           # sheet UUID (used for path construction)
    pins: list[SheetPinInfo]            # connection points
    exists: bool                        # whether the file was found

@dataclass
class SheetPinInfo:
    """A connection point on a hierarchical sheet symbol."""
    name: str                           # must match hierarchical_label in child
    direction: str                      # "input", "output", "bidirectional", etc.

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
    net_classes: list[str]
    nets: dict[int, str]                # net_number -> net_name

@dataclass
class LayerInfo:
    ordinal: int
    name: str
    layer_type: str                     # "signal", "power", "user", "mixed"

@dataclass
class FootprintInfo:
    ref: str
    lib_id: str
    layer: str
    position: tuple[float, float, float]  # x, y, angle
    pad_count: int
    path: str                           # hierarchical sheet path

@dataclass
class ParsedProject:
    """Complete parsed output for a single design unit."""
    design_unit: DesignUnit
    sheet_tree: dict[str, ParsedSheet]  # keyed by absolute file path
    root_sheet: ParsedSheet | None
    board: ParsedBoard | None
    all_components: list[ParsedComponent]   # flattened from all sheets
    all_nets: dict[str, NetInfo]            # computed connectivity
    stats: dict[str, int | bool]

@dataclass
class NetInfo:
    """A resolved net with all connected pins across the hierarchy."""
    name: str
    net_type: str                       # "power", "signal"
    scope: str                          # "global", "local", "hierarchical"
    connected_pins: list[str]           # ["U1:15", "C42:1", ...]
    sheets: list[str]                   # which sheets this net appears on
```

## 4. Discovery (`discovery.py`)

**Goal:** Given a repo directory, find all independent design units.

**Algorithm:**
```
1. Find all .kicad_pro files → each is a potential design unit root
2. Find all .kicad_pcb files → each is a potential design unit
3. For .kicad_pro files:
   - Look for matching .kicad_sch (same stem) in same directory
   - Look for matching .kicad_pcb (same stem) in same directory
   - Create DesignUnit with all found files
4. For .kicad_pcb files NOT already matched to a .kicad_pro:
   - Look for matching .kicad_sch (same stem) in same directory
   - Create DesignUnit (PCB-only or PCB+SCH without project file)
5. For .kicad_sch files NOT already matched:
   - Create DesignUnit (schematic-only)
6. Deduplicate: if same .kicad_pcb appears in multiple units, keep the one with .kicad_pro
```

**Edge cases from pilot data:**
- MNT Reform: 18 sub-projects, each in own subdirectory
- HackRF: 5 boards in `hardware/` subdirectories
- Enaccess: 2 sub-projects deep in `design/source/kicad/`
- Maxlab: 6 hardware revisions in `ai-camera-rev*/` directories

## 5. Loader (`loader.py`)

**Goal:** Load individual KiCad files into kiutils objects with caching.

```python
class KiCadFileLoader:
    def __init__(self):
        self._sch_cache: dict[str, Schematic] = {}  # abs_path -> parsed
        self._board_cache: dict[str, Board] = {}

    def load_schematic(self, path: Path) -> Schematic:
        abs_path = str(path.resolve())
        if abs_path not in self._sch_cache:
            self._sch_cache[abs_path] = Schematic.from_file(abs_path)
        return self._sch_cache[abs_path]

    def load_board(self, path: Path) -> Board:
        abs_path = str(path.resolve())
        if abs_path not in self._board_cache:
            self._board_cache[abs_path] = Board.from_file(abs_path)
        return self._board_cache[abs_path]
```

**Version detection** (from raw file, before full parse):
```python
def detect_version(path: Path) -> int | None:
    """Read first 500 bytes, extract (version NNNN) token."""
    text = path.read_text(errors="replace")[:500]
    match = re.search(r'\(version\s+(\d+)\)', text)
    return int(match.group(1)) if match else None
```

## 6. Hierarchy Walker (`hierarchy.py`)

**Goal:** Recursively load all sheets in a hierarchical design, building the sheet tree.

**Algorithm (BFS with caching):**
```
Input: root_schematic_path (absolute Path)
Output: dict[str, ParsedSheet] keyed by absolute file path

1. Initialize queue = [(root_path, "root", None, root_uuid)]
2. Initialize visited = set()
3. Initialize sheet_tree = {}

4. While queue not empty:
   a. Pop (sch_path, sheet_name, parent_path, sheet_uuid)
   b. abs_path = sch_path.resolve()
   c. If abs_path in visited: continue (shared sheet already loaded)
   d. visited.add(abs_path)

   e. Load schematic via loader (cached)
   f. Detect version
   g. Extract components (with version-aware ref designator resolution)
   h. Extract labels (local, global, hierarchical)
   i. Extract sub-sheet references
   j. Detect power symbols (check lib_symbols for isPower flag)
   k. Create ParsedSheet, add to sheet_tree

   l. For each sub-sheet reference:
      - Resolve file path: sch_path.parent / sub_sheet.file_name
      - Check if resolved path exists
      - If exists: queue (resolved_path, sub_name, abs_path, sub_uuid)
      - If not: warn and set sub_sheet_ref.exists = False
```

**Reference designator resolution (version-aware):**
```python
def get_ref(sym: SchematicSymbol, sch: Schematic, sheet_path: str) -> str:
    """Get reference designator, handling v6 and v7+ formats."""
    # v7+: check sym.instances
    if sym.instances:
        for inst in sym.instances:
            for path in inst.paths:
                if path.sheetInstancePath == sheet_path:
                    return path.reference
        # Fallback: return first instance's reference
        for inst in sym.instances:
            if inst.paths:
                return inst.paths[0].reference

    # v6: check root schematic's symbolInstances
    if sch.symbolInstances:
        for si in sch.symbolInstances:
            if si.path.endswith(str(sym.uuid)):
                return si.reference

    # Last resort: Reference property
    for prop in sym.properties:
        if prop.key == "Reference":
            return prop.value

    return "?"
```

**Power symbol detection:**
```python
def is_power_symbol(sym: SchematicSymbol, lib_symbols: list[Symbol]) -> bool:
    """Check if a schematic symbol is a power symbol."""
    for lib_sym in lib_symbols:
        if lib_sym.libId == sym.libId or lib_sym.entryName == sym.entryName:
            return lib_sym.isPower
    return False
```

**Sheet property access (version-aware):**
```python
def get_sheet_filename(sheet: HierarchicalSheet) -> str:
    """Get sub-sheet filename, handling both v6 and v7+ property naming."""
    # kiutils parses both "Sheet file" and "Sheetfile" into sheet.fileName
    fn = getattr(sheet, 'fileName', None)
    if fn and hasattr(fn, 'value'):
        return fn.value
    return ""

def get_sheet_name(sheet: HierarchicalSheet) -> str:
    """Get sub-sheet display name."""
    sn = getattr(sheet, 'sheetName', None)
    if sn and hasattr(sn, 'value'):
        return sn.value
    return ""
```

## 7. Net Tracer (`nets.py`)

**Goal:** Build net connectivity map across the entire hierarchy.

**Algorithm:**
```
Input: sheet_tree (all parsed sheets)
Output: dict[str, NetInfo]

Phase 1 — Collect all labels:
  For each sheet:
    Collect local_labels, global_labels, hierarchical_labels
    Collect power symbols (each creates an implicit global net)
    Collect component pins (from schematicSymbols)

Phase 2 — Resolve global nets:
  All global_labels with same name → same net (across all sheets)
  All power symbols of same type → same global net (VCC, GND, etc.)

Phase 3 — Resolve hierarchical connections:
  For each parent sheet:
    For each sub_sheet_ref:
      For each pin in sub_sheet_ref.pins:
        Find matching hierarchical_label in child sheet (by name, exact match)
        Connect parent-side net to child-side net

Phase 4 — Classify nets:
  If net name matches power pattern → type = "power"
  If net has global_labels → scope = "global"
  If net has hierarchical_labels → scope = "hierarchical"
  Otherwise → scope = "local"
```

**Note:** Full coordinate-based wire tracing (connecting pins by XY position overlap)
is complex and not needed for pattern extraction. We use label-based connectivity
which captures all named nets. Unnamed nets (two pins connected by a wire with no
label) are missed but rare in well-designed schematics.

## 8. Board Parser (in `loader.py`)

**Goal:** Extract board-level metrics from .kicad_pcb.

```python
def parse_board(board: Board) -> ParsedBoard:
    # Layers
    layers = []
    for layer in board.layers:
        if layer.type in ("signal", "power", "mixed"):
            layers.append(LayerInfo(layer.ordinal, layer.name, layer.type))

    # Track/via/zone counts
    track_count = 0
    via_count = 0
    for item in board.traceItems:
        if isinstance(item, Segment):
            track_count += 1
        elif isinstance(item, Via):
            via_count += 1
        # Arc tracks also count as tracks
        elif isinstance(item, Arc):
            track_count += 1

    zone_count = len(board.zones)

    # Nets
    nets = {n.number: n.name for n in board.nets}

    # Footprints
    footprints = []
    for fp in board.footprints:
        ref = ""
        for prop_key, prop_val in fp.properties.items():
            if prop_key == "Reference":
                ref = prop_val
                break
        # Note: fp.properties is Dict[str,str] in kiutils (not List[Property])
        footprints.append(FootprintInfo(
            ref=ref,
            lib_id=fp.libId,
            layer=fp.layer,
            position=(fp.position.X, fp.position.Y, fp.position.angle or 0),
            pad_count=len(fp.pads),
            path=fp.path or "",
        ))

    # Net classes — kiutils doesn't parse these cleanly
    # Fall back to regex on raw file if needed
    net_classes = []
    for nc in getattr(board, 'netClasses', []):
        name = getattr(nc, 'name', '')
        if name:
            net_classes.append(name)

    return ParsedBoard(
        file_path=Path(board.filePath),
        kicad_version=detect_version(Path(board.filePath)) if board.filePath else None,
        layers=layers,
        footprints=footprints,
        track_count=track_count,
        via_count=via_count,
        zone_count=zone_count,
        net_count=len(nets),
        net_classes=net_classes,
        nets=nets,
    )
```

## 9. Export (`export.py`)

**Goal:** Serialize ParsedProject to JSON for downstream pattern extraction.

Uses `dataclasses.asdict()` with custom serializers for Path objects.
Output matches the JSON schema defined in `docs/thesis.md` Section 6 Stage 4.

## 10. Edge Cases Checklist

From pilot project analysis — the parser MUST handle all of these:

| Edge Case | Example | Handling |
|-----------|---------|----------|
| No .kicad_pro | VESC, LibreSolar, Crazyflie | Discover by .kicad_pcb presence |
| PCB-only (no schematic) | Crazyflie, LibreSolar, VESC | Create DesignUnit with pcb_file only |
| Multiple sub-projects in repo | MNT (18), HackRF (5), Maxlab (6) | Discovery finds ALL independently |
| Depth-2 hierarchy | MNT motherboard30 | Recursive BFS handles any depth |
| Spaces in filenames | Crazyflie, Enaccess, STM32F7 FC | Use Path objects, never split on whitespace |
| Ampersand in filename | STM32F7 FC "Sensors & Peripherals" | Path objects handle this |
| KiCad 3-5 legacy format | Crazyflie, VESC, LibreSolar | Detect version, skip if < 20211014 (v6) |
| Mixed versions in repo | MNT (v4-v9), HackRF (v4-v6) | Per-file version detection |
| "Sheet name" vs "Sheetname" | KiCad 6 vs 7+ | kiutils normalizes to sheetName attribute |
| v6 symbolInstances vs v7+ instances | Depends on file version | Version-aware ref resolution |
| Shared sub-sheets | Possible in MNT | Cache by absolute path |
| Missing sub-sheet files | Possible after sparse checkout | Warn, set exists=False, continue |
| Deep nesting (5+ dirs) | Enaccess | Use absolute paths throughout |
| Broken relative lib paths | Enaccess, HackRF | Tolerate — we don't need to resolve libs |
| Legacy sym-lib-table types | HackRF | Ignore — we read embedded libSymbols |
| Power symbols as implicit nets | Universal | Check isPower flag on lib_symbols |
| KiCad 8+ format changes | Antmicro (v9), Maxlab (v8) | kiutils handles most; patch tstamp→uuid if needed |
| Two PCBs in one directory | MNT batterypack | Each becomes its own DesignUnit |

## 11. Test Strategy

**TDD with real files. No mocks.**

```
tests/
├── test_discovery.py       # Test design unit discovery on all 10 pilots
├── test_loader.py          # Test file loading + caching
├── test_hierarchy.py       # Test hierarchy walking on hierarchical pilots
├── test_nets.py            # Test net extraction + power net detection
├── test_board.py           # Test board parsing on all PCB files
├── test_export.py          # Test JSON export + round-trip
└── conftest.py             # Fixtures pointing to data/raw/ pilot projects
```

**Key test cases:**

1. `test_discovery_finds_all_mnt_subprojects` — must find 18 design units in MNT Reform
2. `test_discovery_finds_all_hackrf_boards` — must find 5 boards
3. `test_discovery_handles_no_kicad_pro` — VESC, LibreSolar, Crazyflie
4. `test_hierarchy_depth_2` — MNT motherboard30 (root → power → regulators)
5. `test_hierarchy_depth_1` — STM32F7 FC, HackRF, Antmicro
6. `test_hierarchy_flat` — joric/nrfmicro (no hierarchy)
7. `test_ref_designator_v6` — HackRF (KiCad 6 symbolInstances format)
8. `test_ref_designator_v7plus` — Antmicro (KiCad 9 per-symbol instances)
9. `test_filename_with_spaces` — STM32F7 FC "Sensors & Peripherals"
10. `test_pcb_only_project` — Crazyflie, VESC
11. `test_power_symbol_detection` — verify VCC/GND detected as power nets
12. `test_board_layer_count` — verify correct layer counts
13. `test_board_track_via_counts` — verify track/via/zone metrics
14. `test_version_detection` — all KiCad versions across all pilots
15. `test_component_extraction` — verify components extracted from all sheets
