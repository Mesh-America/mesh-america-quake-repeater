#!/usr/bin/env python3
"""Qualify the capture-only startup hook against Arduino3.1.3's actual ISR."""
from pathlib import Path
import unittest

import test_hwcdc_3311_startup_session as reviewed_v3

CORE = Path(__file__).resolve().parent / "fixtures/hwcdc_313"
RAW = (CORE / "HWCDC.cpp").read_text()
PATCHED = reviewed_v3.FIX.patched_hwcdc_startup_source(RAW, version=(3, 1, 3))


class Hwcdc313StartupSessionTests(reviewed_v3.Hwcdc3311StartupSessionTests):
    # Same production owner gate/session assertions and negative controls,
    # with 3.1.3's own ISR and application non-backport cleanup path.
    core, raw, patched, version = CORE, RAW, PATCHED, (3, 1, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
