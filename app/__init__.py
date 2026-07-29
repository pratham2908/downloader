"""Reel — YouTube downloader package.

Ensure a CA bundle is available for TLS. Some Python installs (notably fresh
Homebrew/venv setups on macOS) ship without system CA certs, which makes
yt-dlp fail with CERTIFICATE_VERIFY_FAILED. Pointing SSL_CERT_FILE at certifi's
bundle fixes it transparently.
"""
import os

try:  # pragma: no cover - environment dependent
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("SSL_CERT_DIR", os.path.dirname(certifi.where()))
except Exception:  # noqa: BLE001
    pass
