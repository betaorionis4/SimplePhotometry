import csv
import re
import os
import numpy as np
from astropy.coordinates import SkyCoord
import astropy.units as u
from astropy.stats import sigma_clipped_stats
from astroquery.vizier import Vizier
from astropy.table import Table

def fetch_online_catalog(ra_deg, dec_deg, radius_arcmin=15, catalog_name="ATLAS", verbose=True):
    """
    Queries VizieR for photometric reference stars.
    Supports ATLAS (ATLAS-RefCat2) and APASS.
    """
    if verbose:
        print(f"Fetching {catalog_name} catalog from VizieR for RA={ra_deg:.4f}, Dec={dec_deg:.4f}...")
    
    # Configure Vizier
    # ATLAS-RefCat2: J/ApJ/867/105
    # APASS DR9: II/336
    viz_map = {
        "ATLAS": "J/ApJ/867/105",
        "APASS": "II/336"
    }
    
    if catalog_name not in viz_map:
        print(f"Error: Unknown catalog {catalog_name}. Defaulting to ATLAS.")
        catalog_id = viz_map["ATLAS"]
    else:
        catalog_id = viz_map[catalog_name]

    # Increase timeout and configure Vizier
    from astropy.utils.data import Conf
    Conf.remote_timeout.set(60) # 60 seconds timeout
    
    v = Vizier(columns=['*'], row_limit=-1)
    coord = SkyCoord(ra=ra_deg, dec=dec_deg, unit=(u.deg, u.deg), frame='icrs')
    
    try:
        if verbose:
            print(f"Querying VizieR {catalog_id}...")
        result = v.query_region(coord, radius=radius_arcmin * u.arcmin, catalog=catalog_id)
    except Exception as e:
        print(f"Error querying VizieR: {e}")
        return []

    if not result or len(result) == 0:
        print(f"VizieR returned no tables for {catalog_name}. Trying fallback ID...")
        # Fallback for ATLAS if specific ID fails
        if catalog_name == "ATLAS":
            try:
                result = v.query_region(coord, radius=radius_arcmin * u.arcmin, catalog="atlas")
                if not result:
                    return []
            except:
                return []
        else:
            return []

    table = result[0]
    print(f"VizieR returned {len(table)} raw rows from {catalog_name}.")
    ref_stars = []
    
    # Check available columns once
    cols = table.colnames
    
    for row in table:
        try:
            if catalog_name == "ATLAS":
                ra = float(row['RA_ICRS'])
                dec = float(row['DE_ICRS'])
                
                g = float(row['gmag']) if 'gmag' in cols else np.nan
                r = float(row['rmag']) if 'rmag' in cols else np.nan
                
                # Transformations for Pan-STARRS (ATLAS) to Johnson V/B
                # Using Tonry et al. (2012) coefficients
                if not np.isnan(g) and not np.isnan(r):
                    color = g - r
                    # V = g - 0.011 - 0.494*(g-r) - 0.003*(g-r)^2
                    v_mag = g - 0.011 - 0.494 * color - 0.003 * (color**2)
                    # B = g + 0.195 + 0.490*(g-r) + 0.165*(g-r)^2
                    b_mag = g + 0.195 + 0.490 * color + 0.165 * (color**2)
                else:
                    v_mag = g if not np.isnan(g) else np.nan
                    b_mag = r if not np.isnan(r) else np.nan
                
                # Check for explicit Vmag/Bmag if they exist
                if 'Vmag' in cols and not np.isnan(float(row['Vmag'])): v_mag = float(row['Vmag'])
                if 'Bmag' in cols and not np.isnan(float(row['Bmag'])): b_mag = float(row['Bmag'])

            else:
                # APASS columns: RAJ2000, DEJ2000, Vmag, Bmag
                ra = float(row['RAJ2000'])
                dec = float(row['DEJ2000'])
                v_mag = float(row['Vmag']) if 'Vmag' in cols else np.nan
                b_mag = float(row['Bmag']) if 'Bmag' in cols else np.nan

            # Filtering: Only keep stars brighter than 18 mag (user's limit ~16)
            if not np.isnan(v_mag) and v_mag < 18.0:
                ref_stars.append({
                    'id': f"online_{len(ref_stars)}",
                    'ra_deg': ra,
                    'dec_deg': dec,
                    'V_mag': v_mag,
                    'B_mag': b_mag
                })
        except:
            continue

    if verbose:
        print(f"Successfully retrieved {len(ref_stars)} stars from {catalog_name}.")
    return ref_stars

def get_cached_catalog(ra, dec, radius, catalog_name, cache_dir="photometry_refstars/cache", verbose=True):
    """
    Checks for a cached version of the catalog query.
    """
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)
        
    cache_file = os.path.join(cache_dir, f"{catalog_name}_{ra:.3f}_{dec:.3f}_{radius}.csv")
    
    if os.path.exists(cache_file):
        if verbose:
            print(f"Loading cached catalog from {cache_file}")
        ref_stars = []
        with open(cache_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                ref_stars.append({
                    'id': row['id'],
                    'ra_deg': float(row['ra_deg']),
                    'dec_deg': float(row['dec_deg']),
                    'V_mag': float(row['V_mag']),
                    'B_mag': float(row['B_mag'])
                })
        return ref_stars
    return None

def save_to_cache(ref_stars, ra, dec, radius, catalog_name, cache_dir="photometry_refstars/cache", verbose=True):
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)
    
    cache_file = os.path.join(cache_dir, f"{catalog_name}_{ra:.3f}_{dec:.3f}_{radius}.csv")
    with open(cache_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'ra_deg', 'dec_deg', 'V_mag', 'B_mag'])
        writer.writeheader()
        writer.writerows(ref_stars)
    if verbose:
        print(f"Saved catalog to cache: {cache_file}")

def read_reference_catalog(csv_path):
    """
    Reads the AAVSO reference star CSV.
    Extracts RA (deg), Dec (deg), V mag, and B mag.
    """
    ref_stars = []
    
    if not os.path.exists(csv_path):
        print(f"Error: Reference catalog not found at {csv_path}")
        return ref_stars

    with open(csv_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                auid = row.get('AUID', 'Unknown')
                ra_str = row.get('RA', '')
                dec_str = row.get('Dec', '')
                v_str = row.get('V', '')
                bv_str = row.get('B-V', '0.0')
                
                # Extract decimal degrees inside brackets e.g. [144.38566589°]
                ra_match = re.search(r'\[(.*?)[°]\]', ra_str)
                dec_match = re.search(r'\[(.*?)[°]\]', dec_str)
                
                if ra_match and dec_match:
                    ra_deg = float(ra_match.group(1))
                    dec_deg = float(dec_match.group(1))
                else:
                    # Try direct float conversion
                    ra_deg = float(ra_str)
                    dec_deg = float(dec_str)
                
                # Extract magnitudes, ignoring uncertainties in parentheses
                v_mag = float(v_str.split()[0]) if v_str else np.nan
                bv_mag = float(bv_str.split()[0]) if bv_str else 0.0
                
                # Calculate B magnitude: B = (B-V) + V
                b_mag = bv_mag + v_mag
                
                ref_stars.append({
                    'id': auid,
                    'ra_deg': ra_deg,
                    'dec_deg': dec_deg,
                    'V_mag': v_mag,
                    'B_mag': b_mag
                })
            except Exception:
                continue
                
    return ref_stars

def get_ref_stars(ref_catalog_file, center_ra=None, center_dec=None, radius_arcmin=15, verbose=True):
    """
    Helper function to load stars from local CSV or Online Catalog.
    """
    ref_stars = []
    if ref_catalog_file.upper() in ["ATLAS", "APASS"] and center_ra is not None and center_dec is not None:
        cat_name = ref_catalog_file.upper()
        ref_stars = get_cached_catalog(center_ra, center_dec, radius_arcmin, cat_name, verbose=verbose)
        if not ref_stars:
            ref_stars = fetch_online_catalog(center_ra, center_dec, radius_arcmin, cat_name, verbose=verbose)
            if ref_stars:
                save_to_cache(ref_stars, center_ra, center_dec, radius_arcmin, cat_name, verbose=verbose)
    else:
        ref_stars = read_reference_catalog(ref_catalog_file)
    return ref_stars

def match_and_calibrate(results, ref_catalog_file, filter_name, tolerance_arcsec=2.0, 
                        default_zp=23.399, run_new_calibration=True, output_report=None,
                        center_ra=None, center_dec=None, snr_threshold=10.0,
                        print_to_console=True):
    print("\n=================================================================")
    print("--- 4. Zero Point Calibration ---")
    print("=================================================================\n")
    
    # Calculate instrumental magnitudes
    for rs in results:
        net_flux = rs.get('net_flux', 0)
        if net_flux > 0:
            rs['mag_inst'] = -2.5 * np.log10(net_flux)
        else:
            rs['mag_inst'] = np.nan
            
    if not run_new_calibration:
        print(f"Skipping new calibration. Applying default Zero Point: {default_zp:.3f}")
        for rs in results:
            if 'mag_inst' in rs and not np.isnan(rs['mag_inst']):
                rs['mag_calibrated'] = rs['mag_inst'] + default_zp
                rs['mag_calibrated_err'] = rs.get('mag_inst_err', np.nan)
            else:
                rs['mag_calibrated'] = np.nan
                rs['mag_calibrated_err'] = np.nan
        return
        
    ref_stars = get_ref_stars(ref_catalog_file, center_ra, center_dec, verbose=print_to_console)

    if not ref_stars:
        print(f"WARNING: No reference stars loaded. Applying default Zero Point: {default_zp:.3f}")
        for rs in results:
            if 'mag_inst' in rs and not np.isnan(rs['mag_inst']):
                rs['mag_calibrated'] = rs['mag_inst'] + default_zp
                rs['mag_calibrated_err'] = rs.get('mag_inst_err', np.nan)
            else:
                rs['mag_calibrated'] = np.nan
                rs['mag_calibrated_err'] = np.nan
        return
        
    mag_key = 'B_mag' if 'B' in filter_name.upper() else 'V_mag'
    print(f"Using {mag_key} from reference catalog for calibration.")
    print(f"SNR Threshold for calibration stars: {snr_threshold}")
    
    ref_ra = [s['ra_deg'] for s in ref_stars]
    ref_dec = [s['dec_deg'] for s in ref_stars]
    ref_coords = SkyCoord(ra=ref_ra*u.deg, dec=ref_dec*u.deg)
    ref_mags = np.array([s[mag_key] for s in ref_stars])
    
    det_valid = []
    det_ra = []
    det_dec = []
    for rs in results:
        # NEW: Filter by SNR threshold for calibration
        if 'ra_deg' in rs and 'dec_deg' in rs and rs['ra_deg'] != "" and not np.isnan(rs.get('mag_inst', np.nan)):
            if rs.get('snr', 0) >= snr_threshold:
                det_valid.append(rs)
                det_ra.append(float(rs['ra_deg']))
                det_dec.append(float(rs['dec_deg']))
            
    if not det_valid:
        print(f"WARNING: No detected stars with SNR >= {snr_threshold} to match.")
        for rs in results:
            rs['mag_calibrated'] = np.nan
        return
        
    det_coords = SkyCoord(ra=det_ra*u.deg, dec=det_dec*u.deg)
    
    idx, d2d, d3d = det_coords.match_to_catalog_sky(ref_coords)
    
    match_mask = d2d.arcsec < tolerance_arcsec
    matched_det = np.array(det_valid)[match_mask]
    matched_ref_mags = ref_mags[idx[match_mask]]
    
    if len(matched_det) == 0:
        print(f"WARNING: No matches found within {tolerance_arcsec} arcsec. Applying default Zero Point: {default_zp:.3f}")
        for rs in results:
            if 'mag_inst' in rs and not np.isnan(rs['mag_inst']):
                rs['mag_calibrated'] = rs['mag_inst'] + default_zp
                rs['mag_calibrated_err'] = rs.get('mag_inst_err', np.nan)
            else:
                rs['mag_calibrated'] = np.nan
                rs['mag_calibrated_err'] = np.nan
        return
        
    print(f"Found {len(matched_det)} matches with reference catalog.")
    
    report_lines = []
    report_lines.append(f"# Zero Point Calibration Report")
    report_lines.append(f"**Filter**: {filter_name}")
    report_lines.append(f"**Matches Found**: {len(matched_det)}\n")
    report_lines.append(f"| Match ID | Ref Mag | Inst Mag | Zero Point |")
    report_lines.append(f"| :--- | :--- | :--- | :--- |")
    
    zps = []
    for i, det_rs in enumerate(matched_det):
        mag_inst = det_rs['mag_inst']
        mag_ref = matched_ref_mags[i]
        zp = mag_ref - mag_inst
        zps.append(zp)
        
        # Add SNR info to the printout
        snr = det_rs.get('snr', 0)
        if print_to_console:
            print(f"  Match: {det_rs['id']} (SNR: {snr:.1f}) -> ZP: {zp:.3f} (Ref: {mag_ref:.3f}, Inst: {mag_inst:.3f})")
        report_lines.append(f"| {det_rs['id']} | {mag_ref:.3f} | {mag_inst:.3f} | {zp:.3f} |")
        
    zps = np.array(zps)
    mean_zp, median_zp, std_zp = sigma_clipped_stats(zps, sigma=3.0, maxiters=5)
    
    print(f"\nCalculated Zero Point: {median_zp:.3f} ± {std_zp:.3f} (Median)")
    
    report_lines.append(f"\n## Results")
    report_lines.append(f"- **Calculated Median Zero Point**: {median_zp:.3f}")
    report_lines.append(f"- **Standard Deviation**: ± {std_zp:.3f}\n")
    
    if output_report:
        with open(output_report, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report_lines))
    
    for rs in results:
        if 'mag_inst' in rs and not np.isnan(rs['mag_inst']):
            rs['mag_calibrated'] = rs['mag_inst'] + median_zp
            mag_inst_err = rs.get('mag_inst_err', np.nan)
            if not np.isnan(mag_inst_err):
                rs['mag_calibrated_err'] = np.sqrt(mag_inst_err**2 + std_zp**2)
            else:
                rs['mag_calibrated_err'] = np.nan
        else:
            rs['mag_calibrated'] = np.nan
            rs['mag_calibrated_err'] = np.nan

if __name__ == '__main__':
    # Test the parser
    test_file = r'c:\Astro\StarID\photometry_refstars\reference_stars.csv'
    print(f"Testing parsing of: {test_file}")
    stars = read_reference_catalog(test_file)
    print(f"Successfully loaded {len(stars)} reference stars:")
    for s in stars[:10]:
        print(f"ID: {s['id']}, RA: {s['ra_deg']:.4f}, Dec: {s['dec_deg']:.4f}, V: {s['V_mag']:.3f}, B: {s['B_mag']:.3f}")
