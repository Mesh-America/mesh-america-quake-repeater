"""Run the production management wrapper and reporter on existing host boundaries."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

from test_replay_reset_integration import extract_braced


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/management"


class ManagementCliWrapperTests(unittest.TestCase):
    def test_unavailable_password_wipe_allocation_failure_and_routing(self):
        candidates = [Path(os.environ.get("MESHCORE_CRYPTO_DIR", "/nonexistent"))]
        candidates += sorted((ROOT / ".pio/libdeps").glob("*/Crypto"))
        crypto = next((path for path in candidates if (path / "AES128.cpp").is_file()), None)
        if crypto is None:
            raise RuntimeError("Install rweather/Crypto 0.4.0 or set MESHCORE_CRYPTO_DIR (no mock fallback)")
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            self.skipTest("a host C++17 compiler is required")
        source = (ROOT / "src/helpers/CommonCLI_Management.cpp").read_text(encoding="ascii")
        wrapper = extract_braced(source, "bool CommonCLI::handleManagementCommand(")
        # Keep existing hardware/route fixtures, adding only the member surface
        # needed to run the actual wrapper with the actual production reporter.
        header = (FIXTURE / "CommonCLI.h").read_text(encoding="ascii")
        header = header.replace("class CommonCLI {", "class SensorManager;\nclass ClientACL;\nclass CommonCLICallbacks;\nclass CommonCLI {", 1)
        header = header.replace("public:\n  uint8_t path_len", """public:
  mesh::ManagementReporter* _management = nullptr;
  mesh::Mesh* _management_mesh = nullptr;
  FILESYSTEM* _management_fs = nullptr;
  mesh::MainBoard* _board = nullptr;
  SensorManager* _sensors = nullptr;
  ClientACL* _acl = nullptr;
  NodePrefs* _prefs = nullptr;
  CommonCLICallbacks* _callbacks = nullptr;
  std::vector<std::string> data_commands;
  bool handleManagementCommand(char* command, char* reply);
  bool handleDataTxCommand(char* command, char* reply);
  uint8_t path_len""", 1)
        header = header.replace("#include <vector>", "#include <vector>\n#include <string>\nnamespace mesh { class ManagementReporter; }")
        sources = ["AES128.cpp", "AESCommon.cpp", "BlockCipher.cpp", "Crypto.cpp", "SHA256.cpp", "Hash.cpp"]
        sanitizer_flags = [] if os.name == "nt" else [
            "-DHOST_BUILD", "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie"]
        with tempfile.TemporaryDirectory(prefix="management-wrapper-") as directory:
            work = Path(directory)
            for name in ("ManagementReporter.cpp", "ManagementReporter.h", "FileRead.h",
                         "ContactFileTransaction.h", "PersistentStoreFormat.h"):
                shutil.copyfile(ROOT / "src/helpers" / name, work / name)
            shutil.copyfile(FIXTURE / "Mesh.h", work / "Mesh.h")
            shutil.copyfile(FIXTURE / "wrapper_test.cpp", work / "wrapper_test.cpp")
            shutil.copyfile(ROOT / "test/fixtures/radio_profiles/mocks/helpers/IdentityStore.h", work / "IdentityStore.h")
            (work / "CommonCLI.h").write_text(header, encoding="ascii")
            (work / "production_wrapper.inc").write_text(wrapper, encoding="ascii")
            parser = "namespace mesh {\n" + "\n".join(
                extract_braced(source, signature) for signature in (
                    "static uint8_t nibble(", "static char* trimDataRoute(",
                    "static bool parseDataPath(")) + "\n}\n"
            (work / "production_path_parser.inc").write_text(parser, encoding="ascii")
            executable = work / "wrapper-test"
            command = [compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-DRP2040_PLATFORM",
                       *sanitizer_flags, "-I", directory, "-I", str(crypto),
                       "-I", str(ROOT / "src/helpers"), "-I", str(ROOT / "src"),
                       str(work / "ManagementReporter.cpp"), str(ROOT / "src/helpers/ManagementReport.cpp"),
                       str(work / "wrapper_test.cpp")]
            command += [str(crypto / name) for name in sources] + ["-o", str(executable)]
            built = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stderr)
            tested = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
            self.assertEqual(tested.returncode, 0, tested.stderr)


if __name__ == "__main__":
    unittest.main()
