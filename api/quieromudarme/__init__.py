"""QuieroMudarme package."""

from importlib import metadata

try:
    # Get installed version for this package
    __version__ = metadata.version(__name__)
except metadata.PackageNotFoundError:
    # package is not installed
    __version__ = "0.0.0"
