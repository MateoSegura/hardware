"""Tests for pattern merging and normalization."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.pipeline.pattern_merge import (
    merge_similar_patterns,
    normalize_ic_family,
    normalize_net_name,
    reindex_patterns,
)


# ── normalize_net_name tests ──────────────────────────────────────────


class TestNormalizeNetName:
    """Test net name normalization across naming conventions."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            # SPI numbered bus prefixes
            ("SPI1_MOSI", "MOSI"),
            ("SPI2_MISO", "MISO"),
            ("SPI1_SCK", "SCK"),
            # SPI generic prefixes
            ("SPI_MOSI", "MOSI"),
            ("HSPI_MOSI", "MOSI"),
            ("VSPI_MISO", "MISO"),
            # SPI aliases
            ("SCLK", "SCK"),
            ("SDI", "MOSI"),
            ("SDO", "MISO"),
            # Bare signal names (no change)
            ("MOSI", "MOSI"),
            ("MISO", "MISO"),
            ("SCK", "SCK"),
            ("CS", "CS"),
            # CS aliases
            ("NCS", "CS"),
            ("CSN", "CS"),
            ("SS", "CS"),
            ("NSS", "CS"),
        ],
    )
    def test_spi_signals(self, raw: str, expected: str) -> None:
        assert normalize_net_name(raw) == expected

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("I2C_SDA", "SDA"),
            ("I2C_SCL", "SCL"),
            ("I2C1_SDA", "SDA"),
            ("I2C2_SCL", "SCL"),
            ("SDA", "SDA"),
            ("SCL", "SCL"),
        ],
    )
    def test_i2c_signals(self, raw: str, expected: str) -> None:
        assert normalize_net_name(raw) == expected

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("UART_TX", "TX"),
            ("UART1_RX", "RX"),
            ("USART1_TX", "TX"),
            ("TXD", "TX"),
            ("RXD", "RX"),
            ("TX", "TX"),
            ("RX", "RX"),
        ],
    )
    def test_uart_signals(self, raw: str, expected: str) -> None:
        assert normalize_net_name(raw) == expected

    @pytest.mark.parametrize(
        "raw, expected",
        [
            # Peripheral-specific prefixes
            ("GYRO_SCK", "SCK"),
            ("BARO_I2C_SDA", "SDA"),
            ("FLASH_CS", "CS"),
            ("ADC_MISO", "MISO"),
            ("ETH_INT", "INT"),
            # Voltage prefixes
            ("3V3_SPI_SCLK", "SCK"),
            ("3V3_SPI_SDO", "MISO"),
            ("3V3_ADC_CS", "CS"),
        ],
    )
    def test_peripheral_prefixes(self, raw: str, expected: str) -> None:
        assert normalize_net_name(raw) == expected

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("/audio/codec.sda", "SDA"),
            ("/audio/codec.scl", "SCL"),
            ("/flash/FLASH_SCK", "SCK"),
            ("/Slots and Peripherals/PICO_SDA", "SDA"),
            ("/CAM.SCL", "SCL"),
        ],
    )
    def test_hierarchical_paths(self, raw: str, expected: str) -> None:
        assert normalize_net_name(raw) == expected

    def test_tilde_markup(self) -> None:
        assert normalize_net_name("/audio/~{reset}") == "RESET"

    def test_case_insensitive(self) -> None:
        assert normalize_net_name("spi1_mosi") == "MOSI"
        assert normalize_net_name("Sclk") == "SCK"

    def test_usb_signal_prefix(self) -> None:
        assert normalize_net_name("USB_D+") == "D+"
        assert normalize_net_name("USB_D-") == "D-"

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("uC_TX", "TX"),
            ("uC_RX", "RX"),
            ("/uart_tx", "TX"),
            ("/uart_rx", "RX"),
        ],
    )
    def test_uart_variants(self, raw: str, expected: str) -> None:
        assert normalize_net_name(raw) == expected


# ── normalize_ic_family tests ─────────────────────────────────────────


class TestNormalizeIcFamily:
    """Test IC family normalization."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("STM32F", "STM32"),
            ("STM32G", "STM32"),
            ("STM32H", "STM32"),
        ],
    )
    def test_stm32_variants(self, raw: str, expected: str) -> None:
        assert normalize_ic_family(raw) == expected

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("ESP32-S3", "ESP32"),
            ("ESP32-C3", "ESP32"),
            ("ESP32-C6", "ESP32"),
            ("ESP32", "ESP32"),
        ],
    )
    def test_esp32_variants(self, raw: str, expected: str) -> None:
        assert normalize_ic_family(raw) == expected

    def test_flash_variants(self) -> None:
        assert normalize_ic_family("W25Q") == "W25x_FLASH"
        assert normalize_ic_family("W25N") == "W25x_FLASH"

    def test_ina_variants(self) -> None:
        assert normalize_ic_family("INA237") == "INAx"
        assert normalize_ic_family("INA260") == "INAx"
        assert normalize_ic_family("INA229") == "INAx"

    def test_imu_variants(self) -> None:
        assert normalize_ic_family("ICP-42688-P") == "ICM_IMU"
        assert normalize_ic_family("IC_ICM-42670-P") == "ICM_IMU"

    def test_usb_protection(self) -> None:
        assert normalize_ic_family("USBLC6") == "USB_PROT"
        assert normalize_ic_family("TPD4E") == "USB_PROT"
        assert normalize_ic_family("IP4220CZ") == "USB_PROT"

    def test_unknown_family_passthrough(self) -> None:
        assert normalize_ic_family("UNKNOWN_CHIP") == "UNKNOWN_CHIP"
        assert normalize_ic_family("MyCustomIC") == "MyCustomIC"


# ── merge_similar_patterns tests ──────────────────────────────────────


def _make_pattern(
    ic_a: str,
    ic_b: str,
    iface: str,
    nets: list[str],
    project: str,
    sample_count: int = 1,
) -> dict:
    """Helper to create a pattern dict for testing."""
    return {
        "ic_a_family": ic_a,
        "ic_b_family": ic_b,
        "interface_type": iface,
        "canonical_connections": [
            {"ic_a_pad": str(i), "ic_b_pad": str(i), "net_name": n}
            for i, n in enumerate(nets)
        ],
        "seen_in_projects": [project],
        "sample_count": sample_count,
        "confidence": "low",
    }


class TestMergeSimilarPatterns:
    """Test pattern merging logic."""

    def test_merge_stm32_spi_flash_variants(self) -> None:
        """STM32F+W25N and STM32G+W25Q with SPI should merge."""
        patterns = [
            _make_pattern(
                "STM32F",
                "W25N",
                "SPI",
                ["cs", "miso", "mosi", "sck"],
                "project_a",
            ),
            _make_pattern(
                "STM32G",
                "W25Q",
                "SPI",
                ["FLASH_CS", "SPI1_MISO", "SPI1_MOSI", "SPI1_SCK"],
                "project_b",
            ),
        ]
        merged = merge_similar_patterns(patterns)
        assert len(merged) == 1
        assert merged[0]["ic_a_family"] == "STM32"
        assert merged[0]["ic_b_family"] == "W25x_FLASH"
        assert merged[0]["sample_count"] == 2
        assert merged[0]["confidence"] == "medium"
        assert set(merged[0]["seen_in_projects"]) == {"project_a", "project_b"}

    def test_merge_same_family_different_nets(self) -> None:
        """Same IC families with different SPI net names should merge."""
        patterns = [
            _make_pattern(
                "STM32F",
                "W25Q",
                "SPI",
                ["SPI1_SCK", "SPI1_MOSI", "SPI1_MISO", "SPI1_CS"],
                "proj_1",
            ),
            _make_pattern(
                "STM32H",
                "W25N",
                "SPI",
                ["FLASH_SCK", "FLASH_MOSI", "FLASH_MISO", "FLASH_CS"],
                "proj_2",
            ),
        ]
        merged = merge_similar_patterns(patterns)
        assert len(merged) == 1
        assert merged[0]["confidence"] == "medium"

    def test_no_merge_different_interfaces(self) -> None:
        """Same families but different interfaces should not merge."""
        patterns = [
            _make_pattern("ESP32-S3", "W25Q", "SPI", ["SCK", "MOSI"], "proj_1"),
            _make_pattern("ESP32-S3", "W25Q", "GPIO", ["RESET"], "proj_2"),
        ]
        merged = merge_similar_patterns(patterns)
        assert len(merged) == 2

    def test_no_merge_different_families(self) -> None:
        """Different IC families should not merge."""
        patterns = [
            _make_pattern("STM32F", "W25Q", "SPI", ["SCK", "MOSI"], "proj_1"),
            _make_pattern("ESP32-S3", "W25Q", "SPI", ["SCK", "MOSI"], "proj_2"),
        ]
        merged = merge_similar_patterns(patterns)
        assert len(merged) == 2

    def test_confidence_high_three_projects(self) -> None:
        """Three distinct projects should yield high confidence."""
        patterns = [
            _make_pattern("STM32F", "W25Q", "SPI", ["SCK", "MOSI", "MISO"], f"proj_{i}")
            for i in range(3)
        ]
        merged = merge_similar_patterns(patterns)
        assert len(merged) == 1
        assert merged[0]["confidence"] == "high"
        assert merged[0]["sample_count"] == 3

    def test_sample_count_summed(self) -> None:
        """Sample counts from merged patterns should be summed."""
        patterns = [
            _make_pattern(
                "STM32F", "W25Q", "SPI", ["SCK", "MOSI"], "proj_1", sample_count=3
            ),
            _make_pattern(
                "STM32G", "W25N", "SPI", ["SCLK", "SDI"], "proj_2", sample_count=2
            ),
        ]
        merged = merge_similar_patterns(patterns)
        assert len(merged) == 1
        assert merged[0]["sample_count"] == 5

    def test_preserves_ic_variants(self) -> None:
        """Merged patterns should list original IC family names."""
        patterns = [
            _make_pattern("STM32F", "W25Q", "SPI", ["SCK", "MOSI"], "proj_1"),
            _make_pattern("STM32G", "W25N", "SPI", ["SCLK", "SDI"], "proj_2"),
        ]
        merged = merge_similar_patterns(patterns)
        assert len(merged) == 1
        assert "ic_a_variants" in merged[0]
        assert set(merged[0]["ic_a_variants"]) == {"STM32F", "STM32G"}
        assert "ic_b_variants" in merged[0]
        assert set(merged[0]["ic_b_variants"]) == {"W25Q", "W25N"}

    def test_canonical_connections_from_best(self) -> None:
        """Canonical connections should come from pattern with most connections."""
        patterns = [
            _make_pattern(
                "STM32F",
                "W25Q",
                "SPI",
                ["SCK", "MOSI", "MISO", "CS", "INT"],
                "proj_1",
            ),
            _make_pattern(
                "STM32G",
                "W25N",
                "SPI",
                ["SCLK", "SDI", "SDO", "NSS"],
                "proj_2",
            ),
        ]
        merged = merge_similar_patterns(patterns)
        assert len(merged) == 1
        # Should use the pattern with 5 connections (proj_1), not 4
        assert len(merged[0]["canonical_connections"]) == 5

    def test_sorted_by_confidence_then_count(self) -> None:
        """Output should be sorted: high confidence first, then by sample_count."""
        patterns = [
            _make_pattern("A", "B", "GPIO", ["X"], "p1"),
            _make_pattern("C", "D", "GPIO", ["Y"], "p2"),
        ]
        # Make a "high confidence" pattern by having 3 projects
        for i in range(3):
            patterns.append(
                _make_pattern("STM32F", "W25Q", "SPI", ["SCK", "MOSI"], f"hp_{i}")
            )
        merged = merge_similar_patterns(patterns)
        # The high-confidence pattern should be first
        confidences = [p["confidence"] for p in merged]
        assert confidences[0] == "high"

    def test_gpio_different_connection_count_no_merge(self) -> None:
        """GPIO patterns with different connection counts should not merge."""
        patterns = [
            _make_pattern("ESP32", "LDO_A", "GPIO", ["EN"], "proj_1"),
            _make_pattern("ESP32", "LDO_A", "GPIO", ["EN", "PG"], "proj_2"),
        ]
        merged = merge_similar_patterns(patterns)
        assert len(merged) == 2

    def test_i2c_merge_ignores_auxiliary_signals(self) -> None:
        """I2C patterns with different auxiliary signals should merge."""
        patterns = [
            _make_pattern(
                "ESP32-S3",
                "INA237",
                "I2C",
                ["I2C_SDA", "I2C_SCL", "ALERT_INT"],
                "proj_1",
            ),
            _make_pattern(
                "ESP32-C3",
                "INA260",
                "I2C",
                ["SDA", "SCL"],
                "proj_2",
            ),
        ]
        merged = merge_similar_patterns(patterns)
        assert len(merged) == 1
        assert merged[0]["confidence"] == "medium"


# ── reindex_patterns tests ────────────────────────────────────────────


class TestReindexPatterns:
    """Test the full reindex pipeline."""

    def test_reindex_reduces_count(self) -> None:
        """Reindexing should produce fewer patterns with higher confidence."""
        data = {
            "pattern_count": 4,
            "patterns": [
                _make_pattern(
                    "STM32F", "W25Q", "SPI", ["SCK", "MOSI", "MISO", "CS"], "proj_1"
                ),
                _make_pattern(
                    "STM32G", "W25N", "SPI", ["SCLK", "SDI", "SDO", "NSS"], "proj_2"
                ),
                _make_pattern(
                    "STM32H",
                    "W25Q",
                    "SPI",
                    ["SPI1_SCK", "SPI1_MOSI", "SPI1_MISO", "FLASH_CS"],
                    "proj_3",
                ),
                _make_pattern("ESP32", "AS5600", "I2C", ["SDA", "SCL"], "proj_4"),
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.json"
            output_path = Path(tmp) / "output.json"
            input_path.write_text(json.dumps(data))

            summary = reindex_patterns(input_path, output_path)

            assert summary["before_count"] == 4
            assert summary["after_count"] == 2  # 3 SPI merge + 1 I2C
            assert summary["reduction"] == 2
            assert summary["after_confidence"]["high"] == 1  # 3 projects for SPI
            assert summary["after_confidence"]["low"] == 1  # 1 project for I2C

            # Verify output file
            result = json.loads(output_path.read_text())
            assert result["pattern_count"] == 2
            assert result["merge_metadata"]["original_count"] == 4

    def test_reindex_preserves_unmerged(self) -> None:
        """Patterns with no merge candidates should pass through unchanged."""
        data = {
            "pattern_count": 2,
            "patterns": [
                _make_pattern("ESP32", "BME280", "I2C", ["SDA", "SCL"], "proj_1"),
                _make_pattern(
                    "RP2040", "W5500", "SPI", ["SCK", "MOSI", "MISO"], "proj_2"
                ),
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.json"
            output_path = Path(tmp) / "output.json"
            input_path.write_text(json.dumps(data))

            summary = reindex_patterns(input_path, output_path)

            assert summary["before_count"] == 2
            assert summary["after_count"] == 2
            assert summary["reduction"] == 0

    def test_merged_output_has_fewer_entries_higher_confidence(self) -> None:
        """Core requirement: merged output has fewer entries but higher confidence."""
        data = {
            "pattern_count": 6,
            "patterns": [
                _make_pattern(
                    "STM32F", "W25Q", "SPI", ["SCK", "MOSI", "MISO"], f"proj_{i}"
                )
                for i in range(3)
            ]
            + [
                _make_pattern(
                    "STM32G", "W25N", "SPI", ["SCLK", "SDI", "SDO"], f"proj_{i + 3}"
                )
                for i in range(3)
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.json"
            output_path = Path(tmp) / "output.json"
            input_path.write_text(json.dumps(data))

            summary = reindex_patterns(input_path, output_path)

            assert summary["after_count"] < summary["before_count"]
            assert summary["after_confidence"].get("high", 0) > summary[
                "before_confidence"
            ].get("high", 0)
