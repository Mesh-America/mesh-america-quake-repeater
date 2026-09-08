#pragma once

// Squeezed Regular 6 by Oliver Kraus. Public domain.
// Lossless conversion of the ASCII glyphs from the upstream BDF.
// Source: https://raw.githubusercontent.com/olikraus/u8g2/57d191014bebc263868526491e7f7c33ddcf6042/tools/font/bdf/u8g2_squeezed_regular_6.bdf
// BDF SHA-256: a50740bd62accaa104e52da98210b3db10e03d75c6fbac1a31010177fad92277
// Reference: test/fixtures/small_message_font/squeezed6.bdf

#include "SmallFontGlyph.h"

namespace mesh {
namespace ui {

static const uint8_t squeezed6Bitmaps[] = {
    0xF4, 0xB4, 0x57, 0xD5, 0xF5, 0x00, 0x23, 0xE8, 0xE2, 0xF8, 0x80, 0xA5,
    0x29, 0x40, 0x4A, 0x4A, 0xA5, 0xC0, 0x6A, 0x90, 0x95, 0x60, 0xAB, 0xAA,
    0x5D, 0x00, 0xC0, 0xC0, 0x80, 0x25, 0x29, 0x00, 0x56, 0xDA, 0x80, 0x75,
    0x50, 0x96, 0xB0, 0xD9, 0x60, 0xB7, 0x92, 0x40, 0xE9, 0x60, 0x53, 0x5A,
    0x80, 0xE5, 0x24, 0x80, 0x55, 0x5A, 0x80, 0x55, 0x92, 0x80, 0xA0, 0x98,
    0x64, 0xCC, 0x98, 0x9A, 0x20, 0x69, 0xBB, 0x87, 0x57, 0xDB, 0x40, 0xD7,
    0x5B, 0x80, 0x6A, 0x90, 0xD6, 0xDB, 0x80, 0xEE, 0xB0, 0xEE, 0xA0, 0x72,
    0xDA, 0xC0, 0xB7, 0xDB, 0x40, 0xFC, 0x55, 0x70, 0xB7, 0x5B, 0x40, 0xAA,
    0xB0, 0x8E, 0xEB, 0x18, 0xC4, 0x9D, 0xB9, 0x99, 0x56, 0xDA, 0x80, 0xD7,
    0x49, 0x00, 0x56, 0xDA, 0xC0, 0xD7, 0x5B, 0x40, 0x69, 0x60, 0xE9, 0x24,
    0x80, 0xB6, 0xDB, 0xC0, 0xB6, 0xD4, 0x80, 0x8C, 0x63, 0x5A, 0xA8, 0xB5,
    0x2B, 0x40, 0xB6, 0xA4, 0x80, 0xD6, 0xB0, 0xEA, 0xB0, 0x91, 0x22, 0x40,
    0xD5, 0x70, 0x54, 0xC0, 0x90, 0x76, 0xB0, 0x93, 0x5B, 0x80, 0x69, 0x25,
    0xDA, 0xC0, 0x57, 0x30, 0x6E, 0xA0, 0x75, 0x9C, 0x93, 0x5B, 0x40, 0xBC,
    0x45, 0x58, 0x92, 0xEB, 0x40, 0xFC, 0xF5, 0x6B, 0x50, 0xD6, 0xD0, 0x56,
    0xA0, 0xD6, 0xE8, 0x76, 0xB2, 0xBA, 0x40, 0x66, 0xAE, 0x90, 0xB6, 0xF0,
    0xB6, 0xE0, 0x8D, 0x6A, 0xA0, 0xA9, 0x50, 0xB5, 0x94, 0xDB, 0x2B, 0x24,
    0x40, 0xFC, 0x89, 0xA5, 0x00, 0x5A,
};

static const SmallFontGlyph squeezed6Glyphs[] = {
    {0, 0, 0, 2, 0, 1}, // ASCII 32
    {0, 1, 6, 2, 0, -5}, // ASCII 33
    {1, 3, 2, 4, 0, -5}, // ASCII 34
    {2, 5, 5, 6, 0, -4}, // ASCII 35
    {6, 5, 7, 6, 0, -5}, // ASCII 36
    {11, 3, 6, 4, 0, -5}, // ASCII 37
    {14, 4, 6, 5, 0, -5}, // ASCII 38
    {17, 1, 2, 2, 0, -5}, // ASCII 39
    {18, 2, 6, 3, 0, -5}, // ASCII 40
    {20, 2, 6, 3, 0, -5}, // ASCII 41
    {22, 3, 5, 4, 0, -5}, // ASCII 42
    {24, 3, 3, 4, 0, -4}, // ASCII 43
    {26, 1, 2, 2, 0, 0}, // ASCII 44
    {27, 2, 1, 3, 0, -3}, // ASCII 45
    {28, 1, 1, 2, 0, 0}, // ASCII 46
    {29, 3, 6, 4, 0, -5}, // ASCII 47
    {32, 3, 6, 4, 0, -5}, // ASCII 48
    {35, 2, 6, 3, 0, -5}, // ASCII 49
    {37, 2, 6, 3, 0, -5}, // ASCII 50
    {39, 2, 6, 3, 0, -5}, // ASCII 51
    {41, 3, 6, 4, 0, -5}, // ASCII 52
    {44, 2, 6, 3, 0, -5}, // ASCII 53
    {46, 3, 6, 4, 0, -5}, // ASCII 54
    {49, 3, 6, 4, 0, -5}, // ASCII 55
    {52, 3, 6, 4, 0, -5}, // ASCII 56
    {55, 3, 6, 4, 0, -5}, // ASCII 57
    {58, 1, 3, 2, 0, -3}, // ASCII 58
    {59, 1, 5, 2, 0, -3}, // ASCII 59
    {60, 2, 3, 3, 0, -4}, // ASCII 60
    {61, 2, 3, 3, 0, -4}, // ASCII 61
    {62, 2, 3, 3, 0, -4}, // ASCII 62
    {63, 2, 6, 3, 0, -5}, // ASCII 63
    {65, 4, 6, 5, 0, -5}, // ASCII 64
    {68, 3, 6, 4, 0, -5}, // ASCII 65
    {71, 3, 6, 4, 0, -5}, // ASCII 66
    {74, 2, 6, 3, 0, -5}, // ASCII 67
    {76, 3, 6, 4, 0, -5}, // ASCII 68
    {79, 2, 6, 3, 0, -5}, // ASCII 69
    {81, 2, 6, 3, 0, -5}, // ASCII 70
    {83, 3, 6, 4, 0, -5}, // ASCII 71
    {86, 3, 6, 4, 0, -5}, // ASCII 72
    {89, 1, 6, 2, 0, -5}, // ASCII 73
    {90, 2, 6, 3, 0, -5}, // ASCII 74
    {92, 3, 6, 4, 0, -5}, // ASCII 75
    {95, 2, 6, 3, 0, -5}, // ASCII 76
    {97, 5, 6, 6, 0, -5}, // ASCII 77
    {101, 4, 6, 5, 0, -5}, // ASCII 78
    {104, 3, 6, 4, 0, -5}, // ASCII 79
    {107, 3, 6, 4, 0, -5}, // ASCII 80
    {110, 3, 6, 4, 0, -5}, // ASCII 81
    {113, 3, 6, 4, 0, -5}, // ASCII 82
    {116, 2, 6, 3, 0, -5}, // ASCII 83
    {118, 3, 6, 4, 0, -5}, // ASCII 84
    {121, 3, 6, 4, 0, -5}, // ASCII 85
    {124, 3, 6, 4, 0, -5}, // ASCII 86
    {127, 5, 6, 6, 0, -5}, // ASCII 87
    {131, 3, 6, 4, 0, -5}, // ASCII 88
    {134, 3, 6, 4, 0, -5}, // ASCII 89
    {137, 2, 6, 3, 0, -5}, // ASCII 90
    {139, 2, 6, 3, 0, -5}, // ASCII 91
    {141, 3, 6, 4, 0, -5}, // ASCII 92
    {144, 2, 6, 3, 0, -5}, // ASCII 93
    {146, 3, 2, 4, 0, -5}, // ASCII 94
    {147, 2, 1, 3, 0, 0}, // ASCII 95
    {148, 2, 2, 3, 0, -5}, // ASCII 96
    {149, 3, 4, 4, 0, -3}, // ASCII 97
    {151, 3, 6, 4, 0, -5}, // ASCII 98
    {154, 2, 4, 3, 0, -3}, // ASCII 99
    {155, 3, 6, 4, 0, -5}, // ASCII 100
    {158, 3, 4, 4, 0, -3}, // ASCII 101
    {160, 2, 6, 3, 0, -5}, // ASCII 102
    {162, 3, 5, 4, 0, -3}, // ASCII 103
    {164, 3, 6, 4, 0, -5}, // ASCII 104
    {167, 1, 6, 2, 0, -5}, // ASCII 105
    {168, 2, 7, 3, 0, -5}, // ASCII 106
    {170, 3, 6, 4, 0, -5}, // ASCII 107
    {173, 1, 6, 2, 0, -5}, // ASCII 108
    {174, 5, 4, 6, 0, -3}, // ASCII 109
    {177, 3, 4, 4, 0, -3}, // ASCII 110
    {179, 3, 4, 4, 0, -3}, // ASCII 111
    {181, 3, 5, 4, 0, -3}, // ASCII 112
    {183, 3, 5, 4, 0, -3}, // ASCII 113
    {185, 3, 4, 4, 0, -3}, // ASCII 114
    {187, 2, 4, 3, 0, -3}, // ASCII 115
    {188, 2, 6, 3, 0, -5}, // ASCII 116
    {190, 3, 4, 4, 0, -3}, // ASCII 117
    {192, 3, 4, 4, 0, -3}, // ASCII 118
    {194, 5, 4, 6, 0, -3}, // ASCII 119
    {197, 3, 4, 4, 0, -3}, // ASCII 120
    {199, 3, 5, 4, 0, -3}, // ASCII 121
    {201, 2, 4, 3, 0, -3}, // ASCII 122
    {202, 3, 6, 4, 0, -5}, // ASCII 123
    {205, 1, 6, 2, 0, -5}, // ASCII 124
    {206, 3, 6, 4, 0, -5}, // ASCII 125
    {209, 4, 2, 5, 0, -5}, // ASCII 126
};

}  // namespace ui
}  // namespace mesh
