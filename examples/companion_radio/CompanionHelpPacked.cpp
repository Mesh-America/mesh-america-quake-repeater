#if defined(RAK_4631) && defined(COMPANION_RADIO_FULL)
// This is the only Companion translation unit compiled as C++17. Include the
// same feature/board context as MyMesh before expanding the single help source.
#include "MyMesh.h"
#include "CompanionHelpWriter.h"

namespace mesh { namespace companion {
size_t writePackedCompanionHelp(Stream& output) {
    // Constant evaluation retains only the exact-sized packed help image.
    // The source fragments and every feature gate remain shared below.
    static constexpr auto packed_help = []() constexpr {
      constexpr char help_text[] =
#define MESH_COMPANION_HELP_BEGIN
#define MESH_COMPANION_HELP_END
#define MESH_COMPANION_HELP_LINE_BEGIN
#define MESH_COMPANION_HELP_LINE_END "\r\n"
#include "CompanionHelp.inc"
#undef MESH_COMPANION_HELP_BEGIN
#undef MESH_COMPANION_HELP_END
#undef MESH_COMPANION_HELP_LINE_BEGIN
#undef MESH_COMPANION_HELP_LINE_END
          ;
      static_assert(mesh::companion::validHelpText(help_text),
                    "Packed help requires ASCII without embedded NUL bytes");
      return mesh::companion::packHelp<
          mesh::companion::packedHelpSize(help_text)>(help_text);
    }();
    return mesh::companion::writePackedHelp(output, packed_help.bytes,
                                    sizeof(packed_help.bytes));
}
} } // namespace mesh::companion
#endif
