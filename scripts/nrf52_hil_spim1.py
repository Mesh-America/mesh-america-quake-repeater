"""Bind a default-off Tag/Tower radio experiment to SPIM1 in private copies.

Global SPI keeps the board's existing initialization, recovery, and shutdown
ownership. SPI1 remains on SPIM2 for SD/display. The nrfx configuration must be
identical in every C/C++ translation unit, so force it before driver headers.
Never modify the installed framework and fail closed on a framework update.
"""

import hashlib
import importlib.util
from pathlib import Path


FLAG = "MC_NRF52_HIL_SPIM1_RADIO"
SDK_FILES = {
    "cores/nRF5/nordic/nrfx_config.h": "36c2e96f77a7a1b872f6ace9d880d5c7b5525f45f2498e21feb414d1ca589ff9",
    "libraries/SPI/SPI.cpp": "8ab92597c833c3351c0f4a5c8c07a84290815f95cf35b60c58209cab368accfb",
}
OLD_MAPPING = "  #define _SPI_DEV    NRF_SPIM3 // 32 Mhz\n  #define _SPI1_DEV   NRF_SPIM2\n"
NEW_MAPPING = "  #define _SPI_DEV    NRF_SPIM1 // Private Tag/Tower radio HIL candidate\n  #define _SPI1_DEV   NRF_SPIM2\n"
OLD_INCLUDE = '#include "SPI.h"\n'
NEW_INCLUDE = OLD_INCLUDE + '#include <helpers/nrf52/Nrf52HilSpim1Owner.h>\n'


def digest(source):
    return hashlib.sha256(source.replace("\r\n", "\n").encode("ascii")).hexdigest()


def patched_spi(source):
    source = source.replace("\r\n", "\n")
    if digest(source) != SDK_FILES["libraries/SPI/SPI.cpp"]:
        raise RuntimeError("nRF52 HIL SPIM1: changed pinned SPI.cpp; review before building")
    if source.count(OLD_MAPPING) != 1 or source.count(OLD_INCLUDE) != 1:
        raise RuntimeError("nRF52 HIL SPIM1: unrecognized global SPI binding")
    return source.replace(OLD_MAPPING, NEW_MAPPING, 1).replace(OLD_INCLUDE, NEW_INCLUDE, 1)


def values_for(build_env):
    parser_path = Path(build_env.subst("$PROJECT_DIR")) / "scripts/nrf52_flash_trim.py"
    spec = importlib.util.spec_from_file_location("mesh_spim1_flag_parser", parser_path)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    return parser.flag_defines(build_env.get("BUILD_FLAGS", ()), build_env.get("CPPDEFINES", ()))


def enabled(values):
    value = values.get(FLAG)
    if value is None:
        return False
    if str(value).strip("() ") not in ("0", "1"):
        raise RuntimeError("nRF52 HIL SPIM1 radio flag must be 0 or 1")
    return str(value).strip("() ") == "1"


def replace_spi(build_env, node):
    source = Path(node.srcnode().get_abspath())
    if source.name != "SPI.cpp" or source.parent.name != "SPI":
        raise RuntimeError("nRF52 HIL SPIM1: unexpected SPI middleware source")
    patched = patched_spi(source.read_text(encoding="ascii"))
    destination = Path(build_env.subst("$BUILD_DIR")) / "patched-nrf52-hil-spim1/SPI.cpp"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or destination.read_text(encoding="ascii") != patched:
        destination.write_text(patched, encoding="ascii")
    build_env.AppendUnique(CPPPATH=[str(source.parent), build_env.subst("$PROJECT_DIR/src")])
    return build_env.File(str(destination))


def install(build_env):
    values = values_for(build_env)
    if not enabled(values):
        return
    if (build_env.PioPlatform().name != "nordicnrf52"
            or build_env.BoardConfig().get("build.mcu", "").lower() != "nrf52840"):
        raise RuntimeError("nRF52 HIL SPIM1 requires the pinned nRF52840 core")
    boards = [name for name in ("RAK_WISMESH_TAG", "HELTEC_TOWER_V2") if values.get(name) is not None]
    if len(boards) != 1:
        raise RuntimeError("nRF52 HIL SPIM1 supports only RAK WisMesh Tag or MeshTower V2")
    if any(values.get(name) is not None for name in ("ETHERNET_ENABLED", "ENV_PIN_SDA", "ENV_PIN_SCL")):
        raise RuntimeError("nRF52 HIL SPIM1 has an unreviewed Ethernet or secondary I2C owner")
    framework = build_env.PioPlatform().get_package_dir("framework-arduinoadafruitnrf52")
    if not framework:
        raise RuntimeError("nRF52 HIL SPIM1 cannot find the pinned framework")
    for name, expected in SDK_FILES.items():
        source = Path(framework) / name
        if digest(source.read_text(encoding="ascii")) != expected:
            raise RuntimeError("nRF52 HIL SPIM1: changed pinned " + name + "; review before building")
    build_env.AppendUnique(CPPDEFINES=[("MC_NRF52_HIL_SPIM1_BOUND", 1)])
    # Keep the option and argument in one token: another pre-script adds its
    # own -include pair with AppendUnique, which deduplicates bare options.
    build_env.AppendUnique(CCFLAGS=["-include" + build_env.subst("$PROJECT_DIR/src/helpers/nrf52/Nrf52HilSpim1Config.h")])
    build_env.AddBuildMiddleware(replace_spi, "*libraries*SPI*SPI.cpp")


if "Import" in globals():
    Import("env")
    install(env)
