"""Verify explicit HIL observer bindings without editing the installed core."""

import importlib.util
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "nrf52_hil_irq_observer", ROOT / "scripts/nrf52_hil_irq_observer.py")
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)

STARTUP = """    .section .rodata
    .balign 4
    .globl test_vectors
test_vectors:
    .long   SVC_Handler
    .long   PendSV_Handler
""" + "".join("    .long   " + symbol + "\n" for symbol in PATCH.IRQ_HANDLERS) + r"""
    .text
    .globl Default_Handler
Default_Handler:
    ret
    .macro IRQ handler
    .weak \handler
    .set \handler, Default_Handler
    .endm
""" + "".join("    IRQ  " + symbol + "\n" for symbol in PATCH.IRQ_HANDLERS) + """
    .section .note.GNU-stack,"",@progbits
"""
PORT = """/* Existing scheduler and exception definitions stay in their object. */
""" + PATCH.PORT_DECLARATION + "\n" + PATCH.PORT_DEFINITION + """
    __asm volatile
    (
    "   stmdb sp!, {r3}                     \\n"
    "   msr basepri, r0                     \\n"
""" + PATCH.PORT_CALL + """    "   msr basepri, r0                     \\n"
    "   ldmia sp!, {r3}                     \\n"
    "   bx r14                              \\n"
    );
}
"""


class Node:
    def __init__(self, path):
        self.path = path

    def srcnode(self):
        return self

    def get_abspath(self):
        return str(self.path)


class BuildEnv(dict):
    def __init__(self, build_dir, flags=(), defines=(), mcu="nrf52840", name="nordicnrf52"):
        super().__init__(BUILD_FLAGS=flags, CPPDEFINES=defines)
        self.build_dir = build_dir
        self.mcu = mcu
        self.name = name
        self.middleware = []

    def PioPlatform(self):
        return types.SimpleNamespace(name=self.name)

    def BoardConfig(self):
        return {"build.mcu": self.mcu}

    def AppendUnique(self, **kwargs):
        for name, values in kwargs.items():
            self.setdefault(name, [])
            self[name].extend(value for value in values if value not in self[name])

    def AddBuildMiddleware(self, callback, pattern):
        self.middleware.append((callback, pattern))

    def subst(self, value):
        if value == "$PROJECT_DIR":
            return str(ROOT)
        assert value == "$BUILD_DIR"
        return str(self.build_dir)

    def File(self, value):
        return Path(value)


class Nrf52HilIrqBindingTest(unittest.TestCase):
    def test_actual_scons_entry_without_file_uses_project_root(self):
        source = (ROOT / "scripts/nrf52_hil_irq_observer.py").read_text(encoding="ascii")
        with tempfile.TemporaryDirectory() as directory:
            for flag, expected in (("0", 0), ("1", 2)):
                env = BuildEnv(Path(directory), "-DMESH_HIL_IRQ_TIMING=" + flag)
                scope = {}
                scope["Import"] = lambda name: scope.update({name: env})
                exec(compile(source, "nrf52_hil_irq_observer.py", "exec"), scope)
                self.assertNotIn("__file__", scope)
                self.assertEqual(len(env.middleware), expected)

    def test_startup_changes_only_selected_vectors_and_preserves_all_real_aliases(self):
        patched = PATCH.patched_startup(STARTUP.replace("\n", "\r\n"))
        self.assertEqual(PATCH.patched_startup(patched), patched)
        expected = STARTUP
        for symbol in PATCH.IRQ_HANDLERS:
            expected = expected.replace("    .long   " + symbol + "\n",
                                        "    .long   __wrap_" + symbol + "\n")
            self.assertEqual(patched.count("    IRQ  " + symbol + "\n"), 1)
        self.assertEqual(patched, expected)
        for invalid in (
            STARTUP.replace(".long   RTC1_IRQHandler", ".word   RTC1_IRQHandler"),
            STARTUP.replace(".long   RTC1_IRQHandler", ".long   __wrap_RTC1_IRQHandler"),
            STARTUP + "    .long   RTC1_IRQHandler\n",
            STARTUP.replace("    IRQ  RTC1_IRQHandler\n", ""),
            patched.replace("    .long   SVC_Handler\n", "    .long   __wrap_SVC_Handler\n"),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                PATCH.patched_startup(invalid)

    def test_port_changes_only_c_call_target_in_existing_naked_assembly(self):
        patched = PATCH.patched_port(PORT.replace("\n", "\r\n"))
        self.assertEqual(patched.replace(PATCH.WRAPPED_PORT_CALL, PATCH.PORT_CALL), PORT)
        self.assertEqual(PATCH.patched_port(patched), patched)
        for invalid in (
            PORT.replace(PATCH.PORT_CALL, ""),
            PORT + PATCH.PORT_CALL,
            PORT + PATCH.WRAPPED_PORT_CALL,
            PORT.replace(PATCH.PORT_DECLARATION, ""),
            PORT.replace("/* This is a naked function. */", "/* Changed port. */"),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                PATCH.patched_port(invalid)

    def test_disabled_build_registers_no_hook_link_flag_or_private_copy(self):
        with tempfile.TemporaryDirectory(prefix="mesh-hil-irq-off-") as directory:
            for flags, defines in (((), ()), ("-DMESH_HIL_IRQ_TIMING=0", ()),
                                   ("-UMESH_HIL_IRQ_TIMING", (("MESH_HIL_IRQ_TIMING", 1),))):
                env = BuildEnv(Path(directory) / "build", flags, defines)
                PATCH.install(env)
                self.assertEqual(env.middleware, [])
                self.assertNotIn("LINKFLAGS", env)
                self.assertFalse(env.build_dir.exists())

    def test_enabled_build_uses_private_copies_and_wrapped_real_symbol_resolution(self):
        with tempfile.TemporaryDirectory(prefix="mesh-hil-irq-copy-") as directory:
            directory = Path(directory)
            env = BuildEnv(directory / "build", "-D MESH_HIL_IRQ_TIMING=1")
            PATCH.install(env)
            self.assertEqual(len(env.middleware), 2)
            self.assertEqual(env["LINKFLAGS"], ["-Wl,--wrap=" + name for name in PATCH.WRAPPED_SYMBOLS])
            for filename, text, replace, patch in (
                ("gcc_startup_nrf52840.S", STARTUP, PATCH.replace_startup, PATCH.patched_startup),
                ("port.c", PORT, PATCH.replace_port, PATCH.patched_port),
            ):
                sdk = directory / "shared-sdk" / filename
                sdk.parent.mkdir(exist_ok=True)
                sdk.write_text(text)
                private = replace(env, Node(sdk))
                self.assertTrue(private.is_relative_to(env.build_dir))
                self.assertEqual(private.read_text(), patch(text))
                self.assertEqual(sdk.read_text(), text)
                stamp = private.stat().st_mtime_ns
                self.assertEqual(replace(env, Node(sdk)).stat().st_mtime_ns, stamp)
                self.assertIn(str(sdk.parent), env["CPPPATH"])
            for mcu, name in (("nrf52832", "nordicnrf52"), ("nrf52840", "espressif32")):
                with self.subTest(mcu=mcu, name=name), self.assertRaises(RuntimeError):
                    PATCH.install(BuildEnv(directory, "-DMESH_HIL_IRQ_TIMING=1", mcu=mcu, name=name))
            with self.assertRaises(RuntimeError):
                PATCH.observer_enabled("-DMESH_HIL_IRQ_TIMING=2")
            self.assertTrue(PATCH.observer_enabled(cppdefines=(("MESH_HIL_IRQ_TIMING", 1),)))

    @unittest.skipUnless(shutil.which("c++") and platform.machine() == "x86_64",
                         "native x86_64 GNU toolchain unavailable")
    def test_real_weak_vector_bypasses_link_wrap_then_explicit_binding_observes_once(self):
        # The original same-object weak aliases reproduce the final-ELF failure.
        # Explicit vector targets must call each wrapper and each real handler
        # exactly once, including when the other C++ translation unit uses LTO.
        with tempfile.TemporaryDirectory(prefix="mesh-hil-irq-link-", dir="/var/tmp") as directory:
            directory = Path(directory)
            source = '#include <cassert>\n#include <cstdint>\n'
            source += 'extern "C" const uint32_t test_vectors[];\n'
            source += 'extern "C" void SVC_Handler() {}\nextern "C" void PendSV_Handler() {}\n'
            source += f"static unsigned real_calls[{len(PATCH.IRQ_HANDLERS)}], wrapped_calls[{len(PATCH.IRQ_HANDLERS)}];\n"
            for index, symbol in enumerate(PATCH.IRQ_HANDLERS):
                source += f'extern "C" void {symbol}() {{ ++real_calls[{index}]; }}\n'
                source += f'extern "C" void __real_{symbol}();\n'
                source += (f'extern "C" void __wrap_{symbol}() {{ ++wrapped_calls[{index}]; '
                           f'__real_{symbol}(); }}\n')
            source += f"int main() {{ for (unsigned i = 0; i < {len(PATCH.IRQ_HANDLERS)}; ++i) {{ "
            source += "reinterpret_cast<void(*)()>(uintptr_t(test_vectors[i+2]))(); "
            source += "assert(real_calls[i] == 1); assert(wrapped_calls[i] == EXPECT_WRAPPED); } }\n"
            (directory / "handlers.cpp").write_text(source)
            for patched in (False, True):
                with self.subTest(patched=patched):
                    (directory / "startup.S").write_text(PATCH.patched_startup(STARTUP) if patched else STARTUP)
                    binary = directory / "vectors"
                    built = subprocess.run([
                        "c++", "-std=c++17", "-O2", "-flto", "-fno-semantic-interposition", "-no-pie",
                        f"-DEXPECT_WRAPPED={int(patched)}", str(directory / "handlers.cpp"),
                        str(directory / "startup.S"),
                        *("-Wl,--wrap=" + name for name in PATCH.IRQ_HANDLERS), "-o", str(binary),
                    ], capture_output=True, text=True, cwd=directory)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    result = subprocess.run([str(binary)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_nrf52_base_installs_binding_hook_once(self):
        config = (ROOT / "platformio.ini").read_text()
        base = config.split("[nrf52_base]", 1)[1].split("\n[", 1)[0]
        self.assertEqual(base.count("pre:scripts/nrf52_hil_irq_observer.py"), 1)


if __name__ == "__main__":
    unittest.main()
