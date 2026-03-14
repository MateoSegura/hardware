"""Tests for vendored kiutils fixes.

Validates all 6 patches applied to kiutils v1.4.8 for KiCad 8/9 compatibility.
Uses real pilot project data from data/raw/.
"""

import sys
from pathlib import Path

import pytest

# Use vendored kiutils from tools/
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from kiutils.utils.sexpr import parse_sexp
from kiutils.items.common import Effects
from kiutils.items.brditems import Segment, Via, Arc
from kiutils.symbol import Symbol
from kiutils.schematic import Schematic
from kiutils.board import Board
from kiutils.footprint import Footprint

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
ANTMICRO_DIR = DATA_DIR / "antmicro__jetson-nano-baseboard"
HACKRF_DIR = DATA_DIR / "greatscottgadgets__hackrf"


# ── Fix 6: Scientific notation in S-expression parser ────────────────────────


class TestScientificNotation:
    """sexpr.py must parse numbers like 1e-6, 3.14e10, -2.5e+3."""

    def test_simple_scientific(self):
        result = parse_sexp("(value 1e-6)")
        assert result == ["value", 1e-6]

    def test_positive_exponent(self):
        result = parse_sexp("(value 3.14e10)")
        assert result == ["value", 3.14e10]

    def test_negative_float_scientific(self):
        result = parse_sexp("(value -2.5e+3)")
        assert result == ["value", -2500.0]

    def test_integer_scientific(self):
        result = parse_sexp("(value 1e3)")
        assert result == ["value", 1000.0]

    def test_scientific_in_context(self):
        """Scientific notation alongside normal numbers."""
        result = parse_sexp("(pad (size 1e-6 0.5))")
        assert result[0] == "pad"
        assert result[1][0] == "size"
        assert result[1][1] == 1e-6
        assert result[1][2] == 0.5

    def test_normal_numbers_still_work(self):
        result = parse_sexp("(pos 1.5 -2.0 3)")
        assert result == ["pos", 1.5, -2.0, 3]


# ── Fix 1: tstamp → uuid rename in board items ──────────────────────────────


class TestTstampUuidRename:
    """Segment, Via, Arc must accept both (tstamp ...) and (uuid ...) tokens."""

    def test_segment_tstamp(self):
        exp = ["segment", ["start", 0.0, 0.0], ["end", 1.0, 1.0],
               ["width", 0.25], ["layer", "F.Cu"], ["net", 1],
               ["tstamp", "abc-123"]]
        seg = Segment.from_sexpr(exp)
        assert seg.tstamp == "abc-123"

    def test_segment_uuid(self):
        exp = ["segment", ["start", 0.0, 0.0], ["end", 1.0, 1.0],
               ["width", 0.25], ["layer", "F.Cu"], ["net", 1],
               ["uuid", "def-456"]]
        seg = Segment.from_sexpr(exp)
        assert seg.tstamp == "def-456"

    def test_via_tstamp(self):
        exp = ["via", ["at", 5.0, 5.0], ["size", 0.8], ["drill", 0.4],
               ["layers", "F.Cu", "B.Cu"], ["net", 2],
               ["tstamp", "old-id"]]
        via = Via.from_sexpr(exp)
        assert via.tstamp == "old-id"

    def test_via_uuid(self):
        exp = ["via", ["at", 5.0, 5.0], ["size", 0.8], ["drill", 0.4],
               ["layers", "F.Cu", "B.Cu"], ["net", 2],
               ["uuid", "new-id"]]
        via = Via.from_sexpr(exp)
        assert via.tstamp == "new-id"

    def test_arc_tstamp(self):
        exp = ["arc", ["start", 0.0, 0.0], ["mid", 0.5, 0.5],
               ["end", 1.0, 0.0], ["width", 0.2], ["layer", "F.Cu"],
               ["net", 1], ["tstamp", "arc-old"]]
        arc = Arc.from_sexpr(exp)
        assert arc.tstamp == "arc-old"

    def test_arc_uuid(self):
        exp = ["arc", ["start", 0.0, 0.0], ["mid", 0.5, 0.5],
               ["end", 1.0, 0.0], ["width", 0.2], ["layer", "F.Cu"],
               ["net", 1], ["uuid", "arc-new"]]
        arc = Arc.from_sexpr(exp)
        assert arc.tstamp == "arc-new"

    def test_kicad9_board_vias_have_uuid(self):
        """Parse real KiCad 9 PCB and verify vias have their uuid stored."""
        pcb_file = ANTMICRO_DIR / "jetson-nano-baseboard.kicad_pcb"
        if not pcb_file.exists():
            pytest.skip("Antmicro pilot data not available")
        board = Board.from_file(str(pcb_file))
        vias = [t for t in board.traceItems if isinstance(t, Via)]
        assert len(vias) > 0, "Expected vias in KiCad 9 board"
        for via in vias[:5]:
            assert via.tstamp, f"Via missing tstamp/uuid"
            # KiCad 9 UUIDs have the standard format
            assert "-" in via.tstamp, f"Expected UUID format, got: {via.tstamp}"


# ── Fix 2: (hide yes) syntax in Effects ──────────────────────────────────────


class TestHideYesSyntax:
    """Effects must handle both bare 'hide' and (hide yes) tokens."""

    def test_bare_hide(self):
        """KiCad <= 7 style: (effects ... hide)"""
        exp = ["effects", ["font", ["size", 1.27, 1.27]], "hide"]
        eff = Effects.from_sexpr(exp)
        assert eff.hide is True

    def test_hide_yes(self):
        """KiCad 8+ style: (effects ... (hide yes))"""
        exp = ["effects", ["font", ["size", 1.27, 1.27]], ["hide", "yes"]]
        eff = Effects.from_sexpr(exp)
        assert eff.hide is True

    def test_hide_no(self):
        """(hide no) should set hide to False."""
        exp = ["effects", ["font", ["size", 1.27, 1.27]], ["hide", "no"]]
        eff = Effects.from_sexpr(exp)
        assert eff.hide is False

    def test_no_hide(self):
        """No hide token at all."""
        exp = ["effects", ["font", ["size", 1.27, 1.27]]]
        eff = Effects.from_sexpr(exp)
        assert eff.hide is False

    def test_kicad9_schematic_parses_hide_yes(self):
        """Parse real KiCad 9 schematic with (hide yes) tokens without crashing."""
        sch_file = ANTMICRO_DIR / "supply.kicad_sch"
        if not sch_file.exists():
            pytest.skip("Antmicro pilot data not available")
        sch = Schematic.from_file(str(sch_file))
        assert sch.version == 20250114


# ── Fix 3: Symbol name regex ────────────────────────────────────────────────


class TestSymbolNameRegex:
    """Symbol libId setter must not split names like 'C_100n_0402'."""

    def test_simple_unit_style(self):
        """Standard child symbol: 'OpAmp_1_1' → entryName=OpAmp, unit=1, style=1"""
        sym = Symbol()
        sym.libId = "OpAmp_1_1"
        assert sym.entryName == "OpAmp"
        assert sym.unitId == 1
        assert sym.styleId == 1

    def test_underscored_name_with_unit_style(self):
        """Name with underscores: 'LM358_DGK_1_1' → entryName=LM358_DGK, unit=1, style=1"""
        sym = Symbol()
        sym.libId = "LM358_DGK_1_1"
        assert sym.entryName == "LM358_DGK"
        assert sym.unitId == 1
        assert sym.styleId == 1

    def test_numeric_name_not_split(self):
        """Name 'C_100n_0402' has non-numeric segments so it should NOT match unit/style pattern.
        '100n' is not all digits, so the regex won't match _\d+_\d+$ and it becomes a plain name."""
        sym = Symbol()
        sym.libId = "C_100n_0402"
        # '100n' is not purely numeric, so no unit/style split
        assert sym.entryName == "C_100n_0402"
        assert sym.unitId is None

    def test_library_prefixed(self):
        """Library:Name format: 'Device:R' → libraryNickname=Device, entryName=R"""
        sym = Symbol()
        sym.libId = "Device:R"
        assert sym.libraryNickname == "Device"
        assert sym.entryName == "R"

    def test_plain_name(self):
        """Plain name without underscores or colons."""
        sym = Symbol()
        sym.libId = "MySymbol"
        assert sym.entryName == "MySymbol"
        assert sym.libraryNickname is None
        assert sym.unitId is None


# ── Fix 4: generator_version token ──────────────────────────────────────────


class TestGeneratorVersion:
    """Schematic, Board, Footprint must parse generator_version from KiCad 9+."""

    def test_schematic_generator_version(self):
        sch_file = ANTMICRO_DIR / "jetson-nano-baseboard.kicad_sch"
        if not sch_file.exists():
            pytest.skip("Antmicro pilot data not available")
        sch = Schematic.from_file(str(sch_file))
        assert sch.generatorVersion == "9.0"

    def test_board_generator_version(self):
        pcb_file = ANTMICRO_DIR / "jetson-nano-baseboard.kicad_pcb"
        if not pcb_file.exists():
            pytest.skip("Antmicro pilot data not available")
        board = Board.from_file(str(pcb_file))
        assert board.generatorVersion == "9.0"

    def test_schematic_without_generator_version(self):
        """Older KiCad files should have generatorVersion=None."""
        sch_files = list(HACKRF_DIR.rglob("*.kicad_sch"))
        if not sch_files:
            pytest.skip("HackRF pilot data not available")
        sch = Schematic.from_file(str(sch_files[0]))
        assert sch.generatorVersion is None


# ── Fix 5: embedded_fonts token ─────────────────────────────────────────────


class TestEmbeddedFonts:
    """Schematic must parse embedded_fonts token without crashing."""

    def test_embedded_fonts_parsed(self):
        sch_file = ANTMICRO_DIR / "jetson-nano-baseboard.kicad_sch"
        if not sch_file.exists():
            pytest.skip("Antmicro pilot data not available")
        sch = Schematic.from_file(str(sch_file))
        # KiCad 9 has (embedded_fonts no) at top level
        assert sch.embeddedFonts is not None

    def test_older_schematic_no_embedded_fonts(self):
        sch_files = list(HACKRF_DIR.rglob("*.kicad_sch"))
        if not sch_files:
            pytest.skip("HackRF pilot data not available")
        sch = Schematic.from_file(str(sch_files[0]))
        assert sch.embeddedFonts is None


# ── Integration: Parse all pilot projects ────────────────────────────────────


class TestPilotProjectParsing:
    """All pilot projects must parse without exceptions."""

    @pytest.mark.parametrize("project_name", [
        "antmicro__jetson-nano-baseboard",
        "greatscottgadgets__hackrf",
        "joric__nrfmicro",
        "maxlab-io__tokay-lite-pcb",
        "mnt__reform",
        "rishikesh2715__stm32f7-fc",
    ])
    def test_schematic_parsing(self, project_name):
        project_dir = DATA_DIR / project_name
        if not project_dir.exists():
            pytest.skip(f"{project_name} pilot data not available")
        sch_files = list(project_dir.rglob("*.kicad_sch"))
        if not sch_files:
            pytest.skip(f"No schematic files in {project_name}")
        for sch_file in sch_files[:3]:  # Test up to 3 per project
            sch = Schematic.from_file(str(sch_file))
            assert sch.version is not None

    @pytest.mark.parametrize("project_name", [
        "antmicro__jetson-nano-baseboard",
        "greatscottgadgets__hackrf",
        "joric__nrfmicro",
        "maxlab-io__tokay-lite-pcb",
    ])
    def test_board_parsing(self, project_name):
        project_dir = DATA_DIR / project_name
        if not project_dir.exists():
            pytest.skip(f"{project_name} pilot data not available")
        pcb_files = list(project_dir.rglob("*.kicad_pcb"))
        if not pcb_files:
            pytest.skip(f"No PCB files in {project_name}")
        board = Board.from_file(str(pcb_files[0]))
        assert board.version is not None
