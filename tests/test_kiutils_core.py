"""Core test suite for kiutils parsing against pilot project data.

Tests verify that the vendored kiutils library correctly parses real KiCad
project files from ~/hardware/data/raw/. Each test is independent with no
shared state.

Run: cd ~/hardware && python3 -m pytest tests/test_kiutils_core.py -v
"""

import sys
from pathlib import Path

import pytest

# Ensure vendored kiutils is importable
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from kiutils.schematic import Schematic
from kiutils.board import Board
from kiutils.items.brditems import Segment, Via
from kiutils.items.schitems import (
    HierarchicalSheet,
    SchematicSymbol,
    SymbolInstance,
    HierarchicalLabel,
    GlobalLabel,
    LocalLabel,
    HierarchicalPin,
)
from kiutils.items.common import Net


# ============================================================================
# Helpers
# ============================================================================

DATA_RAW = Path(__file__).resolve().parent.parent / "data" / "raw"


def _skip_if_missing(filepath: Path):
    """Skip a test if the required data file doesn't exist."""
    if not filepath.exists():
        pytest.skip(f"Pilot data not found: {filepath}")


def _load_sch(filepath: Path) -> Schematic:
    """Load a schematic, skipping if the file is missing."""
    _skip_if_missing(filepath)
    return Schematic.from_file(str(filepath))


def _load_board(filepath: Path) -> Board:
    """Load a board, skipping if the file is missing."""
    _skip_if_missing(filepath)
    return Board.from_file(str(filepath))


# ============================================================================
# Schematic Parsing Tests
# ============================================================================


class TestSchematicParsing:
    """Tests 1-10: Schematic file parsing."""

    def test_load_flat_schematic(self, nrfmicro_sch):
        """Test 1: Load joric/nrfmicro flat schematic, verify components exist."""
        sch = _load_sch(nrfmicro_sch)
        assert len(sch.schematicSymbols) > 0, "Flat schematic should have components"
        assert len(sch.sheets) == 0, "Flat schematic should have no sub-sheets"

    def test_load_hierarchical_schematic(self, stm32f7_root_sch):
        """Test 2: Load STM32F7 FC root schematic, verify 4 hierarchical sheets."""
        sch = _load_sch(stm32f7_root_sch)
        assert len(sch.sheets) == 4, f"Expected 4 sheets, got {len(sch.sheets)}"
        # Root of hierarchical design typically has no direct components
        assert len(sch.schematicSymbols) == 0, (
            "Root sheet of STM32F7 FC should have no direct components"
        )

    def test_schematic_symbols_extraction(self, stm32f7_power_sch):
        """Test 3: Load FC_Power sub-sheet, verify schematicSymbols populated."""
        sch = _load_sch(stm32f7_power_sch)
        assert len(sch.schematicSymbols) > 0, (
            "Power sub-sheet should have components"
        )
        # Verify symbols are SchematicSymbol instances
        for sym in sch.schematicSymbols:
            assert isinstance(sym, SchematicSymbol)

    def test_lib_symbols_embedded(self, stm32f7_power_sch):
        """Test 4: Verify libSymbols (template definitions) are populated."""
        sch = _load_sch(stm32f7_power_sch)
        assert len(sch.libSymbols) > 0, (
            "Sub-sheet should have embedded library symbol definitions"
        )

    def test_sheet_filename_property(self, stm32f7_root_sch):
        """Test 5: Verify sheet.fileName.value returns a valid filename string."""
        sch = _load_sch(stm32f7_root_sch)
        expected_files = {
            "FC_Power.kicad_sch",
            "FC_MCU.kicad_sch",
            "FC_Connectors.kicad_sch",
            "Sensors & Peripherals.kicad_sch",
        }
        actual_files = {s.fileName.value for s in sch.sheets}
        assert actual_files == expected_files

    def test_sheet_name_property(self, stm32f7_root_sch):
        """Test 6: Verify sheet.sheetName.value returns the display name."""
        sch = _load_sch(stm32f7_root_sch)
        expected_names = {"Power", "MCU", "Connectors", "Sensors & Peripherals"}
        actual_names = {s.sheetName.value for s in sch.sheets}
        assert actual_names == expected_names

    def test_labels_extraction(self, nrfmicro_sch, stm32f7_power_sch):
        """Test 7: Verify labels, globalLabels, hierarchicalLabels are populated."""
        # nrfmicro flat schematic has local and global labels
        sch_flat = _load_sch(nrfmicro_sch)
        assert len(sch_flat.labels) > 0, "nrfmicro should have local labels"
        assert len(sch_flat.globalLabels) > 0, "nrfmicro should have global labels"

        # FC_Power sub-sheet has global labels
        sch_power = _load_sch(stm32f7_power_sch)
        assert len(sch_power.globalLabels) > 0, (
            "FC_Power should have global labels"
        )

    def test_component_properties(self, stm32f7_power_sch):
        """Test 8: Verify Reference, Value, Footprint properties on schematicSymbols."""
        sch = _load_sch(stm32f7_power_sch)
        sym = sch.schematicSymbols[0]

        prop_keys = {p.key for p in sym.properties}
        assert "Reference" in prop_keys, "Symbol should have Reference property"
        assert "Value" in prop_keys, "Symbol should have Value property"
        assert "Footprint" in prop_keys, "Symbol should have Footprint property"

    def test_component_lib_id(self, stm32f7_power_sch):
        """Test 9: Verify libId returns 'library:name' format."""
        sch = _load_sch(stm32f7_power_sch)
        for sym in sch.schematicSymbols:
            lib_id = sym.libId
            assert isinstance(lib_id, str), "libId should be a string"
            assert len(lib_id) > 0, "libId should not be empty"
            # Most symbols have library:name format (some power symbols may not)
            if sym.libraryNickname:
                assert ":" in lib_id, (
                    f"libId should contain ':' separator, got {lib_id!r}"
                )

    def test_kicad9_schematic(self, antmicro_root_sch):
        """Test 10: Load Antmicro Jetson baseboard (KiCad 9), verify parsing."""
        sch = _load_sch(antmicro_root_sch)
        # KiCad 9 version should be >= 20250114
        assert int(sch.version) >= 20250000, (
            f"Expected KiCad 9 version, got {sch.version}"
        )
        assert len(sch.sheets) > 0, "Antmicro root should have hierarchical sheets"


# ============================================================================
# Board Parsing Tests
# ============================================================================


class TestBoardParsing:
    """Tests 11-16: PCB board file parsing."""

    def test_load_board(self, stm32f7_pcb):
        """Test 11: Load STM32F7 FC PCB, verify footprints > 0."""
        board = _load_board(stm32f7_pcb)
        assert len(board.footprints) > 0, "Board should have footprints"

    def test_board_layers(self, stm32f7_pcb):
        """Test 12: Verify STM32F7 FC has 8 signal/power/mixed layers."""
        board = _load_board(stm32f7_pcb)
        copper_layers = [
            l for l in board.layers if l.type in ("signal", "power", "mixed")
        ]
        assert len(copper_layers) == 8, (
            f"Expected 8 copper layers, got {len(copper_layers)}"
        )

    def test_board_trace_items(self, stm32f7_pcb):
        """Test 13: Verify traceItems contains Segment and Via instances."""
        board = _load_board(stm32f7_pcb)
        assert len(board.traceItems) > 0, "Board should have trace items"

        has_segment = any(isinstance(t, Segment) for t in board.traceItems)
        has_via = any(isinstance(t, Via) for t in board.traceItems)
        assert has_segment, "Board should have Segment trace items"
        assert has_via, "Board should have Via trace items"

    def test_board_footprint_properties(self, stm32f7_pcb):
        """Test 14: Verify footprint properties are accessible as Dict."""
        board = _load_board(stm32f7_pcb)
        fp = board.footprints[0]
        assert isinstance(fp.properties, dict), (
            "Footprint properties should be a dict"
        )
        # STM32F7 FC footprints have Sheetfile/Sheetname properties
        assert isinstance(fp.libId, str), "Footprint should have libId"
        assert isinstance(fp.layer, str), "Footprint should have layer"

    def test_board_nets(self, stm32f7_pcb):
        """Test 15: Verify nets list is populated with Net objects."""
        board = _load_board(stm32f7_pcb)
        assert len(board.nets) > 0, "Board should have nets"
        for net in board.nets:
            assert isinstance(net, Net), "Each net should be a Net object"
            assert isinstance(net.number, int), "Net number should be an int"
            assert isinstance(net.name, str), "Net name should be a string"

    def test_board_zones(self, stm32f7_pcb):
        """Test 16: Verify zones are parsed."""
        board = _load_board(stm32f7_pcb)
        assert len(board.zones) > 0, "STM32F7 FC board should have zones"


# ============================================================================
# Cross-Version Tests
# ============================================================================


class TestCrossVersion:
    """Tests 17-18: Cross-version compatibility."""

    @pytest.mark.parametrize(
        "project_subpath,expected_version",
        [
            ("joric__nrfmicro/hardware/nrfmicro.kicad_sch", 20211123),
            ("rishikesh2715__stm32f7-fc/Flight_Controller.kicad_sch", 20211123),
            ("greatscottgadgets__hackrf/hardware/hackrf-one/hackrf-one.kicad_sch", 20211123),
            ("antmicro__jetson-nano-baseboard/jetson-nano-baseboard.kicad_sch", 20250114),
        ],
    )
    def test_version_detection(self, data_raw, project_subpath, expected_version):
        """Test 17: Verify (version NNNN) is correctly read for each pilot."""
        filepath = data_raw / project_subpath
        sch = _load_sch(filepath)
        assert int(sch.version) == expected_version, (
            f"Expected version {expected_version}, got {sch.version}"
        )

    def test_kicad6_vs_kicad9_schematic(self, hackrf_root_sch, antmicro_root_sch):
        """Test 18: Load both HackRF (v6) and Antmicro (v9), verify both parse."""
        sch_v6 = _load_sch(hackrf_root_sch)
        sch_v9 = _load_sch(antmicro_root_sch)

        # v6 uses symbolInstances at root level
        assert int(sch_v6.version) < 20230000, "HackRF should be KiCad 6"
        assert len(sch_v6.symbolInstances) > 0, (
            "v6 root should have symbolInstances"
        )

        # v9 uses per-symbol instances
        assert int(sch_v9.version) >= 20250000, "Antmicro should be KiCad 9"
        assert len(sch_v9.sheets) > 0, "v9 root should have sheets"


# ============================================================================
# Edge Case Tests
# ============================================================================


class TestEdgeCases:
    """Tests 19-20: Edge cases from pilot data."""

    def test_filename_with_spaces(self, stm32f7_root_sch, stm32f7_fc_dir):
        """Test 19: Verify 'Sensors & Peripherals.kicad_sch' sheet reference
        is accessible and the file can be loaded."""
        sch = _load_sch(stm32f7_root_sch)

        # Find the sheet with spaces and ampersand in filename
        matching = [
            s for s in sch.sheets
            if "Sensors" in s.fileName.value and "&" in s.fileName.value
        ]
        assert len(matching) == 1, (
            "Should find exactly one sheet with 'Sensors & Peripherals'"
        )

        # Verify the referenced file can actually be loaded
        sheet_file = stm32f7_fc_dir / matching[0].fileName.value
        _skip_if_missing(sheet_file)
        sub_sch = Schematic.from_file(str(sheet_file))
        assert len(sub_sch.schematicSymbols) > 0, (
            "Sub-sheet with spaces in filename should parse with components"
        )

    def test_pcb_only_project(self, vesc_pcb):
        """Test 20: Verify Board.from_file works on VESC PCB (legacy, no schematic)."""
        board = _load_board(vesc_pcb)
        # Legacy KiCad 4 board — version will be "4" (not YYYYMMDD format)
        assert str(board.version) == "4", (
            f"VESC should be version 4, got {board.version}"
        )
        # Legacy format may not parse footprints (modules vs footprints)
        # but the file should load without error
        assert board is not None
