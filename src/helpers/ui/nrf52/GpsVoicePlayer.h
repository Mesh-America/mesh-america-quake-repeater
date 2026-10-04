#pragma once

#include <Arduino.h>
#include <HardwarePWM.h>
#include <helpers/ui/GpsVoice.h>

namespace mesh { namespace audio {

class GpsVoicePlayer {
  static constexpr uint32_t OWNER = 0x63696f56; // Voic
  static constexpr size_t BLOCK = 128;
#if defined(MESH_BUTTON_AUDIO_HIL) && ((defined(MESH_GPS_VOICE_BINARY_DRIVE) && MESH_GPS_VOICE_BINARY_DRIVE) || (defined(MESH_GPS_VOICE_PDM_DRIVE) && MESH_GPS_VOICE_PDM_DRIVE) || (defined(MESH_GPS_VOICE_PCM32_DRIVE) && !MESH_GPS_VOICE_PCM32_DRIVE))
  static constexpr uint16_t TOP = 250; // 64 kHz carrier
#else
  static constexpr uint16_t TOP = 500; // tested 32 kHz carrier and output
#endif
  VoiceDecoder decoder_;
  VoiceInterpolator interpolator_;
  alignas(4) uint16_t buffers_[2][BLOCK] = {};
  uint16_t lengths_[2] = {};
  bool last_[2] = {};
  bool owned_ = false;
  volatile bool playing_ = false;
  volatile uint32_t played_ = 0;
  volatile uint32_t completed_ = 0;
  uint32_t started_ = 0;
  uint32_t cancelled_ = 0;
  uint8_t gain_ = 8; // acoustically selected drive for the T1000-E buzzer
#if defined(MESH_BUTTON_AUDIO_HIL) && defined(MESH_GPS_VOICE_BINARY_DRIVE) && MESH_GPS_VOICE_BINARY_DRIVE
  // Acoustic experiment: full GPIO-level drive with a small hysteresis band.
  // Unlike carrier PWM, silence holds a constant level instead of chattering.
  bool binary_level_ = false;
#endif
#if defined(MESH_BUTTON_AUDIO_HIL) && defined(MESH_GPS_VOICE_PDM_DRIVE) && MESH_GPS_VOICE_PDM_DRIVE
  int32_t density_error_ = 0;
  int32_t held_pcm_ = 0;
  bool density_repeat_ = false;
#endif

  void fill(unsigned n) {
    const uint32_t before = decoder_.position();
    for (size_t i = 0; i < BLOCK; ++i) {
#if defined(MESH_BUTTON_AUDIO_HIL) && defined(MESH_GPS_VOICE_PDM_DRIVE) && MESH_GPS_VOICE_PDM_DRIVE
      // Twice the reconstruction rate: full-width pulses instead of narrow
      // duty-cycle pulses. Error feedback moves quantization noise upwards.
      if (!density_repeat_) held_pcm_ = interpolator_.next(decoder_) * gain_;
      density_repeat_ = !density_repeat_;
      int32_t pcm = held_pcm_;
#else
      int32_t pcm = interpolator_.next(decoder_) * gain_;
#endif
      if (pcm > 32767) pcm = 32767;
      if (pcm < -32768) pcm = -32768;
#if defined(MESH_BUTTON_AUDIO_HIL) && defined(MESH_GPS_VOICE_PDM_DRIVE) && MESH_GPS_VOICE_PDM_DRIVE
      density_error_ += pcm;
      const bool high = density_error_ >= 0;
      density_error_ -= high ? 32767 : -32768;
      buffers_[n][i] = 0x8000 | (high ? TOP : 0);
#elif defined(MESH_BUTTON_AUDIO_HIL) && defined(MESH_GPS_VOICE_BINARY_DRIVE) && MESH_GPS_VOICE_BINARY_DRIVE
      if (pcm > 1024) binary_level_ = true;
      else if (pcm < -1024) binary_level_ = false;
      buffers_[n][i] = 0x8000 | (binary_level_ ? TOP : 0);
#else
      buffers_[n][i] = 0x8000 | ((pcm + 32768) * TOP / 65536);
#endif
    }
    lengths_[n] = decoder_.position() - before;
    last_[n] = decoder_.done();
  }
  void finishFromInterrupt() {
    NRF_PWM3->INTENCLR = 0xffffffff;
    NRF_PWM3->SHORTS = 0;
    NRF_PWM3->ENABLE = 0;
    digitalWrite(PIN_BUZZER, LOW);
    playing_ = false;
    ++completed_;
  }
public:
  bool start(VoiceClip clip) {
    stop();
    if (!clip.valid() || !HwPWM3.takeOwnership(OWNER)) return false;
    owned_ = true;
    if (!HwPWM3.addPin(PIN_BUZZER)) { stop(); return false; }
    decoder_.begin(clip);
    interpolator_.begin(clip.sample_rate);
#if defined(MESH_BUTTON_AUDIO_HIL) && defined(MESH_GPS_VOICE_BINARY_DRIVE) && MESH_GPS_VOICE_BINARY_DRIVE
    binary_level_ = false;
#endif
#if defined(MESH_BUTTON_AUDIO_HIL) && defined(MESH_GPS_VOICE_PDM_DRIVE) && MESH_GPS_VOICE_PDM_DRIVE
    density_error_ = held_pcm_ = 0;
    density_repeat_ = false;
#endif
    fill(0);
    fill(1);
    played_ = 0;
    NRF_PWM3->ENABLE = 0;
    NRF_PWM3->MODE = PWM_MODE_UPDOWN_Up;
    NRF_PWM3->COUNTERTOP = TOP;
    NRF_PWM3->PRESCALER = PWM_PRESCALER_PRESCALER_DIV_1;
    NRF_PWM3->DECODER = PWM_DECODER_LOAD_Common;
    NRF_PWM3->LOOP = 1;
    NRF_PWM3->SHORTS = PWM_SHORTS_LOOPSDONE_SEQSTART0_Msk;
    for (unsigned i = 0; i < 2; ++i) {
      NRF_PWM3->SEQ[i].PTR = reinterpret_cast<uintptr_t>(buffers_[i]);
      NRF_PWM3->SEQ[i].CNT = BLOCK;
#if defined(MESH_BUTTON_AUDIO_HIL) && !(defined(MESH_GPS_VOICE_PDM_DRIVE) && MESH_GPS_VOICE_PDM_DRIVE) && ((defined(MESH_GPS_VOICE_BINARY_DRIVE) && MESH_GPS_VOICE_BINARY_DRIVE) || (defined(MESH_GPS_VOICE_PCM32_DRIVE) && !MESH_GPS_VOICE_PCM32_DRIVE))
      NRF_PWM3->SEQ[i].REFRESH = 1;
#else
      NRF_PWM3->SEQ[i].REFRESH = 0;
#endif
      NRF_PWM3->SEQ[i].ENDDELAY = 0;
      NRF_PWM3->EVENTS_SEQEND[i] = 0;
      NRF_PWM3->EVENTS_SEQSTARTED[i] = 0;
    }
    NRF_PWM3->EVENTS_STOPPED = 0;
    NRF_PWM3->EVENTS_LOOPSDONE = 0;
    NVIC_ClearPendingIRQ(PWM3_IRQn);
    NVIC_SetPriority(PWM3_IRQn, 7); // below SoftDevice/radio interrupts
    NRF_PWM3->INTENSET = PWM_INTENSET_SEQEND0_Msk | PWM_INTENSET_SEQEND1_Msk;
    playing_ = true;
    ++started_;
    NRF_PWM3->ENABLE = 1;
    NVIC_EnableIRQ(PWM3_IRQn);
    NRF_PWM3->TASKS_SEQSTART[0] = 1;
    return true;
  }
  void interrupt() {
    for (unsigned i = 0; i < 2; ++i) {
      if (!NRF_PWM3->EVENTS_SEQEND[i]) continue;
      NRF_PWM3->EVENTS_SEQEND[i] = 0;
      if (!playing_) continue;
      played_ += lengths_[i];
      if (last_[i]) { finishFromInterrupt(); break; }
      fill(i); // refill the inactive buffer; no allocation or blocking in IRQ
    }
  }
  void service() { if (owned_ && !playing_) stop(); }
  void stop() {
    if (!owned_) return;
    NVIC_DisableIRQ(PWM3_IRQn);
    NRF_PWM3->INTENCLR = 0xffffffff;
    NRF_PWM3->SHORTS = 0;
    NRF_PWM3->ENABLE = 0;
    NVIC_ClearPendingIRQ(PWM3_IRQn);
    if (playing_) ++cancelled_;
    playing_ = false;
    HwPWM3.removePin(PIN_BUZZER);
    HwPWM3.releaseOwnership(OWNER);
    digitalWrite(PIN_BUZZER, LOW);
    owned_ = false;
  }
  bool playing() const { return playing_; }
  bool active() const { return owned_; } // includes deferred IRQ-completion cleanup
#ifdef MESH_BUTTON_AUDIO_HIL
  bool setGain(uint8_t gain) {
    if (active() || gain < 1 || gain > 8) return false;
    gain_ = gain;
    return true;
  }
#endif
  uint8_t gain() const { return gain_; }
  uint32_t played() const { return played_; }
  uint32_t started() const { return started_; }
  uint32_t completed() const { return completed_; }
  uint32_t cancelled() const { return cancelled_; }
};

}} // namespace mesh::audio
