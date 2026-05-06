# Color Transformation Calibration Report

Analyzed 958 common stars.
Applied 2-sigma iterative outlier rejection.
Applied Extinction Correction:
- B-Filter: k=0.35, X=1.055
- V-Filter: k=0.20, X=1.109

## Derived Coefficients (Cleaned)
- **$\mu$ (Color Scale):** 0.9326  (R=0.926)
- **$\psi$ (B-Term):** 0.1546  (R=0.422)
- **$\epsilon$ (V-Term):** 0.0128  (R=0.096)

## Transformation Equations
Using these coefficients, your calibrated magnitudes are:
1. $(B-V)_{std} = 0.933 \cdot (b-v)_{corr} + -0.122$
2. $B_{std} = b_{corr} + 0.155 \cdot (B-V)_{std} + 23.968$
3. $V_{std} = v_{corr} + 0.013 \cdot (B-V)_{std} + 24.247$
*(Note: v_corr and b_corr are the instrumental magnitudes corrected for extinction)*

![Color Diagnostic Plots](color_plots.png)
