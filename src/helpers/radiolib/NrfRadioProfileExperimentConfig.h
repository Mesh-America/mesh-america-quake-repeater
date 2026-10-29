#pragma once

#ifndef MC_NRF_RADIO_PROFILE_PRIORITY
#define MC_NRF_RADIO_PROFILE_PRIORITY 0
#endif
#ifndef MC_NRF_RADIO_PROFILE_USB_IRQ_GUARD
#define MC_NRF_RADIO_PROFILE_USB_IRQ_GUARD 0
#endif
#ifndef MC_NRF_RADIO_PROFILE_COMBINED
#define MC_NRF_RADIO_PROFILE_COMBINED 0
#endif
#if MC_NRF_RADIO_PROFILE_COMBINED != 0 && MC_NRF_RADIO_PROFILE_COMBINED != 1
#error "Combined radio profile experiment must be 0 or 1"
#endif
#if MC_NRF_RADIO_PROFILE_COMBINED && (!MC_NRF_RADIO_PROFILE_PRIORITY || !MC_NRF_RADIO_PROFILE_USB_IRQ_GUARD)
#error "Combined radio profile experiment requires both priority and USB IRQ experiments"
#endif
#if MC_NRF_RADIO_PROFILE_PRIORITY && MC_NRF_RADIO_PROFILE_USB_IRQ_GUARD && !MC_NRF_RADIO_PROFILE_COMBINED
#error "Measure the USB IRQ and task-priority experiments separately unless explicitly opting into the combined HIL experiment"
#endif
