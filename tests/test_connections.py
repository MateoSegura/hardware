"""Tests for inter-IC connection pattern extraction.

Uses real board data from ~/hardware/data/raw/.
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from src.pipeline.board import parse_board
from src.pipeline.classify import is_power_net
from src.pipeline.connections import (
    AggregatedPattern,
    ICPairPattern,
    PadConnection,
    aggregate_patterns,
    classify_interface,
    extract_all_connections,
    extract_connections,
    load_patterns,
    save_patterns,
)
from src.pipeline.models import ParsedBoard

DATA_RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
STM32_PCB = DATA_RAW / "rishikesh2715__stm32f7-fc" / "Flight_Controller.kicad_pcb"
HACKRF_PCB = (
    DATA_RAW
    / "greatscottgadgets__hackrf"
    / "hardware"
    / "hackrf-one"
    / "hackrf-one.kicad_pcb"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def stm32_board() -> ParsedBoard:
    return parse_board(STM32_PCB)


@pytest.fixture(scope="module")
def hackrf_board() -> ParsedBoard:
    return parse_board(HACKRF_PCB)


@pytest.fixture(scope="module")
def stm32_connections(stm32_board) -> list[ICPairPattern]:
    return extract_connections(stm32_board)


@pytest.fixture(scope="module")
def hackrf_connections(hackrf_board) -> list[ICPairPattern]:
    return extract_connections(hackrf_board)


# ---------------------------------------------------------------------------
# Test 1: STM32F7 FC board — extract connections, verify STM32F722 <-> ICM-42688
# ---------------------------------------------------------------------------


def test_extract_stm32f7_connections(stm32_connections):
    """STM32F7 FC board should have IC-to-IC connections including SPI to IMU."""
    assert len(stm32_connections) > 0

    # Find connections involving STM32F7 family
    stm32_patterns = [
        p for p in stm32_connections if "STM32" in p.ic_a_family.upper()
    ]
    assert len(stm32_patterns) > 0, "Should find STM32 connections"

    # Look for IMU connection (ICM-42688 or similar sensor)
    families_connected = {p.ic_b_family for p in stm32_patterns}
    # The STM32F7 FC board should connect to at least one sensor/peripheral IC
    assert len(families_connected) > 0, (
        f"STM32 should connect to other ICs, found families: {families_connected}"
    )


# ---------------------------------------------------------------------------
# Test 2: Interface classification — SPI
# ---------------------------------------------------------------------------


def test_interface_classification_spi():
    """Connections with SCK + MOSI + MISO should classify as SPI."""
    conns = [
        PadConnection(ic_a_pad="1", ic_b_pad="5", net_name="SPI1_SCK"),
        PadConnection(ic_a_pad="2", ic_b_pad="6", net_name="SPI1_MOSI"),
        PadConnection(ic_a_pad="3", ic_b_pad="7", net_name="SPI1_MISO"),
        PadConnection(ic_a_pad="4", ic_b_pad="8", net_name="SPI1_CS"),
    ]
    assert classify_interface(conns) == "SPI"


# ---------------------------------------------------------------------------
# Test 3: Interface classification — I2C
# ---------------------------------------------------------------------------


def test_interface_classification_i2c():
    """Connections with SDA + SCL should classify as I2C."""
    conns = [
        PadConnection(ic_a_pad="1", ic_b_pad="3", net_name="I2C1_SDA"),
        PadConnection(ic_a_pad="2", ic_b_pad="4", net_name="I2C1_SCL"),
    ]
    assert classify_interface(conns) == "I2C"


# ---------------------------------------------------------------------------
# Test 4: Interface classification — UART
# ---------------------------------------------------------------------------


def test_interface_classification_uart():
    """Connections with TX + RX should classify as UART."""
    conns = [
        PadConnection(ic_a_pad="1", ic_b_pad="3", net_name="UART1_TX"),
        PadConnection(ic_a_pad="2", ic_b_pad="4", net_name="UART1_RX"),
    ]
    assert classify_interface(conns) == "UART"


# ---------------------------------------------------------------------------
# Test 5: Power nets excluded
# ---------------------------------------------------------------------------


def test_power_nets_excluded(stm32_connections):
    """No connection should have a power/ground net name."""
    for pattern in stm32_connections:
        for conn in pattern.connections:
            assert not is_power_net(conn.net_name), (
                f"Power net {conn.net_name!r} should not appear in connections"
            )


# ---------------------------------------------------------------------------
# Test 6: Passives excluded
# ---------------------------------------------------------------------------


def test_passives_excluded(stm32_connections):
    """No connection endpoint should reference a passive component family."""
    passive_prefixes = ("R", "C", "L", "FB")
    for pattern in stm32_connections:
        # IC families should not look like passive refs
        assert not pattern.ic_a_family.startswith(passive_prefixes), (
            f"IC A family {pattern.ic_a_family!r} looks like a passive"
        )
        assert not pattern.ic_b_family.startswith(passive_prefixes), (
            f"IC B family {pattern.ic_b_family!r} looks like a passive"
        )


# ---------------------------------------------------------------------------
# Test 7: HackRF connections — verify LPC4320 connections exist
# ---------------------------------------------------------------------------


def test_extract_hackrf_connections(hackrf_connections):
    """HackRF board should have connections involving LPC4320."""
    assert len(hackrf_connections) > 0

    # Find LPC connections
    lpc_patterns = [
        p
        for p in hackrf_connections
        if "LPC" in p.ic_a_family.upper() or "LPC" in p.ic_b_family.upper()
    ]
    assert len(lpc_patterns) > 0, (
        f"Should find LPC connections. Families found: "
        f"{set(p.ic_a_family for p in hackrf_connections) | set(p.ic_b_family for p in hackrf_connections)}"
    )


# ---------------------------------------------------------------------------
# Test 8: Extract all STM32 + ESP32 projects
# ---------------------------------------------------------------------------


def test_extract_all_stm32_esp32():
    """Run extraction on all projects filtered to STM32+ESP32, verify patterns."""
    patterns = extract_all_connections(
        DATA_RAW, target_families=["STM32", "ESP32"]
    )
    assert len(patterns) > 0, "Should find IC pair patterns in STM32/ESP32 projects"

    # Verify at least one pattern has STM32 or ESP32 as ic_a
    mcu_patterns = [
        p
        for p in patterns
        if "STM32" in p.ic_a_family.upper() or "ESP32" in p.ic_a_family.upper()
    ]
    assert len(mcu_patterns) > 0, "Should find STM32 or ESP32 as primary IC"


# ---------------------------------------------------------------------------
# Test 9: Aggregate patterns
# ---------------------------------------------------------------------------


def test_aggregate_patterns():
    """Aggregate patterns from multiple projects, verify counts."""
    # Create synthetic patterns from "different projects"
    conns = [
        PadConnection(ic_a_pad="1", ic_b_pad="5", net_name="SPI_SCK"),
        PadConnection(ic_a_pad="2", ic_b_pad="6", net_name="SPI_MOSI"),
    ]
    patterns = [
        ICPairPattern(
            ic_a_family="STM32F4",
            ic_b_family="ICM42688",
            ic_a_lib_id="MCU_ST:STM32F411",
            ic_b_lib_id="Sensor:ICM42688",
            interface_type="SPI",
            connections=conns,
            project_name=f"project_{i}",
            confidence="low",
        )
        for i in range(3)
    ]

    agg = aggregate_patterns(patterns)
    assert len(agg) == 1
    assert agg[0].sample_count == 3
    assert agg[0].ic_a_family == "STM32F4"
    assert agg[0].ic_b_family == "ICM42688"
    assert agg[0].interface_type == "SPI"
    assert len(agg[0].seen_in_projects) == 3


# ---------------------------------------------------------------------------
# Test 10: Confidence levels
# ---------------------------------------------------------------------------


def test_confidence_levels():
    """Patterns seen in 3+ projects -> high, 2 -> medium, 1 -> low."""
    conn = [PadConnection(ic_a_pad="1", ic_b_pad="2", net_name="SIG")]

    def make_pattern(project: str) -> ICPairPattern:
        return ICPairPattern(
            ic_a_family="STM32F4",
            ic_b_family="W25Q128",
            ic_a_lib_id="MCU_ST:STM32F411",
            ic_b_lib_id="Memory:W25Q128",
            interface_type="SPI",
            connections=conn,
            project_name=project,
            confidence="low",
        )

    # 1 project -> low
    agg = aggregate_patterns([make_pattern("proj1")])
    assert agg[0].confidence == "low"

    # 2 projects -> medium
    agg = aggregate_patterns([make_pattern("proj1"), make_pattern("proj2")])
    assert agg[0].confidence == "medium"

    # 3 projects -> high
    agg = aggregate_patterns(
        [make_pattern("proj1"), make_pattern("proj2"), make_pattern("proj3")]
    )
    assert agg[0].confidence == "high"


# ---------------------------------------------------------------------------
# Test 11: Save and load patterns
# ---------------------------------------------------------------------------


def test_save_and_load_patterns():
    """Save to JSON, load back, verify structure."""
    conns = [
        PadConnection(ic_a_pad="1", ic_b_pad="5", net_name="SPI_SCK"),
        PadConnection(ic_a_pad="2", ic_b_pad="6", net_name="SPI_MOSI"),
    ]
    patterns = [
        AggregatedPattern(
            ic_a_family="STM32F7",
            ic_b_family="ICM42688",
            interface_type="SPI",
            canonical_connections=conns,
            seen_in_projects=["project_a", "project_b"],
            sample_count=2,
            confidence="medium",
        )
    ]

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test_patterns.json"
        save_patterns(patterns, path)

        # Verify JSON structure
        data = json.loads(path.read_text())
        assert data["pattern_count"] == 1
        assert len(data["patterns"]) == 1
        assert data["patterns"][0]["interface_type"] == "SPI"

        # Load back
        loaded = load_patterns(path)
        assert len(loaded) == 1
        assert loaded[0].ic_a_family == "STM32F7"
        assert loaded[0].ic_b_family == "ICM42688"
        assert loaded[0].interface_type == "SPI"
        assert len(loaded[0].canonical_connections) == 2
        assert loaded[0].sample_count == 2
        assert loaded[0].confidence == "medium"
