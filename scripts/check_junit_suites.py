#!/usr/bin/env python3
"""Fail unless every named PlatformIO test suite ran and passed in a JUnit report.

`pio test -f <suite>` can select nothing and still exit 0, and a report can list fewer suites than
were asked for. This script counts the named suites itself, so "zero or fewer than expected ran" is a
failure whatever the exit status of pio was.

usage: check_junit_suites.py REPORT.xml SUITE [SUITE ...]

A suite counts as present when a <testsuite> or <testcase> in the report carries its name in its
name or classname attribute. It passes when none of its test cases failed, errored or were skipped
and at least one test case ran.
"""
import sys
import xml.etree.ElementTree as ET


def tally(root, suites):
    seen = {s: {"cases": 0, "bad": 0} for s in suites}
    for case in root.iter("testcase"):
        ident = " ".join(filter(None, [case.get("classname"), case.get("name"),
                                       (case.get("file") or "")]))
        for suite in suites:
            if suite in ident:
                seen[suite]["cases"] += 1
                if (case.find("failure") is not None or case.find("error") is not None
                        or case.find("skipped") is not None):
                    seen[suite]["bad"] += 1
    # Some reports name only the <testsuite>; attribute its totals to the suite it names.
    for ts in root.iter("testsuite"):
        name = ts.get("name") or ""
        for suite in suites:
            if suite in name and seen[suite]["cases"] == 0:
                tests = int(ts.get("tests") or 0)
                bad = sum(int(ts.get(k) or 0) for k in ("failures", "errors", "skipped"))
                seen[suite]["cases"] += tests
                seen[suite]["bad"] += bad
    return seen


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    report, suites = argv[1], argv[2:]
    root = ET.parse(report).getroot()
    seen = tally(root, suites)
    failed = False
    for suite in suites:
        s = seen[suite]
        status = "ok" if s["cases"] > 0 and s["bad"] == 0 else "FAIL"
        failed = failed or status != "ok"
        print(f"{status:4} {suite}: {s['cases']} test case(s), {s['bad']} failed/errored/skipped")
    if failed:
        print(f"::error::expected all {len(suites)} suites to run and pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
