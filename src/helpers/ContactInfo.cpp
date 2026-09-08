#include "ContactInfo.h"

#if MESH_CONTACT_CACHE
#include "ContactSecretCache.h"

#ifndef MAX_CONTACTS
#define MAX_CONTACTS 32
#endif

namespace mesh {

ContactPathStorage& contactPathStorage() {
  // Eight anonymous peers plus room for independent in-flight snapshots.
  static ContactPathPool<MAX_CONTACTS + 40> pool;
  return pool;
}

ContactSecretCache& contactSecretCache() {
  static ContactSecretCache cache;
  return cache;
}

} // namespace mesh

const uint8_t* ContactInfo::getSharedSecret(const mesh::LocalIdentity& self_id) const {
  return mesh::contactSecretCache().get(self_id, id.pub_key);
}
#endif
