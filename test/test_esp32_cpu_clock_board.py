"""Execute the production board clock API and actual role policy handoffs."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_esp32_usb_sleep import board_method
from cpp_source import body

ROOT=Path(__file__).resolve().parents[1]

PRELUDE=r'''
#include <cassert>
#include <cstdint>
#include <helpers/esp32/CpuClockPolicy.h>
#include <helpers/esp32/PowerTestControls.h>
static uint16_t actual_mhz=240;
static unsigned clock_writes=0;
static bool fail_clock=false,wrong_readback=false;
static uint32_t now_ms=100;
uint32_t millis(){return now_ms;}
uint32_t getCpuFrequencyMhz(){return actual_mhz;}
bool setCpuFrequencyMhz(uint32_t value){
 ++clock_writes;if(fail_clock)return false;actual_mhz=wrong_readback?80:value;return true;
}
#define EFUSE_BLK0_RDATA3_REG 0
#define EFUSE_RD_CHIP_CPU_FREQ_RATED 1
#define EFUSE_RD_CHIP_CPU_FREQ_LOW 2
static unsigned fuse_bits=0;
#define REG_GET_BIT(reg,mask) (fuse_bits&(mask))
using esp_err_t=int;constexpr int ESP_OK=0;
struct esp_pm_config_t {int max_freq_mhz,min_freq_mhz;bool light_sleep_enable;};
using esp_pm_config_esp32_t=esp_pm_config_t;
using esp_pm_config_esp32s3_t=esp_pm_config_t;
using esp_pm_config_esp32c3_t=esp_pm_config_t;
static esp_pm_config_t applied_pm{};
int esp_pm_configure(esp_pm_config_t* config){
 ++clock_writes;if(fail_clock)return 9;applied_pm=*config;
 actual_mhz=wrong_readback?80:config->min_freq_mhz;return ESP_OK;
}
struct MainBoard {
 virtual uint16_t getCpuFrequencyMHz()const=0;
 virtual bool supportsCpuFrequencyMHz(uint16_t)const=0;
 virtual bool applyCpuFrequencyMHz(uint16_t,bool)=0;
};
struct ESP32Board:MainBoard {
 bool companion_cpu_clock_policy=false;
 unsigned quiet_services=0;
 void servicePowerTestControls(){++quiet_services;}
 @METHODS@
} board;
namespace mesh {
struct Console {void printf(const char*,...){}};
Console& usbLoggingPort(){static Console value;return value;}
}
struct Prefs {uint16_t cpu_freq_mhz=0;bool powersaving_enabled=true;} prefs;
struct Mesh {Prefs* getNodePrefs(){return &prefs;}} the_mesh;
'''


class CpuClockBoardTest(unittest.TestCase):
    def fixture(self):
        methods="\n".join(board_method(signature) for signature in (
            "void setCompanionCpuClockPolicy(","uint16_t getCpuFrequencyMHz() const override",
            "bool supportsCpuFrequencyMHz(","bool applyCpuFrequencyMHz("))
        return PRELUDE.replace("@METHODS@",methods)

    def run_fixture(self,main,defines=()):
        with tempfile.TemporaryDirectory(prefix="mesh-esp32-clock-board-") as directory:
            folder=Path(directory);path=folder/"test.cpp";path.write_text(self.fixture()+main)
            result=subprocess.run([os.environ.get("CXX","c++"),"-std=c++17","-Wall","-Wextra",
                "-fsanitize=address,undefined","-fno-sanitize-recover=all","-fno-pie","-no-pie",
                "-DESP32_CPU_FREQ=240","-I",str(ROOT/"src"),*defines,str(path),"-o",str(folder/"test")],
                capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(folder/"test")],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_supported_silicon_fixed_clocks_pm_and_auto_role_policy(self):
        source=r'''
int main(){
 const unsigned nominal=board.supportsCpuFrequencyMHz(240)?240:160;
 assert(board.supportsCpuFrequencyMHz(80)&&board.supportsCpuFrequencyMHz(160));
#if CONFIG_IDF_TARGET_ESP32C3 || CONFIG_IDF_TARGET_ESP32C6
 assert(!board.supportsCpuFrequencyMHz(240));
#else
 assert(board.supportsCpuFrequencyMHz(240));
#endif
 assert(!board.supportsCpuFrequencyMHz(120)&&!board.supportsCpuFrequencyMHz(0));
 unsigned before=clock_writes;assert(!board.applyCpuFrequencyMHz(120,true));assert(clock_writes==before);
 for(uint16_t selected:{uint16_t(80),uint16_t(160)}){
   for(bool ps:{false,true}){
     assert(board.applyCpuFrequencyMHz(selected,ps));assert(board.getCpuFrequencyMHz()==selected);
#if CONFIG_PM_ENABLE
     assert(applied_pm.min_freq_mhz==selected&&applied_pm.max_freq_mhz==selected);
#endif
   }
 }
 board.setCompanionCpuClockPolicy(true);
 assert(board.applyCpuFrequencyMHz(0,true));
#if CONFIG_PM_ENABLE
 assert(applied_pm.max_freq_mhz==80&&applied_pm.min_freq_mhz==40);
#if ENABLE_USB_INTERFACE || ARDUINO_USB_CDC_ON_BOOT
 assert(!applied_pm.light_sleep_enable);
#else
 assert(applied_pm.light_sleep_enable);
#endif
#else
 assert(actual_mhz==80);
#endif
 assert(board.applyCpuFrequencyMHz(0,false));assert(actual_mhz==nominal);
 board.setCompanionCpuClockPolicy(false);
 assert(board.applyCpuFrequencyMHz(0,true));assert(actual_mhz==nominal);
#if CONFIG_PM_ENABLE
 assert(unsigned(applied_pm.max_freq_mhz)==nominal&&unsigned(applied_pm.min_freq_mhz)==nominal&&!applied_pm.light_sleep_enable);
#endif
 fail_clock=true;assert(!board.applyCpuFrequencyMHz(160,true));fail_clock=false;
 wrong_readback=true;assert(!board.applyCpuFrequencyMHz(160,true));wrong_readback=false;
#if CONFIG_IDF_TARGET_ESP32
 // Rated+low is the classic160MHz-only eFuse combination. Reject explicit
 //240 without letting Arduino silently replace it with a different clock.
 for(unsigned bits:{0U,1U,2U,3U}){
   fuse_bits=bits;assert(board.supportsCpuFrequencyMHz(240)==(bits!=3));
 }
 before=clock_writes;assert(!board.applyCpuFrequencyMHz(240,false));assert(clock_writes==before);
 assert(board.applyCpuFrequencyMHz(0,false)&&actual_mhz==160);
#endif
}
'''
        source="#include <initializer_list>\n"+source
        for target in ("ESP32","ESP32S3","ESP32C3","ESP32C6"):
            for pm in (0,1):
                with self.subTest(target=target,pm=pm):
                    self.run_fixture(source,[f"-DCONFIG_IDF_TARGET_{target}=1",f"-DCONFIG_PM_ENABLE={pm}","-DENABLE_USB_INTERFACE=1"])
        self.run_fixture(source,["-DCONFIG_IDF_TARGET_ESP32S3=1","-DCONFIG_PM_ENABLE=1"])

    def test_actual_companion_service_tracks_clock_choice_independently_of_ps(self):
        main=(ROOT/"examples/companion_radio/main.cpp").read_text()
        methods="\n".join(body(main,signature) for signature in (
            "static bool applyCompanionPowerSaving(","static void serviceCompanionPowerSaving("))
        prefix=r'''
static int8_t applied_power_saving=-1,attempted_power_saving=-1;
static uint16_t applied_cpu_frequency=UINT16_MAX,attempted_cpu_frequency=UINT16_MAX;
static unsigned long power_saving_retry_at=0;
'''
        tests=r'''
int main(){
 board.setCompanionCpuClockPolicy(true);serviceCompanionPowerSaving(true);
 assert(actual_mhz==80);unsigned writes=clock_writes;
 serviceCompanionPowerSaving();assert(clock_writes==writes);
 prefs.cpu_freq_mhz=160;serviceCompanionPowerSaving();assert(actual_mhz==160);
 prefs.powersaving_enabled=false;serviceCompanionPowerSaving();assert(actual_mhz==160);
 prefs.powersaving_enabled=true;serviceCompanionPowerSaving();assert(actual_mhz==160);
 prefs.cpu_freq_mhz=0;serviceCompanionPowerSaving();assert(actual_mhz==80);
 prefs.powersaving_enabled=false;serviceCompanionPowerSaving();assert(actual_mhz==240);
 // Failures retain the request and retry after the original bounded delay.
 prefs.cpu_freq_mhz=160;fail_clock=true;serviceCompanionPowerSaving();writes=clock_writes;
 serviceCompanionPowerSaving();assert(clock_writes==writes);
 now_ms+=5000;fail_clock=false;serviceCompanionPowerSaving();assert(actual_mhz==160);
}
'''
        self.run_fixture(prefix+methods+tests,["-DCONFIG_IDF_TARGET_ESP32S3=1","-DCONFIG_PM_ENABLE=0",
            "-DCOMPANION_IDF_PM_AVAILABLE=0","-DCOMPANION_BT_MODEM_SLEEP_AVAILABLE=0"])

    def test_actual_infrastructure_loop_services_saved_choice_and_quiet_deadline(self):
        for role in ("simple_repeater","simple_room_server","simple_sensor"):
            source=(ROOT/"examples"/role/"main.cpp").read_text()
            start=source.index("  board.servicePowerTestControls();",source.index("void loop()"))
            end=source.index("#endif",start)
            service=source[start:end]
            tests="void role_service(){\n"+service+"}\n"+r'''
int main(){
 prefs.cpu_freq_mhz=160;role_service();assert(actual_mhz==160&&board.quiet_services==1);
 unsigned writes=clock_writes;role_service();assert(clock_writes==writes&&board.quiet_services==2);
 prefs.powersaving_enabled=false;role_service();assert(actual_mhz==160);
 prefs.cpu_freq_mhz=80;role_service();assert(actual_mhz==80);
 prefs.cpu_freq_mhz=0;role_service();assert(actual_mhz==240);
}
'''
            with self.subTest(role=role):
                self.run_fixture(tests,["-DCONFIG_IDF_TARGET_ESP32S3=1","-DCONFIG_PM_ENABLE=0"])

    def test_rc32_post_boot_nominal_survives_shared_policy_and_explicit_selection(self):
        main=(ROOT/"examples/companion_radio/main.cpp").read_text()
        apply=body(main,"static bool applyCompanionPowerSaving(")
        tests=r'''
int main(){
 // RC32 starts peripherals at 240 MHz, then uses 160 MHz as its Auto nominal.
 // This must take precedence over the generic ESP32_CPU_FREQ=240 fixture.
 board.setCompanionCpuClockPolicy(true);
 assert(applyCompanionPowerSaving(false)&&actual_mhz==160);
 assert(applyCompanionPowerSaving(true)&&actual_mhz==80);
 assert(applyCompanionPowerSaving(false)&&actual_mhz==160);
 // A saved explicit clock remains an operator choice even with PS enabled.
 prefs.cpu_freq_mhz=240;
 assert(applyCompanionPowerSaving(true)&&actual_mhz==240);
 prefs.cpu_freq_mhz=0;
 assert(applyCompanionPowerSaving(false)&&actual_mhz==160);
 // Infrastructure Auto also uses the post-boot nominal in either PS state.
 board.setCompanionCpuClockPolicy(false);
 for(bool ps:{false,true})assert(board.applyCpuFrequencyMHz(0,ps)&&actual_mhz==160);
}
'''
        self.run_fixture("#include <initializer_list>\n"+apply+tests,[
            "-DCONFIG_IDF_TARGET_ESP32S3=1","-DCONFIG_PM_ENABLE=0",
            "-DESP32_POST_BOOT_CPU_FREQ=160","-DCOMPANION_IDF_PM_AVAILABLE=0",
            "-DCOMPANION_BT_MODEM_SLEEP_AVAILABLE=0"])


if __name__=="__main__": unittest.main(verbosity=2)
