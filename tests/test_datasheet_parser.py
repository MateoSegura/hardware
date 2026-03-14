"""Tests for datasheet PDF parser."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.pipeline.datasheet_parser import (
    ParsedDatasheet,
    _auto_group_pin,
    _extract_via_claude,
    parse_datasheet,
)
from src.pipeline.symbol_gen import ChipDef, PinDef

# Path to the already-downloaded ESP32-S3-WROOM-1 datasheet
ESP32_PDF = Path(__file__).resolve().parent.parent / "data" / "datasheets" / "esp32-s3-wroom-1.pdf"


@pytest.fixture
def parsed() -> ParsedDatasheet:
    """Parse the ESP32-S3-WROOM-1 datasheet using the hardcoded fallback.

    We mock _extract_via_claude to return None so the fallback is used
    deterministically (avoids a 120s Claude CLI timeout in CI).
    """
    assert ESP32_PDF.exists(), f"Datasheet not found: {ESP32_PDF}"
    with patch("src.pipeline.datasheet_parser._extract_via_claude", return_value=None):
        return parse_datasheet(ESP32_PDF)


class TestParseEsp32s3Datasheet:
    """Integration tests for parse_datasheet() with the ESP32-S3-WROOM-1."""

    def test_chip_name(self, parsed: ParsedDatasheet):
        """Chip name is correctly identified."""
        assert "ESP32-S3" in parsed.chip_name

    def test_manufacturer(self, parsed: ParsedDatasheet):
        """Manufacturer is Espressif."""
        assert parsed.manufacturer.lower() == "espressif"

    def test_pin_count_41(self, parsed: ParsedDatasheet):
        """ESP32-S3-WROOM-1 has 41 pins (40 + exposed pad)."""
        assert parsed.pin_count == 41
        assert len(parsed.pins) == 41

    def test_package(self, parsed: ParsedDatasheet):
        """Package type includes pin count."""
        assert "41" in parsed.package


class TestPinGrouping:
    """Tests for the _auto_group_pin heuristic."""

    def test_gnd_is_power(self):
        assert _auto_group_pin("GND", []) == "Power"

    def test_3v3_is_power(self):
        assert _auto_group_pin("3V3", []) == "Power"

    def test_epad_is_power(self):
        assert _auto_group_pin("EPAD", []) == "Power"

    def test_en_is_control(self):
        assert _auto_group_pin("EN", ["CHIP_EN"]) == "Control"

    def test_txd0_is_uart(self):
        assert _auto_group_pin("TXD0", ["U0TXD"]) == "UART"

    def test_rxd0_is_uart(self):
        assert _auto_group_pin("RXD0", ["U0RXD"]) == "UART"

    def test_io4_with_adc_and_touch(self):
        # ADC matches before Touch in the heuristic chain
        assert _auto_group_pin("IO4", ["ADC1_CH3", "TOUCH4"]) == "ADC"

    def test_usb_dm_is_usb(self):
        assert _auto_group_pin("USB_D-", []) == "USB"

    def test_spi_function_detected(self):
        assert _auto_group_pin("IO10", ["FSPICS0", "ADC1_CH9"]) == "SPI"

    def test_jtag_mtck_detected(self):
        assert _auto_group_pin("IO39", ["MTCK"]) == "JTAG"

    def test_plain_gpio_fallback(self):
        assert _auto_group_pin("IO0", []) == "GPIO"


class TestPowerRequirements:
    """Tests for power requirement extraction."""

    def test_supply_voltage_min(self, parsed: ParsedDatasheet):
        assert parsed.power_requirements.supply_voltage_min == pytest.approx(3.0)

    def test_supply_voltage_typ(self, parsed: ParsedDatasheet):
        assert parsed.power_requirements.supply_voltage_typ == pytest.approx(3.3)

    def test_supply_voltage_max(self, parsed: ParsedDatasheet):
        assert parsed.power_requirements.supply_voltage_max == pytest.approx(3.6)

    def test_power_pins_listed(self, parsed: ParsedDatasheet):
        power_pins = parsed.power_requirements.power_pins
        assert "3V3" in power_pins
        assert "GND" in power_pins

    def test_decoupling_caps_present(self, parsed: ParsedDatasheet):
        caps = parsed.power_requirements.decoupling_caps
        assert len(caps) >= 2
        values = [c["value"] for c in caps]
        assert any("22" in v for v in values), "Expected bulk cap (22uF)"
        assert any("0.1" in v for v in values), "Expected bypass cap (0.1uF)"


class TestPinTypes:
    """Tests for pin electrical type mapping."""

    def test_gnd_is_power_in(self, parsed: ParsedDatasheet):
        gnd_pins = [p for p in parsed.pins if p.name == "GND"]
        assert len(gnd_pins) >= 1
        for p in gnd_pins:
            assert p.electrical_type == "power_in"

    def test_io4_is_bidirectional(self, parsed: ParsedDatasheet):
        io4 = [p for p in parsed.pins if p.name == "IO4"]
        assert len(io4) == 1
        assert io4[0].electrical_type == "bidirectional"

    def test_en_is_input(self, parsed: ParsedDatasheet):
        en = [p for p in parsed.pins if p.name == "EN"]
        assert len(en) == 1
        assert en[0].electrical_type == "input"


class TestOutputIsChipDef:
    """Tests that ParsedDatasheet integrates with symbol_gen."""

    def test_to_chipdef_returns_chipdef(self, parsed: ParsedDatasheet):
        chipdef = parsed.to_chipdef()
        assert isinstance(chipdef, ChipDef)

    def test_chipdef_has_all_pins(self, parsed: ParsedDatasheet):
        chipdef = parsed.to_chipdef()
        assert len(chipdef.pins) == 41

    def test_chipdef_pins_are_pindef(self, parsed: ParsedDatasheet):
        chipdef = parsed.to_chipdef()
        for pin in chipdef.pins:
            assert isinstance(pin, PinDef)
            assert pin.number
            assert pin.name
            assert pin.electrical_type
            assert pin.group


class TestReferenceCircuit:
    """Tests for reference circuit extraction."""

    def test_components_present(self, parsed: ParsedDatasheet):
        comps = parsed.reference_circuit.components
        assert len(comps) >= 2

    def test_en_pullup_resistor(self, parsed: ParsedDatasheet):
        comps = parsed.reference_circuit.components
        pullups = [c for c in comps if "pullup" in c.get("purpose", "").lower()
                   or "pull" in c.get("purpose", "").lower()]
        assert len(pullups) >= 1, "Expected EN pullup resistor in reference circuit"

    def test_decoupling_in_reference(self, parsed: ParsedDatasheet):
        comps = parsed.reference_circuit.components
        decoupling = [c for c in comps if "decoupl" in c.get("purpose", "").lower()
                      or "bypass" in c.get("purpose", "").lower()]
        assert len(decoupling) >= 1, "Expected decoupling caps in reference circuit"

    def test_notes_present(self, parsed: ParsedDatasheet):
        assert len(parsed.reference_circuit.notes) >= 1
