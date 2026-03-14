#!/usr/bin/env bash
set -euo pipefail

# Bulk clone KiCad project candidates using sparse checkout.
#
# Usage:
#   bash scripts/clone_candidates.sh [--count N] [--offset N] [--dry-run]
#
# Reads data/candidates.json and clones the top N repos (default 100)
# into data/raw/ using sparse checkout to only fetch KiCad-relevant files.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CANDIDATES="$PROJECT_ROOT/data/candidates.json"
RAW_DIR="$PROJECT_ROOT/data/raw"

COUNT=100
OFFSET=0
DRY_RUN=false
SLEEP_SECONDS=2

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --count)
            COUNT="$2"
            shift 2
            ;;
        --offset)
            OFFSET="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --sleep)
            SLEEP_SECONDS="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [--count N] [--offset N] [--sleep N] [--dry-run]"
            echo ""
            echo "Options:"
            echo "  --count N    Number of repos to clone (default: 100)"
            echo "  --offset N   Skip first N candidates (default: 0)"
            echo "  --sleep N    Seconds between clones (default: 2)"
            echo "  --dry-run    Show what would be cloned without cloning"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

if [[ ! -f "$CANDIDATES" ]]; then
    echo "Error: candidates.json not found at $CANDIDATES" >&2
    echo "Run: python3 scripts/filter_repos.py" >&2
    exit 1
fi

# Check jq is available
if ! command -v jq &>/dev/null; then
    echo "Error: jq is required but not installed" >&2
    exit 1
fi

mkdir -p "$RAW_DIR"

# Extract repos from candidates.json
TOTAL=$(jq 'length' "$CANDIDATES")
END=$((OFFSET + COUNT))
if [[ $END -gt $TOTAL ]]; then
    END=$TOTAL
fi

echo "Candidates file: $CANDIDATES"
echo "Total candidates: $TOTAL"
echo "Cloning repos $OFFSET to $((END - 1)) ($((END - OFFSET)) repos)"
echo "Output directory: $RAW_DIR"
echo "Rate limit: ${SLEEP_SECONDS}s between clones"
echo ""

SUCCESS=0
SKIPPED=0
FAILED=0

for i in $(seq "$OFFSET" "$((END - 1))"); do
    FULL_NAME=$(jq -r ".[$i].full_name" "$CANDIDATES")
    URL=$(jq -r ".[$i].html_url" "$CANDIDATES")
    STARS=$(jq -r ".[$i].stars" "$CANDIDATES")

    # Convert owner/repo to owner__repo
    OWNER=$(echo "$FULL_NAME" | cut -d'/' -f1)
    REPO=$(echo "$FULL_NAME" | cut -d'/' -f2)
    DIR_NAME="${OWNER}__${REPO}"
    DEST="$RAW_DIR/$DIR_NAME"

    # Skip if already exists
    if [[ -d "$DEST" ]]; then
        echo "[$((i + 1))/$END] SKIP (exists): $FULL_NAME"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    if [[ "$DRY_RUN" == true ]]; then
        echo "[$((i + 1))/$END] DRY-RUN: $FULL_NAME (${STARS} stars) -> $DIR_NAME"
        continue
    fi

    echo "[$((i + 1))/$END] Cloning: $FULL_NAME (${STARS} stars)..."

    # Clone with sparse checkout
    if git clone --depth 1 --filter=blob:none --sparse \
        "$URL" "$DEST" 2>/dev/null; then

        # Set sparse checkout patterns for KiCad files
        (
            cd "$DEST"
            git sparse-checkout set --no-cone \
                '*.kicad_pro' '*.kicad_sch' '*.kicad_pcb' \
                '*.kicad_sym' '*.kicad_mod' \
                'sym-lib-table' 'fp-lib-table' \
                '*BOM*' '*bom*' '*.csv' \
                'README*' 'LICENSE*' \
                2>/dev/null
        )

        SUCCESS=$((SUCCESS + 1))
        echo "  -> OK: $DEST"
    else
        FAILED=$((FAILED + 1))
        echo "  -> FAILED: $FULL_NAME"
        # Clean up partial clone
        rm -rf "$DEST" 2>/dev/null || true
    fi

    # Rate limiting
    if [[ $i -lt $((END - 1)) ]]; then
        sleep "$SLEEP_SECONDS"
    fi
done

echo ""
echo "Done. Success: $SUCCESS, Skipped: $SKIPPED, Failed: $FAILED"
