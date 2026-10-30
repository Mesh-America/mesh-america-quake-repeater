/*
  Copyright (c) 2015 Arduino LLC. All right reserved.
  Copyright (c) 2016 Sandeep Mistry. All right reserved.

  This library is free software; you can redistribute it and/or modify it
  under the terms of the GNU Lesser General Public License as published by
  the Free Software Foundation; either version 2.1 of the License, or (at
  your option) any later version.

  This library is distributed in the hope that it will be useful, but WITHOUT
  ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
  FITNESS FOR A PARTICULAR PURPOSE. See the GNU Lesser General Public License
  for more details.

  You should have received a copy of the GNU Lesser General Public License
  along with this library; if not, write to the Free Software Foundation,
  Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA.
*/

// Frozen narrow core methods, independent of a CI package installation.
// Source: framework-arduinoadafruitnrf52 1.10701.0, cores/nRF5/Uart.cpp.
// Repository: https://github.com/meshcore-dev/Adafruit_nRF52_Arduino
// Complete source SHA256:
// 369f8847272f7884aabacce10a395099616212df614f7728931e212f3fce9df5
// Uart.h public bool returns _begun; complete header SHA256:
// f26b2a82c40925d5ebcdaa5806dd7767941098389d22aa55379c7ba7c190dacf
// Constructor, pin setter and end body below are copied without changes.
Uart::Uart(NRF_UARTE_Type *_nrfUart, IRQn_Type _IRQn, uint8_t _pinRX, uint8_t _pinTX)
{
  nrfUart = _nrfUart;
  IRQn = _IRQn;
  uc_pinRX = g_ADigitalPinMap[_pinRX];
  uc_pinTX = g_ADigitalPinMap[_pinTX];
  uc_hwFlow = 0;

  _end_tx_sem = NULL;
  _begun = false;
}

void Uart::setPins(uint8_t pin_rx, uint8_t pin_tx)
{
  uc_pinRX = g_ADigitalPinMap[pin_rx];
  uc_pinTX = g_ADigitalPinMap[pin_tx];
}

void Uart::end()
{
  NVIC_DisableIRQ(IRQn);

  nrfUart->INTENCLR = UARTE_INTENSET_ENDRX_Msk | UARTE_INTENSET_ENDTX_Msk;

  nrfUart->EVENTS_RXTO = 0;
  nrfUart->EVENTS_TXSTOPPED = 0;

  nrfUart->TASKS_STOPRX = 0x1UL;
  nrfUart->TASKS_STOPTX = 0x1UL;

  // Wait for TXSTOPPED event and for RXTO event
  // This is required before disabling UART to fully power down transceiver PHY.
  // Otherwise transceiver will continue to consume ~900uA
  while ( !(nrfUart->EVENTS_TXSTOPPED && nrfUart->EVENTS_RXTO) ) yield();

  nrfUart->ENABLE = UARTE_ENABLE_ENABLE_Disabled;

  nrfUart->PSEL.TXD = 0xFFFFFFFF;
  nrfUart->PSEL.RXD = 0xFFFFFFFF;

  nrfUart->PSEL.RTS = 0xFFFFFFFF;
  nrfUart->PSEL.CTS = 0xFFFFFFFF;

  rxBuffer.clear();

  vSemaphoreDelete(_end_tx_sem);
  _end_tx_sem = NULL;
  _begun = false;
}
