#pragma once

#include <stddef.h>

namespace mesh { namespace ota {
struct OtaManager {
  enum State { IDLE, FAILED, FETCHING, VERIFYING, COMPLETE };
  State state = IDLE;
  size_t serve_jobs = 0, manifest_jobs = 0;
  State fetchState() const { return state; }
  size_t pendingServeJobs() const { return serve_jobs; }
  size_t pendingManifestJobs() const { return manifest_jobs; }
};
struct OtaContext {
  OtaManager manager;
  bool apply_pending = false, bootloader_apply_pending = false;
  bool folder_active = false, folder_dest = false, capture_waiting = false;
  bool serving = false, serve_expected = false;
  bool folderCaptureWaiting() const { return capture_waiting; }
};
inline OtaContext* test_ota_context = nullptr;
inline const OtaContext* ota_context_if_active() { return test_ota_context; }
} }  // namespace mesh::ota
