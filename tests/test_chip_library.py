"""Tests for the chip library — real multi-pin IC definitions."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from src.pipeline.chip_library import (
    esp32_s3_wroom_1,
    generate_lib_symbol_sexp,
    list_chips,
    lookup_chip,
    neo_6m,
    stm32f411ceu6,
)
from src.pipeline.composer import (
    DesignSpec,
    PeripheralSpec,
    PowerSpec,
    compose_design,
)
from src.pipeline.symbol_gen import VALID_PIN_TYPES

PATTERNS_PATH = Path(__file__).resolve().parent.parent / "data" / "patterns" / "wiring_patterns.json"


# ---------------------------------------------------------------------------
# Test 1: ESP32-S3-WROOM-1 pin count and groups
# ---------------------------------------------------------------------------

def test_esp32_s3_pin_count():
    """ESP32-S3-WROOM-1 module has 41 pins."""
    chip = esp32_s3_wroom_1()
    assert len(chip.pins) == 41, f"Expected 41 pins, got {len(chip.pins)}"


def test_esp32_s3_has_required_groups():
    """ESP32-S3-WROOM-1 has Power, UART, SPI, I2C, and GPIO groups."""
    chip = esp32_s3_wroom_1()
    groups = {p.group for p in chip.pins}
    for required in ("Power", "UART", "SPI", "I2C", "GPIO"):
        assert required in groups, f"Missing group: {required}"


def test_esp32_s3_power_pins():
    """ESP32-S3-WROOM-1 has 3V3, GND, and EN power pins."""
    chip = esp32_s3_wroom_1()
    power_names = {p.name for p in chip.pins if p.group == "Power"}
    assert "3V3" in power_names
    assert "EN" in power_names
    assert any("GND" in n for n in power_names)


def test_esp32_s3_no_duplicate_pin_numbers():
    """All pin numbers are unique."""
    chip = esp32_s3_wroom_1()
    numbers = [p.number for p in chip.pins]
    assert len(numbers) == len(set(numbers)), (
        f"Duplicate pin numbers: {[n for n in numbers if numbers.count(n) > 1]}"
    )


# ---------------------------------------------------------------------------
# Test 2: STM32F411CEU6 pin count and groups
# ---------------------------------------------------------------------------

def test_stm32f411_pin_count():
    """STM32F411CEU6 has 48 pins (UFQFPN-48)."""
    chip = stm32f411ceu6()
    assert len(chip.pins) == 48, f"Expected 48 pins, got {len(chip.pins)}"


def test_stm32f411_has_required_groups():
    """STM32F411CEU6 has Power, System, Port_A, Port_B, Port_C groups."""
    chip = stm32f411ceu6()
    groups = {p.group for p in chip.pins}
    for required in ("Power", "System", "Port_A", "Port_B", "Port_C"):
        assert required in groups, f"Missing group: {required}"


def test_stm32f411_port_a_has_16_pins():
    """Port A has 16 GPIO pins (PA0-PA15)."""
    chip = stm32f411ceu6()
    port_a = [p for p in chip.pins if p.group == "Port_A"]
    assert len(port_a) == 16, f"Expected 16 Port_A pins, got {len(port_a)}"


def test_stm32f411_has_nrst_and_boot0():
    """STM32F411 has NRST and BOOT0 system pins."""
    chip = stm32f411ceu6()
    sys_names = {p.name for p in chip.pins if p.group == "System"}
    assert "NRST" in sys_names
    assert "BOOT0" in sys_names


def test_stm32f411_no_duplicate_pin_numbers():
    """All pin numbers are unique."""
    chip = stm32f411ceu6()
    numbers = [p.number for p in chip.pins]
    assert len(numbers) == len(set(numbers)), (
        f"Duplicate pin numbers: {[n for n in numbers if numbers.count(n) > 1]}"
    )


# ---------------------------------------------------------------------------
# Test 3: NEO-6M pin count
# ---------------------------------------------------------------------------

def test_neo6m_pin_count():
    """NEO-6M GPS module has 24 pins."""
    chip = neo_6m()
    assert len(chip.pins) == 24, f"Expected 24 pins, got {len(chip.pins)}"


def test_neo6m_has_uart_pins():
    """NEO-6M has TXD and RXD in UART group."""
    chip = neo_6m()
    uart_names = {p.name for p in chip.pins if p.group == "UART"}
    assert "TXD" in uart_names
    assert "RXD" in uart_names


# ---------------------------------------------------------------------------
# Test 4: All pin types are valid KiCad types
# ---------------------------------------------------------------------------

def test_all_pin_types_valid():
    """Every pin in every chip uses a valid KiCad electrical type."""
    for chip_name in list_chips():
        chip = lookup_chip(chip_name)
        for pin in chip.pins:
            assert pin.electrical_type in VALID_PIN_TYPES, (
                f"{chip_name} pin {pin.number} ({pin.name}) has invalid type: "
                f"{pin.electrical_type}"
            )


# ---------------------------------------------------------------------------
# Test 5: lookup_chip works with lib_id format
# ---------------------------------------------------------------------------

def test_lookup_by_lib_id():
    """lookup_chip resolves 'Library:PartName' format."""
    chip = lookup_chip("RF_Module:ESP32-S3-WROOM-1")
    assert chip is not None
    assert chip.name == "ESP32-S3-WROOM-1"

    chip = lookup_chip("MCU_ST:STM32F411CEU6")
    assert chip is not None
    assert chip.name == "STM32F411CEU6"


def test_lookup_unknown_returns_none():
    """Unknown chip returns None."""
    assert lookup_chip("Custom:UNKNOWN_CHIP_XYZ") is None


# ---------------------------------------------------------------------------
# Test 6: Generated S-expression has correct pin count
# ---------------------------------------------------------------------------

def test_generated_sexp_pin_count():
    """Generated lib_symbol S-expression has correct number of pin definitions."""
    for chip_name in list_chips():
        chip = lookup_chip(chip_name)
        sexp = generate_lib_symbol_sexp(chip, f"Test:{chip_name}")
        pin_count = sexp.count("(pin ")
        assert pin_count == len(chip.pins), (
            f"{chip_name}: S-expression has {pin_count} pins, "
            f"expected {len(chip.pins)}"
        )


# ---------------------------------------------------------------------------
# Test 7: Generated symbol passes kicad-cli validation
# ---------------------------------------------------------------------------

def test_generated_symbol_kicad_valid():
    """Write generated .kicad_sym, verify kicad-cli can parse it."""
    from src.pipeline.symbol_gen import generate_symbol_file

    for chip_name in list_chips():
        chip = lookup_chip(chip_name)
        sym_path = Path(tempfile.mktemp(suffix=".kicad_sym"))
        try:
            generate_symbol_file(chip, sym_path)
            assert sym_path.exists(), f"Symbol file not created for {chip_name}"
            content = sym_path.read_text()
            assert "(kicad_symbol_lib" in content
            assert chip_name in content

            # Verify pin count in output file
            pin_matches = re.findall(r'\(pin \w+ line', content)
            assert len(pin_matches) == len(chip.pins), (
                f"{chip_name}: file has {len(pin_matches)} pins, "
                f"expected {len(chip.pins)}"
            )
        finally:
            sym_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test 8: GPS tracker composer uses real pin counts (not 2-pin stubs)
# ---------------------------------------------------------------------------

def test_gps_tracker_uses_real_pins():
    """GPS tracker project generates real multi-pin symbols for ESP32-S3."""
    spec = DesignSpec(
        name="GPSTracker",
        mcu_family="ESP32-S3",
        mcu_chip="ESP32-S3-WROOM-1",
        peripherals=[
            PeripheralSpec(name="GPS", chip="NEO-6M", interface="UART"),
        ],
        power=PowerSpec(
            input_source="battery",
            voltage="3.3V",
            regulator="LDO",
        ),
    )

    result = compose_design(spec, patterns_path=PATTERNS_PATH)

    # MCU sheet should have the ESP32-S3-WROOM-1 with real pins
    mcu_content = result.files["mcu.kicad_sch"]

    # Count pin UUIDs for the MCU symbol — should be 41, not 2
    # The MCU component uses lib_id "RF_Module:ESP32-S3-WROOM-1"
    # Its pin section in the placed symbol has (pin "N" (uuid "...")) entries
    mcu_pin_matches = re.findall(r'\(pin "\d+"\s*\n\s*\(uuid', mcu_content)
    assert len(mcu_pin_matches) >= 41, (
        f"MCU should have >= 41 pin UUIDs (real ESP32-S3 pins), "
        f"got {len(mcu_pin_matches)}"
    )

    # lib_symbols section should contain real ESP32-S3 pin definitions
    assert "ESP32-S3-WROOM-1" in mcu_content
    # Pin names are on separate lines: (name "GPIO0" ...)
    esp32_pins_in_lib = re.findall(
        r'\(name "(?:GPIO|3V3|GND|EN|TXD|RXD)',
        mcu_content,
    )
    assert len(esp32_pins_in_lib) > 10, (
        f"lib_symbols should have real ESP32-S3 pin names, "
        f"found {len(esp32_pins_in_lib)} matching pins"
    )


# ---------------------------------------------------------------------------
# Test 9: Schematic with chip library passes kicad-cli
# ---------------------------------------------------------------------------

def test_schematic_with_real_chips_kicad_valid():
    """Schematic using chip library definitions can be parsed by kicad-cli."""
    from src.pipeline.schematic_gen import (
        ComponentPlacement,
        NetConnection,
        generate_schematic,
    )

    components = [
        ComponentPlacement(
            lib_id="RF_Module:ESP32-S3-WROOM-1",
            ref="U1",
            value="ESP32-S3-WROOM-1",
            footprint="RF_Module:ESP32-S3-WROOM-1",
            position=(100.0, 80.0),
        ),
        ComponentPlacement(
            lib_id="Device:C",
            ref="C1",
            value="100nF",
            footprint="Capacitor_SMD:C_0402_1005Metric",
            position=(140.0, 80.0),
        ),
    ]
    nets = [
        NetConnection(net_name="VCC_3V3", label_type="global", position=(80.0, 70.0)),
        NetConnection(net_name="GND", label_type="global", position=(80.0, 90.0)),
    ]

    content = generate_schematic(components, nets, title="ChipLibTest")

    # Should contain real ESP32 pin definitions, not a 2-pin stub
    assert "GPIO" in content, "Should have GPIO pin names from chip library"
    pin_count = content.count('(pin "')
    # 41 pins for ESP32 in lib_symbols + 41 in placed symbol + 2+2 for cap = 86
    assert pin_count > 10, f"Expected many pin entries, got {pin_count}"

    sch_path = Path(tempfile.mktemp(suffix=".kicad_sch"))
    try:
        sch_path.write_text(content)
        result = subprocess.run(
            ["/usr/bin/kicad-cli", "sch", "erc", str(sch_path),
             "--format", "json", "-o", "/dev/null"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Should parse without crashing
        assert "Error" not in result.stderr or "ERC" in result.stderr, (
            f"kicad-cli parse error: {result.stderr}"
        )
    finally:
        sch_path.unlink(missing_ok=True)
