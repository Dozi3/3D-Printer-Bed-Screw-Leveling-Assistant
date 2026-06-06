from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BuildScriptTests(unittest.TestCase):
    def test_build_scripts_are_v4_branded_and_checkable(self) -> None:
        for script_name in ("build_standalone.ps1", "build_onefile.ps1", "build_linux_standalone.ps1"):
            with self.subTest(script=script_name):
                text = (ROOT / script_name).read_text(encoding="utf-8")
                self.assertIn("BedScrewSolverV4", text)
                self.assertNotIn("BedScrewSolverV3", text)
                self.assertIn("CheckOnly", text)
                self.assertIn("OutputDir", text)
                self.assertIn("Resolve-ProjectPython", text)

    def test_python_resolution_prefers_workspace_venv(self) -> None:
        text = (ROOT / "build_support.ps1").read_text(encoding="utf-8")

        self.assertIn(".venv\\Scripts\\python.exe", text)
        self.assertIn(".venv/bin/python", text)
        self.assertIn("3.13", text)
        self.assertIn("3.12", text)
        self.assertIn("python", text)

    def test_validation_helper_runs_expected_gates(self) -> None:
        text = (ROOT / "validate_all.ps1").read_text(encoding="utf-8")

        self.assertIn("import PySide6, numpy, nuitka", text)
        self.assertIn("compileall", text)
        self.assertIn("unittest", text)
        self.assertIn("build_onefile.ps1", text)


if __name__ == "__main__":
    unittest.main()
