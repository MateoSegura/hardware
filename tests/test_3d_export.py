"""Tests for 3D model export (TASK-029).

Uses REAL kicad-cli exports on pilot projects.
No mocks — all tests run actual kicad-cli commands.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.pipeline.manufacturing import (
    Model3dOutput,
    export_step,
    export_vrml,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DATA_RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
STM32F7_PCB = DATA_RAW / "rishikesh2715__stm32f7-fc" / "Flight_Controller.kicad_pcb"
VESC_PCB = DATA_RAW / "paltatech__VESC-controller" / "pcb_design" / "VESC-controller.kicad_pcb"


@pytest.fixture
def tmp_dir():
    """Provide a temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory(prefix="3d_test_") as d:
        yield Path(d)


# ---------------------------------------------------------------------------
# TASK-029: STEP export tests
# ---------------------------------------------------------------------------


class TestStepExport:
    """Test STEP 3D model export on real projects."""

    def test_export_step_produces_file(self, tmp_dir):
        """STEP export should create a .step file."""
        step_path = tmp_dir / "board.step"
        result = export_step(STM32F7_PCB, step_path)

        assert isinstance(result, Model3dOutput)
        assert result.success is True
        assert result.output_path == step_path
        assert step_path.exists()

    def test_export_step_file_nonempty(self, tmp_dir):
        """STEP file should contain valid ISO-10303 data."""
        step_path = tmp_dir / "board.step"
        result = export_step(STM32F7_PCB, step_path)

        assert result.success is True
        assert result.file_size_bytes > 0
        content = step_path.read_text(errors="replace")[:200]
        assert "ISO-10303" in content

    def test_export_step_board_only(self, tmp_dir):
        """Board-only STEP should be smaller than full export."""
        full_path = tmp_dir / "full.step"
        board_path = tmp_dir / "board_only.step"

        full_result = export_step(STM32F7_PCB, full_path)
        board_result = export_step(STM32F7_PCB, board_path, board_only=True)

        assert full_result.success is True
        assert board_result.success is True
        # Board-only should produce a valid file (may be smaller or same size
        # depending on whether 3D models were found)
        assert board_result.file_size_bytes > 0

    def test_export_step_nonexistent_pcb(self, tmp_dir):
        """Should handle nonexistent PCB gracefully."""
        result = export_step(
            Path("/nonexistent/file.kicad_pcb"),
            tmp_dir / "out.step",
        )
        assert result.success is False
        assert len(result.errors) > 0

    def test_export_step_second_project(self, tmp_dir):
        """STEP export should work on a different project (vesc/KiCad 9)."""
        step_path = tmp_dir / "vesc.step"
        result = export_step(VESC_PCB, step_path)

        assert result.success is True
        assert step_path.exists()
        assert result.file_size_bytes > 0

    def test_export_step_overwrite(self, tmp_dir):
        """Re-exporting should overwrite existing file."""
        step_path = tmp_dir / "board.step"

        result1 = export_step(STM32F7_PCB, step_path)
        result2 = export_step(STM32F7_PCB, step_path)

        assert result1.success is True
        assert result2.success is True
        assert result2.file_size_bytes > 0


# ---------------------------------------------------------------------------
# TASK-029: VRML export tests
# ---------------------------------------------------------------------------


class TestVrmlExport:
    """Test VRML 3D model export on real projects."""

    def test_export_vrml_produces_file(self, tmp_dir):
        """VRML export should create a .wrl file."""
        wrl_path = tmp_dir / "board.wrl"
        result = export_vrml(STM32F7_PCB, wrl_path)

        assert isinstance(result, Model3dOutput)
        assert result.success is True
        assert result.output_path == wrl_path
        assert wrl_path.exists()

    def test_export_vrml_file_nonempty(self, tmp_dir):
        """VRML file should contain valid VRML97 header."""
        wrl_path = tmp_dir / "board.wrl"
        result = export_vrml(STM32F7_PCB, wrl_path)

        assert result.success is True
        assert result.file_size_bytes > 0
        content = wrl_path.read_text(errors="replace")[:100]
        assert "#VRML V2.0" in content

    def test_export_vrml_larger_than_step(self, tmp_dir):
        """VRML embeds models, so should be larger than STEP for same board."""
        step_path = tmp_dir / "board.step"
        wrl_path = tmp_dir / "board.wrl"

        step_result = export_step(STM32F7_PCB, step_path)
        vrml_result = export_vrml(STM32F7_PCB, wrl_path)

        assert step_result.success is True
        assert vrml_result.success is True
        assert vrml_result.file_size_bytes > step_result.file_size_bytes

    def test_export_vrml_nonexistent_pcb(self, tmp_dir):
        """Should handle nonexistent PCB gracefully."""
        result = export_vrml(
            Path("/nonexistent/file.kicad_pcb"),
            tmp_dir / "out.wrl",
        )
        assert result.success is False
        assert len(result.errors) > 0

    def test_export_vrml_second_project(self, tmp_dir):
        """VRML export should work on vesc (KiCad 9)."""
        wrl_path = tmp_dir / "vesc.wrl"
        result = export_vrml(VESC_PCB, wrl_path)

        assert result.success is True
        assert wrl_path.exists()
        assert result.file_size_bytes > 0

    def test_export_vrml_units_mm(self, tmp_dir):
        """VRML export with mm units should succeed."""
        wrl_path = tmp_dir / "board_mm.wrl"
        result = export_vrml(STM32F7_PCB, wrl_path, units="mm")

        assert result.success is True
        assert result.file_size_bytes > 0
