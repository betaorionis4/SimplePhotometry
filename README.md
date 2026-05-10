# Calibra: Automated Photometric Analysis & Calibration Toolkit

**Version:** 3.0 — 2026-05-10
**Description:** 
An automated, highly robust Python toolkit for extracting scientific-grade photometry, calibrating zero points, obtaining color transformation coefficients for V and B filters, and estimating formal CCD/CMOS errors from astronomical monochrome FITS images. Calibra features **Ensemble Differential Photometry** with multiple comparison stars, **Time-Series Light Curve** generation with AAVSO-format reporting, and integrates **AAVSO VSX** cross-matching to automatically exclude known variable stars from calibration sets.

The code was created with lots of help from Google Antigravity (various agents), guided, tested and debugged by me. I have made several tests to verify the results and ensure the results are reasonable. This code is far from what codes like, e.g., AIJ or Tycho Tracker can do. The purpose is simply to have a playground for understanding the principles of CCD/CMOS based photometry and having a tool to compare to what AIJ or Tycho Tracker provide as fluxes, zero points, etc.

---

## What's New in v3.0

- **Centralized File Management**: A unified persistent `FITS File Manager` has replaced tab-specific file inputs, allowing users to load and preview files across all processing stages.
- **Unified Analysis Workflow**: "Detect & Measure" and "Color & Differential" have been merged into a single `Analysis & Calibration` tab, promoting a logical top-to-bottom photometric workflow.
- **Plate Solving Integration**: Direct integration with the ASTAP command-line engine for non-destructive batch plate-solving (WCS) from within the GUI.
- **Enhanced UI & Aesthetics**: Implemented a modern deep-blue professional theme, consistent visual hierarchy, scrollable window interfaces for smaller screens, and real-time dual-preview panels for transformation and accuracy evaluations.
- **Ensemble Photometry Scaling**: Enhanced workflow for time-series analysis and light curve reporting.

---

## Quick Start
1.  **Installation**:
    ```bash
    pip install numpy scipy matplotlib Pillow astropy photutils astroquery
    ```
2.  **Run**:
    ```bash
    python main.py
    ```
    This launches the **Configuration GUI** where you can set your CCD parameters and file paths. The pipeline supports **Automated Color Calibration**, **Differential Photometry**, and **Time-Series Light Curves** via ATLAS refcat2, APASS DR9, GAIA DR3 and Landolt standard stars.

---

## Documentation
For a more detailed dive into the mathematical principles, theoretical background, and stage-by-stage processing details, please refer to the comprehensive **User Manual**:

👉 **[photometry_user_manual.md](photometry_user_manual.md)**

### Key Manual Sections:
*   **Theory of Operation**: Aperture Photometry vs. Sky Annulus math.
*   **Mathematical Principles**: PSF Fitting, Sub-pixel Refinement, and Error Propagation.
*   **The Processing Pipeline**: From Star Detection to Shift Analysis and color calibration.
*   **Differential Photometry**: Computing formal AAVSO-ready magnitudes ($B$, $V$, $B-V$) using reference stars.
*   **Time-Series & Light Curves**: Ensemble comparison star photometry with formal uncertainty propagation.
*   **GUI Guide**: The new v3.0 FITS File Manager, unified Analysis tab layout, and Plate Solving.

---

## Directory Structure
- `main.py`: The main script to run the pipeline.
- `gui.py`: The v2.0 Configuration GUI (tkinter).
- `photometry/`: Python modules for photometry, calibration, color terms, differential, and time series.
- `photometry_refstars/`: Reference catalogs and online query cache.
- `photometry_output/`: Auto-generated results, logfiles, reports, and light curves.
- `photometry_plots/`: Optional diagnostic PSF plots.
- `calibra_session.json`: Persistent session settings (auto-generated).
