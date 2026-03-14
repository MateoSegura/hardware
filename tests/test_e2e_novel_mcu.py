"""End-to-end test: novel MCU (from datasheet PDF only) -> valid KiCad project.

Proves the full pipeline works for a chip with NO hardcoded fallback:
  1. Parse a real PDF datasheet via Claude CLI
  2. Generate a KiCad symbol from the parsed pin data
  3. Compose a hierarchical KiCad project using the composer
  4. Validate the project with kicad-cli ERC

Uses the ESP32-C6-WROOM-1 datasheet, which has no fallback in
datasheet_parser.py and must be extracted live via the Claude CLI.
"""

from __future__ import annotations

import shutil

import pytest

from src.pipeline.composer import (
    DesignSpec,
    PeripheralSpec,
    PowerSpec,
    compose_design,
)
from src.pipeline.datasheet_parser import parse_datasheet
from src.pipeline.symbol_gen import generate_symbol_file
from src.pipeline.validate import run_erc

CLAUDE_CLI = shutil.which("claude")


@pytest.mark.skipif(not CLAUDE_CLI, reason="Claude CLI not available")
class TestNovelMCUE2E:
    """Full pipeline: datasheet PDF -> parsed pins -> symbol -> project -> ERC."""

    def test_parse_esp32_c6_datasheet(self, tmp_path):
        """Parse the ESP32-C6-WROOM-1 datasheet via Claude CLI."""
        result = parse_datasheet("data/datasheets/esp32-c6-wroom-1.pdf")

        assert result.chip_name, "chip_name should not be empty"
        assert "ESP32" in result.chip_name.upper() or "C6" in result.chip_name.upper()
        assert result.manufacturer, "manufacturer should not be empty"
        assert len(result.pins) >= 20, (
            f"Expected at least 20 pins, got {len(result.pins)}"
        )

        # Should have power pins
        groups = {p.group for p in result.pins}
        assert "Power" in groups, f"Missing Power group in {groups}"

        # Power requirements should be populated
        assert result.power_requirements.supply_voltage_typ > 0

    def test_generate_symbol_from_datasheet(self, tmp_path):
        """Generate a KiCad symbol from a parsed datasheet."""
        result = parse_datasheet("data/datasheets/esp32-c6-wroom-1.pdf")
        chip_def = result.to_chipdef()
        sym_path = tmp_path / f"{result.chip_name}.kicad_sym"

        generate_symbol_file(chip_def, sym_path)

        assert sym_path.is_file()
        content = sym_path.read_text()
        assert "(kicad_symbol_lib" in content
        assert "(pin " in content

        # Verify pin count matches
        pin_count = content.count("(pin ")
        assert pin_count == len(result.pins), (
            f"Symbol has {pin_count} pins but datasheet parsed {len(result.pins)}"
        )

    def test_full_pipeline_datasheet_to_project(self, tmp_path):
        """Full chain: datasheet PDF -> symbol -> project -> kicad-cli ERC."""
        # Step 1: Parse datasheet
        parsed = parse_datasheet("data/datasheets/esp32-c6-wroom-1.pdf")
        assert len(parsed.pins) >= 20

        # Step 2: Generate symbol
        chip_def = parsed.to_chipdef()
        sym_path = tmp_path / f"{parsed.chip_name}.kicad_sym"
        generate_symbol_file(chip_def, sym_path)
        assert sym_path.stat().st_size > 100

        # Step 3: Compose a project
        spec = DesignSpec(
            name="ESP32C6_Test",
            mcu_family="ESP32-C6",
            mcu_chip=parsed.chip_name,
            peripherals=[
                PeripheralSpec(name="LED", chip="LED_Generic", interface="GPIO"),
            ],
            power=PowerSpec(
                input_source="USB-C", voltage="3.3V", regulator="LDO"
            ),
        )
        project = compose_design(spec)

        # Should have root + sub-sheets + project files
        assert len(project.files) >= 5
        assert "esp32c6_test.kicad_sch" in project.files
        assert len(project.bom) >= 1

        # Step 4: Write project files
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        for filename, content in project.files.items():
            (project_dir / filename).write_text(content)
        shutil.copy2(sym_path, project_dir / sym_path.name)

        # Step 5: Run kicad-cli ERC
        root_sch = project_dir / "esp32c6_test.kicad_sch"
        erc_result = run_erc(root_sch)

        # ERC should run successfully (the tool itself should not crash)
        assert erc_result["success"] is True, (
            f"kicad-cli ERC failed to run: {erc_result['stderr']}"
        )

        # Verify schematic files were written
        sch_files = list(project_dir.glob("*.kicad_sch"))
        assert len(sch_files) >= 3, (
            f"Expected at least 3 .kicad_sch files, got {len(sch_files)}"
        )
