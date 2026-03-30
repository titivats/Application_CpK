# Machine Cpk Capability Reporter

Desktop application for entering repeatability measurements across dynamic axis tabs, calculating `Cp / Cpk / Pp / Ppk`, previewing capability charts, and exporting a customer-ready PDF report.

## Features

- Enter `30` measurements for each axis
- Add extra axis tabs and rename them for studies such as `X1`, `X2`, `Y1`, `Y2`
- Remove axis tabs that are not needed from the current study
- Set `LSL`, `Target`, `USL`, and required `Cpk`
- Load `30` values manually or query them directly from Excel
- Preview capability charts styled like a Minitab-style report
- Use static preview rendering for smoother scrolling and resize behavior
- Export a multi-page PDF with summary and per-axis analysis

## Run From Source

1. Activate the virtual environment if needed.
2. Start the app:

```bat
run_cpk_app.bat
```

Or:

```bat
venv\Scripts\python.exe main.py
```

## Build EXE

```bat
build_exe.bat
```

The packaged executable will be created here:

```text
dist\MachineCpkReporter.exe
```

## Notes

- The app runs as a desktop GUI and can be packaged as a standalone `.exe`.
- PDF export is generated directly by the desktop app using `reportlab`.
- Charts are generated with `matplotlib`.

## Main Files

- `main.py` - desktop app launcher
- `desktop_main.py` - desktop runtime bootstrap
- `cpk_ui.py` - desktop GUI flow and application shell
- `cpk_desktop/assets.py` - runtime asset path helpers
- `cpk_desktop/axes.py` - axis naming, validation, and color helpers
- `cpk_desktop/widgets.py` - reusable scroll and preview widgets
- `cpk_reporting.py` - chart rendering and PDF generation
- `cpk_tool/analysis.py` - Cpk calculation logic
