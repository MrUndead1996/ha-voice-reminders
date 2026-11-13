"""Discover and run the project's standalone test functions."""

import importlib.util
import inspect
from pathlib import Path
import sys
import traceback
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
package = types.ModuleType("custom_components.voice_reminders")
package.__path__ = [str(ROOT / "custom_components" / "voice_reminders")]
sys.modules["custom_components.voice_reminders"] = package


def main() -> int:
    """Run every test function and report the results."""
    passed = failed = skipped = 0
    for path in sorted(Path(__file__).resolve().parent.glob("test_*.py")):
        try:
            spec = importlib.util.spec_from_file_location(path.stem, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception:
            failed += 1
            print(f"FAIL {path.name} (import)")
            traceback.print_exc()
            continue
        for name, function in inspect.getmembers(module, inspect.isfunction):
            if not name.startswith("test_"):
                continue
            try:
                function()
            except unittest.SkipTest as err:
                skipped += 1
                print(f"SKIP {path.name}::{name} ({err})")
            except Exception:
                failed += 1
                print(f"FAIL {path.name}::{name}")
                traceback.print_exc()
            else:
                passed += 1
                print(f"PASS {path.name}::{name}")
    print(f"{passed} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
