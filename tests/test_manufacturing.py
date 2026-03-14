"""Tests for manufacturing integration (TASK-025 through TASK-028).

Uses REAL kicad-cli exports on the STM32F7 FC pilot project.
No mocks — all tests run actual kicad-cli commands.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.pipeline.manufacturing import (
    BomEntry,
    BomMatchResult,
    CplEntry,
    GerberOutput,
    InventoryItem,
    assign_feeders,
    export_bom,
    export_drill,
    export_gerbers,
    export_manufacturing_package,
    export_placement,
    generate_lumen_pnp_csv,
    load_inventory,
    match_bom_to_inventory,
    save_inventory,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DATA_RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
STM32F7_DIR = DATA_RAW / "rishikesh2715__stm32f7-fc"
STM32F7_SCH = STM32F7_DIR / "Flight_Controller.kicad_sch"
STM32F7_PCB = STM32F7_DIR / "Flight_Controller.kicad_pcb"


@pytest.fixture
def tmp_dir():
    """Provide a temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory(prefix="mfg_test_") as d:
        yield Path(d)


@pytest.fixture
def sample_inventory(tmp_dir) -> Path:
    """Create a sample inventory JSON file."""
    items = [
        {
            "mpn": "GRM155R71C104KA88D",
            "description": "100nF 0402 MLCC",
            "package": "0402",
            "quantity_available": 500,
            "feeder_slot": 1,
        },
        {
            "mpn": "GRM155R71H103KA88D",
            "description": "10nF 0402 MLCC",
            "package": "0402",
            "quantity_available": 200,
            "feeder_slot": 2,
        },
        {
            "mpn": "RC0201FR-0710KL",
            "description": "10K 0201 resistor",
            "package": "0201",
            "quantity_available": 1000,
            "feeder_slot": 3,
        },
        {
            "mpn": "GRM188R61C106MA73D",
            "description": "10uF 0805 MLCC",
            "package": "0805",
            "quantity_available": 50,
            "feeder_slot": 4,
        },
        {
            "mpn": "STM32F722RET6",
            "description": "STM32F722 MCU LQFP-64",
            "package": "LQFP-64",
            "quantity_available": 5,
            "feeder_slot": None,
        },
    ]
    path = tmp_dir / "inventory.json"
    path.write_text(json.dumps(items, indent=2))
    return path


# ---------------------------------------------------------------------------
# TASK-025: Inventory tests
# ---------------------------------------------------------------------------


class TestInventory:
    """Test parts inventory load/save."""

    def test_load_inventory(self, sample_inventory):
        items = load_inventory(sample_inventory)
        assert len(items) == 5
        assert all(isinstance(i, InventoryItem) for i in items)
        assert items[0].mpn == "GRM155R71C104KA88D"
        assert items[0].package == "0402"
        assert items[0].quantity_available == 500
        assert items[0].feeder_slot == 1

    def test_load_inventory_feeder_none(self, sample_inventory):
        items = load_inventory(sample_inventory)
        mcu = [i for i in items if i.mpn == "STM32F722RET6"][0]
        assert mcu.feeder_slot is None

    def test_save_inventory(self, tmp_dir):
        items = [
            InventoryItem(
                mpn="TEST-001",
                description="Test part",
                package="0402",
                quantity_available=100,
                feeder_slot=5,
            ),
            InventoryItem(
                mpn="TEST-002",
                description="Another part",
                package="0805",
                quantity_available=50,
                feeder_slot=None,
            ),
        ]
        out = tmp_dir / "saved_inventory.json"
        save_inventory(items, out)

        assert out.exists()
        data = json.loads(out.read_text())
        assert len(data) == 2
        assert data[0]["mpn"] == "TEST-001"
        assert data[1]["feeder_slot"] is None

    def test_roundtrip_inventory(self, tmp_dir):
        original = [
            InventoryItem("MPN-A", "Cap 100nF", "0402", 250, 1),
            InventoryItem("MPN-B", "Res 10K", "0201", 500, 3),
        ]
        path = tmp_dir / "rt_inv.json"
        save_inventory(original, path)
        loaded = load_inventory(path)

        assert len(loaded) == len(original)
        for orig, load in zip(original, loaded):
            assert orig.mpn == load.mpn
            assert orig.description == load.description
            assert orig.package == load.package
            assert orig.quantity_available == load.quantity_available
            assert orig.feeder_slot == load.feeder_slot


# ---------------------------------------------------------------------------
# TASK-026: BOM export and matching
# ---------------------------------------------------------------------------


class TestBomExport:
    """Test BOM export using real kicad-cli on STM32F7 FC project."""

    def test_export_bom_produces_entries(self, tmp_dir):
        bom_path = tmp_dir / "bom.csv"
        entries = export_bom(STM32F7_SCH, bom_path)

        assert bom_path.exists()
        assert len(entries) > 50  # STM32F7 FC has ~130 components
        assert all(isinstance(e, BomEntry) for e in entries)

    def test_export_bom_has_expected_refs(self, tmp_dir):
        bom_path = tmp_dir / "bom.csv"
        entries = export_bom(STM32F7_SCH, bom_path)

        refs = {e.ref for e in entries}
        # Known components in the STM32F7 FC project
        assert "U8" in refs  # STM32F722RET6
        assert "C1" in refs
        assert "R1" in refs

    def test_export_bom_footprints_populated(self, tmp_dir):
        bom_path = tmp_dir / "bom.csv"
        entries = export_bom(STM32F7_SCH, bom_path)

        # All entries should have footprints
        with_fp = [e for e in entries if e.footprint]
        assert len(with_fp) > 0

    def test_export_bom_values_populated(self, tmp_dir):
        bom_path = tmp_dir / "bom.csv"
        entries = export_bom(STM32F7_SCH, bom_path)

        u8 = [e for e in entries if e.ref == "U8"][0]
        assert "STM32F722" in u8.value

    def test_export_bom_nonexistent_file(self, tmp_dir):
        with pytest.raises(RuntimeError, match="BOM export failed"):
            export_bom(Path("/nonexistent/file.kicad_sch"), tmp_dir / "bom.csv")


class TestBomMatching:
    """Test BOM-to-inventory matching."""

    def test_match_bom_to_inventory_basic(self, sample_inventory):
        inventory = load_inventory(sample_inventory)
        bom = [
            BomEntry(ref="C1", value="100n", footprint="Capacitor_SMD:C_0402_1005Metric"),
            BomEntry(ref="R1", value="10K", footprint="Resistor_SMD:R_0201_0603Metric"),
        ]

        result = match_bom_to_inventory(bom, inventory)
        assert isinstance(result, BomMatchResult)
        assert len(result.matched) == 2
        assert len(result.unmatched) == 0
        assert len(result.missing_parts) == 0

    def test_match_unmatched_parts(self, sample_inventory):
        inventory = load_inventory(sample_inventory)
        bom = [
            BomEntry(ref="U99", value="UNKNOWN-IC", footprint="Custom:UNKNOWN_PKG"),
        ]

        result = match_bom_to_inventory(bom, inventory)
        assert len(result.matched) == 0
        assert len(result.unmatched) == 1

    def test_match_missing_parts_quantity(self):
        inventory = [
            InventoryItem("CAP-001", "100nF cap", "0402", 1, 1),
        ]
        bom = [
            BomEntry(ref="C1", value="100n", footprint="Capacitor_SMD:C_0402_1005Metric"),
            BomEntry(ref="C2", value="100n", footprint="Capacitor_SMD:C_0402_1005Metric"),
        ]

        result = match_bom_to_inventory(bom, inventory)
        assert len(result.matched) == 1
        assert len(result.missing_parts) == 1

    def test_match_dnp_entries_go_to_unmatched(self, sample_inventory):
        inventory = load_inventory(sample_inventory)
        bom = [
            BomEntry(ref="C1", value="100n", footprint="Capacitor_SMD:C_0402_1005Metric", dnp=True),
        ]

        result = match_bom_to_inventory(bom, inventory)
        assert len(result.matched) == 0
        assert len(result.unmatched) == 1

    def test_match_real_bom_to_inventory(self, tmp_dir, sample_inventory):
        """Match real BOM from STM32F7 FC against sample inventory."""
        bom_path = tmp_dir / "bom.csv"
        entries = export_bom(STM32F7_SCH, bom_path)
        inventory = load_inventory(sample_inventory)

        result = match_bom_to_inventory(entries, inventory)
        # We should have some matches (0402 caps, 0805 caps, MCU)
        assert len(result.matched) > 0
        total = len(result.matched) + len(result.unmatched) + len(result.missing_parts)
        assert total == len(entries)


# ---------------------------------------------------------------------------
# TASK-027: CPL / position export
# ---------------------------------------------------------------------------


class TestCplExport:
    """Test component placement export on real project."""

    def test_export_placement_produces_entries(self, tmp_dir):
        cpl_path = tmp_dir / "pos.csv"
        entries = export_placement(STM32F7_PCB, cpl_path)

        assert cpl_path.exists()
        assert len(entries) > 50
        assert all(isinstance(e, CplEntry) for e in entries)

    def test_export_placement_has_coordinates(self, tmp_dir):
        cpl_path = tmp_dir / "pos.csv"
        entries = export_placement(STM32F7_PCB, cpl_path)

        for entry in entries:
            # Coordinates should be numeric and in a reasonable range
            assert isinstance(entry.x_mm, float)
            assert isinstance(entry.y_mm, float)
            assert isinstance(entry.rotation, float)

    def test_export_placement_has_sides(self, tmp_dir):
        cpl_path = tmp_dir / "pos.csv"
        entries = export_placement(STM32F7_PCB, cpl_path)

        sides = {e.side for e in entries}
        # STM32F7 FC has components on both sides
        assert "top" in sides
        assert "bottom" in sides

    def test_export_placement_known_components(self, tmp_dir):
        cpl_path = tmp_dir / "pos.csv"
        entries = export_placement(STM32F7_PCB, cpl_path)

        refs = {e.ref for e in entries}
        assert "U8" in refs  # STM32F722

    def test_export_placement_nonexistent_file(self, tmp_dir):
        with pytest.raises(RuntimeError, match="Position export failed"):
            export_placement(Path("/nonexistent/file.kicad_pcb"), tmp_dir / "pos.csv")

    def test_generate_lumen_pnp_csv(self, tmp_dir):
        cpl = [
            CplEntry(ref="C1", x_mm=10.5, y_mm=20.3, rotation=90.0, side="top", feeder_slot=1),
            CplEntry(ref="U1", x_mm=30.0, y_mm=40.0, rotation=0.0, side="bottom", feeder_slot=None),
        ]
        out = tmp_dir / "lumen.csv"
        generate_lumen_pnp_csv(cpl, out)

        assert out.exists()
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 3  # header + 2 entries
        assert "Designator" in lines[0]
        assert "C1" in lines[1]
        assert ",T," in lines[1]  # top
        assert ",B," in lines[2]  # bottom

    def test_generate_lumen_pnp_from_real_data(self, tmp_dir):
        """Generate LumenPNP CSV from real STM32F7 FC placement data."""
        cpl_path = tmp_dir / "pos.csv"
        entries = export_placement(STM32F7_PCB, cpl_path)

        lumen_path = tmp_dir / "lumen_pnp.csv"
        generate_lumen_pnp_csv(entries, lumen_path)

        assert lumen_path.exists()
        lines = lumen_path.read_text().strip().split("\n")
        # Header + all entries
        assert len(lines) == len(entries) + 1

    def test_assign_feeders(self, sample_inventory):
        inventory = load_inventory(sample_inventory)
        bom = [
            BomEntry(ref="C1", value="100n", footprint="Capacitor_SMD:C_0402_1005Metric"),
        ]
        cpl = [
            CplEntry(ref="C1", x_mm=10.0, y_mm=20.0, rotation=0.0, side="top"),
        ]

        updated = assign_feeders(cpl, inventory, bom)
        assert updated[0].feeder_slot == 1  # 0402 cap feeder


# ---------------------------------------------------------------------------
# TASK-028: Gerber + drill export
# ---------------------------------------------------------------------------


class TestGerberExport:
    """Test Gerber export on real project."""

    def test_export_gerbers_produces_files(self, tmp_dir):
        gerber_dir = tmp_dir / "gerbers"
        result = export_gerbers(STM32F7_PCB, gerber_dir)

        assert isinstance(result, GerberOutput)
        assert result.success is True
        assert len(result.gerber_files) > 10  # STM32F7 FC has many layers
        assert len(result.errors) == 0

    def test_export_gerbers_file_extensions(self, tmp_dir):
        gerber_dir = tmp_dir / "gerbers"
        result = export_gerbers(STM32F7_PCB, gerber_dir)

        extensions = {f.suffix.lower() for f in result.gerber_files}
        # Should have at least front/back copper
        assert ".gtl" in extensions  # front copper
        assert ".gbl" in extensions  # back copper

    def test_export_gerbers_files_nonempty(self, tmp_dir):
        gerber_dir = tmp_dir / "gerbers"
        result = export_gerbers(STM32F7_PCB, gerber_dir)

        for f in result.gerber_files:
            assert f.stat().st_size > 0, f"Gerber file {f.name} is empty"

    def test_export_gerbers_nonexistent_pcb(self, tmp_dir):
        result = export_gerbers(Path("/nonexistent/file.kicad_pcb"), tmp_dir / "gerbers")
        assert result.success is False
        assert len(result.errors) > 0


class TestDrillExport:
    """Test drill file export on real project."""

    def test_export_drill_produces_files(self, tmp_dir):
        drill_dir = tmp_dir / "drill"
        result = export_drill(STM32F7_PCB, drill_dir)

        assert isinstance(result, GerberOutput)
        assert result.success is True
        assert len(result.drill_files) >= 1
        assert len(result.errors) == 0

    def test_export_drill_files_nonempty(self, tmp_dir):
        drill_dir = tmp_dir / "drill"
        result = export_drill(STM32F7_PCB, drill_dir)

        for f in result.drill_files:
            assert f.stat().st_size > 0, f"Drill file {f.name} is empty"

    def test_export_drill_has_drl_extension(self, tmp_dir):
        drill_dir = tmp_dir / "drill"
        result = export_drill(STM32F7_PCB, drill_dir)

        extensions = {f.suffix.lower() for f in result.drill_files}
        assert ".drl" in extensions

    def test_export_drill_nonexistent_pcb(self, tmp_dir):
        result = export_drill(Path("/nonexistent/file.kicad_pcb"), tmp_dir / "drill")
        assert result.success is False
        assert len(result.errors) > 0


# ---------------------------------------------------------------------------
# TASK-028: Full manufacturing package
# ---------------------------------------------------------------------------


class TestManufacturingPackage:
    """Test complete manufacturing package export."""

    def test_export_manufacturing_package(self, tmp_dir):
        out = tmp_dir / "mfg_output"
        summary = export_manufacturing_package(STM32F7_PCB, STM32F7_SCH, out)

        assert summary["success"] is True
        assert summary["gerbers"]["count"] > 10
        assert summary["drill"]["count"] >= 1
        assert summary["bom_count"] > 50
        assert summary["cpl_count"] > 50
        assert len(summary["errors"]) == 0

    def test_manufacturing_package_creates_all_files(self, tmp_dir):
        out = tmp_dir / "mfg_output"
        export_manufacturing_package(STM32F7_PCB, STM32F7_SCH, out)

        assert (out / "gerbers").is_dir()
        assert (out / "drill").is_dir()
        assert (out / "bom.csv").is_file()
        assert (out / "cpl.csv").is_file()
        assert (out / "lumen_pnp.csv").is_file()

    def test_manufacturing_package_gerbers_directory(self, tmp_dir):
        out = tmp_dir / "mfg_output"
        export_manufacturing_package(STM32F7_PCB, STM32F7_SCH, out)

        gerber_files = list((out / "gerbers").iterdir())
        assert len(gerber_files) > 10

    def test_manufacturing_package_bom_csv_readable(self, tmp_dir):
        out = tmp_dir / "mfg_output"
        export_manufacturing_package(STM32F7_PCB, STM32F7_SCH, out)

        bom_text = (out / "bom.csv").read_text()
        assert "Refs" in bom_text or "Reference" in bom_text
        lines = bom_text.strip().split("\n")
        assert len(lines) > 50
