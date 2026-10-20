"""Exercise production profile validation and per-tuple airtime on each chip."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from cpp_source import body

ROOT = Path(__file__).resolve().parents[1]


class ProfileValidationBackportTests(unittest.TestCase):
    def test_supported_tuples_protocol_guards_and_operational_airtime(self):
        source = (ROOT / "src/helpers/radiolib/RadioLibWrappers.cpp").read_text()
        methods = "\n".join(body(source, signature).replace("RadioLibWrapper::", "").replace("uint8_t cr)", "uint8_t cr = 0)")
                            for signature in ("bool RadioLibWrapper::validateProfile(",
                                              "uint32_t RadioLibWrapper::getProfileAirtime(",
                                              "uint32_t RadioLibWrapper::getBeaconAirtime("))
        harness = r'''
#include <cassert>
#include <cmath>
#include <RadioProfiles.h>
#define MAX_TRANS_UNIT 255
#define MESH_ENABLE_ETHERNET_WIRE 1
struct RadioLibWrapper {
 mesh::RadioProfiles _profiles;
 bool foreign=false;
 bool supportsMeshtext()const{return foreign;}
 bool supportsEthernetTunnel()const{return foreign;}
 uint16_t profilePreamble(uint8_t)const{return 32;}
 uint32_t getEstAirtimeFor(int){return 777;}
 @METHODS@
};
int main(){
 RadioLibWrapper w;
 mesh::RadioProfileParams p;p.freq=MESH_RADIO_PROFILE_CHIP==1268?433:915;p.bw=125;p.sf=8;p.cr=5;
 assert(w.validateProfile(p));
 p.protocol=mesh::RadioProfileProtocol::Meshtext;assert(!w.validateProfile(p));
 w.foreign=true;assert(w.validateProfile(p));
 p.protocol=mesh::RadioProfileProtocol::Ethernet;assert(w.validateProfile(p));
 w.foreign=false;assert(!w.validateProfile(p));p.protocol=mesh::RadioProfileProtocol::MeshCore;
 p.freq=137;
 assert(w.validateProfile(p)==(MESH_RADIO_PROFILE_CHIP==1276));
 p.freq=149;assert(w.validateProfile(p)==(MESH_RADIO_PROFILE_CHIP==1276));
 p.freq=915;p.bw=406.25f;
 assert(w.validateProfile(p)==(MESH_RADIO_PROFILE_CHIP==2021));
 p.freq=2400;
 assert(w.validateProfile(p)==(MESH_RADIO_PROFILE_CHIP==1121||MESH_RADIO_PROFILE_CHIP==2021));
 p.freq=2300;assert(!w.validateProfile(p));
 p.freq=MESH_RADIO_PROFILE_CHIP==1268?433:915;p.bw=125;p.sf=8;
 w._profiles.primary=p;
 assert(w.getProfileAirtime(0,10)==777); // Preserve the existing live-tuple path.
 w._profiles.secondary.params=p;w._profiles.secondary.mode=mesh::RadioProfileMode::Rx;
 const auto short_air=w.getProfileAirtime(0,1);
#if MESH_RADIO_PROFILE_CHIP==1110||MESH_RADIO_PROFILE_CHIP==1121
 assert(short_air==200);
#else
 assert(short_air<200);
#endif
#if MESH_RADIO_PROFILE_CHIP==1121
 p.freq=2400;p.bw=812.5;p.sf=12;w._profiles.primary=p;
 // Pinned LR11xx forces high-band LDRO: 51 coded blocks * CR5, plus overhead.
 const auto expected=uint32_t(ceil((32+4.25+8+51*5)*4096.0/812.5));
 assert(w.getProfileAirtime(0,255)==expected);
 assert(w.getBeaconAirtime(p,255)==expected);
#endif
 assert(w.getProfileAirtime(2,10)==0&&w.getProfileAirtime(0,-1)==0);
 assert(w.getProfileAirtime(0,256)==0);
 for(float bandwidth:{31.25f,41.67f,41.7f,62.5f,83.34f,101.56f,125.0f,203.125f,250.0f,406.25f,500.0f,812.5f,1000.0f}) {
  p.freq=915;p.bw=bandwidth;
#if MESH_RADIO_PROFILE_CHIP==2021
  assert(w.validateProfile(p));
#endif
 }
}
'''.replace("#include <cassert>", "#include <cassert>\n#include <initializer_list>").replace("@METHODS@", methods)
        with tempfile.TemporaryDirectory(prefix="profile-validation-") as folder:
            cpp = Path(folder) / "test.cpp"
            binary = Path(folder) / "test.exe"
            cpp.write_text(harness)
            for chip in (1262, 1268, 1276, 1272, 68, 1110, 1121, 2021):
                with self.subTest(chip=chip):
                    flags = [] if os.name == "nt" else ["-fsanitize=address,undefined", "-fno-pie", "-no-pie"]
                    built = subprocess.run([os.environ.get("CXX", "g++"), "-std=c++11", *flags,
                        "-DMESH_RADIO_PROFILE_CHIP="+str(chip), "-I", str(ROOT / "src"),
                        str(cpp), "-o", str(binary)], capture_output=True, text=True, timeout=60)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                    self.assertEqual(ran.returncode, 0, ran.stderr)


if __name__ == "__main__": unittest.main()
