"""Make the nRF52 core's loop task use the configured stack even under LTO.

GNU --wrap only redirects undefined references. The pinned core and FreeRTOS
share an LTO graph, so its xTaskCreate call can bind directly to the real
function and silently retain the framework's 4 KiB stack. Explicitly route
only the core loop-task call through MeshCore's existing stack policy in a
private build copy. Never edit the shared framework package.
"""

from pathlib import Path


OLD_LOOP_CREATE = '  xTaskCreate(loop_task, "loop", LOOP_STACK_SZ, NULL, TASK_PRIO_LOW, &_loopHandle);'
LOOP_CREATE = OLD_LOOP_CREATE.replace("xTaskCreate(", "__wrap_xTaskCreate(", 1)
DECLARATION = """extern "C" BaseType_t __wrap_xTaskCreate(
    TaskFunction_t task_code, const char* const task_name,
    const configSTACK_DEPTH_TYPE stack_depth, void* const parameters,
    UBaseType_t priority, TaskHandle_t* const created_task);

"""
LOOP_STACK = "#define LOOP_STACK_SZ       (256*4)"


def patched_source(source):
    source = source.replace("\r\n", "\n")
    if (source.count(LOOP_CREATE) == 1 and source.count(DECLARATION) == 1
            and OLD_LOOP_CREATE not in source and source.count(LOOP_STACK) == 1):
        return source
    if (source.count(OLD_LOOP_CREATE) != 1 or source.count(LOOP_STACK) != 1
            or LOOP_CREATE in source or DECLARATION in source):
        raise RuntimeError(
            "nRF52 loop stack fix: unrecognized core task creation; review the "
            "framework update before building (shared SDK not modified)"
        )
    return source.replace(LOOP_STACK, DECLARATION + LOOP_STACK).replace(
        OLD_LOOP_CREATE, LOOP_CREATE)


def replace_core(build_env, node):
    source = Path(node.srcnode().get_abspath())
    patched = patched_source(source.read_text(encoding="utf-8"))
    destination = Path(build_env.subst("$BUILD_DIR")) / "patched-nrf52-core" / "main.cpp"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or destination.read_text(encoding="utf-8") != patched:
        destination.write_text(patched, encoding="utf-8")
    print("nRF52 loop stack: explicit LTO-safe core task policy enabled")
    return build_env.File(str(destination))


def install(build_env):
    build_env.AddBuildMiddleware(replace_core, "*cores*nRF5*main.cpp")


if "Import" in globals():
    Import("env")
    install(env)
