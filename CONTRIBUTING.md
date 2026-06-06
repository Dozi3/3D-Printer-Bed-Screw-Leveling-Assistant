# Contributing

Thanks for taking the time to improve Bed Screw Solver V4.

## Development Setup

Use a local virtual environment and keep generated files out of commits:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run the full validation gate before opening a pull request:

```powershell
.\validate_all.ps1
```

## Pull Request Expectations

- Keep solver behavior changes covered by focused tests.
- Treat baseline plane-fit output as the primary regression contract.
- Keep physical-response behavior clearly advisory.
- Do not commit `.venv`, `dist`, `dist-linux`, `dist-validation`, `dist-release`, archives, or executable outputs.
- Explain user-visible behavior changes in the PR description.
- By contributing, you agree that your contribution is provided under the project license in [LICENSE](LICENSE).

## Reporting Issues

Please include:

- app version or commit SHA
- operating system
- mesh dimensions and bounds
- screw count and coordinate convention
- whether the physical-response model was enabled
- expected result and actual result
