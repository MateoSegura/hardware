"""Tests for src/pipeline/classify.py — shared classification utilities.

Covers power net detection, component classification, passive type
classification, IC family extraction, footprint reference extraction,
and KiCad version detection.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure vendored kiutils and src are importable
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
SRC_DIR = Path(__file__).resolve().parent.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from src.pipeline.classify import (
    ComponentType,
    classify_component,
    classify_passive_type,
    detect_kicad_version,
    extract_ic_family,
    get_footprint_ref,
    is_ic,
    is_passive,
    is_power_net,
)

DATA_RAW = Path(__file__).resolve().parent.parent / "data" / "raw"


# ── Power net detection ──────────────────────────────────────────────────


class TestPowerNet:
    """Tests for is_power_net()."""

    @pytest.mark.parametrize(
        "name",
        [
            # Voltage patterns
            "+3V3", "+5V", "-12V", "3V3", "1V8", "+1V8", "+12V",
            "+3.3V", "-5V",
            # VCC/VDD/VSS variants
            "VCC", "VDD", "VSS", "VEE", "VBAT", "VBUS", "VIN", "VOUT",
            "VREF", "VREG",
            # Case insensitive
            "vcc", "Vdd", "gnd",
            # Ground variants
            "GND", "AGND", "DGND", "PGND", "GNDREF", "GNDA", "GNDD",
            # PWR_FLAG
            "PWR_FLAG",
            # Unconnected
            "unconnected-U1-pad3",
            "unconnected-J2-pad1",
            # Empty string
            "",
        ],
    )
    def test_power_nets(self, name: str) -> None:
        assert is_power_net(name) is True, f"{name!r} should be a power net"

    @pytest.mark.parametrize(
        "name",
        [
            "SPI_MOSI", "SPI_MISO", "SPI_CLK", "SPI_CS",
            "I2C_SDA", "I2C_SCL",
            "UART_TX", "UART_RX",
            "RESET", "NRST",
            "LED_R", "LED_G", "LED_B",
            "Net-(C1-Pad1)",
            "USB_D+", "USB_D-",
            "SWDIO", "SWCLK",
            "GPIO0", "PA0", "PB1",
        ],
    )
    def test_signal_nets(self, name: str) -> None:
        assert is_power_net(name) is False, f"{name!r} should NOT be a power net"


# ── Component classification ─────────────────────────────────────────────


class TestClassifyComponent:
    """Tests for classify_component()."""

    # -- ICs --
    @pytest.mark.parametrize(
        "lib_id, footprint, ref, pad_count",
        [
            ("MCU_ST:STM32F722RET6", "", "U1", 64),
            ("Regulator_Linear:AP2112K-3.3", "", "U3", 5),
            ("Sensor_Temperature:TMP116", "", "U2", 6),
            ("Interface_USB:FT232RL", "", "U4", 28),
            ("Driver_Motor:DRV8301", "", "U5", 48),
            ("Memory_Flash:W25Q128", "", "U6", 8),
            ("Amplifier_Operational:OPA340", "", "U7", 5),
            ("Comparator:LM393", "", "U8", 8),
            ("Timer:NE555", "", "U9", 8),
            ("FPGA_Xilinx:XC7A35T", "", "U10", 236),
            ("RF_Module:ESP32-WROOM-32", "", "U11", 38),
            ("Power_Management:TPS62160", "", "U12", 10),
            # Pad count heuristic
            ("SomeLib:SomePart", "", "U1", 16),
        ],
    )
    def test_classify_ic(
        self, lib_id: str, footprint: str, ref: str, pad_count: int
    ) -> None:
        result = classify_component(lib_id, footprint, ref, pad_count)
        assert result == ComponentType.IC, (
            f"{lib_id} / {ref} classified as {result!r}, expected 'ic'"
        )

    # -- Passives --
    @pytest.mark.parametrize(
        "lib_id, footprint, ref",
        [
            ("Device:R", "R_0402", "R1"),
            ("Device:R_Small", "R_0603", "R42"),
            ("Device:C", "C_0402", "C1"),
            ("Device:C_Small", "C_0805", "C100"),
            ("Device:C_Polarized", "", "C5"),
            ("Device:L", "L_0603", "L1"),
            ("Device:L_Small", "", "L2"),
            ("Device:R_Pack", "R_Pack_04", "R10"),
            ("Device:C_Pack", "C_Pack_02", "C20"),
            ("Device:Ferrite_Bead", "", "FB1"),
            # Footprint-based detection
            ("SomeLib:SomePart", "R_0402_1005Metric", "R99"),
            ("SomeLib:SomePart", "C_0805_2012Metric", "C99"),
            ("SomeLib:SomePart", "L_0603_1608Metric", "L99"),
            ("SomeLib:SomePart", "R_Array_Convex_4x0402", "R50"),
            ("SomeLib:SomePart", "C_Array_Concave_2x0603", "C50"),
            # Ref-only detection
            ("", "", "R1"),
            ("", "", "C42"),
            ("", "", "L3"),
            ("", "", "FB1"),
        ],
    )
    def test_classify_passive(self, lib_id: str, footprint: str, ref: str) -> None:
        result = classify_component(lib_id, footprint, ref)
        assert result == ComponentType.PASSIVE, (
            f"{lib_id} / {ref} classified as {result!r}, expected 'passive'"
        )

    # -- Connectors --
    @pytest.mark.parametrize(
        "lib_id, footprint, ref",
        [
            ("Connector:Conn_01x04", "", "J1"),
            ("Connector_USB:USB_C_Receptacle", "", "J2"),
            ("Connector_Generic:Conn_02x10", "", "J3"),
            ("Connector_RJ:RJ45", "", "J4"),
            # Footprint-based
            ("SomeLib:Part", "PinHeader_1x04_P2.54mm", "J5"),
            ("SomeLib:Part", "USB_C_Receptacle", "J6"),
            ("SomeLib:Part", "PinSocket_2x10_P2.54mm", "J7"),
            ("SomeLib:Part", "Barrel_Jack_MountingPin", "J8"),
            # Ref-only
            ("", "", "J1"),
        ],
    )
    def test_classify_connector(self, lib_id: str, footprint: str, ref: str) -> None:
        result = classify_component(lib_id, footprint, ref)
        assert result == ComponentType.CONNECTOR, (
            f"{lib_id} / {ref} classified as {result!r}, expected 'connector'"
        )

    # -- Mechanical --
    @pytest.mark.parametrize(
        "lib_id, footprint, ref",
        [
            ("Mechanical:MountingHole", "MountingHole_3.2mm", "H1"),
            ("Mechanical:MountingHole_Pad", "MountingHole_3.2mm_Pad", "H2"),
            ("TestPoint:TestPoint", "TestPoint_Pad_1.0x1.0mm", "TP1"),
            ("Mechanical:Fiducial", "Fiducial_1mm", "FID1"),
            # Footprint-only
            ("SomeLib:Part", "MountingHole_3.2mm", "X1"),
            ("SomeLib:Part", "TestPoint_Probe_Pad", "X2"),
            ("SomeLib:Part", "Fiducial_0.5mm_Dia", "X3"),
            # Ref-only
            ("", "", "H1"),
            ("", "", "TP5"),
            ("", "", "FID3"),
            ("", "", "MH1"),
        ],
    )
    def test_classify_mechanical(
        self, lib_id: str, footprint: str, ref: str
    ) -> None:
        result = classify_component(lib_id, footprint, ref)
        assert result == ComponentType.MECHANICAL, (
            f"{lib_id} / {ref} classified as {result!r}, expected 'mechanical'"
        )

    # -- Switches --
    @pytest.mark.parametrize(
        "lib_id, footprint, ref",
        [
            ("Switch:SW_Push", "SW_Push_1P1T", "SW1"),
            ("Switch:SW_DPDT", "", "SW2"),
            ("Key:Cherry_MX", "", "K1"),
            ("Keyboard:MX_Switch", "MX-100", "K2"),
            ("Keyboard:Choc_V1", "Choc_V1", "K3"),
            # Footprint-only
            ("SomeLib:Part", "SW_Push_SPST", "X1"),
            ("SomeLib:Part", "Key_Cherry_MX", "X2"),
            ("SomeLib:Part", "MX-1U", "X3"),
            ("SomeLib:Part", "Choc_V2_hotswap", "X4"),
            ("SomeLib:Part", "Cherry_MX_Plate", "X5"),
            # Ref-only
            ("", "", "SW1"),
            ("", "", "K1"),
        ],
    )
    def test_classify_switch(self, lib_id: str, footprint: str, ref: str) -> None:
        result = classify_component(lib_id, footprint, ref)
        assert result == ComponentType.SWITCH, (
            f"{lib_id} / {ref} classified as {result!r}, expected 'switch'"
        )

    def test_unknown_component(self) -> None:
        result = classify_component("SomeLib:Mystery", "mystery_pkg", "X1", pad_count=2)
        assert result == ComponentType.UNKNOWN


class TestConvenienceFunctions:
    """Tests for is_passive() and is_ic()."""

    def test_is_passive_true(self) -> None:
        assert is_passive("Device:R", "R_0402", "R1") is True

    def test_is_passive_false(self) -> None:
        assert is_passive("MCU_ST:STM32F722RET6", "", "U1") is False

    def test_is_ic_true(self) -> None:
        assert is_ic("MCU_ST:STM32F722RET6", "", "U1", 64) is True

    def test_is_ic_false(self) -> None:
        assert is_ic("Device:R", "R_0402", "R1") is False


# ── Passive type classification ──────────────────────────────────────────


class TestClassifyPassiveType:
    """Tests for classify_passive_type()."""

    @pytest.mark.parametrize(
        "lib_id, footprint, ref, expected",
        [
            # Resistors
            ("Device:R", "R_0402", "R1", "R"),
            ("Device:R_Small", "", "R2", "R"),
            ("Device:R_Pack", "R_Pack_04", "R10", "R"),
            ("SomeLib:X", "R_0603_1608Metric", "", "R"),
            # Capacitors
            ("Device:C", "C_0402", "C1", "C"),
            ("Device:C_Small", "", "C2", "C"),
            ("Device:C_Polarized", "", "C3", "C"),
            ("Device:C_Pack", "C_Pack_02", "C20", "C"),
            ("SomeLib:X", "C_0805_2012Metric", "", "C"),
            # Inductors
            ("Device:L", "L_0603", "L1", "L"),
            ("Device:L_Small", "", "L2", "L"),
            ("SomeLib:X", "L_1210_3225Metric", "", "L"),
            # Ferrite beads
            ("Device:Ferrite_Bead", "", "FB1", "FB"),
            # Ref-only fallback
            ("", "", "R1", "R"),
            ("", "", "C42", "C"),
            ("", "", "L3", "L"),
            ("", "", "FB1", "FB"),
            # Unknown passive
            ("Device:Crystal", "", "Y1", "passive"),
        ],
    )
    def test_passive_type(
        self, lib_id: str, footprint: str, ref: str, expected: str
    ) -> None:
        result = classify_passive_type(lib_id, footprint, ref)
        assert result == expected, (
            f"classify_passive_type({lib_id!r}, {footprint!r}, {ref!r}) "
            f"= {result!r}, expected {expected!r}"
        )


# ── IC family extraction ────────────────────────────────────────────────


class TestExtractICFamily:
    """Tests for extract_ic_family()."""

    @pytest.mark.parametrize(
        "lib_id, value, expected",
        [
            # STM32 families
            ("MCU_ST_STM32F7:STM32F722RETx", "", "STM32F7"),
            ("MCU_ST_STM32F4:STM32F411CEU6", "", "STM32F4"),
            ("MCU_ST_STM32H7:STM32H743ZIT6", "", "STM32H7"),
            # ESP32
            ("espressif:ESP32-S3", "", "ESP32-S3"),
            ("RF_Module:ESP32-WROOM-32", "", "ESP32"),
            # RP2040
            ("MCU_RaspberryPi:RP2040", "", "RP2040"),
            # ATmega/ATtiny
            ("MCU_Microchip_ATmega:ATmega328P-AU", "", "ATmega"),
            ("MCU_Microchip_ATtiny:ATtiny85-20PU", "", "ATtiny"),
            # nRF
            ("MCU_Nordic:nRF52840", "", "nRF52"),
            # LPC
            ("MCU_NXP_LPC:LPC1768", "", "LPC1768"),
            # Generic
            ("Regulator_Linear:AP2112K-3.3", "", "AP2112K"),
            # Value fallback
            ("SomeLib:???", "TPS62160", "TPS62160"),
            # Empty fallback
            ("", "", "Unknown"),
        ],
    )
    def test_extract_family(
        self, lib_id: str, value: str, expected: str
    ) -> None:
        result = extract_ic_family(lib_id, value)
        assert result == expected, (
            f"extract_ic_family({lib_id!r}, {value!r}) = {result!r}, "
            f"expected {expected!r}"
        )


# ── Footprint reference extraction ──────────────────────────────────────


class TestGetFootprintRef:
    """Tests for get_footprint_ref()."""

    def test_kicad89_properties_dict(self) -> None:
        """KiCad 8/9 stores reference in fp.properties dict."""
        fp = MagicMock()
        fp.properties = {"Reference": "U1", "Value": "STM32F722"}
        assert get_footprint_ref(fp) == "U1"

    def test_kicad67_graphic_items(self) -> None:
        """KiCad 6/7 stores reference in graphicItems."""
        gi = MagicMock()
        gi.type = "reference"
        gi.text = "C42"

        fp = MagicMock()
        fp.properties = []  # Not a dict → skip
        fp.graphicItems = [gi]
        assert get_footprint_ref(fp) == "C42"

    def test_no_reference_found(self) -> None:
        """Returns empty string when no reference can be found."""
        fp = MagicMock()
        fp.properties = []
        fp.graphicItems = []
        assert get_footprint_ref(fp) == ""

    def test_properties_dict_without_reference(self) -> None:
        """Properties dict exists but has no Reference key."""
        fp = MagicMock()
        fp.properties = {"Value": "100nF"}
        fp.graphicItems = []
        assert get_footprint_ref(fp) == ""


# ── KiCad version detection ─────────────────────────────────────────────


class TestDetectKicadVersion:
    """Tests for detect_kicad_version()."""

    def test_version_from_schematic(self, tmp_path: Path) -> None:
        """Extract version from a .kicad_sch file header."""
        sch = tmp_path / "test.kicad_sch"
        sch.write_text('(kicad_sch (version 20231120) (generator "eeschema")\n')
        assert detect_kicad_version(sch) == 20231120

    def test_version_from_pcb(self, tmp_path: Path) -> None:
        """Extract version from a .kicad_pcb file header."""
        pcb = tmp_path / "test.kicad_pcb"
        pcb.write_text('(kicad_pcb (version 20221018) (generator "pcbnew")\n')
        assert detect_kicad_version(pcb) == 20221018

    def test_no_version(self, tmp_path: Path) -> None:
        """Return None for a file with no version token."""
        f = tmp_path / "test.txt"
        f.write_text("no version here\n")
        assert detect_kicad_version(f) is None

    def test_missing_file(self, tmp_path: Path) -> None:
        """Return None for a nonexistent file."""
        assert detect_kicad_version(tmp_path / "nonexistent.kicad_sch") is None


# ── Integration tests with real KiCad data ──────────────────────────────


@pytest.fixture
def stm32f7_pcb() -> Path:
    return DATA_RAW / "rishikesh2715__stm32f7-fc" / "Flight_Controller.kicad_pcb"


@pytest.fixture
def stm32f7_sch() -> Path:
    return DATA_RAW / "rishikesh2715__stm32f7-fc" / "Flight_Controller.kicad_sch"


class TestIntegrationRealData:
    """Integration tests using real KiCad pilot project data."""

    @pytest.mark.skipif(
        not (DATA_RAW / "rishikesh2715__stm32f7-fc").exists(),
        reason="Pilot data not available",
    )
    def test_version_detection_real_pcb(self, stm32f7_pcb: Path) -> None:
        """Detect version from a real KiCad PCB file."""
        version = detect_kicad_version(stm32f7_pcb)
        assert version is not None
        assert version > 20200000  # At least KiCad 6

    @pytest.mark.skipif(
        not (DATA_RAW / "rishikesh2715__stm32f7-fc").exists(),
        reason="Pilot data not available",
    )
    def test_version_detection_real_sch(self, stm32f7_sch: Path) -> None:
        """Detect version from a real KiCad schematic file."""
        version = detect_kicad_version(stm32f7_sch)
        assert version is not None
        assert version > 20200000

    @pytest.mark.skipif(
        not (DATA_RAW / "rishikesh2715__stm32f7-fc").exists(),
        reason="Pilot data not available",
    )
    def test_footprint_ref_real_pcb(self, stm32f7_pcb: Path) -> None:
        """Extract footprint refs from a real PCB using vendored kiutils."""
        from kiutils.board import Board

        board = Board.from_file(str(stm32f7_pcb))
        refs = [get_footprint_ref(fp) for fp in board.footprints]
        # Should have many non-empty refs
        non_empty = [r for r in refs if r]
        assert len(non_empty) > 10, f"Expected many refs, got {len(non_empty)}"
        # Should include common ref prefixes
        prefixes = {r[0] for r in non_empty if r[0].isalpha()}
        assert "U" in prefixes or "C" in prefixes or "R" in prefixes

    @pytest.mark.skipif(
        not (DATA_RAW / "rishikesh2715__stm32f7-fc").exists(),
        reason="Pilot data not available",
    )
    def test_classify_real_footprints(self, stm32f7_pcb: Path) -> None:
        """Classify components from a real PCB file."""
        from kiutils.board import Board

        board = Board.from_file(str(stm32f7_pcb))
        type_counts: dict[str, int] = {}
        for fp in board.footprints:
            ref = get_footprint_ref(fp)
            lib_id = fp.libId or ""
            fp_name = fp.entryName or ""
            ctype = classify_component(lib_id, fp_name, ref, len(fp.pads))
            type_counts[ctype] = type_counts.get(ctype, 0) + 1

        # Real boards have passives and ICs
        assert type_counts.get(ComponentType.PASSIVE, 0) > 0, (
            "Expected passives on a real board"
        )
        # STM32F7 FC board should have ICs
        assert type_counts.get(ComponentType.IC, 0) > 0, (
            "Expected ICs on a real board"
        )

    @pytest.mark.skipif(
        not (DATA_RAW / "rishikesh2715__stm32f7-fc").exists(),
        reason="Pilot data not available",
    )
    def test_power_net_detection_real_pcb(self, stm32f7_pcb: Path) -> None:
        """Check that power nets from a real board are detected."""
        from kiutils.board import Board

        board = Board.from_file(str(stm32f7_pcb))
        net_names = [n.name for n in board.nets if n.name]
        power_nets = [n for n in net_names if is_power_net(n)]
        signal_nets = [n for n in net_names if not is_power_net(n)]

        assert len(power_nets) > 0, "Expected power nets on a real board"
        assert len(signal_nets) > 0, "Expected signal nets on a real board"

        # Specific checks: GND and some voltage rail should be detected
        all_power = set(power_nets)
        assert "GND" in all_power or any(
            "GND" in n for n in all_power
        ), "GND should be detected as power"


# ── Edge case tests ──────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_inputs(self) -> None:
        """Empty strings should not crash."""
        assert classify_component("", "", "", 0) == ComponentType.UNKNOWN
        assert classify_passive_type("", "", "") == "passive"
        assert extract_ic_family("", "") == "Unknown"

    def test_connector_not_passive(self) -> None:
        """Connectors in Device: lib should not be classified as passives."""
        # Connectors have their own lib prefix
        result = classify_component("Connector:USB_C", "", "J1")
        assert result == ComponentType.CONNECTOR

    def test_mounting_hole_not_ic(self) -> None:
        """Mounting holes with many pads should not be classified as ICs."""
        result = classify_component(
            "Mechanical:MountingHole_Pad", "MountingHole_3.2mm_Pad", "H1",
            pad_count=1,
        )
        assert result == ComponentType.MECHANICAL

    def test_test_point_not_ic(self) -> None:
        """Test points should be mechanical, not IC."""
        result = classify_component(
            "TestPoint:TestPoint", "TestPoint_Pad_1.0x1.0mm", "TP1",
            pad_count=1,
        )
        assert result == ComponentType.MECHANICAL

    def test_keyboard_switch_not_connector(self) -> None:
        """Keyboard switches should not be confused with connectors."""
        result = classify_component(
            "Key:Cherry_MX", "MX-1U", "K1", pad_count=2,
        )
        assert result == ComponentType.SWITCH

    def test_r_pack_is_passive(self) -> None:
        """R_Pack with many pads should still be passive, not IC."""
        result = classify_component(
            "Device:R_Pack", "R_Pack_04", "R10", pad_count=8,
        )
        assert result == ComponentType.PASSIVE

    def test_large_pad_count_heuristic(self) -> None:
        """Unknown components with many pads should be classified as IC."""
        result = classify_component(
            "SomeLib:UnknownChip", "QFP-100", "U1", pad_count=100,
        )
        assert result == ComponentType.IC

    def test_fiducial_ref_prefix(self) -> None:
        """FID prefix should be mechanical."""
        result = classify_component("", "", "FID1")
        assert result == ComponentType.MECHANICAL

    def test_case_insensitive_ref(self) -> None:
        """Reference matching should be case-insensitive for mechanical."""
        result = classify_component("", "", "tp1")
        assert result == ComponentType.MECHANICAL
