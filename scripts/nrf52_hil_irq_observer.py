"""Bind the optional HIL IRQ observer in private nRF52840 framework copies.

The framework's same-object weak vector aliases and its LTO-visible scheduler
call bypass GNU --wrap. Only for MESH_HIL_IRQ_TIMING=1, name the wrappers at
those eight call sites explicitly. Keep each real handler, SVC/PendSV vector,
and the naked port's register/exception-return sequence unchanged. The linker
wrap options still resolve the observer's __real_* calls to the real handlers.
No installed framework source is modified.
"""

import importlib.util
from pathlib import Path


IRQ_HANDLERS = (
    "POWER_CLOCK_IRQHandler", "UARTE0_UART0_IRQHandler", "GPIOTE_IRQHandler",
    "RTC1_IRQHandler", "USBD_IRQHandler", "UARTE1_IRQHandler",
    "SPIM0_SPIS0_TWIM0_TWIS0_SPI0_TWI0_IRQHandler",
)
WRAPPED_SYMBOLS = IRQ_HANDLERS + ("vTaskSwitchContext",)
PORT_CALL = '    "   bl vTaskSwitchContext               \\n"\n'
WRAPPED_PORT_CALL = PORT_CALL.replace("bl vTaskSwitchContext", "bl __wrap_vTaskSwitchContext")
PORT_DECLARATION = "void xPortPendSVHandler( void ) __attribute__ (( naked ));"
PORT_DEFINITION = "void xPortPendSVHandler( void )\n{\n    /* This is a naked function. */"


def _error(part):
    return RuntimeError(
        "nRF52 HIL IRQ observer: unrecognized " + part + "; review the pinned "
        "framework before building (shared SDK not modified)")


def patched_startup(source):
    source = source.replace("\r\n", "\n")
    pairs = [("    .long   " + symbol + "\n",
              "    .long   __wrap_" + symbol + "\n") for symbol in IRQ_HANDLERS]
    # Fail closed on partial patches, duplicate entries, or changed weak aliases.
    for symbol in IRQ_HANDLERS:
        if source.count("    IRQ  " + symbol + "\n") != 1:
            raise _error("startup weak IRQ aliases")
    for symbol in ("SVC_Handler", "PendSV_Handler"):
        if source.count("    .long   " + symbol + "\n") != 1:
            raise _error("startup exception vectors")
    original = all(source.count(old) == 1 and new not in source for old, new in pairs)
    patched = all(source.count(new) == 1 and old not in source for old, new in pairs)
    if not original and not patched:
        raise _error("startup IRQ vector entries")
    for old, new in pairs:
        source = source.replace(old, new)
    return source


def patched_port(source):
    source = source.replace("\r\n", "\n")
    if (source.count(PORT_DECLARATION) != 1 or source.count(PORT_DEFINITION) != 1):
        raise _error("GCC naked PendSV definition")
    if source.count(WRAPPED_PORT_CALL) == 1 and PORT_CALL not in source:
        return source
    if source.count(PORT_CALL) != 1 or WRAPPED_PORT_CALL in source:
        raise _error("GCC PendSV scheduler call")
    return source.replace(PORT_CALL, WRAPPED_PORT_CALL)


def _private_copy(build_env, node, patch, relative):
    source = Path(node.srcnode().get_abspath())
    patched = patch(source.read_text(encoding="utf-8"))
    destination = Path(build_env.subst("$BUILD_DIR")) / "patched-nrf52-hil-irqs" / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or destination.read_text(encoding="utf-8") != patched:
        destination.write_text(patched, encoding="utf-8")
    # Preserve any quoted, source-relative includes after relocation.
    build_env.AppendUnique(CPPPATH=[str(source.parent)])
    return build_env.File(str(destination))


def replace_startup(build_env, node):
    return _private_copy(build_env, node, patched_startup, "gcc_startup_nrf52840.S")


def replace_port(build_env, node):
    return _private_copy(build_env, node, patched_port, "port.c")


def observer_enabled(flags=(), cppdefines=(), parser_path=None):
    # Reuse the repository's effective -D/-U parser, including split -D values.
    if parser_path is None:
        parser_path = Path(__file__).with_name("nrf52_flash_trim.py")
    spec = importlib.util.spec_from_file_location(
        "mesh_nrf52_flash_trim_irq_flags", parser_path)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    values = parser.flag_defines(flags, cppdefines)
    value = values.get("MESH_HIL_IRQ_TIMING")
    if value is None:
        return False
    value = str(value).strip("() ")
    if value not in ("0", "1"):
        raise RuntimeError("nRF52 HIL IRQ observer flag must be 0 or 1")
    return value == "1"


def install(build_env):
    # SCons executes extra scripts without defining __file__.
    parser_path = Path(build_env.subst("$PROJECT_DIR")) / "scripts/nrf52_flash_trim.py"
    if not observer_enabled(build_env.get("BUILD_FLAGS", ()), build_env.get("CPPDEFINES", ()), parser_path):
        return
    if (build_env.PioPlatform().name != "nordicnrf52"
            or build_env.BoardConfig().get("build.mcu", "").lower() != "nrf52840"):
        raise RuntimeError("nRF52 HIL IRQ observer binding requires the pinned nRF52840 core")
    build_env.AppendUnique(LINKFLAGS=["-Wl,--wrap=" + name for name in WRAPPED_SYMBOLS])
    build_env.AddBuildMiddleware(replace_startup, "*cores*nRF5*linker*gcc_startup_nrf52840.S")
    build_env.AddBuildMiddleware(replace_port, "*cores*nRF5*freertos*portable*GCC*nrf52*port.c")


if "Import" in globals():
    Import("env")
    install(env)
