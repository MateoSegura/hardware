"""LCSC datasheet downloader.

Downloads component datasheets from LCSC's CDN. Works by:
1. Fetching the LCSC product page for a given part number
2. Extracting the datasheet CDN URL from the product page HTML
3. Downloading the actual PDF via curl (handles redirects better than urllib)

CDN pattern: https://datasheet.lcsc.com/lcsc/{date}_{manufacturer}-{part}_{lcsc_number}.pdf
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen


# LCSC product page URL template
_PRODUCT_URL = "https://www.lcsc.com/product-detail/{lcsc_number}.html"

# Pattern to find datasheet CDN URLs in page HTML
_CDN_PATTERN = re.compile(
    r'https?://datasheet\.lcsc\.com/lcsc/[^\s"\'<>]+\.pdf',
    re.IGNORECASE,
)

# Browser-like headers so LCSC doesn't reject us
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def get_datasheet_url(lcsc_number: str) -> str | None:
    """Get the CDN URL for a component's datasheet.

    Fetches the LCSC product page and extracts the datasheet download link
    matching the CDN pattern ``datasheet.lcsc.com/lcsc/...pdf``.

    Args:
        lcsc_number: LCSC part number, e.g. ``"C2913200"``.

    Returns:
        Full CDN URL string, or ``None`` if not found.
    """
    url = _PRODUCT_URL.format(lcsc_number=lcsc_number)
    req = Request(url, headers=_HEADERS)
    try:
        with urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    match = _CDN_PATTERN.search(html)
    if match:
        return match.group(0)

    # Sometimes the URL is percent-encoded or split across attributes —
    # try a looser search for the CDN domain and reconstruct.
    if "datasheet.lcsc.com" in html:
        # Pull all href/src values
        for attr_match in re.finditer(r'(?:href|src)=["\']([^"\']+)["\']', html):
            val = attr_match.group(1)
            if "datasheet.lcsc.com" in val and val.endswith(".pdf"):
                return val

    return None


def download_datasheet(lcsc_number: str, output_dir: Path) -> Path | None:
    """Download a datasheet PDF from LCSC CDN.

    Discovers the CDN URL via :func:`get_datasheet_url`, then downloads the
    PDF using ``curl`` (which handles LCSC redirects more reliably than
    Python's urllib).

    Args:
        lcsc_number: LCSC part number, e.g. ``"C2913200"``.
        output_dir: Directory to save the PDF into.

    Returns:
        Path to the downloaded PDF file, or ``None`` on failure.
    """
    cdn_url = get_datasheet_url(lcsc_number)
    if cdn_url is None:
        return None

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Derive a filename from the CDN URL
    filename = cdn_url.rsplit("/", 1)[-1]
    dest = output_dir / filename

    try:
        result = subprocess.run(
            [
                "curl", "-fsSL",
                "--max-time", "60",
                "-o", str(dest),
                "-H", f"User-Agent: {_HEADERS['User-Agent']}",
                cdn_url,
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        if result.returncode != 0:
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    # Sanity-check: must be a real PDF (>10 KB, starts with %PDF)
    if not dest.exists() or dest.stat().st_size < 10_000:
        dest.unlink(missing_ok=True)
        return None

    with open(dest, "rb") as f:
        magic = f.read(5)
    if magic != b"%PDF-":
        dest.unlink(missing_ok=True)
        return None

    return dest
