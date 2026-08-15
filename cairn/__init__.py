"""Cairn — a shared ledger for AI-assisted mathematical research."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("cairn-mcp")
except PackageNotFoundError:  # running from a checkout, not an install
    __version__ = "0.3.0"
