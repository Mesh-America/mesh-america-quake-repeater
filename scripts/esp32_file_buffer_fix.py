"""Reject unhonored stdio buffer sizes in the pinned Arduino-ESP32 FS copy.

Newlib can return success after falling back to a larger allocation. Keep the
shared framework intact and make File::setBufferSize fail before caller I/O.
"""
import hashlib
from pathlib import Path
import re


PINNED_VFS_SHA256 = "db3eb3fef8e59c0bafd01416ea18e2d5f36f38a9b180cd415ff3563a59fcfb65"
PATCHED_VFS_SHA256 = "e6d5a27af0fceb3ee937e95c42eb8341c0c0c762e4cbf9cf54fd522c8eba8d60"
SOURCE_SUFFIX = ("libraries", "FS", "src", "vfs_api.cpp")
INCLUDE = '#include "vfs_api.h"\n'
LAYOUT_GUARD = '''
// MeshCore strict buffer admission for pinned Arduino 2.0.17/newlib 3.3.0.
// This check deliberately fails compilation if the reviewed FILE ABI changes.
#include <newlib.h>
#include <stddef.h>
#include <type_traits>
#if __NEWLIB__ != 3 || __NEWLIB_MINOR__ != 3 || __NEWLIB_PATCHLEVEL__ != 0
#error "MeshCore FS buffer fix: changed pinned newlib; review FILE layout"
#endif
static_assert(sizeof(void*) == 4 && offsetof(FILE, _bf) == 16
              && offsetof(__sbuf, _size) == 4,
              "MeshCore FS buffer fix: changed pinned FILE layout");
static_assert(std::is_same<decltype(((FILE*)nullptr)->_bf._size), int>::value,
              "MeshCore FS buffer fix: changed pinned buffer-size type");
'''
ORIGINAL_METHOD = '''bool VFSFileImpl::setBufferSize(size_t size)
{
    if(_isDirectory || !_f) {
        return 0;
    }
    int res = setvbuf(_f,NULL,_IOFBF,size);
    return res == 0;
}'''
STRICT_METHOD = ORIGINAL_METHOD.replace(
    "    return res == 0;",
    '''    // A successful newlib fallback may have selected a larger buffer.
    // Preserve size==0's public choose-default behavior; bounded callers use
    // nonzero sizes and must not start I/O unless their request was honored.
    return res == 0 && (size == 0 || (_f->_bf._size > 0
        && static_cast<size_t>(_f->_bf._size) == size));''')


def patched_vfs_source(source):
    source = source.replace("\r\n", "\n")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if digest == PATCHED_VFS_SHA256:
        return source
    if (digest != PINNED_VFS_SHA256 or source.count(INCLUDE) != 1
            or source.count(ORIGINAL_METHOD) != 1):
        raise RuntimeError("ESP32 FS buffer fix: changed pinned2.0.17 source; review SDK update")
    patched = source.replace(INCLUDE, INCLUDE + LAYOUT_GUARD, 1).replace(
        ORIGINAL_METHOD, STRICT_METHOD, 1)
    if hashlib.sha256(patched.encode("utf-8")).hexdigest() != PATCHED_VFS_SHA256:
        raise RuntimeError("ESP32 FS buffer fix: unexpected transform result")
    return patched


def esp32_enabled(build_env):
    # USB mode is intentionally irrelevant: UART V3 uses the same FS wrapper.
    defines = {}
    for definition in build_env.get("CPPDEFINES", []):
        if isinstance(definition, (tuple, list)):
            defines[str(definition[0])] = str(definition[1])
        else:
            defines[str(definition)] = "1"
    return any(defines.get(name) not in (None, "0")
               for name in ("ESP32_PLATFORM", "ESP32"))


def require_pinned_framework(source):
    version = source.parents[3] / "cores" / "esp32" / "esp_arduino_version.h"
    try:
        header = version.read_text(encoding="utf-8")
    except OSError as error:
        raise RuntimeError("ESP32 FS buffer fix: missing framework version header") from error
    entries = re.findall(r"^#define ESP_ARDUINO_VERSION_(MAJOR|MINOR|PATCH)\s+(\d+)\s*$",
                         header, re.MULTILINE)
    if (len(entries) != 3 or dict(entries) != {"MAJOR": "2", "MINOR": "0", "PATCH": "17"}):
        raise RuntimeError("ESP32 FS buffer fix: changed/malformed pinned framework version")


def replace_vfs_source(build_env, node):
    if not esp32_enabled(build_env):
        return node
    source = Path(node.srcnode().get_abspath())
    if source.parts[-4:] != SOURCE_SUFFIX:
        return node
    require_pinned_framework(source)
    patched = patched_vfs_source(source.read_text(encoding="utf-8"))
    destination = Path(build_env.subst("$BUILD_DIR")) / "patched-esp32-fs" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or destination.read_text(encoding="utf-8") != patched:
        destination.write_text(patched, encoding="utf-8")
    # The copied source still includes the original FS library's private header.
    build_env.AppendUnique(CPPPATH=[str(source.parent)])
    return build_env.File(str(destination))


def install(build_env):
    build_env.AddBuildMiddleware(replace_vfs_source, "*libraries*FS*src*vfs_api.cpp")


if "Import" in globals():
    Import("env")
    install(env)
