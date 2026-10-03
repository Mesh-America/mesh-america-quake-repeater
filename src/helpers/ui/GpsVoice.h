#pragma once

#include <stddef.h>
#include <stdint.h>

// Decoder experiment only: production speech stays IMA until acoustic tests
// qualify another codec. Do not enable this in release recipes yet.
#if defined(MESH_GPS_VOICE_G726_BITRATE)
#if !defined(MESH_BUTTON_AUDIO_HIL) || !MESH_BUTTON_AUDIO_HIL
#error "G.726 speech is an opt-in MESH_BUTTON_AUDIO_HIL experiment"
#endif
#if MESH_GPS_VOICE_G726_BITRATE != 16 && MESH_GPS_VOICE_G726_BITRATE != 24
#error "G.726 speech bitrate must be 16 or 24 kbps"
#endif
#include <helpers/ui/g726/g726_decoder.h>
#endif

namespace mesh { namespace audio {

#if defined(MESH_GPS_VOICE_G726_BITRATE)
enum class VoiceCodec : uint8_t { Ima, G72616, G72624 };
#endif

// Low nibble first, independent IMA ADPCM stream starting at predictor/index 0.
// The samples live in flash; playback only needs two small DMA buffers in RAM.
struct VoiceClip {
  const uint8_t* data;
  size_t bytes;
  uint32_t samples;
  uint32_t sample_rate;
#if defined(MESH_GPS_VOICE_G726_BITRATE)
  VoiceCodec codec;
  constexpr VoiceClip(const uint8_t* data = nullptr, size_t bytes = 0,
                      uint32_t samples = 0, uint32_t sample_rate = 8000,
                      VoiceCodec codec = VoiceCodec::Ima)
      : data(data), bytes(bytes), samples(samples), sample_rate(sample_rate), codec(codec) {}
  unsigned bits() const {
    if (codec == VoiceCodec::Ima) return 4;
#if MESH_GPS_VOICE_G726_BITRATE == 16
    if (codec == VoiceCodec::G72616) return 2;
#else
    if (codec == VoiceCodec::G72624) return 3;
#endif
    return 0;
  }
  // Divide before multiplying: valid even for UINT32_MAX sample counts and
  // SIZE_MAX byte counts. The final byte may contain unused padding bits.
  size_t requiredBytes(uint32_t count) const {
    const unsigned b = bits();
    return (count / 8) * b + ((count % 8) * b + 7) / 8;
  }
  bool valid() const {
    return data && samples && bits() && bytes >= requiredBytes(samples)
        && (codec == VoiceCodec::Ima ? (sample_rate == 8000 || sample_rate == 16000)
                                    : sample_rate == 8000);
  }
#else
  constexpr VoiceClip(const uint8_t* data = nullptr, size_t bytes = 0,
                      uint32_t samples = 0, uint32_t sample_rate = 8000)
      : data(data), bytes(bytes), samples(samples), sample_rate(sample_rate) {}
#endif
};

class VoiceDecoder {
  VoiceClip clip_ = {};
  uint32_t position_ = 0;
  int32_t predictor_ = 0;
  int index_ = 0;
#if defined(MESH_GPS_VOICE_G726_BITRATE)
  G726State g726_ = {};
#endif
public:
  void begin(VoiceClip clip) {
    clip_ = clip;
    position_ = 0;
    predictor_ = 0;
    index_ = 0;
#if defined(MESH_GPS_VOICE_G726_BITRATE)
    g726_init(&g726_);
#endif
  }
  uint32_t position() const { return position_; }
  bool done() const {
#if defined(MESH_GPS_VOICE_G726_BITRATE)
    return !clip_.data || !clip_.bits() || position_ >= clip_.samples
        || clip_.requiredBytes(position_ + 1) > clip_.bytes;
#else
    return !clip_.data || position_ >= clip_.samples
        || position_ / 2 >= clip_.bytes;
#endif
  }
  int16_t next() {
    static const int16_t steps[89] = {
      7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,
      60,66,73,80,88,97,107,118,130,143,157,173,190,209,230,253,279,
      307,337,371,408,449,494,544,598,658,724,796,876,963,1060,1166,
      1282,1411,1552,1707,1878,2066,2272,2499,2749,3024,3327,3660,
      4026,4428,4871,5358,5894,6484,7132,7845,8630,9493,10442,11487,
      12635,13899,15289,16818,18500,20350,22385,24623,27086,29794,32767
    };
    static const int8_t adjustments[8] = {-1,-1,-1,-1,2,4,6,8};
    if (done()) return 0;
#if defined(MESH_GPS_VOICE_G726_BITRATE)
    if (clip_.codec != VoiceCodec::Ima) {
      const unsigned bits = clip_.bits();
      const unsigned bit = ((position_ % 8) * bits) % 8;
      const size_t byte = (position_ / 8) * bits + ((position_ % 8) * bits) / 8;
      unsigned word = clip_.data[byte];
      unsigned shift;
      if (bit + bits > 8) {
        word = (word << 8) | clip_.data[byte + 1];
        shift = 16 - bit - bits;
      } else shift = 8 - bit - bits;
      ++position_;
      return g726_decode(&g726_, (word >> shift) & ((1u << bits) - 1), bits);
    }
#endif
    const uint8_t code = (clip_.data[position_ / 2]
        >> ((position_ & 1) * 4)) & 15;
    ++position_;
    const int32_t step = steps[index_];
    int32_t delta = step >> 3;
    if (code & 1) delta += step >> 2;
    if (code & 2) delta += step >> 1;
    if (code & 4) delta += step;
    predictor_ += (code & 8) ? -delta : delta;
    if (predictor_ > 32767) predictor_ = 32767;
    if (predictor_ < -32768) predictor_ = -32768;
    index_ += adjustments[code & 7];
    if (index_ < 0) index_ = 0;
    if (index_ > 88) index_ = 88;
    return static_cast<int16_t>(predictor_);
  }
};

// Reconstruction at 32 kHz, without larger clips or allocations. Four phases
// suppress 8 kHz sampling images (3.2 kHz cutoff, Kaiser beta=7). Two phases
// retain the consonant band of 16 kHz clips (7.2 kHz cutoff, Kaiser beta=5).
// Each phase has exactly unity DC gain (Q14).
class VoiceInterpolator {
  int16_t history_[16] = {};
  unsigned head_ = 0;
  unsigned phase_ = 0;
  unsigned phases_ = 4;
public:
  void begin(uint32_t sample_rate = 8000) {
    for (auto& sample : history_) sample = 0;
    head_ = phase_ = 0;
    phases_ = sample_rate == 16000 ? 2 : 4;
  }
  int32_t next(VoiceDecoder& decoder) {
    static const int16_t coefficients[4][16] = {
      {3,-31,86,-84,-181,940,-2310,4633,12885,1341,-1562,983,-394,67,25,-17},
      {2,-35,137,-268,216,424,-2259,8176,11169,-1061,-502,671,-404,141,-19,-4},
      {-4,-19,141,-404,671,-502,-1061,11169,8176,-2259,424,216,-268,137,-35,2},
      {-17,25,67,-394,983,-1562,1341,12885,4633,-2310,940,-181,-84,86,-31,3}
    };
    static const int16_t wide_coefficients[2][16] = {
      {2,21,-113,332,-739,1415,-2581,5802,13506,-1505,150,249,-311,238,-133,51},
      {51,-133,238,-311,249,150,-1505,13506,5802,-2581,1415,-739,332,-113,21,2}
    };
    if (!phase_) {
      head_ = (head_ + 1) & 15;
      history_[head_] = decoder.next();
    }
    int32_t value = 0;
    const int16_t* taps = phases_ == 2 ? wide_coefficients[phase_] : coefficients[phase_];
    for (unsigned i = 0; i < 16; ++i)
      value += static_cast<int32_t>(history_[(head_ - i) & 15]) * taps[i];
    phase_ = (phase_ + 1) & (phases_ - 1);
    return value / 16384;
  }
};

}} // namespace mesh::audio
