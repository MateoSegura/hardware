#!/usr/bin/env bash
# scripts/clone_pilots.sh — Clone the 10 pilot KiCad projects
#
# Usage: bash scripts/clone_pilots.sh [data_dir]
#   data_dir defaults to ./data/raw

set -euo pipefail

DATA_DIR="${1:-./data/raw}"
mkdir -p "${DATA_DIR}"

info()  { echo "  [clone] $*"; }
ok()    { echo "  [clone] ✓ $*"; }
fail()  { echo "  [clone] ✗ $*" >&2; }

clone_sparse() {
  local url="$1"
  local name="$2"
  local target="${DATA_DIR}/${name}"

  if [ -d "${target}" ]; then
    ok "${name} (already exists)"
    return
  fi

  info "Cloning ${name} ..."
  if git clone --depth 1 --filter=blob:none --sparse "${url}" "${target}" 2>/dev/null; then
    cd "${target}"
    git sparse-checkout set --no-cone \
      '*.kicad_pro' '*.kicad_sch' '*.kicad_pcb' \
      '*.kicad_sym' '*.kicad_mod' \
      'sym-lib-table' 'fp-lib-table' \
      '*BOM*' '*bom*' '*.csv' \
      'README*' 'LICENSE*'
    cd - > /dev/null
    ok "${name}"
  else
    fail "${name} — clone failed"
  fi
}

# ── Pilot project list (10 designs) ──────────────────────────────────────────

# 1. Antmicro Jetson Nano baseboard — professional hierarchical design
clone_sparse "https://github.com/antmicro/jetson-nano-baseboard.git" \
  "antmicro__jetson-nano-baseboard"

# 2. MNT Reform — full laptop, DDR routing, multi-board
clone_sparse "https://source.mnt.re/reform/reform.git" \
  "mnt__reform"

# 3. HackRF One — RF design, controlled impedance, NXP LPC4320
clone_sparse "https://github.com/greatscottgadgets/hackrf.git" \
  "greatscottgadgets__hackrf"

# 4. VESC — STM32F4 + gate drivers, current sense, CAN
clone_sparse "https://github.com/vedderb/bldc-hardware.git" \
  "vedderb__bldc-hardware"

# 5. Crazyflie — STM32F4 + nRF51 + BMI088 IMU + barometer
clone_sparse "https://github.com/bitcraze/crazyflie2-pcb.git" \
  "bitcraze__crazyflie2-pcb"

# 6. Cicada-GSM-HW — STM32 + SIM7600 4G modem, production-ready
clone_sparse "https://github.com/EnAccess/Cicada-GSM-HW.git" \
  "enaccess__cicada-gsm-hw"

# 7. STM32F7 Flight Controller — ICM-42688-P IMU
clone_sparse "https://github.com/rishikesh2715/STM32F7_FC.git" \
  "rishikesh2715__stm32f7-fc"

# 8. tokay-lite-pcb — ESP32-S3 + OV2640 camera
clone_sparse "https://github.com/maxlab-io/tokay-lite-pcb.git" \
  "maxlab-io__tokay-lite-pcb"

# 9. LibreSolar MPPT-2420 — STM32G4 + DCDC, CAN, current sensing
clone_sparse "https://github.com/LibreSolar/mppt-2420-lc.git" \
  "libresolar__mppt-2420-lc"

# 10. nrfmicro — nRF52840 BLE, USB-C, LiPo
clone_sparse "https://github.com/joric/nrfmicro.git" \
  "joric__nrfmicro"

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
info "Pilot projects cloned to ${DATA_DIR}/"
ls -1 "${DATA_DIR}/" | while read -r dir; do
  count=$(find "${DATA_DIR}/${dir}" -name "*.kicad_sch" -o -name "*.kicad_pcb" 2>/dev/null | wc -l)
  echo "  ${dir}: ${count} KiCad files"
done
