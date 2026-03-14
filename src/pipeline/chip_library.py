"""Library of real IC pin definitions for common chips.

Provides ChipDef instances with accurate pin names, numbers, types, and
functional groupings based on actual datasheets. Used by schematic_gen.py
to produce multi-pin symbols instead of 2-pin stubs.
"""

from __future__ import annotations

from src.pipeline.symbol_gen import ChipDef, PinDef


# ---------------------------------------------------------------------------
# ESP32-S3-WROOM-1 (module, 41 pins)
# ---------------------------------------------------------------------------
# Source: ESP32-S3-WROOM-1 datasheet (Espressif), KiCad standard library
# Pin numbering follows the module package (QFN with exposed pad)

def esp32_s3_wroom_1() -> ChipDef:
    """Return ChipDef for the ESP32-S3-WROOM-1 Wi-Fi+BLE module.

    41 pins organized into Power, UART, SPI, I2C, Strapping, and GPIO units.
    """
    pins: list[PinDef] = []

    # Power unit
    pins.extend([
        PinDef(number="2", name="3V3", electrical_type="power_in", group="Power"),
        PinDef(number="1", name="GND", electrical_type="power_in", group="Power"),
        PinDef(number="41", name="GND", electrical_type="power_in", group="Power"),
        PinDef(number="40", name="GND", electrical_type="power_in", group="Power"),
        PinDef(number="3", name="EN", electrical_type="input", group="Power"),
    ])

    # UART unit
    pins.extend([
        PinDef(number="37", name="TXD0", electrical_type="output", group="UART"),
        PinDef(number="36", name="RXD0", electrical_type="input", group="UART"),
    ])

    # SPI unit (FSPI default pins)
    pins.extend([
        PinDef(number="12", name="GPIO10/FSPIIO4/FSPICS0", electrical_type="bidirectional", group="SPI"),
        PinDef(number="13", name="GPIO11/FSPIIO5/FSPID", electrical_type="bidirectional", group="SPI"),
        PinDef(number="14", name="GPIO12/FSPIIO6/FSPICLK", electrical_type="bidirectional", group="SPI"),
        PinDef(number="15", name="GPIO13/FSPIIO7/FSPIQ", electrical_type="bidirectional", group="SPI"),
    ])

    # I2C unit (default I2C pins)
    pins.extend([
        PinDef(number="6", name="GPIO1/ADC1_CH0", electrical_type="bidirectional", group="I2C"),
        PinDef(number="7", name="GPIO2/ADC1_CH1", electrical_type="bidirectional", group="I2C"),
    ])

    # Strapping unit
    pins.extend([
        PinDef(number="4", name="GPIO0", electrical_type="bidirectional", group="Strapping"),
        PinDef(number="27", name="GPIO45", electrical_type="bidirectional", group="Strapping"),
        PinDef(number="28", name="GPIO46", electrical_type="input", group="Strapping"),
    ])

    # GPIO unit (remaining general-purpose I/O)
    pins.extend([
        PinDef(number="5", name="GPIO4/ADC1_CH3", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="8", name="GPIO3/ADC1_CH2", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="9", name="GPIO5/ADC1_CH4", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="10", name="GPIO6/ADC1_CH5", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="11", name="GPIO7/ADC1_CH6", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="16", name="GPIO14/ADC2_CH3", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="17", name="GPIO15/ADC2_CH4/XTAL_32K_P", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="18", name="GPIO16/ADC2_CH5/XTAL_32K_N", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="19", name="GPIO17/ADC2_CH6/DAC1", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="20", name="GPIO18/ADC2_CH7/DAC2", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="21", name="GPIO8/ADC1_CH7", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="22", name="GPIO19/USB_D-", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="23", name="GPIO20/USB_D+", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="24", name="GPIO9/ADC1_CH8", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="25", name="GPIO21", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="26", name="GPIO35/FSPID/SPIIO6", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="29", name="GPIO36/FSPICLK/SPIIO7", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="30", name="GPIO37/FSPIQ/SPIDQS", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="31", name="GPIO38/FSPIWP/SPICLK", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="32", name="GPIO39/TCPWM/SPIHD", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="33", name="GPIO40/JTAG_TCK", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="34", name="GPIO41/JTAG_TMS", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="35", name="GPIO42/JTAG_TDI", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="38", name="GPIO47", electrical_type="bidirectional", group="GPIO"),
        PinDef(number="39", name="GPIO48", electrical_type="bidirectional", group="GPIO"),
    ])

    return ChipDef(
        name="ESP32-S3-WROOM-1",
        library="RF_Module",
        description="ESP32-S3 Wi-Fi + Bluetooth LE module, PCB antenna",
        footprint="RF_Module:ESP32-S3-WROOM-1",
        datasheet_url="https://www.espressif.com/sites/default/files/documentation/esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf",
        pins=pins,
    )


# ---------------------------------------------------------------------------
# STM32F411CEU6 (48-pin UFQFPN)
# ---------------------------------------------------------------------------
# Source: STM32F411xC/xE datasheet (STMicroelectronics), DS10314 Rev 9

def stm32f411ceu6() -> ChipDef:
    """Return ChipDef for the STM32F411CEU6 (48-pin UFQFPN).

    48 pins organized into Power, Port A, Port B, Port C, and System units.
    """
    pins: list[PinDef] = []

    # Power unit (UFQFPN-48 pinout from DS10314 Table 9)
    pins.extend([
        PinDef(number="1", name="VBAT", electrical_type="power_in", group="Power"),
        PinDef(number="8", name="VSS_1", electrical_type="power_in", group="Power"),
        PinDef(number="23", name="VSS_2", electrical_type="power_in", group="Power"),
        PinDef(number="35", name="VSS_3", electrical_type="power_in", group="Power"),
        PinDef(number="47", name="VSS_4", electrical_type="power_in", group="Power"),
        PinDef(number="9", name="VDD_1", electrical_type="power_in", group="Power"),
        PinDef(number="24", name="VDD_2", electrical_type="power_in", group="Power"),
        PinDef(number="36", name="VDD_3", electrical_type="power_in", group="Power"),
        PinDef(number="48", name="VDD_4", electrical_type="power_in", group="Power"),
        PinDef(number="13", name="VDDA", electrical_type="power_in", group="Power"),
        PinDef(number="12", name="VSSA", electrical_type="power_in", group="Power"),
    ])

    # System unit (reset, boot, clocks)
    pins.extend([
        PinDef(number="7", name="NRST", electrical_type="input", group="System"),
        PinDef(number="44", name="BOOT0", electrical_type="input", group="System"),
        PinDef(number="5", name="PH0/OSC_IN", electrical_type="input", group="System"),
        PinDef(number="6", name="PH1/OSC_OUT", electrical_type="output", group="System"),
    ])

    # Port A unit (PA0-PA15)
    pins.extend([
        PinDef(number="10", name="PA0", electrical_type="bidirectional", group="Port_A"),
        PinDef(number="11", name="PA1", electrical_type="bidirectional", group="Port_A"),
        PinDef(number="14", name="PA2", electrical_type="bidirectional", group="Port_A"),
        PinDef(number="15", name="PA3", electrical_type="bidirectional", group="Port_A"),
        PinDef(number="16", name="PA4", electrical_type="bidirectional", group="Port_A"),
        PinDef(number="17", name="PA5", electrical_type="bidirectional", group="Port_A"),
        PinDef(number="18", name="PA6", electrical_type="bidirectional", group="Port_A"),
        PinDef(number="19", name="PA7", electrical_type="bidirectional", group="Port_A"),
        PinDef(number="27", name="PA8", electrical_type="bidirectional", group="Port_A"),
        PinDef(number="28", name="PA9", electrical_type="bidirectional", group="Port_A"),
        PinDef(number="29", name="PA10", electrical_type="bidirectional", group="Port_A"),
        PinDef(number="30", name="PA11", electrical_type="bidirectional", group="Port_A"),
        PinDef(number="31", name="PA12", electrical_type="bidirectional", group="Port_A"),
        PinDef(number="32", name="PA13/SWDIO", electrical_type="bidirectional", group="Port_A"),
        PinDef(number="37", name="PA14/SWCLK", electrical_type="bidirectional", group="Port_A"),
        PinDef(number="38", name="PA15", electrical_type="bidirectional", group="Port_A"),
    ])

    # Port B unit (PB0-PB15, available on UFQFPN-48)
    pins.extend([
        PinDef(number="20", name="PB0", electrical_type="bidirectional", group="Port_B"),
        PinDef(number="21", name="PB1", electrical_type="bidirectional", group="Port_B"),
        PinDef(number="22", name="PB2/BOOT1", electrical_type="bidirectional", group="Port_B"),
        PinDef(number="39", name="PB3/SWO", electrical_type="bidirectional", group="Port_B"),
        PinDef(number="40", name="PB4", electrical_type="bidirectional", group="Port_B"),
        PinDef(number="41", name="PB5", electrical_type="bidirectional", group="Port_B"),
        PinDef(number="42", name="PB6", electrical_type="bidirectional", group="Port_B"),
        PinDef(number="43", name="PB7", electrical_type="bidirectional", group="Port_B"),
        PinDef(number="45", name="PB8", electrical_type="bidirectional", group="Port_B"),
        PinDef(number="46", name="PB9", electrical_type="bidirectional", group="Port_B"),
        PinDef(number="25", name="PB10", electrical_type="bidirectional", group="Port_B"),
        PinDef(number="26", name="PB12", electrical_type="bidirectional", group="Port_B"),
        PinDef(number="33", name="PB13", electrical_type="bidirectional", group="Port_B"),
        PinDef(number="34", name="PB14", electrical_type="bidirectional", group="Port_B"),
    ])

    # Port C unit (PC13-PC15 only on 48-pin package)
    pins.extend([
        PinDef(number="2", name="PC13", electrical_type="bidirectional", group="Port_C"),
        PinDef(number="3", name="PC14/OSC32_IN", electrical_type="bidirectional", group="Port_C"),
        PinDef(number="4", name="PC15/OSC32_OUT", electrical_type="bidirectional", group="Port_C"),
    ])

    return ChipDef(
        name="STM32F411CEU6",
        library="MCU_ST",
        description="ARM Cortex-M4 MCU, 512KB Flash, 128KB SRAM, 100MHz, UFQFPN-48",
        footprint="Package_QFP:UFQFPN-48-1EP_7x7mm_P0.5mm_EP5.6x5.6mm",
        datasheet_url="https://www.st.com/resource/en/datasheet/stm32f411ce.pdf",
        pins=pins,
    )


# ---------------------------------------------------------------------------
# NEO-6M GPS module (u-blox)
# ---------------------------------------------------------------------------
# Source: u-blox NEO-6 datasheet, commonly used GPS module in hobby projects

def neo_6m() -> ChipDef:
    """Return ChipDef for the u-blox NEO-6M GPS module.

    24 pins organized into Power, UART, SPI, I2C, Control, and RF units.
    """
    pins: list[PinDef] = []

    # Power unit
    pins.extend([
        PinDef(number="11", name="VCC", electrical_type="power_in", group="Power"),
        PinDef(number="1", name="GND", electrical_type="power_in", group="Power"),
        PinDef(number="12", name="GND", electrical_type="power_in", group="Power"),
        PinDef(number="22", name="V_BCKP", electrical_type="power_in", group="Power"),
    ])

    # UART unit
    pins.extend([
        PinDef(number="20", name="TXD", electrical_type="output", group="UART"),
        PinDef(number="21", name="RXD", electrical_type="input", group="UART"),
    ])

    # SPI unit
    pins.extend([
        PinDef(number="14", name="SPI_CS", electrical_type="input", group="SPI"),
        PinDef(number="15", name="SPI_CLK", electrical_type="input", group="SPI"),
        PinDef(number="16", name="SPI_MISO", electrical_type="output", group="SPI"),
        PinDef(number="17", name="SPI_MOSI", electrical_type="input", group="SPI"),
    ])

    # I2C unit (DDC = I2C in u-blox terminology)
    pins.extend([
        PinDef(number="18", name="SDA/DDC_SDA", electrical_type="bidirectional", group="I2C"),
        PinDef(number="19", name="SCL/DDC_SCL", electrical_type="input", group="I2C"),
    ])

    # Control unit
    pins.extend([
        PinDef(number="9", name="RESET_N", electrical_type="input", group="Control"),
        PinDef(number="10", name="EXTINT", electrical_type="input", group="Control"),
        PinDef(number="3", name="TIMEPULSE", electrical_type="output", group="Control"),
    ])

    # RF unit
    pins.extend([
        PinDef(number="2", name="RF_IN", electrical_type="input", group="RF"),
        PinDef(number="13", name="RF_GND", electrical_type="passive", group="RF"),
    ])

    # Reserved pins
    pins.extend([
        PinDef(number="4", name="RESERVED1", electrical_type="no_connect", group="Reserved"),
        PinDef(number="5", name="RESERVED2", electrical_type="no_connect", group="Reserved"),
        PinDef(number="6", name="RESERVED3", electrical_type="no_connect", group="Reserved"),
        PinDef(number="7", name="RESERVED4", electrical_type="no_connect", group="Reserved"),
        PinDef(number="8", name="RESERVED5", electrical_type="no_connect", group="Reserved"),
        PinDef(number="23", name="USB_DM", electrical_type="bidirectional", group="Reserved"),
        PinDef(number="24", name="USB_DP", electrical_type="bidirectional", group="Reserved"),
    ])

    return ChipDef(
        name="NEO-6M",
        library="GPS_Module",
        description="u-blox NEO-6M GPS/GNSS module",
        footprint="RF_GPS:ublox_NEO-6M",
        datasheet_url="https://www.u-blox.com/sites/default/files/products/documents/NEO-6_DataSheet_(GPS.G6-HW-09005).pdf",
        pins=pins,
    )


# ---------------------------------------------------------------------------
# Registry: maps lib_id fragments to chip definition functions
# ---------------------------------------------------------------------------

_CHIP_REGISTRY: dict[str, callable] = {
    "ESP32-S3-WROOM-1": esp32_s3_wroom_1,
    "STM32F411CEU6": stm32f411ceu6,
    "NEO-6M": neo_6m,
}


def lookup_chip(lib_id: str) -> ChipDef | None:
    """Look up a ChipDef by lib_id (e.g., 'RF_Module:ESP32-S3-WROOM-1').

    Matches against the part after the colon, or the full lib_id if no colon.
    Returns None if no matching chip definition exists.
    """
    # Extract the part name from "Library:PartName" format
    part_name = lib_id.split(":")[-1] if ":" in lib_id else lib_id

    factory = _CHIP_REGISTRY.get(part_name)
    if factory is not None:
        return factory()
    return None


def list_chips() -> list[str]:
    """Return all available chip names in the library."""
    return list(_CHIP_REGISTRY.keys())


def generate_lib_symbol_sexp(chip: ChipDef, lib_id: str) -> str:
    """Generate a KiCad lib_symbol S-expression string from a ChipDef.

    Produces the format expected by schematic_gen._get_lib_symbol_stub(),
    compatible with KiCad 9 (version 20250114).

    Args:
        chip: The chip definition with pin groups.
        lib_id: The full library ID (e.g., 'RF_Module:ESP32-S3-WROOM-1').

    Returns:
        A string containing the (symbol ...) S-expression.
    """
    safe_name = lib_id.replace('"', '\\"')
    ref_prefix = lib_id.split(":")[0][0] if ":" in lib_id else "U"
    # Most ICs use "U" reference
    if ref_prefix in ("R", "C", "L"):
        ref_prefix = "U"

    lines = [f'(symbol "{safe_name}"']
    lines.append('      (pin_names (offset 1.016))')
    lines.append('      (exclude_from_sim no)')
    lines.append('      (in_bom yes)')
    lines.append('      (on_board yes)')
    lines.append('      (property "Reference" "U" (at 0 1.27 0) (effects (font (size 1.27 1.27))))')
    lines.append(f'      (property "Value" "{safe_name}" (at 0 -1.27 0) (effects (font (size 1.27 1.27))))')
    lines.append(f'      (property "Footprint" "{chip.footprint}" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))')
    lines.append(f'      (property "Datasheet" "{chip.datasheet_url}" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))')
    if chip.description:
        lines.append(f'      (property "Description" "{chip.description}" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))')

    # Group pins by functional group
    groups: dict[str, list[PinDef]] = {}
    for pin in chip.pins:
        groups.setdefault(pin.group, []).append(pin)

    # Generate units: unit 0 has shared graphics, units 1+ have pins
    # For simplicity, generate a single-unit symbol (unit 1) like the stubs
    # OR multi-unit with one unit per group
    # Using single unit to match the stub format expected by _gen_component
    all_pins = chip.pins
    pin_count = len(all_pins)

    # Body size
    spacing = 2.54
    height = max((pin_count + 1) * spacing, 5.08)
    width = 15.24
    half_h = height / 2

    # Unit 0 (shared graphics): body rectangle
    lines.append(f'      (symbol "{safe_name}_0_1"')
    lines.append(f'        (rectangle (start -{width / 2} {half_h}) (end {width / 2} -{half_h})')
    lines.append('          (stroke (width 0.254) (type default)) (fill (type background))))')

    # Unit 1: all pins
    lines.append(f'      (symbol "{safe_name}_1_1"')
    start_y = half_h - spacing
    for i, pin_def in enumerate(all_pins):
        y = start_y - i * spacing
        x = -(width / 2) - 2.54  # pin length = 2.54mm
        pin_type = pin_def.electrical_type
        pin_name = pin_def.name.replace('"', '\\"')
        pin_num = str(pin_def.number)
        lines.append(
            f'        (pin {pin_type} line (at {x} {y} 0) (length 2.54)'
            f'\n          (name "{pin_name}" (effects (font (size 1.27 1.27))))'
            f'\n          (number "{pin_num}" (effects (font (size 1.27 1.27)))))'
        )
    lines.append('      )')  # close unit 1

    lines.append('      (embedded_fonts no))')

    return "\n".join(lines)
