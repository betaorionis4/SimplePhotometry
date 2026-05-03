import os
import csv
import numpy as np
from astropy.coordinates import SkyCoord
import astropy.units as u
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.stats import norm

from photometry.calibration import get_ref_stars

def compute_zero_points(Tbv, Tb_bv, Tv_bv, kB, kV, B_ref, V_ref, b_ref, v_ref, XB_ref, XV_ref):
    # Extinction-corrected instrumental magnitudes
    b0 = b_ref - kB * XB_ref
    v0 = v_ref - kV * XV_ref

    # Colors
    BV_ref = B_ref - V_ref
    bv0_ref = b0 - v0

    # Zero point for color equation
    Z_BV = BV_ref - Tbv * bv0_ref

    # Zero point for B equation
    Z_B = B_ref - (b0 + Tb_bv * BV_ref)

    # Zero point for V equation
    Z_V = V_ref - (v0 + Tv_bv * BV_ref)

    return Z_BV, Z_B, Z_V

def compute_target_BV(b_t, v_t, XB_t, XV_t, Tbv, Tb_bv, Tv_bv, Z_BV, Z_B, Z_V, kB, kV):
    # Extinction-corrected instrumental magnitudes
    b0_t = b_t - kB * XB_t
    v0_t = v_t - kV * XV_t

    # Color
    bv0_t = b0_t - v0_t

    # Standard color
    BV_t = Tbv * bv0_t + Z_BV

    # Standard magnitudes
    B_t = b0_t + Tb_bv * BV_t + Z_B
    V_t = v0_t + Tv_bv * BV_t + Z_V

    return B_t, V_t, BV_t

def run_differential_photometry(csv_b, csv_v, ref_catalog, k_b, k_v, Tbv, Tb_bv, Tv_bv, radius_arcmin=15.0, manual_ref_coord=None):
    """
    Reads two CSVs (B and V), matches the stars, selects a reference star,
    and applies differential photometry to all common stars.
    """
    # 1. Read CSVs
    def read_csv_data(filepath):
        data = []
        if not os.path.exists(filepath): return data
        with open(filepath, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(row)
        return data

    data_b = read_csv_data(csv_b)
    data_v = read_csv_data(csv_v)
    
    if not data_b or not data_v:
        return "Error: Could not read B or V CSV files."
        
    # 2. Match B and V stars
    valid_b = [r for r in data_b if r.get('ra_deg') and r.get('dec_deg') and r.get('mag_inst')]
    ra_b = [float(r['ra_deg']) for r in valid_b]
    dec_b = [float(r['dec_deg']) for r in valid_b]
    
    valid_v = [r for r in data_v if r.get('ra_deg') and r.get('dec_deg') and r.get('mag_inst')]
    ra_v = [float(r['ra_deg']) for r in valid_v]
    dec_v = [float(r['dec_deg']) for r in valid_v]
    
    if not valid_b or not valid_v:
        return "Error: Missing valid coordinates or instrumental magnitudes in input CSVs."
        
    coords_b = SkyCoord(ra=ra_b*u.deg, dec=dec_b*u.deg)
    coords_v = SkyCoord(ra=ra_v*u.deg, dec=dec_v*u.deg)
    
    idx, d2d, _ = coords_b.match_to_catalog_sky(coords_v)
    mask = d2d < 2.0 * u.arcsec
    
    matched_pairs = []
    for i, is_match in enumerate(mask):
        if is_match:
            matched_pairs.append({
                'b': valid_b[i],
                'v': valid_v[idx[i]]
            })
            
    if not matched_pairs:
        return "Error: No matching stars found between B and V results."
        
    # 3. Query Reference Catalog
    # Use the center of the field based on the average of all matched stars
    valid_coords = [float(p['v']['ra_deg']) for p in matched_pairs]
    center_ra = sum(valid_coords) / len(valid_coords)
    valid_dec = [float(p['v']['dec_deg']) for p in matched_pairs]
    center_dec = sum(valid_dec) / len(valid_dec)
    
    ref_stars = get_ref_stars(ref_catalog, center_ra, center_dec, radius_arcmin=radius_arcmin, verbose=False)
    if not ref_stars:
        return f"Error: Could not retrieve reference stars from {ref_catalog}."
        
    coords_cat = SkyCoord(ra=[s['ra_deg'] for s in ref_stars]*u.deg, 
                          dec=[s['dec_deg'] for s in ref_stars]*u.deg)
                          
    coords_pairs = SkyCoord(ra=[float(p['v']['ra_deg']) for p in matched_pairs]*u.deg, 
                            dec=[float(p['v']['dec_deg']) for p in matched_pairs]*u.deg)
                            
    idx_cat, d2d_cat, _ = coords_pairs.match_to_catalog_sky(coords_cat)
    mask_cat = d2d_cat < 2.0 * u.arcsec
    
    # 4. Find the best reference star
    best_ref_pair = None
    best_ref_cat = None
    
    if manual_ref_coord:
        # Manual Mode
        man_coord = SkyCoord(ra=manual_ref_coord[0]*u.deg, dec=manual_ref_coord[1]*u.deg)
        seps = coords_pairs.separation(man_coord)
        best_idx = np.argmin(seps)
        min_sep = seps[best_idx].arcsec
        
        if min_sep > 4.0:
            return f"Error: No star found within 4 arcsec of the manual coordinates (closest is {min_sep:.1f} arcsec away)."
            
        if not mask_cat[best_idx]:
            return "Error: The selected manual star was not found in the reference catalog."
            
        best_ref_pair = matched_pairs[best_idx]
        best_ref_cat = ref_stars[idx_cat[best_idx]]
        
        b_cat = best_ref_cat.get('B_mag', np.nan)
        v_cat = best_ref_cat.get('V_mag', np.nan)
        if np.isnan(b_cat) or np.isnan(v_cat):
            return "Error: The selected manual star does not have valid B or V magnitudes in the reference catalog."
            
    else:
        # Automatic Mode: Criteria: 0.4 <= (B-V) <= 0.8, not saturated, brightest
        min_v_inst = float('inf')
        
        for i, is_match in enumerate(mask_cat):
            if is_match:
                pair = matched_pairs[i]
                cat_star = ref_stars[idx_cat[i]]
                
                # Check for saturation (peak > 55000 ADU)
                peak_b = float(pair['b'].get('peak_adu', 0))
                peak_v = float(pair['v'].get('peak_adu', 0))
                if peak_b > 55000 or peak_v > 55000:
                    continue
                    
                b_cat = cat_star.get('B_mag', np.nan)
                v_cat = cat_star.get('V_mag', np.nan)
                
                if np.isnan(b_cat) or np.isnan(v_cat):
                    continue
                    
                bv_cat = b_cat - v_cat
                if 0.4 <= bv_cat <= 0.8:
                    v_inst = float(pair['v']['mag_inst'])
                    if v_inst < min_v_inst:
                        min_v_inst = v_inst
                        best_ref_pair = pair
                        best_ref_cat = cat_star
                        
        if not best_ref_pair:
            return "Error: No suitable reference star found (0.4 <= B-V <= 0.8, unsaturated)."
        
    # 5. Extract Reference Star Data
    B_ref = best_ref_cat['B_mag']
    V_ref = best_ref_cat['V_mag']
    b_ref = float(best_ref_pair['b']['mag_inst'])
    v_ref = float(best_ref_pair['v']['mag_inst'])
    XB_ref = float(best_ref_pair['b'].get('airmass') or 1.0)
    XV_ref = float(best_ref_pair['v'].get('airmass') or 1.0)
    
    Z_BV, Z_B, Z_V = compute_zero_points(Tbv, Tb_bv, Tv_bv, k_b, k_v, B_ref, V_ref, b_ref, v_ref, XB_ref, XV_ref)
    
    # 6. Apply to all matched targets
    output_rows = []
    
    for pair in matched_pairs:
        b_inst = float(pair['b']['mag_inst'])
        v_inst = float(pair['v']['mag_inst'])
        XB = float(pair['b'].get('airmass') or 1.0)
        XV = float(pair['v'].get('airmass') or 1.0)
        
        B_t, V_t, BV_t = compute_target_BV(b_inst, v_inst, XB, XV, Tbv, Tb_bv, Tv_bv, Z_BV, Z_B, Z_V, k_b, k_v)
        
        output_rows.append({
            'id_v': pair['v']['id'],
            'id_b': pair['b']['id'],
            'ra_deg': pair['v']['ra_deg'],
            'dec_deg': pair['v']['dec_deg'],
            'ra_hms': pair['v'].get('ra_hms', ''),
            'dec_dms': pair['v'].get('dec_dms', ''),
            'B_mag': f"{B_t:.4f}",
            'V_mag': f"{V_t:.4f}",
            'B_V': f"{BV_t:.4f}",
            'v_inst': f"{v_inst:.4f}",
            'b_inst': f"{b_inst:.4f}",
            'airmass_v': f"{XV:.4f}",
            'airmass_b': f"{XB:.4f}"
        })
        
    # 7. Write output
    output_dir = os.path.dirname(csv_v)
    out_csv = os.path.join(output_dir, "differential_photometry_results.csv")
    out_md_report = os.path.join(output_dir, "differential_photometry_report.md")
    out_md_results = os.path.join(output_dir, "differential_photometry_results.md")
    
    with open(out_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=output_rows[0].keys())
        writer.writeheader()
        writer.writerows(output_rows)
        
    with open(out_md_report, 'w') as f:
        f.write("# Differential Photometry Report\n\n")
        f.write("## Reference Star\n")
        f.write(f"- RA/Dec: {best_ref_cat['ra_deg']:.5f}, {best_ref_cat['dec_deg']:.5f}\n")
        f.write(f"- Standard B: {B_ref:.4f}\n")
        f.write(f"- Standard V: {V_ref:.4f}\n")
        f.write(f"- Standard B-V: {B_ref - V_ref:.4f}\n")
        f.write(f"- Instrumental B: {b_ref:.4f}\n")
        f.write(f"- Instrumental V: {v_ref:.4f}\n")
        f.write(f"- Airmass B/V: {XB_ref:.3f} / {XV_ref:.3f}\n\n")
        
        f.write("## Calculated Zero Points\n")
        f.write(f"- $Z_{{BV}}$: {Z_BV:.4f}\n")
        f.write(f"- $Z_B$: {Z_B:.4f}\n")
        f.write(f"- $Z_V$: {Z_V:.4f}\n\n")
        
        f.write(f"Detailed results saved to: `{out_csv}` and `{out_md_results}`\n\n")
        
    # 8. Accuracy Evaluation
    dB_list, dV_list, dBV_list = [], [], []
    for i, is_match in enumerate(mask_cat):
        if is_match:
            cat_star = ref_stars[idx_cat[i]]
            if cat_star['id'] == best_ref_cat['id']:
                continue
                
            b_cat = cat_star.get('B_mag', np.nan)
            v_cat = cat_star.get('V_mag', np.nan)
            
            if np.isnan(b_cat) or np.isnan(v_cat):
                continue
                
            bv_cat = b_cat - v_cat
            row = output_rows[i]
            
            dB_list.append(float(row['B_mag']) - b_cat)
            dV_list.append(float(row['V_mag']) - v_cat)
            dBV_list.append(float(row['B_V']) - bv_cat)
            
    if dB_list and dV_list and dBV_list:
        dB, dV, dBV = np.array(dB_list), np.array(dV_list), np.array(dBV_list)
        
        # Fit Gaussians
        mu_B, std_B = norm.fit(dB)
        mu_V, std_V = norm.fit(dV)
        mu_BV, std_BV = norm.fit(dBV)
        
        # Plotting
        os.makedirs('photometry_plots', exist_ok=True)
        fig, axes = plt.subplots(1, 3, figsize=(15, 5))
        fig.suptitle('Differential Photometry Accuracy vs Catalog', fontsize=16)
        
        def plot_hist(ax, data, mu, std, title, xlabel):
            n, bins, patches = ax.hist(data, bins='auto', density=True, alpha=0.6, color='steelblue')
            xmin, xmax = ax.get_xlim()
            x = np.linspace(xmin, xmax, 100)
            p = norm.pdf(x, mu, std)
            ax.plot(x, p, 'k', linewidth=2)
            title_str = f"{title}\nFit: $\\mu$={mu:.3f}, $\\sigma$={std:.3f}"
            ax.set_title(title_str)
            ax.set_xlabel(xlabel)
            ax.set_ylabel('Density')
            
        plot_hist(axes[0], dB, mu_B, std_B, '$\\Delta B$', '$\\Delta B$ [mag]')
        plot_hist(axes[1], dV, mu_V, std_V, '$\\Delta V$', '$\\Delta V$ [mag]')
        plot_hist(axes[2], dBV, mu_BV, std_BV, '$\\Delta(B-V)$', '$\\Delta(B-V)$ [mag]')
        
        plt.tight_layout()
        plot_path = os.path.join('photometry_plots', 'diff_photometry_deviations.png')
        plt.savefig(plot_path)
        plt.close(fig)
        
        # Append to report
        with open(out_md_report, 'a') as f:
            f.write("## Accuracy Evaluation\n")
            f.write("Comparison of computed magnitudes against catalog values (excluding reference star).\n\n")
            f.write(f"- **$\\Delta B$**: $\\mu$ = {mu_B:.4f}, $\\sigma$ = {std_B:.4f}\n")
            f.write(f"- **$\\Delta V$**: $\\mu$ = {mu_V:.4f}, $\\sigma$ = {std_V:.4f}\n")
            f.write(f"- **$\\Delta(B-V)$**: $\\mu$ = {mu_BV:.4f}, $\\sigma$ = {std_BV:.4f}\n\n")
            f.write(f"Plot saved to `{plot_path}`.\n\n")

    # Sort output rows by RA (increasing)
    output_rows.sort(key=lambda r: float(r['ra_deg']))
    
    with open(out_md_results, 'w') as f:
        f.write("# Differential Photometry Results\n\n")
        f.write("| RA (HMS) / Dec (DMS) | RA (deg) | Dec (deg) | V mag | B mag | B-V |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- |\n")
        for row in output_rows:
            # Replace h, m, s and d, m, s with colons
            ra_str = row['ra_hms'].replace('h', ':').replace('m', ':').replace('s', '')
            dec_str = row['dec_dms'].replace('d', ':').replace('m', ':').replace('s', '')
            
            # Add HMS/DMS first, then deg, then V, B, B-V
            coord_hms = f"{ra_str} / {dec_str}"
            f.write(f"| {coord_hms} | {float(row['ra_deg']):.5f} | {float(row['dec_deg']):.5f} | {row['V_mag']} | {row['B_mag']} | {row['B_V']} |\n")
        
    return f"Success! Used 1 reference star to calibrate {len(output_rows)} stars. Saved to {out_csv}."
