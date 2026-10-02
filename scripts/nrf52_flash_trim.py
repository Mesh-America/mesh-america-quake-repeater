"""Feature-preserving flash trim for nRF52 infrastructure, never Companions.

Decide from the effective source filter as well as the environment/OTA alias
and flags: build.sh can synthesize profiles over another PlatformIO recipe.
Unknown roles fail closed. No shared framework or downloaded library is edited.
CDC, USB host, sensor/GPS support, BLE P-256, and stored Ed25519 keys remain.
The compact Ed25519 implementation trades more signing time/stack for flash;
the nRF52 base keeps an 8 KiB loop stack for this and the existing OTA path.
"""

import fnmatch
import hashlib
import importlib.util
import re
import shlex
from pathlib import Path


ROLE_SOURCES = (
    "../examples/simple_repeater/main.cpp",
    "../examples/simple_room_server/main.cpp",
    "../examples/simple_sensor/main.cpp",
    "../examples/kiss_modem/main.cpp",
)
COMPANION_SOURCES = (
    "../examples/companion_radio/MyMesh.cpp",
    "../examples/simple_secure_chat/main.cpp",
)
TRIM_DEFINES = {
    "MESH_NRF52_FLASH_TRIM": 1,
    "ED25519_COMPACT_BASE": 1,
    "ED25519_COMPACT_SHA512": 1,
    # No infrastructure role instantiates these USB *device* classes. Do not
    # touch CDC (including dual CDC logging), DFU, or the MAX3421 USB host.
    "CFG_TUD_MSC": 0,
    "CFG_TUD_HID": 0,
    "CFG_TUD_MIDI": 0,
    "CFG_TUD_VENDOR": 0,
    "CFG_TUD_VIDEO": 0,
    "CFG_TUD_VIDEO_STREAMING": 0,
    # MeshCore uses UBX navigation, not SparkFun's automatic NMEA cache. This
    # does not disable navigation, the UBX parser, or MeshCore NMEA logging.
    "SFE_UBLOX_DISABLE_AUTO_NMEA": 1,
    "SFE_UBLOX_REDUCED_PROG_MEM": 1,
    # SSD1306Display clears the vendor splash before its first panel transfer.
    # Keep MeshCore's own startup logo; only omit the invisible library bitmap.
    "SSD1306_NO_SPLASH": 1,
}
CC310_ARCHIVE_SHA256 = "97dc648d44520e47252f62c402a71f976e36d7b3aef99235bbdc4de79a928577"
CC310_ARCHIVE = "src/cortex-m4/fpv4-sp-d16-hard/libnrf_cc310_0.9.13-no-interrupts.a"


def flag_defines(flags=(), cppdefines=()):
    """Read effective defines without importing PlatformIO/SCons for tests."""
    values = {}
    for define in cppdefines:
        if isinstance(define, (tuple, list)):
            values[str(define[0])] = str(define[1]) if len(define) > 1 else "1"
        else:
            values[str(define)] = "1"
    text = flags if isinstance(flags, str) else " ".join(map(str, flags))
    words = shlex.split(text)
    index = 0
    while index < len(words):
        word = words[index]
        if word in ("-D", "-U"):
            index += 1
            word += words[index] if index < len(words) else ""
        if word.startswith("-D"):
            name, _, value = word[2:].partition("=")
            values[name] = value if "=" in word else "1"
        elif word.startswith("-U"):
            values[word[2:]] = None
        index += 1
    return values


def _enabled(value):
    return value is not None and str(value).strip("\"'() ") not in ("", "0")


def source_selected(src_filter, source):
    """Resolve ordered includes/excludes for the explicit outside-src roles."""
    text = src_filter if isinstance(src_filter, str) else " ".join(map(str, src_filter))
    selected = False
    for sign, pattern in re.findall(r"([+-])<([^>]+)>", text.replace("\\", "/")):
        # +<*.cpp> and +<*> scan PROJECT_SRC_DIR, not ../examples. They do
        # not imply that any example role is part of the image.
        if source.startswith("../examples/") and "examples/" not in pattern:
            continue
        pattern = pattern.rstrip("/")
        if fnmatch.fnmatchcase(source, pattern) or source.startswith(pattern + "/"):
            selected = sign == "+"
    return selected


def trim_policy(platform, mcu, env_name, src_filter, flags=(), cppdefines=(),
                ota_name_mode="front-coded"):
    """Return defaults for a qualified non-Companion role, otherwise nothing.

    The name policy is explicit so the profile can use a different verified
    representation later without changing role selection or hardware trims.
    """
    if platform != "nordicnrf52" or not str(mcu).lower().startswith("nrf52"):
        return {}
    values = flag_defines(flags, cppdefines)
    names = (str(env_name), str(values.get("OTA_VARIANT", "")))
    if any(any(tag in name.lower() for tag in (
            "companion", "comp_radio", "terminal_chat", "term_chat", "terminal-chat", "secure_chat")) for name in names):
        return {}
    if any(_enabled(value) for name, value in values.items()
           if name.startswith("COMPANION_")):
        return {}
    if any(source_selected(src_filter, source) for source in COMPANION_SOURCES):
        return {}
    if not any(source_selected(src_filter, source) for source in ROLE_SOURCES):
        return {}
    if "MESH_NRF52_FLASH_TRIM" in values and not _enabled(values["MESH_NRF52_FLASH_TRIM"]):
        return {}
    if ota_name_mode != "front-coded":
        raise ValueError("unsupported nRF52 OTA name trim policy: " + ota_name_mode)
    definitions = dict(TRIM_DEFINES, OTA_TARGET_NAME_FRONT_CODED=1)
    # Explicit board/user flags retain their value. In particular never undo
    # an opt-out or a board-specific USB configuration by re-defining it.
    return {name: value for name, value in definitions.items() if name not in values}


def supported_cc310(framework_dir, mcu, defines):
    """Only wrap the exact inspected archive; future SDKs retain their getter."""
    if str(mcu).lower() != "nrf52840" or not _enabled(defines.get("USE_CC310_HW_CRYPTO")):
        return False
    archive = Path(framework_dir) / "libraries/Adafruit_nRFCrypto" / CC310_ARCHIVE
    return archive.is_file() and hashlib.sha256(archive.read_bytes()).hexdigest() == CC310_ARCHIVE_SHA256


def trim_tft_library(build_env, node):
    # PlatformIO invokes this on TFT_eSPI's library builder, which is already
    # a private clone. Do not add a global forced include to the project: its
    # User_Setup defines are not appropriate for unrelated sources. The
    # matching ST7735Display translation unit includes this header directly.
    if not build_env.get("MESH_NRF52_TFT_FONT_TRIM_APPLIED", False):
        build_env["MESH_NRF52_TFT_FONT_TRIM_APPLIED"] = True
        build_env.Append(CCFLAGS=[
            "-include", build_env.subst("$PROJECT_DIR/src/helpers/ui/Nrf52TftFontTrim.h"),
        ])
    return node


def install(build_env):
    platform = build_env.PioPlatform()
    mcu = build_env.BoardConfig().get("build.mcu", "")
    flags = build_env.get("BUILD_FLAGS", ())
    cppdefines = build_env.get("CPPDEFINES", ())
    definitions = trim_policy(platform.name, mcu, build_env["PIOENV"],
                              build_env.get("SRC_FILTER", ()), flags, cppdefines)
    if not definitions:
        return
    build_env["MESH_NRF52_FLASH_TRIM_ACTIVE"] = True
    build_env.AppendUnique(CPPDEFINES=list(definitions.items()))
    print("nRF52 infrastructure flash trim: compact crypto, unused USB device classes/GPS cache/vendor splash, compact OTA target names")
    framework = platform.get_package_dir("framework-arduinoadafruitnrf52")
    values = flag_defines(flags, cppdefines)
    if values.get("ST7789") is not None:
        # Keep the font license with this qualified display build, including
        # cached DFU packages. The hook independently checks the effective
        # font override and excludes every Companion transport/profile.
        hook_path = build_env.subst("$PROJECT_DIR/scripts/package_nrf52_font_license.py")
        hook_spec = importlib.util.spec_from_file_location("mesh_nrf52_font_license", hook_path)
        font_license = importlib.util.module_from_spec(hook_spec)
        hook_spec.loader.exec_module(font_license)
        font_license.install(build_env)
    if (values.get("DISPLAY_CLASS") == "ST7735Display"
            and source_selected(build_env.get("SRC_FILTER", ()), "helpers/ui/ST7735Display.cpp")):
        build_env.AddBuildMiddleware(trim_tft_library, "*TFT_eSPI*/*.cpp")
    if framework and supported_cc310(framework, mcu, values):
        build_env.AppendUnique(LINKFLAGS=["-Wl,--wrap=CRYS_ECPKI_GetEcDomain"])
        build_env.AppendUnique(CPPPATH=[str(Path(framework) / "libraries/Adafruit_nRFCrypto/src/nrf_cc310/include")])
        # BuildSources is called on this selected nRF52 environment only. The
        # wrapper is not in the common source filter and cannot leak to other
        # platforms or an excluded Companion role.
        build_env.BuildSources("$BUILD_DIR/nrf52-flash-trim",
                               "$PROJECT_DIR/src/helpers/nrf52",
                               "+<Cc310DomainTrim.c>")
    else:
        print("nRF52 CC310 trim: unsupported/unused SDK; ordinary domain lookup retained")


if "Import" in globals():
    Import("env")
    install(env)
