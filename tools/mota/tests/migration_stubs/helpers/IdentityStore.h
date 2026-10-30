#pragma once
#include <stdint.h>

// Only the filesystem handle crosses the migration driver's store boundary.
// The real persistence implementation is exercised by its separate fault tests.
class MigrationTestFilesystem {};
#define FILESYSTEM MigrationTestFilesystem
