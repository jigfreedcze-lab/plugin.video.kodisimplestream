"""Spustí všechny testy doplňku: python tests/run_tests.py

Testy, které si podvrhují moduly Kodi (xbmc, xbmcgui, …), běží každý ve vlastním procesu,
aby si podvržené moduly navzájem nepřepisovaly.
"""
import importlib
import inspect
import io
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

def discover():
    """Sorts tests/test_*.py by style: unittest classes, pytest-like functions, or scripts with stubbed Kodi."""
    unittest_modules, function_modules, scripts = [], [], []
    for filename in sorted(os.listdir(HERE)):
        if not (filename.startswith("test_") and filename.endswith(".py")):
            continue
        source = open(os.path.join(HERE, filename), encoding="utf-8").read()
        if re.search(r"sys\.modules\[\s*[\"']", source):  # sys.modules["xbmc"] = … (stubbed modules)
            scripts.append(filename)
        elif "unittest.TestCase" in source:
            unittest_modules.append(filename[:-3])
        else:
            function_modules.append(filename[:-3])
    return unittest_modules, function_modules, scripts


def main() -> int:
    failed = []
    UNITTEST_MODULES, FUNCTION_MODULES, SCRIPTS = discover()

    for name in UNITTEST_MODULES:
        suite = unittest.defaultTestLoader.loadTestsFromName(f"tests.{name}")
        result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        print(f"{name}: {result.testsRun} testů, {'OK' if result.wasSuccessful() else 'CHYBA'}")
        for _, trace in result.failures + result.errors:
            print(trace)
        if not result.wasSuccessful():
            failed.append(name)

    for name in FUNCTION_MODULES:
        module = importlib.import_module(f"tests.{name}")
        tests = [fn for fn_name, fn in inspect.getmembers(module, inspect.isfunction) if fn_name.startswith("test_")]
        errors = 0
        for fn in tests:
            try:
                fn()
            except Exception as exc:
                errors += 1
                print(f"  {fn.__name__}: {type(exc).__name__}: {exc}")
        print(f"{name}: {len(tests)} testů, {'OK' if not errors else f'{errors} selhalo'}")
        if errors:
            failed.append(name)

    for script in SCRIPTS:
        proc = subprocess.run([sys.executable, "-X", "utf8", os.path.join(HERE, script)],
                              cwd=REPO, capture_output=True, text=True, encoding="utf-8")
        last = (proc.stdout.strip().splitlines() or [""])[-1]
        print(f"{script}: {'OK' if proc.returncode == 0 else 'CHYBA'} – {last}")
        if proc.returncode != 0:
            print(proc.stdout + proc.stderr)
            failed.append(script)

    print("\nVšechny testy prošly." if not failed else f"\nSelhalo: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
