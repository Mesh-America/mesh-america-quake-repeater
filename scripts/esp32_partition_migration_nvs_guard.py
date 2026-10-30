"""Build-local NVS preservation for callback-free USB migration bridges.

Arduino normally erases the entire NVS partition on NO_FREE_PAGES or a newer
NVS version before setup() runs.  That destroys staged identity/configuration.
For dedicated USB bridges only, retain the initialization error and leave NVS
untouched; the runtime then refuses and returns to its recovery transport.
The shared Arduino SDK and normal firmware builds are never modified.
"""

import hashlib
from pathlib import Path


PINNED_MISC_SHA256 = "d6374832d4e7d987e8c9eb71aa36f12e6f03a5d16c298a139a6b222a108788d1"
GUARD_MARKER = "    // MeshCore USB migrator: preserve NVS on initialization failure.\n"
BINARY_MARKER = "MeshCore USB NVS no-autoerase guard v1"
MARKER_FUNCTION = '''
// Referenced by the dedicated USB runtime: a missing middleware must not link.
const char* meshEsp32MigrationNvsGuardMarker(void) {
    return "MeshCore USB NVS no-autoerase guard v1";
}
'''
AUTOFORMAT = '''    if(err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND){
        const esp_partition_t* partition = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_NVS, NULL);
        if (partition != NULL) {
            err = esp_partition_erase_range(partition, 0, partition->size);
            if(!err){
                err = nvs_flash_init();
            } else {
                log_e("Failed to format the broken NVS partition!");
            }
        } else {
            log_e("Could not find NVS partition");
        }
    }
'''


def patched_misc_source(source):
    source = source.replace("\r\n", "\n")
    # Permit our own exact transformation to be read again without relaxing the
    # original SDK pin.  A stray marker or altered surrounding code is rejected.
    original = source.replace(GUARD_MARKER, AUTOFORMAT) if source.count(GUARD_MARKER) == 1 else source
    if original.endswith(MARKER_FUNCTION):
        original = original[:-len(MARKER_FUNCTION)]
    if (hashlib.sha256(original.encode("utf-8")).hexdigest() != PINNED_MISC_SHA256
            or original.count(AUTOFORMAT) != 1):
        raise RuntimeError("ESP32 USB migration NVS guard: changed Arduino startup; review SDK update")
    return original.replace(AUTOFORMAT, GUARD_MARKER) + MARKER_FUNCTION


def usb_migration_enabled(build_env):
    defines = {}
    for definition in build_env.get("CPPDEFINES", []):
        if isinstance(definition, (tuple, list)):
            defines[definition[0]] = str(definition[1])
        else:
            defines[str(definition)] = "1"
    return defines.get("MESHCORE_MIGRATION_USB") == "1"


def replace_source(build_env, node):
    if not usb_migration_enabled(build_env):
        return node
    source = Path(node.srcnode().get_abspath())
    patched = patched_misc_source(source.read_text(encoding="utf-8"))
    destination = Path(build_env.subst("$BUILD_DIR")) / "patched-esp32-migration" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or destination.read_text(encoding="utf-8") != patched:
        destination.write_text(patched, encoding="utf-8")
    build_env.AppendUnique(CPPPATH=[str(source.parent)])
    return build_env.File(str(destination))


def install(build_env):
    build_env.AddBuildMiddleware(replace_source, "*cores*esp32*esp32-hal-misc.c")


if "Import" in globals():
    Import("env")
    install(env)
