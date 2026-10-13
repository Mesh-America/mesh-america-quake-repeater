#!/usr/bin/env python3
"""Read-only lab A/B: compile temporary decoder copies, never edit firmware.

This diagnostic intentionally reports failing cases rather than teaching CI to
accept a known decoding defect. The ordinary test_morse_rx.py remains the
shipping-code regression suite.
"""
from pathlib import Path
import argparse
import unittest

from test_morse_tx import compile_run
from test_radio_receive_contract import method

ROOT = Path(__file__).resolve().parents[1]


def experimental_estimator(original, *, seed=True):
    """Core's proposed two-level estimator, applied only to a temporary copy."""
    if "if (_keyed && !_floor_settled)" in original:
        return original if seed else original.replace("      _signal = rssi_dbm;\n", "", 1)
    if "if (_keyed && threshold < _signal - 5.0f)" in original:
        return original if seed else original.replace("      _signal = rssi_dbm;\n", "", 1)
    threshold = "const float threshold = _noise + rise - (_keyed ? 3.0f : 0.0f);"
    signal = "if (_keyed && rssi_dbm > _noise + 6.0f)"
    off = "      _keyed = false;\n      _last_edge = edge_at;"
    on = "      _keyed = true;\n      _last_edge = edge_at;"
    assert all(fragment in original for fragment in (threshold, signal, off, on)), "update experiment for the current decoder"
    header = original.replace(threshold, "float threshold = _noise + rise - (_keyed ? 3.0f : 0.0f);\n    if (_keyed) threshold=fmaxf(threshold,_signal-5.0f);")
    header = header.replace(signal, "if (_keyed && raw_keyed && rssi_dbm > _noise + 6.0f)")
    header = header.replace(off, "      _keyed = false;\n      _noise=rssi_dbm; _signal=_noise+12.0f;\n      _last_edge = edge_at;")
    if seed:
        header = header.replace(on, "      _keyed = true; _signal=rssi_dbm;\n      _last_edge = edge_at;")
    return header


def seeded_peak_baseline(original):
    """Recreate the earlier approved peak-5 estimator for historical A/B."""
    if "if (_keyed && !_floor_settled)" not in original:
        return original
    header=original.replace(method(original,"if (_keyed && !_floor_settled)"),
                            "if (_keyed && threshold < _signal - 5.0f) threshold = _signal - 5.0f;")
    header=header.replace("const float span = _signal - _noise;\n    float rise = span * 0.5f;",
                          "float rise = (_signal - _noise) * 0.35f;")
    header=header.replace("    if (rise < 6.0f) rise = 6.0f;",
                          "    if (rise < 6.0f) rise = 6.0f;\n    if (rise > 24.0f) rise = 24.0f;")
    header=header.replace("    const uint16_t maximum_debounce = raw_keyed ? 5 : 10;\n    if (debounce > maximum_debounce) debounce = maximum_debounce;",
                          "    if (debounce > 5) debounce = 5;")
    return header


def legacy_estimator(original):
    """Reconstruct the pre-fix behavior as an executable negative control."""
    header = original
    if "if (_keyed && !_floor_settled)" in header:
        header=header.replace(method(header,"if (_keyed && !_floor_settled)"),"")
        header=header.replace("const float span = _signal - _noise;\n    float rise = span * 0.5f;",
                              "float rise = (_signal - _noise) * 0.35f;")
        header=header.replace("    if (rise < 6.0f) rise = 6.0f;",
                              "    if (rise < 6.0f) rise = 6.0f;\n    if (rise > 24.0f) rise = 24.0f;")
    header = header.replace("    if (_keyed && threshold < _signal - 5.0f) threshold = _signal - 5.0f;\n", "")
    header = header.replace("float threshold = _noise + rise - (_keyed ? 3.0f : 0.0f);",
                            "const float threshold = _noise + rise - (_keyed ? 3.0f : 0.0f);")
    header = header.replace("if (_keyed && raw_keyed && rssi_dbm > _noise + 6.0f)",
                            "if (_keyed && rssi_dbm > _noise + 6.0f)")
    header = header.replace("      _signal = rssi_dbm;\n", "", 1)
    header = header.replace("      _noise = rssi_dbm;\n      _signal = _noise + 12.0f; // do not hide the next, weaker mark with an old peak\n", "")
    header=header.replace("      _noise = rssi_dbm;\n      _floor_settled = true;\n      _signal = _noise + 12.0f; // do not hide the next, weaker mark with an old peak\n","")
    quiet = method(header, "if (!_keyed && !raw_keyed && !_candidate_valid)")
    header = header.replace(quiet, quiet.replace("      _signal = _noise + 12.0f;\n", ""))
    return header


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--estimator", action="store_true", help="test the isolated seeded peak-relative design and existing decoder regressions")
    parser.add_argument("--mark-fade", action="store_true", help="quantify strong carrier fades against an isolated uncapped midpoint proposal")
    parser.add_argument("--hybrid-matrix",action="store_true",help="test provisional span/first-OFF hybrid variants without editing firmware")
    parser.add_argument("--variant-filter",help="Run only isolated variant names containing this string")
    parser.add_argument("--actual-matrix",action="store_true",help="report the current shipping decoder's exact capture and internal edges")
    args = parser.parse_args()
    code = (ROOT / "test/fixtures/morse_rx_floor_step.cpp").read_text(encoding="ascii")
    original = (ROOT / "src/helpers/MorseRx.h").read_text(encoding="utf-8")
    tx = (ROOT / "src/helpers/MorseTx.h").read_text(encoding="utf-8")
    if args.actual_matrix:
        fixture=(ROOT / "test/fixtures/morse_rx_mark_fade.cpp").read_text(encoding="ascii")
        report=compile_run(unittest.TestCase(),fixture,flags=("-DMESH_MORSE_MAX_WPM=240","-DMORSE_HYBRID_MATRIX"))
        rows=[row for row in report.splitlines() if "required=1" in row]
        print(f"Actual matrix {sum('correct=1' in row for row in rows)}/{len(rows)} exact captures")
        print("\n".join(row for row in rows if "correct=0" in row or "cuts=0 " not in row or "false_marks=0 " not in row))
        return
    if args.mark_fade or args.hybrid_matrix:
        fixture=(ROOT / "test/fixtures/morse_rx_mark_fade.cpp").read_text(encoding="ascii")
        original=seeded_peak_baseline(original)
        midpoint=original.replace("(_signal - _noise) * 0.35f","(_signal - _noise) * 0.5f")
        midpoint=midpoint.replace("    if (rise > 24.0f) rise = 24.0f;\n","")
        midpoint=midpoint.replace("    if (_keyed && threshold < _signal - 5.0f) threshold = _signal - 5.0f;\n","")
        assert midpoint!=original,"update midpoint experiment for actual source"
        variants=[("current seeded peak-5dB",original),("isolated uncapped midpoint / minus3dB OFF",midpoint)]
        if args.hybrid_matrix:
            anchor="    const bool raw_keyed = rssi_dbm >= threshold;"
            peak="    if (_keyed && _signal-_noise <= 40.0f && threshold < _signal-5.0f) threshold=_signal-5.0f;\n"
            hybrid=midpoint.replace(anchor,peak+anchor)
            first_only=hybrid.replace("_keyed && _signal-_noise <= 40.0f","_keyed && !_have_floor_after_mark && _signal-_noise <= 40.0f")
            first_only=first_only.replace("  bool _active = false, _keyed = false, _have_noise = false;",
                                          "  bool _have_floor_after_mark=false;\n  bool _active = false, _keyed = false, _have_noise = false;")
            first_only=first_only.replace("    _have_noise = _candidate_valid = _keyed = false;",
                                          "    _have_floor_after_mark=false;\n    _have_noise = _candidate_valid = _keyed = false;")
            first_only=first_only.replace("      _keyed = false;\n      _noise = rssi_dbm;\n",
                                          "      _keyed = false;\n      _have_floor_after_mark=true;\n      _noise = rssi_dbm;\n")
            variants += [("hybrid span<=40 peak bound",hybrid),("hybrid bound only before first OFF",first_only)]
            falling_quarter=first_only.replace("    if (debounce > 5) debounce = 5;",
                                               "    if (raw_keyed && debounce > 5) debounce = 5;")
            assert falling_quarter!=first_only,"update isolated falling debounce for actual decoder"
            variants.append(("first-OFF hybrid with uncapped quarter-dot falling debounce",falling_quarter))
            falling_ten=first_only.replace("    if (debounce > 5) debounce = 5;",
                                           "    if (debounce > (raw_keyed?5:10)) debounce = raw_keyed?5:10;")
            smooth=first_only.replace("    if (_keyed && !_have_floor_after_mark && _signal-_noise <= 40.0f && threshold < _signal-5.0f) threshold=_signal-5.0f;",
                                     "    if (_keyed && !_have_floor_after_mark) {\n      const float margin=fmaxf(5.0f,(_signal-_noise-30.0f)*0.5f);\n      if (threshold < _signal-margin) threshold=_signal-margin;\n    }")
            assert smooth!=first_only,"update smooth provisional margin experiment"
            variants += [("first-OFF hybrid with falling debounce capped10ms",falling_ten),
                         ("first-OFF smooth provisional margin",smooth)]
            smooth_ten=smooth.replace("    if (debounce > 5) debounce = 5;",
                                      "    if (debounce > (raw_keyed?5:10)) debounce = raw_keyed?5:10;")
            variants.append(("smooth provisional margin plus falling debounce capped10ms",smooth_ten))
        for name,header in variants:
            if args.variant_filter and args.variant_filter not in name:
                continue
            print(name)
            flags=("-DMESH_MORSE_MAX_WPM=240","-DMORSE_HYBRID_MATRIX") if args.hybrid_matrix else ()
            result=compile_run(unittest.TestCase(),fixture,flags=flags,headers={"helpers/MorseRx.h":header,"helpers/MorseTx.h":tx})
            if not args.hybrid_matrix:
                print(result,end="")
                continue
            rows=[row for row in result.splitlines() if "required=1" in row]; failed=[row for row in rows if "correct=0" in row]
            print(f"Matrix {len(rows)-len(failed)}/{len(rows)} exact for SNR>=6dB; failures:")
            print("\n".join(failed[:24]))
            for test_fixture in ("morse_rx_decoder.cpp","morse_rx_decay_shoulder.cpp","morse_rx_floor_step.cpp"):
                test_code=(ROOT / "test/fixtures" / test_fixture).read_text(encoding="ascii")
                extra=("-DMORSE_SHOULDER_REQUIRE_PASS",) if "shoulder" in test_fixture else (("-DMORSE_ESTIMATOR_REQUIRE_PASS","-DMORSE_ESTIMATOR_EXTENDED") if "floor_step" in test_fixture else ())
                try:
                    compile_run(unittest.TestCase(),test_code,flags=("-DMESH_MORSE_MAX_WPM=240",)+extra,
                                headers={"helpers/MorseRx.h":header,"helpers/MorseTx.h":tx})
                    print(test_fixture+": PASS")
                except AssertionError as error:
                    print(test_fixture+": FAIL "+str(error)[:250])
                    if "floor_step" in test_fixture:
                        report=compile_run(unittest.TestCase(),test_code,flags=("-DMESH_MORSE_MAX_WPM=240","-DMORSE_ESTIMATOR_EXTENDED"),
                                           headers={"helpers/MorseRx.h":header,"helpers/MorseTx.h":tx})
                        print("\n".join(row for row in report.splitlines() if 'capture="SOS TEST 25"' not in row and 'capture="SOS TEST 25 "' not in row))
                    elif "decoder" in test_fixture and ("quarter-dot" in name or "capped10ms" in name):
                        tail=test_code.replace('rx.pattern("."); rx.quiet(10);','rx.pattern("."); rx.quiet(14);')
                        try:
                            compile_run(unittest.TestCase(),tail,flags=("-DMESH_MORSE_MAX_WPM=240",),
                                        headers={"helpers/MorseRx.h":header,"helpers/MorseTx.h":tx})
                            print("Full decoder with explicitly confirmed14ms OFF tail: PASS")
                        except AssertionError as tail_error:
                            print("Full decoder with confirmed14ms OFF tail: FAIL "+str(tail_error)[:250])
        return
    cap_expression = "if (rise > 24.0f) rise = 24.0f;"
    signal_expression = "if (_keyed && rssi_dbm > _noise + 6.0f)"
    if args.estimator:
        header = experimental_estimator(original)
        print("Current approved estimator; this experiment does not edit shipping firmware")
        headers = {"helpers/MorseRx.h": header, "helpers/MorseTx.h": tx}
        print(compile_run(unittest.TestCase(), code,
              flags=("-DMESH_MORSE_MAX_WPM=240", "-DMORSE_ESTIMATOR_EXTENDED", "-DMORSE_ESTIMATOR_REQUIRE_PASS"),
              headers=headers), end="")
        normal = (ROOT / "test/fixtures/morse_rx_decoder.cpp").read_text(encoding="ascii")
        print(compile_run(unittest.TestCase(), normal, headers=headers), end="")
        return
    original = legacy_estimator(original)
    assert cap_expression in original and signal_expression in original, "update experiment for the current decoder"
    for freeze in (False, True):
        for cap in (24, 40, 60):
            header = original.replace(cap_expression, f"if (rise > {cap}.0f) rise = {cap}.0f;")
            if freeze:
                header = header.replace(signal_expression, "if (_keyed && raw_keyed && rssi_dbm > _noise + 6.0f)")
            print(f"CAP {cap}; freeze signal during OFF debounce: {freeze}")
            print(compile_run(unittest.TestCase(), code, headers={"helpers/MorseRx.h": header,
                                                                 "helpers/MorseTx.h": tx}), end="")


if __name__ == "__main__":
    main()
