#!/usr/bin/env bash
# .devcontainer/ctl.sh — hardware dev container lifecycle management
#
# Host actions:   build | push | create | start
# Container actions (called by devcontainer.json):  post-create | post-start

set -euo pipefail

IMAGE="ghcr.io/mateosegura/dev-env-hardware:latest"
PLATFORM="linux/amd64"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

# ── helpers ───────────────────────────────────────────────────────────────────
info()  { echo "  [ctl] $*"; }
ok()    { echo "  [ctl] ✓ $*"; }
warn()  { echo "  [ctl] ! $*"; }
die()   { echo "  [ctl] ✗ $*" >&2; exit 1; }

usage() {
  cat <<EOF

  Usage: .devcontainer/ctl.sh <action>

  Host actions:
    build         Build the image locally (linux/amd64)
    push          Authenticate via .env token and push to ghcr.io
    create        Create and start the devcontainer
    start         Open a shell in the running container

  Container lifecycle (called by devcontainer.json):
    post-create   Verify toolchain, set up environment
    post-start    Authenticate gh and ghcr.io from GITHUB_TOKEN

  Setup:
    cp .devcontainer/.env.example .devcontainer/.env
    # Fill in GITHUB_TOKEN, then run: .devcontainer/ctl.sh create

EOF
  exit 1
}

_load_env() {
  if [ ! -f "${ENV_FILE}" ]; then
    die "Missing .env — run: cp .devcontainer/.env.example .devcontainer/.env"
  fi
  set -a
  # shellcheck source=/dev/null
  source "${ENV_FILE}"
  set +a
  [ -z "${GITHUB_TOKEN:-}" ] && die "GITHUB_TOKEN is empty in .env"
  [ -z "${IS_SANDBOX:-}" ]   && die "IS_SANDBOX is empty in .env (must be 1)"
}

# ── host actions ─────────────────────────────────────────────────────────────
cmd_build() {
  info "Building ${IMAGE} ..."
  docker build \
    --platform "${PLATFORM}" \
    --tag "${IMAGE}" \
    "${SCRIPT_DIR}"
  ok "Build complete — ${IMAGE}"
}

cmd_push() {
  _load_env
  info "Authenticating with ghcr.io ..."
  echo "${GITHUB_TOKEN}" | docker login ghcr.io -u MateoSegura --password-stdin
  info "Pushing ${IMAGE} ..."
  docker push "${IMAGE}"
  ok "Push complete — ${IMAGE}"
}

cmd_create() {
  command -v devcontainer > /dev/null 2>&1 \
    || die "devcontainer CLI not found — run: npm install -g @devcontainers/cli"
  _load_env
  info "Creating devcontainer ..."
  devcontainer up --workspace-folder "${REPO_ROOT}"
  ok "Devcontainer ready.  Run: .devcontainer/ctl.sh start"
}

cmd_start() {
  command -v devcontainer > /dev/null 2>&1 \
    || die "devcontainer CLI not found — run: npm install -g @devcontainers/cli"
  info "Opening shell ..."
  devcontainer exec --workspace-folder "${REPO_ROOT}" zsh
}

# ── container lifecycle actions ──────────────────────────────────────────────
cmd_post_create() {
  WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

  # ── Verify KiCad CLI ──────────────────────────────────────────────────────
  if command -v kicad-cli > /dev/null 2>&1; then
    ok "kicad-cli $(kicad-cli version 2>/dev/null || echo 'available')"
  else
    warn "kicad-cli not found — validation pipeline will not work"
  fi

  # ── Verify Python packages ────────────────────────────────────────────────
  python3 -c "import kiutils; print('kiutils OK')" 2>/dev/null && ok "kiutils available" || warn "kiutils not importable"
  python3 -c "import sexpdata; print('sexpdata OK')" 2>/dev/null && ok "sexpdata available" || warn "sexpdata not importable"

  # ── Claude Code settings ──────────────────────────────────────────────────
  CLAUDE_DIR="${HOME}/.claude"
  mkdir -p "${CLAUDE_DIR}"
  if [ ! -f "${CLAUDE_DIR}/settings.json" ]; then
    cat > "${CLAUDE_DIR}/settings.json" <<'CLAUDE_SETTINGS'
{
  "permissions": {
    "allow": [],
    "deny": []
  },
  "enableAgentTeams": true
}
CLAUDE_SETTINGS
    ok "Claude settings created with agent teams enabled"
  fi

  # ── Create data directories ───────────────────────────────────────────────
  mkdir -p "${WORKSPACE}/data/raw"
  mkdir -p "${WORKSPACE}/data/parsed"
  mkdir -p "${WORKSPACE}/data/patterns"
  mkdir -p "${WORKSPACE}/data/validated"
  ok "Data directories created"
}

cmd_post_start() {
  if [ -z "${GITHUB_TOKEN:-}" ]; then
    warn "GITHUB_TOKEN not set — skipping auth"
    exit 0
  fi

  if timeout 10 gh auth status 2>&1; then
    ok "gh authenticated (via GITHUB_TOKEN env)"
  else
    warn "gh auth status failed (non-fatal)"
  fi

  mkdir -p /root/.docker
  echo '{}' > /root/.docker/config.json

  if echo "${GITHUB_TOKEN}" | timeout 10 docker login ghcr.io -u MateoSegura --password-stdin 2>&1; then
    ok "ghcr.io authenticated"
  else
    warn "ghcr.io auth failed (non-fatal)"
  fi

  ok "Ready"
}

# ── dispatch ─────────────────────────────────────────────────────────────────
case "${1:-}" in
  build)        cmd_build       ;;
  push)         cmd_push        ;;
  create)       cmd_create      ;;
  start)        cmd_start       ;;
  post-create)  cmd_post_create ;;
  post-start)   cmd_post_start  ;;
  *)            usage           ;;
esac
