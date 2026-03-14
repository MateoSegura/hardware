"""Tests for design composer — generates wired KiCad projects from high-level specs.

Uses real wiring patterns from data/patterns/wiring_patterns.json and
real decoupling rules from data/patterns/decoupling_rules.json.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from src.pipeline.composer import (
    DesignSpec,
    GeneratedProject,
    PeripheralSpec,
    PowerSpec,
    compose_design,
)

PATTERNS_PATH = Path(__file__).resolve().parent.parent / "data" / "patterns" / "wiring_patterns.json"
RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "patterns" / "decoupling_rules.json"


def _default_power() -> PowerSpec:
    """Standard 3.3V LDO power spec for tests."""
    return PowerSpec(input_source="USB-C", voltage="3.3V", regulator="LDO")


# ---------------------------------------------------------------------------
# Test 1: Simple design — ESP32 + LED, generates root + power + mcu sheets
# ---------------------------------------------------------------------------

def test_compose_simple_design():
    """ESP32 + LED → generates at least 3 sheets (root, power, mcu), valid output."""
    spec = DesignSpec(
        name="SimpleLED",
        mcu_family="ESP32",
        mcu_chip="ESP32-WROOM-32",
        peripherals=[
            PeripheralSpec(name="LED", chip="LED_Generic", interface="GPIO"),
        ],
        power=_default_power(),
    )

    result = compose_design(spec, patterns_path=PATTERNS_PATH)

    assert isinstance(result, GeneratedProject)
    assert result.name == "SimpleLED"

    # Should have root + power + mcu + led = 4 files
    assert len(result.files) >= 3, f"Expected >= 3 files, got {len(result.files)}"

    # Root file exists
    root_file = "simpleled.kicad_sch"
    assert root_file in result.files, f"Missing root file, got: {list(result.files.keys())}"

    # Power and MCU sheets exist
    assert "power.kicad_sch" in result.files
    assert "mcu.kicad_sch" in result.files

    # Root contains sheet references
    root_content = result.files[root_file]
    assert "(sheet" in root_content
    assert '"Power"' in root_content
    assert '"MCU"' in root_content

    # All files are valid S-expressions
    for filename, content in result.files.items():
        assert content.startswith("(kicad_sch"), f"{filename} doesn't start with (kicad_sch"
        assert content.strip().endswith(")"), f"{filename} doesn't end with )"

    # BOM is populated
    assert len(result.bom) > 0

    # Wiring notes exist
    assert len(result.wiring_notes) > 0


# ---------------------------------------------------------------------------
# Test 2: SPI peripheral — STM32F + W5500, wiring pattern applied
# ---------------------------------------------------------------------------

def test_compose_with_spi_peripheral():
    """STM32F + W5500 (SPI) → wiring pattern applied, net labels match."""
    spec = DesignSpec(
        name="EtherBoard",
        mcu_family="STM32F7",
        mcu_chip="STM32F722RET6",
        peripherals=[
            PeripheralSpec(name="Ethernet", chip="W5500", interface="SPI"),
        ],
        power=_default_power(),
    )

    result = compose_design(spec, patterns_path=PATTERNS_PATH)

    # Should find the STM32F <-> W5500 SPI pattern from wiring_patterns.json
    # Check that no warnings about missing patterns
    w5500_warnings = [w for w in result.warnings if "W5500" in w]
    assert len(w5500_warnings) == 0, (
        f"Should find W5500 pattern but got warnings: {w5500_warnings}"
    )

    # Wiring notes should mention the pattern
    pattern_notes = [n for n in result.wiring_notes if "Ethernet" in n and "W5500" in n]
    assert len(pattern_notes) > 0, "Should have wiring note for W5500"

    # The peripheral sheet should have global labels matching pattern nets
    eth_file = "ethernet.kicad_sch"
    assert eth_file in result.files
    eth_content = result.files[eth_file]

    # Pattern has: CS, SCK, MISO, MOSI nets
    for net_name in ["CS", "SCK", "MISO", "MOSI"]:
        assert f'"{net_name}"' in eth_content, (
            f"Net label {net_name} missing from ethernet sheet"
        )

    # MCU sheet should also have matching labels
    mcu_content = result.files["mcu.kicad_sch"]
    for net_name in ["CS", "SCK", "MISO", "MOSI"]:
        assert f'"{net_name}"' in mcu_content, (
            f"Net label {net_name} missing from MCU sheet"
        )


# ---------------------------------------------------------------------------
# Test 3: I2C peripheral — ESP32-S3 + RTC (PCF8563T), SDA/SCL nets created
# ---------------------------------------------------------------------------

def test_compose_with_i2c_peripheral():
    """ESP32-S3 + RTC (I2C) → SDA/SCL nets created from pattern."""
    spec = DesignSpec(
        name="RTCBoard",
        mcu_family="ESP32-S3",
        mcu_chip="ESP32-S3-WROOM-1",
        peripherals=[
            PeripheralSpec(name="RTC", chip="PCF8563T", interface="I2C"),
        ],
        power=_default_power(),
    )

    result = compose_design(spec, patterns_path=PATTERNS_PATH)

    # Should find the ESP32-S3 <-> PCF8563T I2C pattern
    rtc_warnings = [w for w in result.warnings if "PCF8563T" in w]
    assert len(rtc_warnings) == 0, (
        f"Should find PCF8563T pattern but got warnings: {rtc_warnings}"
    )

    # RTC sheet should have I2C nets
    rtc_file = "rtc.kicad_sch"
    assert rtc_file in result.files
    rtc_content = result.files[rtc_file]

    # Pattern has: I2C_SCL, I2C_SDA, RTC_INT nets
    assert '"I2C_SCL"' in rtc_content, "I2C_SCL missing from RTC sheet"
    assert '"I2C_SDA"' in rtc_content, "I2C_SDA missing from RTC sheet"

    # MCU sheet should also have I2C net labels
    mcu_content = result.files["mcu.kicad_sch"]
    assert '"I2C_SCL"' in mcu_content, "I2C_SCL missing from MCU sheet"
    assert '"I2C_SDA"' in mcu_content, "I2C_SDA missing from MCU sheet"


# ---------------------------------------------------------------------------
# Test 4: Unknown peripheral — generates sheet with warning
# ---------------------------------------------------------------------------

def test_compose_unknown_peripheral():
    """Peripheral not in patterns → generates sheet with warning."""
    spec = DesignSpec(
        name="UnknownBoard",
        mcu_family="ESP32-S3",
        mcu_chip="ESP32-S3-WROOM-1",
        peripherals=[
            PeripheralSpec(
                name="CustomSensor",
                chip="XYZ9999-QWERTY",
                interface="SPI",
            ),
        ],
        power=_default_power(),
    )

    result = compose_design(spec, patterns_path=PATTERNS_PATH)

    # Should have a warning about missing pattern
    assert len(result.warnings) > 0, "Should have warnings for unknown peripheral"
    xyz_warnings = [w for w in result.warnings if "XYZ9999" in w]
    assert len(xyz_warnings) > 0, f"Should warn about XYZ9999, got: {result.warnings}"

    # Peripheral sheet should still be generated with default net names
    sensor_file = "customsensor.kicad_sch"
    assert sensor_file in result.files

    sensor_content = result.files[sensor_file]
    assert "(kicad_sch" in sensor_content

    # Default SPI nets should be present (CUSTOMSENSOR_SCK, etc.)
    assert "CUSTOMSENSOR_SCK" in sensor_content
    assert "CUSTOMSENSOR_MOSI" in sensor_content
    assert "CUSTOMSENSOR_MISO" in sensor_content
    assert "CUSTOMSENSOR_CS" in sensor_content


# ---------------------------------------------------------------------------
# Test 5: Generated output passes kicad-cli ERC without crash
# ---------------------------------------------------------------------------

def test_compose_generates_valid_kicad():
    """Write composed output, run kicad-cli ERC — should not crash."""
    spec = DesignSpec(
        name="ValidTest",
        mcu_family="ESP32",
        mcu_chip="ESP32-WROOM-32",
        peripherals=[],
        power=_default_power(),
    )

    result = compose_design(spec, patterns_path=PATTERNS_PATH)

    tmp_dir = Path(tempfile.mkdtemp(prefix="composer_test_"))
    try:
        # Write all files
        for filename, content in result.files.items():
            (tmp_dir / filename).write_text(content)

        # Find root file
        root_file = tmp_dir / "validtest.kicad_sch"
        assert root_file.exists(), f"Root file not found: {list(tmp_dir.glob('*'))}"

        # Run kicad-cli — just verify it can parse without crashing
        proc = subprocess.run(
            ["/usr/bin/kicad-cli", "sch", "erc", str(root_file),
             "--format", "json", "-o", "/dev/null"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # A malformed file causes parse errors; ERC violations are OK
        assert "Unable to load" not in proc.stderr, (
            f"kicad-cli could not load file: {proc.stderr}"
        )
    finally:
        for f in tmp_dir.glob("*"):
            f.unlink(missing_ok=True)
        tmp_dir.rmdir()


# ---------------------------------------------------------------------------
# Test 6: MCU sheet has bypass caps from decoupling rules
# ---------------------------------------------------------------------------

def test_compose_includes_decoupling():
    """MCU sheet has bypass caps from decoupling rules."""
    spec = DesignSpec(
        name="DecoupTest",
        mcu_family="ESP32-S3",
        mcu_chip="ESP32-S3-WROOM-1",
        peripherals=[],
        power=_default_power(),
    )

    result = compose_design(spec, patterns_path=PATTERNS_PATH)

    mcu_content = result.files["mcu.kicad_sch"]

    # MCU sheet should have capacitors (Device:C)
    assert '"Device:C"' in mcu_content, "MCU sheet should have decoupling caps"

    # Check BOM has caps on MCU sheet
    mcu_caps = [b for b in result.bom if b["sheet"] == "MCU" and b["lib_id"] == "Device:C"]
    assert len(mcu_caps) > 0, "BOM should include MCU decoupling caps"


# ---------------------------------------------------------------------------
# Test 7: BOM includes all components from all sheets
# ---------------------------------------------------------------------------

def test_compose_bom_complete():
    """BOM includes all components from all sheets."""
    spec = DesignSpec(
        name="BOMTest",
        mcu_family="ESP32-S3",
        mcu_chip="ESP32-S3-WROOM-1",
        peripherals=[
            PeripheralSpec(name="RTC", chip="PCF8563T", interface="I2C"),
        ],
        power=_default_power(),
    )

    result = compose_design(spec, patterns_path=PATTERNS_PATH)

    # BOM should have entries
    assert len(result.bom) > 0

    # Collect unique sheets from BOM
    bom_sheets = {entry["sheet"] for entry in result.bom}

    # Should have components from Power, MCU, and RTC sheets
    assert "Power" in bom_sheets, f"BOM missing Power sheet, got: {bom_sheets}"
    assert "MCU" in bom_sheets, f"BOM missing MCU sheet, got: {bom_sheets}"
    assert "RTC" in bom_sheets, f"BOM missing RTC sheet, got: {bom_sheets}"

    # BOM should include the regulator
    reg_entries = [b for b in result.bom if "Regulator" in b["lib_id"]]
    assert len(reg_entries) > 0, "BOM should include the voltage regulator"

    # BOM should include the MCU
    mcu_entries = [b for b in result.bom if b["value"] == "ESP32-S3-WROOM-1"]
    assert len(mcu_entries) > 0, "BOM should include the MCU"

    # BOM should include the peripheral IC
    periph_entries = [b for b in result.bom if b["value"] == "PCF8563T"]
    assert len(periph_entries) > 0, "BOM should include the peripheral IC"

    # All BOM entries should have required fields
    for entry in result.bom:
        assert "ref" in entry
        assert "value" in entry
        assert "lib_id" in entry
        assert "sheet" in entry


# ---------------------------------------------------------------------------
# Test 8: Full GPS tracker spec → valid project
# ---------------------------------------------------------------------------

def test_compose_gps_tracker():
    """Full GPS tracker spec → valid project with multiple peripherals."""
    spec = DesignSpec(
        name="GPSTracker",
        mcu_family="ESP32-S3",
        mcu_chip="ESP32-S3-WROOM-1",
        peripherals=[
            PeripheralSpec(name="GPS", chip="NEO-6M", interface="UART"),
            PeripheralSpec(name="RTC", chip="PCF8563T", interface="I2C"),
            PeripheralSpec(name="StatusLED", chip="LED_Generic", interface="GPIO"),
        ],
        power=PowerSpec(
            input_source="battery",
            voltage="3.3V",
            regulator="LDO",
        ),
    )

    result = compose_design(spec, patterns_path=PATTERNS_PATH)

    assert isinstance(result, GeneratedProject)
    assert result.name == "GPSTracker"

    # Root + power + mcu + 3 peripherals = 6 files
    assert len(result.files) >= 6, (
        f"Expected >= 6 files, got {len(result.files)}: {list(result.files.keys())}"
    )

    # Check all expected files exist
    assert "gpstracker.kicad_sch" in result.files, "Missing root schematic"
    assert "power.kicad_sch" in result.files, "Missing power sheet"
    assert "mcu.kicad_sch" in result.files, "Missing MCU sheet"
    assert "gps.kicad_sch" in result.files, "Missing GPS sheet"
    assert "rtc.kicad_sch" in result.files, "Missing RTC sheet"
    assert "statusled.kicad_sch" in result.files, "Missing StatusLED sheet"

    # Root schematic references all sub-sheets
    root = result.files["gpstracker.kicad_sch"]
    for sheet_name in ["Power", "MCU", "GPS", "RTC", "StatusLED"]:
        assert f'"{sheet_name}"' in root, f"Root missing {sheet_name} sheet reference"

    # RTC should use I2C pattern (known in wiring_patterns.json)
    rtc_content = result.files["rtc.kicad_sch"]
    assert '"I2C_SCL"' in rtc_content or '"RTC_SCL"' in rtc_content, (
        "RTC sheet should have I2C net labels"
    )

    # BOM should have entries from all sheets
    bom_sheets = {entry["sheet"] for entry in result.bom}
    assert len(bom_sheets) >= 5, (
        f"BOM should cover >= 5 sheets, got: {bom_sheets}"
    )

    # Power sheet should have battery input
    power_content = result.files["power.kicad_sch"]
    assert '"VBAT"' in power_content, "Battery power should use VBAT net"

    # Wiring notes should document what was done
    assert len(result.wiring_notes) >= 3, (
        f"Expected >= 3 wiring notes, got: {result.wiring_notes}"
    )

    # Write and validate with kicad-cli
    tmp_dir = Path(tempfile.mkdtemp(prefix="gps_tracker_test_"))
    try:
        for filename, content in result.files.items():
            (tmp_dir / filename).write_text(content)

        root_file = tmp_dir / "gpstracker.kicad_sch"
        assert root_file.exists()

        proc = subprocess.run(
            ["/usr/bin/kicad-cli", "sch", "erc", str(root_file),
             "--format", "json", "-o", "/dev/null"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert "Unable to load" not in proc.stderr, (
            f"kicad-cli could not load GPS tracker project: {proc.stderr}"
        )
    finally:
        for f in tmp_dir.glob("*"):
            f.unlink(missing_ok=True)
        tmp_dir.rmdir()
