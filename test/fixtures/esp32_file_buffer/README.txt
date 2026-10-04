Pinned, byte-exact source fixtures for the build-local ESP File buffer check.

vfs_api.cpp and esp_arduino_version.h:
Arduino-ESP32 2.0.17, revision dcc1105b0cf1322a437b354c336f2abf72b7e512.
https://github.com/espressif/arduino-esp32/blob/2.0.17/libraries/FS/src/vfs_api.cpp
https://github.com/espressif/arduino-esp32/blob/2.0.17/cores/esp32/esp_arduino_version.h
Both retain their complete upstream copyright/Apache-2.0 notice.
vfs_api.cpp SHA256 db3eb3fef8e59c0bafd01416ea18e2d5f36f38a9b180cd415ff3563a59fcfb65
version header SHA256 b63e57731a24289b06eb96ded9e481ea719f4cde2ce7c41bd83c7646e0a6fe51

newlib_sys_reent.h and _newlib_version.h:
Unmodified installed Xtensa ESP32-S3 8.4.0+2021r2-patch5 toolchain headers,
newlib 3.3.0, as shipped with the pinned Arduino-ESP32 framework toolchain.
https://github.com/espressif/newlib-esp32/blob/esp-2021r2-patch5/newlib/libc/include/sys/reent.h
https://github.com/espressif/newlib-esp32/blob/esp-2021r2-patch5/COPYING.NEWLIB
All original header bytes/comments remain intact; _newlib_version.h is generated.
reent SHA256 33391d61a83ebbfb122e80514fbf7ed4d770556d8e8d46e029addbbf6077cd79
version SHA256 93a397574a25b9c143cee7fcb86d8fc9a0c9ba418e4710a30d2d19ba1e4120db

The actual ELF map resolves setvbuf/__sfvwrite_r/__srefill_r from the pinned
toolchain's no-rtti/libc.a. Its setvbuf allocation-fallback path may return zero
with a filesystem-sized buffer after the requested allocation failed. The
copied VFS method checks FILE::_bf._size before the caller's first read/write.
Compile-time newlib version/type/32-bit-prefix assertions fail closed when the
reviewed internal ABI changes. Native tests extract this exact FILE prefix and
model 32-bit pointer widths rather than borrowing the host libc's FILE layout.

Backend buffer admission is not a wall-clock guarantee: SPIFFS metadata,
garbage collection, flush, close and publication still require hardware tests.
