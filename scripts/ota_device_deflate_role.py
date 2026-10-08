"""Enable bounded on-device OTA encoding only for qualified infrastructure.

Inspect the EFFECTIVE ordered source filter, never the environment name. This
pre-script contributes one shared compiler definition, so the C encoder and all
C++ OTA translation units agree. A custom recipe that omits this hook keeps
OtaDeflateConfig.h's fail-closed default. Companions keep host-precompressed OTA.
"""

import importlib.util
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent if "__file__" in globals() else Path("scripts").resolve()
SPEC = importlib.util.spec_from_file_location(
    "ota_device_deflate_source_policy", SCRIPT_DIR / "nrf52_flash_trim.py")
SOURCE_POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOURCE_POLICY)

DEFINITION = "MESHCORE_OTA_DEVICE_DEFLATE"
ROLE_SOURCES = (
    "../examples/simple_repeater/main.cpp",
    "../examples/simple_room_server/main.cpp",
    "../examples/simple_sensor/main.cpp",
)
EXCLUDED_SOURCES = (
    "../examples/companion_radio/main.cpp",
    "../examples/companion_radio/MyMesh.cpp",
    "../examples/simple_secure_chat/main.cpp",
    "../examples/kiss_modem/main.cpp",
    "../examples/partition_expander/main.cpp",
    "../examples/esp32_partition_migrator/main.cpp",
    "../examples/esp32_partition_legacy_seed/main.cpp",
)


def enabled(values, name):
    value = values.get(name)
    return value is not None and str(value).strip("\"'() ") not in ("", "0")


def bool_override(value):
    # -U leaves the header's default zero and is an explicit opt-out as well.
    if value is None:
        return 0
    text = str(value).strip("\"'() ")
    if text not in ("0", "1"):
        raise ValueError(DEFINITION + " override must be 0 or 1")
    return int(text)


def role_policy(platform, mcu, src_filter, flags=(), cppdefines=()):
    """Return a common define or reject an unsafe explicit enable override."""
    values = SOURCE_POLICY.flag_defines(flags, cppdefines)
    selected = SOURCE_POLICY.source_selected
    known_roles = sum(selected(src_filter, source) for source in ROLE_SOURCES)
    excluded = any(selected(src_filter, source) for source in EXCLUDED_SOURCES)
    seeder = values.get("OTA_SEEDER_ONLY") is not None
    companion = any(enabled(values, name) for name in values
                    if name.startswith("COMPANION_"))
    ota_enabled = enabled(values, "ENABLE_OTA") and not enabled(values, "DISABLE_LORA_OTA")
    esp32 = (platform == "espressif32" and str(mcu).lower().startswith("esp32")
             and enabled(values, "ESP32_PLATFORM"))
    nrf52 = (platform == "nordicnrf52" and str(mcu).lower().startswith("nrf52")
             and enabled(values, "NRF52_PLATFORM")
             and any(enabled(values, store)
                     for store in ("OTA_QSPI_STORE", "OTA_SD_STORE", "OTA_RAK_AUTO_STORE")))
    qualified = (known_roles == 1 and not excluded and not seeder and not companion
                 and ota_enabled and (esp32 or nrf52))
    if DEFINITION in values:
        override = bool_override(values[DEFINITION])
        if override and not qualified:
            raise ValueError(DEFINITION + "=1 requires an OTA infrastructure source role "
                             "and eligible ESP32/external-nRF52 storage")
        return {}  # Preserve an explicit valid definition/opt-out without duplicates.
    return {DEFINITION: 1} if qualified else {}


def install(build_env):
    platform = build_env.PioPlatform().name
    mcu = build_env.BoardConfig().get("build.mcu", "")
    src_filter = build_env.get("SRC_FILTER")
    if src_filter is None:
        src_filter = build_env.GetProjectOption("build_src_filter", "")
    definitions = role_policy(platform, mcu, src_filter,
                              build_env.get("BUILD_FLAGS", ()),
                              build_env.get("CPPDEFINES", ()))
    if definitions:
        build_env.AppendUnique(CPPDEFINES=list(definitions.items()))
        print("Device OTA DEFLATE: qualified infrastructure role; bounded per-block encoder")


if "Import" in globals():
    Import("env")
    install(env)
