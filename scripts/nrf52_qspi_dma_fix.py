"""Align reviewed CustomLFS QSPI buffers in private build copies.

The nRF52840 QSPI driver rejects non-word-aligned EasyDMA addresses. uint8_t
static arrays only guarantee byte alignment; unrelated code/layout changes
can silently break mounting. Retain all three original pools and their size,
allocation lifetime, callbacks and filesystem behavior. Never edit libdeps.
"""
import hashlib
from pathlib import Path

SOURCE_SHA256 = 'b36b21e52480d1c4e56a235d0d9e3d72c4f2141a9d6c46e1781d64dc08180540'
PATCHED_SHA256 = '1d68cf61699e3988c59d9c7e87efb5479caf5391a847bab6c0e502b5593e35dd'
HEADERS = {
    'CustomLFS_QSPIFlash.h': '941596581f9f745b546e60e77e5738548b891d38f1a2830160a50646d6cf7486',
    'CustomLFS.h': '65a2efcf699d6069dd68fd4f19b856a9e0573bda61fa3fc20568951b8d31f52d',
}
ORIGINAL_BUFFERS = '''  static uint8_t read_buffer[256];
  static uint8_t prog_buffer[256];
  static uint8_t lookahead_buffer[32];'''
PATCHED_BUFFERS = '''  // QSPI EasyDMA and the LittleFS word bitmap require word alignment.
  alignas(uint32_t) static uint8_t read_buffer[256];
  alignas(uint32_t) static uint8_t prog_buffer[256];
  alignas(uint32_t) static uint8_t lookahead_buffer[32];'''


def digest(source):
    return hashlib.sha256(source.encode('ascii')).hexdigest()


def patched_source(source):
    source = source.replace('\r\n', '\n')
    fingerprint = digest(source)
    if fingerprint == PATCHED_SHA256:
        return source
    if fingerprint != SOURCE_SHA256 or source.count(ORIGINAL_BUFFERS) != 1:
        raise RuntimeError('nRF52 QSPI DMA fix: changed reviewed CustomLFS source; review dependency update')
    result = source.replace(ORIGINAL_BUFFERS, PATCHED_BUFFERS, 1)
    if digest(result) != PATCHED_SHA256:
        raise RuntimeError('nRF52 QSPI DMA fix: unexpected transform result')
    return result


def write_if_changed(path, content):
    if not path.exists() or path.read_text(encoding='ascii') != content:
        path.write_text(content, encoding='ascii')


def replace_qspi_source(build_env, node):
    source = Path(node.srcnode().get_abspath())
    if source.name != 'CustomLFS_QSPIFlash.cpp' or source.parent.name != 'src':
        return node
    patched = patched_source(source.read_text(encoding='ascii'))
    headers = {}
    for name, expected in HEADERS.items():
        try:
            header = (source.parent / name).read_text(encoding='ascii').replace('\r\n', '\n')
        except (OSError, UnicodeError) as error:
            raise RuntimeError('nRF52 QSPI DMA fix: missing reviewed header') from error
        if digest(header) != expected:
            raise RuntimeError('nRF52 QSPI DMA fix: changed reviewed header; review dependency update')
        headers[name] = header
    destination = Path(build_env.subst('$BUILD_DIR')) / 'patched-nrf52-qspi' / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Quoted includes bind both headers to this reviewed dependency version.
    for name, header in headers.items():
        write_if_changed(destination.parent / name, header)
    write_if_changed(destination, patched)
    return build_env.File(str(destination))


def install(build_env):
    build_env.AddBuildMiddleware(replace_qspi_source, '*CustomLFS_QSPIFlash.cpp')


if 'Import' in globals():
    Import('env')
    install(env)
