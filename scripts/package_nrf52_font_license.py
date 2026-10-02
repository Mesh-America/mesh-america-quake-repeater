"""Carry the production bitmap-font OFL notice alongside affected firmware.

Only the qualified nRF52 infrastructure/ST7789 font mode 9 installs this hook.
The DFU manifest and all application/init-packet entries stay byte-identical;
the extra text entry is not selected by Nordic/Adafruit DFU loaders. UF2 files
are unchanged and travel with an identically named .font-license.txt sidecar.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
from zipfile import BadZipFile, ZIP_STORED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
NOTICE_PATH = ROOT / "licenses/MeshNotoCondensed-OFL.txt"
NOTICE_ENTRY = "FONT-LICENSE.txt"
SIDECAR_SUFFIX = ".font-license.txt"


def notice_bytes():
    # Explicit UTF-8/LF also makes ZIP contents identical on Windows and Linux.
    return NOTICE_PATH.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")


def _defines(flags=(), cppdefines=()):
    """Read effective -D/-U values without requiring PlatformIO in host tests."""
    values = {}
    for define in cppdefines:
        if isinstance(define, (tuple, list)):
            values[str(define[0])] = str(define[1]) if len(define) > 1 else "1"
        else:
            name, separator, value = str(define).partition("=")
            values[name] = value if separator else "1"
    words = shlex.split(flags if isinstance(flags, str) else " ".join(map(str, flags)))
    index = 0
    while index < len(words):
        word = words[index]
        if word in ("-D", "-U"):
            index += 1
            word += words[index] if index < len(words) else ""
        if word.startswith("-D"):
            name, separator, value = word[2:].partition("=")
            values[name] = value if separator else "1"
        elif word.startswith("-U"):
            values[word[2:]] = None
        index += 1
    return values


def _enabled(value):
    return value is not None and str(value).strip("\"'() ") not in ("", "0")


def qualifies(build_env):
    """Match Nrf52FontConfig.h after the infrastructure trim policy qualifies."""
    if not build_env.get("MESH_NRF52_FLASH_TRIM_ACTIVE", False):
        return False
    values = _defines(build_env.get("BUILD_FLAGS", ()), build_env.get("CPPDEFINES", ()))
    if (values.get("NRF52_PLATFORM") is None or values.get("ST7789") is None
            or not _enabled(values.get("MESH_NRF52_FLASH_TRIM"))
            or values.get("COMPANION_RADIO_FULL") is not None):
        return False
    names = (str(build_env.get("PIOENV", "")), str(values.get("OTA_VARIANT", "")))
    if any(any(tag in name.lower() for tag in (
            "companion", "comp_radio", "terminal_chat", "term_chat", "terminal-chat", "secure_chat"))
           for name in names):
        return False
    if any(_enabled(value) for name, value in values.items() if name.startswith("COMPANION_")):
        return False
    mode = values.get("MESH_ARIAL_EXPERIMENT")
    if mode is None:
        mode = values.get("MESH_NRF52_FONT_MODE")
    if mode is None:
        mode = "9"
    try:
        return int(str(mode).strip("\"'() "), 0) == 9
    except ValueError:
        return False  # Unknown/expression overrides must not claim this font.


def package_notice(package):
    """Return the canonical notice, or None for an unaffected DFU package."""
    with ZipFile(package) as archive:
        notices = [info for info in archive.infolist() if info.filename == NOTICE_ENTRY]
        if not notices:
            return None
        if len(notices) != 1 or archive.read(notices[0]) != notice_bytes():
            raise ValueError(f"{package}: unexpected or duplicate font-license entry")
        return archive.read(notices[0])


def _check_existing(path, data):
    if path.exists() and (not path.is_file() or path.read_bytes() != data):
        raise ValueError(f"{path}: refusing to overwrite a different existing font notice")


def _write_new_or_identical(path, data):
    _check_existing(path, data)
    if not path.exists():
        # Never replace an unrelated file, and preserve mtimes on cached builds.
        with path.open("xb") as stream:
            stream.write(data)


def package_font_license(package, sidecar=None):
    """Append one fixed, deterministic text entry; never regenerate DFU data."""
    package = Path(package)
    sidecar = Path(sidecar) if sidecar is not None else package.with_suffix(SIDECAR_SUFFIX)
    data = notice_bytes()
    _check_existing(sidecar, data)
    existing = package_notice(package)
    with ZipFile(package) as archive:
        # Ensure this is an application DFU package before touching anything.
        manifest = json.loads(archive.read("manifest.json"))
        application = manifest["manifest"]["application"]
        for key in ("bin_file", "dat_file"):
            selected = application[key]
            if sum(info.filename == selected for info in archive.infolist()) != 1:
                raise ValueError(f"{package}: invalid DFU application entry {selected}")
        if archive.testzip() is not None:
            raise ValueError(f"{package}: corrupt DFU package")
    if existing is None:
        entry = ZipInfo(NOTICE_ENTRY, date_time=(1980, 1, 1, 0, 0, 0))
        entry.compress_type = ZIP_STORED
        entry.create_system = 3
        entry.external_attr = 0o100644 << 16
        with ZipFile(package, "a") as archive:
            archive.writestr(entry, data)
    _write_new_or_identical(sidecar, data)
    return sidecar


def _sidecar(stem):
    stem = Path(stem)
    return stem.parent / (stem.name + SIDECAR_SUFFIX)


def validate_artifact_notice(stem):
    """Require the notice alongside licensed ZIP/UF2 pairs before hashing."""
    stem = Path(stem)
    package = stem.parent / (stem.name + ".zip")
    sidecar = _sidecar(stem)
    data = package_notice(package) if package.is_file() else None
    if data is None:
        if sidecar.exists():
            raise ValueError(f"{stem}: font sidecar without a licensed DFU package")
        return None
    if not sidecar.is_file() or sidecar.read_bytes() != data:
        raise ValueError(f"{stem}: missing or mismatched font-license sidecar")
    return sidecar


def collect_build_notice(directory, stem):
    """Copy only a notice proved by this build's ZIP, never a stale sidecar."""
    directory = Path(directory)
    package = directory / "firmware.zip"
    data = package_notice(package) if package.is_file() else None
    output = _sidecar(stem)
    if data is None:
        # A prior mode-9 build may leave its source sidecar when opting out.
        # Ignore it; do not delete it or accidentally publish it for mode 0.
        if output.exists():
            raise ValueError(f"{output}: stale output notice for an unaffected build")
        return None
    build_notice = directory / ("firmware" + SIDECAR_SUFFIX)
    if not build_notice.is_file() or build_notice.read_bytes() != data:
        raise ValueError(f"{build_notice}: missing or mismatched build font notice")
    _write_new_or_identical(output, data)
    return output


def install(build_env):
    """Install after nrf52_flash_trim.install has appended effective defines."""
    if not qualifies(build_env) or build_env.get("MESH_NRF52_FONT_LICENSE_INSTALLED", False):
        return False
    build_env["MESH_NRF52_FONT_LICENSE_INSTALLED"] = True
    package = "$BUILD_DIR/${PROGNAME}.zip"
    build_env.Depends(package, [str(NOTICE_PATH), str(Path(__file__).resolve())])

    def attach_notice(source, target, env):
        # buildprog is deliberately idempotent: a cached ZIP still needs its
        # sidecar validated/emitted. Its alias depends on the ZIP builder.
        package_font_license(env.subst(package), env.subst("$BUILD_DIR/${PROGNAME}" + SIDECAR_SUFFIX))

    build_env.AddPostAction(package, attach_notice)
    build_env.AddPostAction("buildprog", attach_notice)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("collect", "validate"))
    parser.add_argument("path", type=Path)
    parser.add_argument("--stem", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "collect":
            if args.stem is None:
                parser.error("collect requires --stem")
            collect_build_notice(args.path, args.stem)
        else:
            validate_artifact_notice(args.path)
    except (OSError, ValueError, KeyError, BadZipFile) as error:
        parser.exit(1, f"Firmware font notice qualification failed: {error}\n")


if __name__ == "__main__":
    main()
