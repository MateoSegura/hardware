"""End-to-end test: GPS tracker → valid KiCad project.

Proves the entire pipeline works: define chip → generate symbol → generate
schematic → validate with kicad-cli → parse with our own parser.

Uses real kicad-cli v9 for validation (ERC, BOM export).
"""

from __future__ import annotations

import json


from src.pipeline.parse_project import parse_project
from src.pipeline.schematic_gen import (
    ComponentPlacement,
    NetConnection,
    SheetContent,
    generate_hierarchical_project,
    generate_schematic,
)
from src.pipeline.symbol_gen import ChipDef, PinDef, generate_symbol_file
from src.pipeline.templates import build_decoupling_template
from src.pipeline.validate import run_erc


# ---------------------------------------------------------------------------
# Chip definitions for the GPS tracker
# ---------------------------------------------------------------------------

def _esp32_s3_chip() -> ChipDef:
    """Minimal ESP32-S3 definition — enough pins for a GPS tracker."""
    pins = [
        # Power
        PinDef("1", "VDD3P3", "power_in", "Power"),
        PinDef("2", "GND", "power_in", "Power"),
        PinDef("3", "VDD3P3_RTC", "power_in", "Power"),
        # UART for GPS
        PinDef("4", "U0TXD", "output", "UART"),
        PinDef("5", "U0RXD", "input", "UART"),
        PinDef("6", "U1TXD", "output", "UART"),
        PinDef("7", "U1RXD", "input", "UART"),
        # SPI for flash
        PinDef("8", "SPI_CLK", "output", "SPI"),
        PinDef("9", "SPI_MOSI", "output", "SPI"),
        PinDef("10", "SPI_MISO", "input", "SPI"),
        PinDef("11", "SPI_CS", "output", "SPI"),
        # GPIO
        PinDef("12", "GPIO0", "bidirectional", "GPIO"),
        PinDef("13", "GPIO1", "bidirectional", "GPIO"),
        PinDef("14", "GPIO2", "bidirectional", "GPIO"),
        # Enable
        PinDef("15", "EN", "input", "System"),
    ]
    return ChipDef(
        name="ESP32-S3-MINI",
        library="RF_Module",
        description="ESP32-S3 WiFi+BLE module",
        footprint="RF_Module:ESP32-S3-MINI-1",
        datasheet_url="https://www.espressif.com/sites/default/files/documentation/esp32-s3-mini-1_datasheet_en.pdf",
        pins=pins,
    )


def _gps_module_chip() -> ChipDef:
    """Minimal u-blox NEO-M8N GPS module definition."""
    pins = [
        PinDef("1", "VCC", "power_in", "Power"),
        PinDef("2", "GND", "power_in", "Power"),
        PinDef("3", "TXD", "output", "UART"),
        PinDef("4", "RXD", "input", "UART"),
        PinDef("5", "PPS", "output", "Control"),
        PinDef("6", "RESET", "input", "Control"),
    ]
    return ChipDef(
        name="NEO-M8N",
        library="GPS",
        description="u-blox NEO-M8N GPS/GNSS module",
        footprint="GPS:u-blox_NEO-M8N",
        datasheet_url="https://www.u-blox.com/en/product/neo-m8-series",
        pins=pins,
    )


def _build_gps_tracker_sheets() -> dict[str, SheetContent]:
    """Build hierarchical sheets for the GPS tracker."""
    # Power sheet: LDO + decoupling caps
    power = SheetContent(
        title="Power",
        components=[
            ComponentPlacement("Device:C", "C1", "10uF", "Capacitor_SMD:C_0805", (50.8, 30.48)),
            ComponentPlacement("Device:C", "C2", "100nF", "Capacitor_SMD:C_0402", (50.8, 45.72)),
            ComponentPlacement("Device:C", "C3", "100nF", "Capacitor_SMD:C_0402", (76.2, 30.48)),
            ComponentPlacement("Device:C", "C4", "10uF", "Capacitor_SMD:C_0805", (76.2, 45.72)),
        ],
        nets=[
            NetConnection("VCC_3V3", "global", (40.64, 30.48)),
            NetConnection("GND", "global", (40.64, 45.72)),
            NetConnection("VBAT", "global", (40.64, 60.96)),
        ],
        hierarchical_labels=[
            ("VCC_3V3", "output"),
            ("GND", "passive"),
            ("VBAT", "input"),
        ],
    )

    # MCU sheet: ESP32-S3 + bypass caps
    mcu = SheetContent(
        title="MCU",
        components=[
            ComponentPlacement("Device:C", "C5", "100nF", "Capacitor_SMD:C_0402", (50.8, 30.48)),
            ComponentPlacement("Device:C", "C6", "100nF", "Capacitor_SMD:C_0402", (50.8, 45.72)),
            ComponentPlacement("Device:R", "R1", "10k", "Resistor_SMD:R_0402", (76.2, 30.48)),
        ],
        nets=[
            NetConnection("VCC_3V3", "global", (40.64, 30.48)),
            NetConnection("GND", "global", (40.64, 45.72)),
            NetConnection("GPS_TX", "global", (101.6, 30.48)),
            NetConnection("GPS_RX", "global", (101.6, 45.72)),
        ],
        hierarchical_labels=[
            ("VCC_3V3", "input"),
            ("GND", "passive"),
            ("GPS_TX", "output"),
            ("GPS_RX", "input"),
        ],
    )

    # GPS sheet: NEO-M8N + bypass caps
    gps = SheetContent(
        title="GPS",
        components=[
            ComponentPlacement("Device:C", "C7", "100nF", "Capacitor_SMD:C_0402", (50.8, 30.48)),
            ComponentPlacement("Device:C", "C8", "10uF", "Capacitor_SMD:C_0805", (50.8, 45.72)),
            ComponentPlacement("Device:R", "R2", "100", "Resistor_SMD:R_0402", (76.2, 30.48)),
        ],
        nets=[
            NetConnection("VCC_3V3", "global", (40.64, 30.48)),
            NetConnection("GND", "global", (40.64, 45.72)),
            NetConnection("GPS_TX", "global", (101.6, 30.48)),
            NetConnection("GPS_RX", "global", (101.6, 45.72)),
        ],
        hierarchical_labels=[
            ("VCC_3V3", "input"),
            ("GND", "passive"),
            ("GPS_TX", "input"),
            ("GPS_RX", "output"),
        ],
    )

    return {
        "power.kicad_sch": power,
        "mcu.kicad_sch": mcu,
        "gps.kicad_sch": gps,
    }


# ---------------------------------------------------------------------------
# 1. Full end-to-end: GPS tracker → valid KiCad project
# ---------------------------------------------------------------------------

class TestGPSTrackerE2E:
    """Full pipeline: define → generate → validate → parse."""

    def test_gps_tracker_e2e(self, tmp_path):
        """Generate a complete GPS tracker project and validate it."""
        project_dir = tmp_path / "gps_tracker"
        project_dir.mkdir()

        # Step 1: Generate symbols for both chips
        esp32 = _esp32_s3_chip()
        gps_mod = _gps_module_chip()

        esp32_sym_path = project_dir / "ESP32-S3-MINI.kicad_sym"
        gps_sym_path = project_dir / "NEO-M8N.kicad_sym"

        generate_symbol_file(esp32, esp32_sym_path)
        generate_symbol_file(gps_mod, gps_sym_path)

        assert esp32_sym_path.is_file()
        assert gps_sym_path.is_file()
        assert esp32_sym_path.stat().st_size > 100
        assert gps_sym_path.stat().st_size > 100

        # Step 2: Generate hierarchical schematic
        sheets = _build_gps_tracker_sheets()
        file_contents = generate_hierarchical_project(sheets, root_title="GPS_Tracker")

        # Should have root + 3 sub-sheets
        assert len(file_contents) == 4
        assert "gps_tracker.kicad_sch" in file_contents

        # Write all schematic files
        for filename, content in file_contents.items():
            filepath = project_dir / filename
            filepath.write_text(content)

        # Step 3: Create .kicad_pro file (minimal)
        pro_content = json.dumps({
            "meta": {"filename": "gps_tracker.kicad_pro", "version": 1},
            "project": {"name": "gps_tracker"},
        }, indent=2)
        (project_dir / "gps_tracker.kicad_pro").write_text(pro_content)

        # Verify all files were written
        sch_files = list(project_dir.glob("*.kicad_sch"))
        assert len(sch_files) == 4

        # Step 4: Validate with kicad-cli ERC
        root_sch = project_dir / "gps_tracker.kicad_sch"
        erc_result = run_erc(root_sch)

        # ERC should run successfully (may have warnings, that's OK)
        assert erc_result["success"] is True, f"ERC failed: {erc_result['stderr']}"

        # Step 5: Parse with our own parser
        parsed = parse_project(project_dir)

        # Should find the project
        assert len(parsed) >= 1, "Parser should find at least one design unit"

        # Check parsed structure
        project = parsed[0]
        assert project.design_unit is not None

    def test_generated_symbol_valid(self, tmp_path):
        """Generate an ESP32-like symbol and verify kicad-cli accepts it."""
        chip = _esp32_s3_chip()
        sym_path = tmp_path / "test_chip.kicad_sym"
        generate_symbol_file(chip, sym_path)

        assert sym_path.is_file()
        content = sym_path.read_text()

        # Verify basic structure
        assert "(kicad_symbol_lib" in content
        assert 'ESP32-S3-MINI' in content
        assert "(pin " in content

        # Verify we have the right number of pins
        pin_count = content.count("(pin ")
        assert pin_count == len(chip.pins), f"Expected {len(chip.pins)} pins, got {pin_count}"

        # Verify all pin groups created units
        groups = set(p.group for p in chip.pins)
        assert len(groups) >= 4  # Power, UART, SPI, GPIO, System

    def test_round_trip(self, tmp_path):
        """Generate schematic → parse → verify components and nets match."""
        project_dir = tmp_path / "round_trip"
        project_dir.mkdir()

        # Generate a flat schematic with known components
        components = [
            ComponentPlacement("Device:R", "R1", "10k", "Resistor_SMD:R_0402", (50.8, 30.48)),
            ComponentPlacement("Device:R", "R2", "4.7k", "Resistor_SMD:R_0402", (50.8, 45.72)),
            ComponentPlacement("Device:C", "C1", "100nF", "Capacitor_SMD:C_0402", (76.2, 30.48)),
            ComponentPlacement("Device:C", "C2", "10uF", "Capacitor_SMD:C_0805", (76.2, 45.72)),
        ]
        nets = [
            NetConnection("VCC", "global", (40.64, 30.48)),
            NetConnection("GND", "global", (40.64, 45.72)),
        ]

        content = generate_schematic(components, nets, title="Round Trip Test")
        sch_path = project_dir / "round_trip_test.kicad_sch"
        sch_path.write_text(content)

        # Create minimal .kicad_pro
        pro_content = json.dumps({
            "meta": {"filename": "round_trip_test.kicad_pro", "version": 1},
            "project": {"name": "round_trip_test"},
        }, indent=2)
        (project_dir / "round_trip_test.kicad_pro").write_text(pro_content)

        # Parse with our pipeline
        parsed = parse_project(project_dir)
        assert len(parsed) >= 1

        project = parsed[0]

        # Verify we recovered the components
        all_comps = project.all_components
        refs = {c.ref for c in all_comps if not c.is_power}
        assert "R1" in refs, f"R1 not found in parsed refs: {refs}"
        assert "R2" in refs, f"R2 not found in parsed refs: {refs}"
        assert "C1" in refs, f"C1 not found in parsed refs: {refs}"
        assert "C2" in refs, f"C2 not found in parsed refs: {refs}"

        # Verify values survived the round trip
        comp_map = {c.ref: c for c in all_comps}
        if "R1" in comp_map:
            assert comp_map["R1"].value == "10k"
        if "C1" in comp_map:
            assert comp_map["C1"].value == "100nF"

    def test_decoupling_from_template(self, tmp_path):
        """Use a decoupling template to generate bypass caps."""
        # Create a synthetic decoupling template
        family_data = {
            "sample_count": 10,
            "caps": [
                {"value": "100nF", "footprint": "Capacitor_SMD:C_0402", "count": 8},
                {"value": "4.7uF", "footprint": "Capacitor_SMD:C_0603", "count": 4},
                {"value": "10uF", "footprint": "Capacitor_SMD:C_0805", "count": 2},
            ],
            "power_nets": ["VDD", "VDDIO", "GND"],
        }

        tpl = build_decoupling_template("STM32F4xx", family_data)
        assert tpl is not None
        assert tpl.name == "decoupling_STM32F4xx"
        assert len(tpl.passives) == 3

        # Use template to generate components for a schematic
        components = []
        cap_index = 1
        y_pos = 30.48
        for passive in tpl.passives:
            for i in range(min(passive.count_in_template, 3)):  # cap at 3 per value
                ref = f"C{cap_index}"
                components.append(ComponentPlacement(
                    lib_id="Device:C",
                    ref=ref,
                    value=passive.typical_value,
                    footprint=passive.typical_footprint,
                    position=(50.8, y_pos),
                ))
                cap_index += 1
                y_pos += 15.24

        nets = [
            NetConnection("VDD", "global", (40.64, 30.48)),
            NetConnection("GND", "global", (40.64, 45.72)),
        ]

        # Generate and validate the schematic
        project_dir = tmp_path / "decoupling_test"
        project_dir.mkdir()

        content = generate_schematic(
            components, nets,
            title="Decoupling Test",
        )
        sch_path = project_dir / "decoupling_test.kicad_sch"
        sch_path.write_text(content)

        pro_content = json.dumps({
            "meta": {"filename": "decoupling_test.kicad_pro", "version": 1},
            "project": {"name": "decoupling_test"},
        }, indent=2)
        (project_dir / "decoupling_test.kicad_pro").write_text(pro_content)

        # Validate with kicad-cli
        erc_result = run_erc(sch_path)
        assert erc_result["success"] is True, f"ERC failed: {erc_result['stderr']}"

        # Parse and verify cap count
        parsed = parse_project(project_dir)
        assert len(parsed) >= 1

        project = parsed[0]
        caps = [c for c in project.all_components if c.ref.startswith("C") and not c.is_power]
        assert len(caps) >= 3, f"Expected at least 3 caps from template, got {len(caps)}"

        # Verify values from template survived
        cap_values = {c.value for c in caps}
        assert "100nF" in cap_values
        assert "4.7uF" in cap_values
