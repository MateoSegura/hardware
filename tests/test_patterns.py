"""Tests for decoupling pattern extractor and sheet pattern extractor.

Uses real parsed data from data/parsed/ — no mocks.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.pipeline.decoupling import (
    _extract_footprint_short,
    _extract_ic_family,
    _is_capacitor,
    _normalize_cap_value,
    extract_decoupling_patterns,
    run as decoupling_run,
)
from src.pipeline.sheet_patterns import (
    _classify_sheet_domain,
    _compute_hierarchy_depth,
    extract_sheet_patterns,
    run as sheet_run,
)

PARSED_DIR = Path(__file__).parent.parent / "data" / "parsed"


# ── Decoupling: unit tests ─────────────────────────────────────────


class TestIsCapacitor:
    def test_ref_C1(self):
        assert _is_capacitor({"ref": "C1", "lib_id": ""}) is True

    def test_ref_C100(self):
        assert _is_capacitor({"ref": "C100", "lib_id": ""}) is True

    def test_ref_R1_not_cap(self):
        assert _is_capacitor({"ref": "R1", "lib_id": ""}) is False

    def test_lib_id_Device_C(self):
        assert _is_capacitor({"ref": "X1", "lib_id": "Device:C"}) is True

    def test_lib_id_C_Small(self):
        assert _is_capacitor({"ref": "X1", "lib_id": "Device:C_Small"}) is True

    def test_lib_id_C_Polarized(self):
        assert _is_capacitor({"ref": "X1", "lib_id": "Device:C_Polarized"}) is True

    def test_lib_id_passive_C(self):
        assert _is_capacitor({"ref": "X1", "lib_id": "passive:C"}) is True

    def test_lib_id_resistor_not_cap(self):
        assert _is_capacitor({"ref": "X1", "lib_id": "Device:R"}) is False

    def test_empty(self):
        assert _is_capacitor({"ref": "", "lib_id": ""}) is False


class TestExtractICFamily:
    def test_stm32f7(self):
        assert _extract_ic_family("MCU_ST_STM32F7:STM32F722RETx", "") == "STM32F7"

    def test_stm32f4(self):
        assert _extract_ic_family("MCU_ST_STM32F4:STM32F411CEU6", "") == "STM32F4"

    def test_esp32(self):
        assert _extract_ic_family("RF_Module:ESP32-WROOM-32", "") == "ESP32"

    def test_esp32_s3(self):
        assert _extract_ic_family("espressif:ESP32-S3", "") == "ESP32-S3"

    def test_rp2040(self):
        assert _extract_ic_family("MCU_RaspberryPi:RP2040", "") == "RP2040"

    def test_atmega(self):
        assert _extract_ic_family("MCU_Microchip_ATmega:ATmega328P-AU", "") == "ATmega"

    def test_nrf52(self):
        assert _extract_ic_family("Nordic:nRF52840", "") == "nRF52"

    def test_lpc(self):
        assert _extract_ic_family("MCU_NXP_LPC:LPC1768", "") == "LPC1768"

    def test_fallback_value(self):
        result = _extract_ic_family("", "ATtiny85")
        assert "ATtiny" in result

    def test_fallback_unknown(self):
        result = _extract_ic_family("", "")
        assert result  # Should return something, not empty


class TestNormalizeCapValue:
    def test_100n(self):
        assert _normalize_cap_value("100n") == "100nF"

    def test_100nF(self):
        assert _normalize_cap_value("100nF") == "100nF"

    def test_0_1u_to_100n(self):
        assert _normalize_cap_value("0.1u") == "100nF"

    def test_4u7(self):
        assert _normalize_cap_value("4u7") == "4.7uF"

    def test_10p(self):
        assert _normalize_cap_value("10p") == "10pF"

    def test_1u(self):
        assert _normalize_cap_value("1u") == "1uF"

    def test_unparseable(self):
        assert _normalize_cap_value("DNP") == "DNP"

    def test_with_F_suffix(self):
        assert _normalize_cap_value("100nF") == "100nF"

    def test_10uF(self):
        assert _normalize_cap_value("10uF") == "10uF"


class TestExtractFootprintShort:
    def test_0402(self):
        assert _extract_footprint_short("Capacitor_SMD:C_0402_1005Metric") == "C_0402"

    def test_0805(self):
        assert _extract_footprint_short("Capacitor_SMD:C_0805_2012Metric") == "C_0805"

    def test_0603(self):
        assert _extract_footprint_short("Capacitor_SMD:C_0603_1608Metric") == "C_0603"

    def test_no_colon(self):
        result = _extract_footprint_short("C_0402_1005Metric")
        assert result == "C_0402"

    def test_non_cap_footprint(self):
        result = _extract_footprint_short("Resistor_SMD:R_0402")
        assert result  # Should return something


# ── Decoupling: integration tests on real data ─────────────────────


class TestDecouplingExtraction:
    """Test decoupling extraction on real parsed data."""

    @pytest.fixture(scope="class")
    def patterns(self):
        """Extract patterns once for all tests in this class."""
        if not PARSED_DIR.exists():
            pytest.skip("data/parsed/ not found")
        return extract_decoupling_patterns(PARSED_DIR)

    def test_has_by_ic_family(self, patterns):
        assert "by_ic_family" in patterns
        assert isinstance(patterns["by_ic_family"], dict)

    def test_has_global_stats(self, patterns):
        assert "global_stats" in patterns
        stats = patterns["global_stats"]
        assert "total_ics_analyzed" in stats
        assert "total_caps_found" in stats
        assert "families_found" in stats
        assert "avg_caps_per_ic" in stats

    def test_found_some_families(self, patterns):
        assert patterns["global_stats"]["families_found"] > 0

    def test_found_some_caps(self, patterns):
        assert patterns["global_stats"]["total_caps_found"] > 0

    def test_found_some_ics(self, patterns):
        assert patterns["global_stats"]["total_ics_analyzed"] > 0

    def test_family_has_caps_list(self, patterns):
        for family, data in patterns["by_ic_family"].items():
            assert "caps" in data
            assert isinstance(data["caps"], list)
            assert "sample_count" in data
            assert "power_nets" in data
            break  # Just check the first

    def test_cap_entries_have_value_and_footprint(self, patterns):
        for family, data in patterns["by_ic_family"].items():
            for cap in data["caps"]:
                assert "value" in cap
                assert "footprint" in cap
                assert "count" in cap
                break
            break

    def test_run_writes_json(self, patterns):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "decoupling_rules.json"
            result = decoupling_run(PARSED_DIR, out)
            assert out.exists()
            loaded = json.loads(out.read_text())
            assert "by_ic_family" in loaded
            assert "global_stats" in loaded


# ── Sheet patterns: unit tests ─────────────────────────────────────


class TestClassifySheetDomain:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Power Supplies", "power"),
            ("power_supply", "power"),
            ("PSU", "power"),
            ("LDO_Regulators", "power"),
            ("Processor", "mcu"),
            ("MCU", "mcu"),
            ("STM32_Controller", "mcu"),
            ("USB_Interface", "communication"),
            ("Ethernet", "communication"),
            ("UART_Debug", "communication"),
            ("Stepper Driver", "motor"),
            ("Motor_Control", "motor"),
            ("IMU_Sensor", "sensor"),
            ("Temperature_ADC", "sensor"),
            ("OLED_Display", "display"),
            ("LED_Driver", "display"),
            ("Headers", "connector"),
            ("GPIO_Expansion", "connector"),
            ("JTAG_Debug", "connector"),
            ("SD_Card", "memory"),
            ("EEPROM", "memory"),
            ("Audio_Codec", "audio"),
            ("Data_Bus_Transceivers", "data_bus"),
            ("RandomSheetName", "other"),
        ],
    )
    def test_domain_classification(self, name, expected):
        assert _classify_sheet_domain(name) == expected


class TestComputeHierarchyDepth:
    def test_empty(self):
        assert _compute_hierarchy_depth({}) == 0

    def test_single_sheet(self):
        tree = {
            "/root.kicad_sch": {
                "sheet_name": "root",
                "parent_path": None,
            }
        }
        assert _compute_hierarchy_depth(tree) == 0

    def test_depth_1(self):
        tree = {
            "/root.kicad_sch": {
                "sheet_name": "root",
                "parent_path": None,
            },
            "/power.kicad_sch": {
                "sheet_name": "Power",
                "parent_path": "/root.kicad_sch",
            },
            "/mcu.kicad_sch": {
                "sheet_name": "MCU",
                "parent_path": "/root.kicad_sch",
            },
        }
        assert _compute_hierarchy_depth(tree) == 1

    def test_depth_2(self):
        tree = {
            "/root.kicad_sch": {
                "sheet_name": "root",
                "parent_path": None,
            },
            "/power.kicad_sch": {
                "sheet_name": "Power",
                "parent_path": "/root.kicad_sch",
            },
            "/regulator.kicad_sch": {
                "sheet_name": "Regulator",
                "parent_path": "/power.kicad_sch",
            },
        }
        assert _compute_hierarchy_depth(tree) == 2


# ── Sheet patterns: integration tests on real data ─────────────────


class TestSheetPatternExtraction:
    """Test sheet pattern extraction on real parsed data."""

    @pytest.fixture(scope="class")
    def patterns(self):
        if not PARSED_DIR.exists():
            pytest.skip("data/parsed/ not found")
        return extract_sheet_patterns(PARSED_DIR)

    def test_has_top_sheet_names(self, patterns):
        assert "top_sheet_names" in patterns
        assert isinstance(patterns["top_sheet_names"], list)

    def test_has_domain_distribution(self, patterns):
        assert "domain_distribution" in patterns
        assert isinstance(patterns["domain_distribution"], dict)

    def test_has_global_stats(self, patterns):
        assert "global_stats" in patterns
        stats = patterns["global_stats"]
        assert "total_projects_analyzed" in stats
        assert "hierarchical_projects" in stats
        assert "flat_projects" in stats
        assert "avg_sheets_per_project" in stats
        assert "avg_components_per_sheet" in stats
        assert "avg_hierarchy_depth" in stats
        assert "max_hierarchy_depth" in stats

    def test_analyzed_many_projects(self, patterns):
        stats = patterns["global_stats"]
        # We have 110+ parsed projects with 779 design units
        assert stats["total_projects_analyzed"] > 100

    def test_found_hierarchical_projects(self, patterns):
        stats = patterns["global_stats"]
        assert stats["hierarchical_projects"] > 0

    def test_found_flat_projects(self, patterns):
        stats = patterns["global_stats"]
        assert stats["flat_projects"] > 0

    def test_avg_components_reasonable(self, patterns):
        stats = patterns["global_stats"]
        # Average components per sheet should be positive
        assert stats["avg_components_per_sheet"] > 0

    def test_domain_has_sheet_count(self, patterns):
        for domain, data in patterns["domain_distribution"].items():
            assert "sheet_count" in data
            assert "avg_components" in data
            break

    def test_power_domain_exists(self, patterns):
        # Most projects have a power sheet
        assert "power" in patterns["domain_distribution"]

    def test_run_writes_json(self, patterns):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "sheet_organization.json"
            result = sheet_run(PARSED_DIR, out)
            assert out.exists()
            loaded = json.loads(out.read_text())
            assert "top_sheet_names" in loaded
            assert "global_stats" in loaded
