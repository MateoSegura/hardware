"""Tests for kicad-cli validation module against pilot data in data/raw/."""

import csv
import tempfile
from pathlib import Path


from src.pipeline.validate import (
    export_bom,
    export_netlist,
    run_drc,
    run_erc,
    validate_project,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

STM32_SCH = DATA_DIR / "rishikesh2715__stm32f7-fc" / "Flight_Controller.kicad_sch"
STM32_PCB = DATA_DIR / "rishikesh2715__stm32f7-fc" / "Flight_Controller.kicad_pcb"
HACKRF_SCH = DATA_DIR / "greatscottgadgets__hackrf" / "hardware" / "hackrf-one" / "hackrf-one.kicad_sch"
ANTMICRO_SCH = DATA_DIR / "antmicro__jetson-nano-baseboard" / "jetson-nano-baseboard.kicad_sch"
NRFMICRO_SCH = DATA_DIR / "joric__nrfmicro" / "hardware" / "nrfmicro.kicad_sch"
NRFMICRO_PCB = DATA_DIR / "joric__nrfmicro" / "hardware" / "nrfmicro.kicad_pcb"
NRFMICRO_DIR = DATA_DIR / "joric__nrfmicro" / "hardware"
VESC_PCB = DATA_DIR / "vedderb__bldc-hardware" / "design" / "BLDC_4.kicad_pcb"
VESC_DIR = DATA_DIR / "vedderb__bldc-hardware" / "design"


# ---------------------------------------------------------------------------
# Test 1: ERC on STM32F7 FC
# ---------------------------------------------------------------------------

def test_erc_stm32f7():
    """Run ERC on STM32F7 FC, verify structured results."""
    result = run_erc(STM32_SCH)
    assert result["success"] is True
    assert isinstance(result["violations"], int)
    assert isinstance(result["errors"], int)
    assert isinstance(result["warnings"], int)
    assert isinstance(result["details"], list)
    # STM32F7 FC will have some violations (real project, not perfect)
    assert result["violations"] >= 0


# ---------------------------------------------------------------------------
# Test 2: ERC on HackRF
# ---------------------------------------------------------------------------

def test_erc_hackrf():
    """Run ERC on HackRF (KiCad 6 format)."""
    result = run_erc(HACKRF_SCH)
    assert result["success"] is True
    assert isinstance(result["violations"], int)
    assert isinstance(result["details"], list)


# ---------------------------------------------------------------------------
# Test 3: ERC on Antmicro Jetson (KiCad 9)
# ---------------------------------------------------------------------------

def test_erc_antmicro():
    """Run ERC on Antmicro Jetson baseboard (KiCad 9 format)."""
    result = run_erc(ANTMICRO_SCH)
    assert result["success"] is True
    assert isinstance(result["violations"], int)


# ---------------------------------------------------------------------------
# Test 4: DRC on STM32F7 PCB
# ---------------------------------------------------------------------------

def test_drc_stm32f7():
    """Run DRC on STM32F7 PCB, verify structured results."""
    result = run_drc(STM32_PCB)
    assert result["success"] is True
    assert isinstance(result["violations"], int)
    assert isinstance(result["errors"], int)
    assert isinstance(result["warnings"], int)
    assert isinstance(result["unconnected"], int)
    assert isinstance(result["details"], list)


# ---------------------------------------------------------------------------
# Test 5: DRC on nrfmicro PCB
# ---------------------------------------------------------------------------

def test_drc_nrfmicro():
    """Run DRC on nrfmicro PCB."""
    result = run_drc(NRFMICRO_PCB)
    assert result["success"] is True
    assert isinstance(result["violations"], int)
    assert isinstance(result["unconnected"], int)
    # Violation counts should be consistent
    assert result["violations"] == result["errors"] + result["warnings"]


# ---------------------------------------------------------------------------
# Test 6: Export netlist
# ---------------------------------------------------------------------------

def test_export_netlist():
    """Export netlist, verify output file exists and is non-empty."""
    with tempfile.NamedTemporaryFile(suffix=".net", delete=False) as tmp:
        output = Path(tmp.name)

    try:
        result = export_netlist(NRFMICRO_SCH, output)
        assert result == output
        assert output.exists()
        assert output.stat().st_size > 0
        # Should contain KiCad netlist content
        content = output.read_text()
        assert "export" in content or "net" in content.lower()
    finally:
        output.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test 7: Export BOM
# ---------------------------------------------------------------------------

def test_export_bom():
    """Export BOM, verify CSV output."""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        output = Path(tmp.name)

    try:
        result = export_bom(NRFMICRO_SCH, output)
        assert result == output
        assert output.exists()
        assert output.stat().st_size > 0

        # Parse as CSV and verify structure
        with open(output) as f:
            reader = csv.reader(f)
            headers = next(reader)
            assert "Refs" in headers or "Reference" in headers
            assert "Value" in headers
            rows = list(reader)
            assert len(rows) > 0  # Should have at least one component
    finally:
        output.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test 8: Full project validation (e2e)
# ---------------------------------------------------------------------------

def test_validate_project_e2e():
    """Full validation on nrfmicro (simplest project)."""
    report = validate_project(NRFMICRO_DIR)
    assert report["project_dir"] == str(NRFMICRO_DIR)
    assert report["schematic"] is not None
    assert report["pcb"] is not None

    # ERC should have run
    assert report["erc"] is not None
    assert report["erc"]["success"] is True
    assert isinstance(report["erc"]["violations"], int)

    # DRC should have run
    assert report["drc"] is not None
    assert report["drc"]["success"] is True
    assert isinstance(report["drc"]["violations"], int)


# ---------------------------------------------------------------------------
# Test 9: Legacy format graceful handling
# ---------------------------------------------------------------------------

def test_legacy_format_graceful():
    """VESC (KiCad 4 PCB, no schematic) should not crash."""
    # DRC on legacy PCB should still succeed (kicad-cli handles upgrades)
    result = run_drc(VESC_PCB)
    assert result["success"] is True

    # ERC on nonexistent schematic should fail gracefully
    nonexistent = VESC_DIR / "nonexistent.kicad_sch"
    result = run_erc(nonexistent)
    assert result["success"] is False
    assert "not found" in result["stderr"].lower() or "File not found" in result["stderr"]

    # validate_project on VESC dir (PCB only, no schematic)
    report = validate_project(VESC_DIR)
    assert report["erc"] is None  # No schematic found
    assert report["drc"] is not None
    assert report["drc"]["success"] is True
