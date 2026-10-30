"""Compile only the selected small STM32WL Companion help producer as C++17.

All source selection and object overrides are reused without installing any
nRF52 trim, changing a global language standard or changing feature defines.
The C++ producer itself checks the final platform and terminal capabilities.
"""

import importlib.util
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent if "__file__" in globals() else Path("scripts").resolve()
SPEC = importlib.util.spec_from_file_location("stm32_help_source_policy", SCRIPT_DIR / "nrf52_flash_trim.py")
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)
COMPANION_SOURCES = ("../examples/companion_radio/main.cpp",
                     "../examples/companion_radio/MyMesh.cpp")


def packed_help_policy(platform, mcu, src_filter):
    if platform != "ststm32" or not str(mcu).lower().startswith("stm32wl"):
        return False
    return (all(POLICY.source_selected(src_filter, source) for source in COMPANION_SOURCES)
            and not any(POLICY.source_selected(src_filter, source)
                        for source in POLICY.ROLE_SOURCES + POLICY.COMPANION_SOURCES[1:]))


def install(build_env):
    source_filter = build_env.get("SRC_FILTER")
    if source_filter is None:
        source_filter = build_env.GetProjectOption("build_src_filter", "")
    if packed_help_policy(build_env.PioPlatform().name,
                          build_env.BoardConfig().get("build.mcu", ""), source_filter):
        build_env.AddBuildMiddleware(POLICY.compile_packed_help, "*CompanionHelpPacked.cpp")


if "Import" in globals():
    Import("env")
    install(env)
