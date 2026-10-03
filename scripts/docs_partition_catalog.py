"""Publish the canonical partition catalog without keeping a second source copy."""

from pathlib import Path

from mkdocs.structure.files import File


CATALOG_URI = "_data/esp32_partition_catalog.json"


def on_files(files, config):
    source = (
        Path(config.config_file_path).resolve().parent
        / "firmware" / "esp32_partition_catalog.json"
    )
    if not source.is_file():
        raise FileNotFoundError(f"Canonical partition catalog is missing: {source}")
    files.append(File.generated(config, CATALOG_URI, abs_src_path=str(source)))
    return files
