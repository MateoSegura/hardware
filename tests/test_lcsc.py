"""Tests for LCSC datasheet downloader."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.lcsc import _CDN_PATTERN, download_datasheet, get_datasheet_url

# Known CDN URL for ESP32-S3-WROOM-1 (C2913200)
KNOWN_CDN_URL = (
    "https://datasheet.lcsc.com/lcsc/"
    "2411121101_ESPRESSIF-ESP32-S3-WROOM-1-N4R8_C2913200.pdf"
)


class TestGetDatasheetUrl:
    """Tests for get_datasheet_url()."""

    def test_cdn_pattern_matches_known_url(self):
        """The regex pattern matches a known LCSC CDN URL."""
        html = f'<a href="{KNOWN_CDN_URL}">Download</a>'
        match = _CDN_PATTERN.search(html)
        assert match is not None
        assert match.group(0) == KNOWN_CDN_URL

    def test_cdn_pattern_rejects_non_lcsc(self):
        """The regex does not match non-LCSC URLs."""
        html = '<a href="https://example.com/datasheet.pdf">Download</a>'
        assert _CDN_PATTERN.search(html) is None

    @patch("src.pipeline.lcsc.urlopen")
    def test_get_datasheet_url_extracts_from_html(self, mock_urlopen):
        """get_datasheet_url extracts the CDN link from product page HTML."""
        fake_html = f"""
        <html><body>
        <a href="{KNOWN_CDN_URL}" class="download">Datasheet</a>
        </body></html>
        """.encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_html
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        url = get_datasheet_url("C2913200")
        assert url == KNOWN_CDN_URL

    @patch("src.pipeline.lcsc.urlopen")
    def test_get_datasheet_url_returns_none_on_no_match(self, mock_urlopen):
        """get_datasheet_url returns None when no CDN link is found."""
        fake_html = b"<html><body>No datasheet here</body></html>"
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_html
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        url = get_datasheet_url("C0000000")
        assert url is None

    @patch("src.pipeline.lcsc.urlopen", side_effect=Exception("network error"))
    def test_get_datasheet_url_returns_none_on_error(self, mock_urlopen):
        """get_datasheet_url returns None on network errors."""
        assert get_datasheet_url("C2913200") is None


class TestDownloadDatasheet:
    """Tests for download_datasheet()."""

    @patch("src.pipeline.lcsc.get_datasheet_url", return_value=None)
    def test_download_returns_none_when_no_url(self, mock_get_url):
        """download_datasheet returns None when URL discovery fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download_datasheet("C0000000", Path(tmpdir))
            assert result is None

    @patch("src.pipeline.lcsc.subprocess.run")
    @patch("src.pipeline.lcsc.get_datasheet_url", return_value=KNOWN_CDN_URL)
    def test_download_creates_pdf_file(self, mock_get_url, mock_run):
        """download_datasheet writes a valid PDF to the output dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "2411121101_ESPRESSIF-ESP32-S3-WROOM-1-N4R8_C2913200.pdf"

            def fake_curl(*args, **kwargs):
                # Write a fake PDF file
                dest.write_bytes(b"%PDF-1.5 " + b"\x00" * 20_000)
                return subprocess.CompletedProcess(args=[], returncode=0)

            mock_run.side_effect = fake_curl

            result = download_datasheet("C2913200", Path(tmpdir))
            assert result is not None
            assert result.exists()
            assert result.stat().st_size > 10_000
            with open(result, "rb") as f:
                assert f.read(5) == b"%PDF-"

    @patch("src.pipeline.lcsc.subprocess.run")
    @patch("src.pipeline.lcsc.get_datasheet_url", return_value=KNOWN_CDN_URL)
    def test_download_rejects_tiny_files(self, mock_get_url, mock_run):
        """download_datasheet rejects files smaller than 10KB."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "2411121101_ESPRESSIF-ESP32-S3-WROOM-1-N4R8_C2913200.pdf"

            def fake_curl(*args, **kwargs):
                dest.write_bytes(b"%PDF-1.5 tiny")
                return subprocess.CompletedProcess(args=[], returncode=0)

            mock_run.side_effect = fake_curl

            result = download_datasheet("C2913200", Path(tmpdir))
            assert result is None
