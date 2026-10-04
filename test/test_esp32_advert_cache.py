#!/usr/bin/env python3
"""Exercise production ESP advert jobs and their MyMesh route under sanitizers."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_t096_full_memory import method

ROOT = Path(__file__).resolve().parents[1]


class AdvertCacheTest(unittest.TestCase):
    def test_inline_contacts(self):
        self.run_fixture(0)

    def test_cached_contacts(self):
        self.run_fixture(1)

    def test_synchronous_received_advert_is_detected(self):
        self.run_fixture(0, synchronous=True)

    def run_fixture(self, cache, synchronous=False):
        source = (ROOT / 'examples/companion_radio/DataStore.cpp').read_text()
        header = (ROOT / 'examples/companion_radio/DataStore.h').read_text()
        start = header.index('  struct AdvertWriteState {')
        end = header.index('\n#endif', start)
        state = header[start:end]
        signatures = ('static File openWrite(', 'inline void makeBlobPath(', 'bool DataStore::queueAdvertByKey(',
                      'void DataStore::retireAdvertWrite(', 'void DataStore::invalidateAdvertWrite(',
                      'bool DataStore::consumeSynchronousAdvertIO(',
                      'bool DataStore::hasPendingAdvertWrites() const',
                      'bool DataStore::isAdvertWriteDue(', 'bool DataStore::serviceAdvertWrites(',
                      'bool DataStore::flushAdvertWrites(', 'void DataStore::begin()',
                      'bool DataStore::formatFileSystem()')
        # ESP/non-LittleFS blob methods follow the final makeBlobPath helper.
        blob_source = source[source.rindex('inline void makeBlobPath('):]
        implementation = '\n'.join(method(source, s) for s in signatures)
        implementation += '\n' + '\n'.join(method(blob_source, s) for s in (
            'uint8_t DataStore::getBlobByKey(', 'bool DataStore::putBlobByKey(',
            'bool DataStore::deleteBlobByKey('))
        presence = method(source, 'static bool companionPathPresence(').replace(
            '::stat(vfs_path, &info)', 'fixtureStat(fs, vfs_path, &info)')
        mesh_header = (ROOT / 'examples/companion_radio/MyMesh.h').read_text()
        route = method(mesh_header, '  bool putBlobByKey(').replace(' override', '')
        route = route.replace('bool putBlobByKey(', 'bool MyMesh::putBlobByKey(', 1)
        if synchronous:
            route = route.replace('_store->queueAdvertByKey(', '_store->putBlobByKey(')
        mesh_source = (ROOT / 'examples/companion_radio/MyMesh.cpp').read_text()
        scheduling = method(mesh_source, 'void MyMesh::servicePersistence()')
        flush = method(mesh_source, 'bool MyMesh::flushContactsBeforeReboot()')
        work = method(mesh_source, 'bool MyMesh::hasPendingWork() const')
        recovery = method(mesh_source, 'bool MyMesh::canRecoverUsbLogging() const')
        # The entire production scheduling body runs below. This order check
        # additionally pins its call site after either serial dispatch route.
        loop = method(mesh_source, 'void MyMesh::loop()')
        self.assertLess(loop.index('checkSerialInterface();'), loop.index('servicePersistence();'))
        self.assertLess(loop.index('checkCLIRescueCmd();'), loop.index('servicePersistence();'))
        with tempfile.TemporaryDirectory(prefix='mesh-advert-jobs-') as directory:
            temp = Path(directory)
            (temp / 'advert_state.h').write_text(state)
            (temp / 'presence.h').write_text(presence)
            (temp / 'store.h').write_text(implementation)
            (temp / 'mesh.h').write_text('\n'.join((route, scheduling, flush, work, recovery)))
            binary = temp / 'test'
            result = subprocess.run([
                'c++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                '-DESP32_PLATFORM=1', '-DESP32=1', f'-DMESH_CONTACT_CACHE={cache}',
                '-I', str(ROOT / 'test/fixtures/advert_cache'),
                '-I', str(ROOT / 'src'), '-I', str(temp),
                str(ROOT / 'test/fixtures/advert_cache/test.cpp'), '-o', str(binary),
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            if synchronous:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('advert_rx_no_fs', result.stderr)
            else:
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
