"""Execute finite per-frame radio yield budgets and default-off behavior."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from test_rak3401_buffered_radio_hal import MOCK_HAL

ROOT = Path(__file__).resolve().parents[1]

MOCK = MOCK_HAL.replace('virtual ~ArduinoHal() = default;', '''
  unsigned yields = 0;
  virtual ~ArduinoHal() = default;
  virtual void yield() { ++yields; }
''')

FIXTURE = r'''
#include <helpers/radiolib/Nrf52BufferedRadioHal.h>
int main() {
  SPIClass bus;
  Nrf52BufferedRadioHal concrete(bus,8000000);
  ArduinoHal& radio=concrete;
  constexpr unsigned budget=MC_NRF_RADIO_BUSY_SPIN_POLLS;
#if MC_NRF_RADIO_BUSY_SPIN_POLLS == 0
  static_assert(sizeof(Nrf52BufferedRadioHal)==sizeof(ArduinoHal),"default RAM growth");
#endif
  // The first pre-transfer wait delegates immediately, even in opt-in builds.
  for(unsigned i=0;i<1000;++i) radio.yield();
  assert(radio.yields==1000 && bus.bursts==0);
  radio.spiTransfer(nullptr,0,nullptr);
  radio.yield();
  assert(radio.yields==1001 && bus.bursts==0);

  uint8_t tx[]={0x86,0x12,0x34},rx[3]={};
  for(unsigned frame=0;frame<1000;++frame) {
    const unsigned before=radio.yields;
    radio.spiTransfer(tx,sizeof(tx),rx);
    assert(rx[0]==uint8_t(tx[0]^0xa5) && rx[2]==uint8_t(tx[2]^0xa5));
    for(unsigned i=0;i<budget;++i) radio.yield();
    assert(radio.yields==before);
    radio.yield(); assert(radio.yields==before+1);
    // A zero-byte call must not replenish an exhausted budget.
    radio.spiTransfer(nullptr,0,nullptr);
    radio.yield(); assert(radio.yields==before+2);
  }
  assert(bus.bursts==1000 && bus.bytes==0);

  // Neither a zero-size transfer midway through a budget nor later ordinary
  // waits can turn the finite budget into perpetual spinning.
  unsigned before=radio.yields;
  radio.spiTransfer(tx,sizeof(tx),rx);
  for(unsigned i=0;i<budget/2;++i) radio.yield();
  radio.spiTransfer(nullptr,0,nullptr);
  for(unsigned i=budget/2;i<budget;++i) radio.yield();
  assert(radio.yields==before);
  for(unsigned i=0;i<100000;++i) radio.yield();
  assert(radio.yields==before+100000);
  before=radio.yields;
  radio.spiTransfer(tx,sizeof(tx),rx);
  for(unsigned i=0;i<100000;++i) radio.yield();
  assert(radio.yields==before+100000-budget);
  assert(bus.bursts==1002 && bus.bytes==0);
}
'''


class NrfRadioYieldBudgetTest(unittest.TestCase):
    def test_zero_four_eight_sixteen_preserve_transfer_and_bound_skipped_yields(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            (folder/'hal/Arduino').mkdir(parents=True)
            (folder/'hal/Arduino/ArduinoHal.h').write_text(MOCK,encoding='ascii')
            cpp,binary=folder/'test.cpp',folder/'test.exe'
            cpp.write_text(FIXTURE,encoding='ascii')
            for budget in (0,4,8,16):
                with self.subTest(budget=budget):
                    built=subprocess.run([os.environ.get('CXX','g++'),'-std=c++17',
                        '-Wall','-Wextra','-Werror',f'-DMC_NRF_RADIO_BUSY_SPIN_POLLS={budget}',
                        '-I',str(folder),'-I',str(ROOT/'src'),str(cpp),'-o',str(binary)],
                        capture_output=True,text=True)
                    self.assertEqual(built.returncode,0,built.stderr)
                    ran=subprocess.run([str(binary)],capture_output=True,text=True)
                    self.assertEqual(ran.returncode,0,ran.stderr)
            for budget in (-1,17):
                with self.subTest(invalid_budget=budget):
                    built=subprocess.run([os.environ.get('CXX','g++'),'-std=c++17',
                        f'-DMC_NRF_RADIO_BUSY_SPIN_POLLS={budget}','-I',str(folder),
                        '-I',str(ROOT/'src'),str(cpp),'-o',str(binary)],
                        capture_output=True,text=True)
                    self.assertNotEqual(built.returncode,0)
                    self.assertIn('bounded 0..16 poll budget',built.stderr)

    def test_default_preprocessing_omits_budget_and_override(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            (folder/'hal/Arduino').mkdir(parents=True)
            (folder/'hal/Arduino/ArduinoHal.h').write_text(MOCK,encoding='ascii')
            result=subprocess.run([os.environ.get('CXX','g++'),'-std=c++17','-E','-P',
                '-x','c++','-I',str(folder),'-I',str(ROOT/'src'),'-'],
                input='#include <helpers/radiolib/Nrf52BufferedRadioHal.h>\n',
                capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            production=result.stdout.split('class Nrf52BufferedRadioHal',1)[1]
            self.assertNotIn('_busy_spin_polls_remaining',production)
            self.assertNotIn('void yield()',production)


if __name__=='__main__':
    unittest.main()
