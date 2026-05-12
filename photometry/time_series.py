import os
import csv
import numpy as np
import matplotlib.pyplot as plt
from astropy.io import fits
from astropy.coordinates import SkyCoord, EarthLocation
from astropy.time import Time
import astropy.units as u
from astropy.stats import sigma_clipped_stats
from photutils.aperture import CircularAperture, CircularAnnulus, aperture_photometry
from photutils.centroids import centroid_2dg
import json

# Session-based caches to avoid re-calculating photometry/PSF when roles change
# Now persisted to disk to survive restarts
_SESSION_PHOT_CACHE = {} # (fpath, ra, dec, ap, ann_in, ann_out) -> measure_star dict
_SESSION_FWHM_CACHE = {} # (fpath, aperture_radius) -> median_fwhm

CACHE_FILE = os.path.join("photometry_output", "time_series_cache.json")

def load_session_cache():
    global _SESSION_PHOT_CACHE, _SESSION_FWHM_CACHE
    if not os.path.exists(CACHE_FILE):
        return
    try:
        with open(CACHE_FILE, 'r') as f:
            data = json.load(f)
            # JSON doesn't support tuple keys, so we convert back
            for k, v in data.get('phot', {}).items():
                parts = k.split('|')
                if len(parts) == 6:
                    key = (parts[0], float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]), float(parts[5]))
                    _SESSION_PHOT_CACHE[key] = v
            for k, v in data.get('fwhm', {}).items():
                parts = k.split('|')
                if len(parts) == 2:
                    key = (parts[0], float(parts[1]))
                    _SESSION_FWHM_CACHE[key] = v
    except Exception as e:
        print(f"Warning: Could not load photometry cache: {e}")

def save_session_cache():
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        phot_export = {"|".join(map(str, k)): v for k, v in _SESSION_PHOT_CACHE.items()}
        fwhm_export = {"|".join(map(str, k)): v for k, v in _SESSION_FWHM_CACHE.items()}
        with open(CACHE_FILE, 'w') as f:
            json.dump({'phot': phot_export, 'fwhm': fwhm_export}, f)
    except Exception as e:
        print(f"Warning: Could not save photometry cache: {e}")

# Initial load
load_session_cache()

def get_hjd(time_str, ra, dec, header, site_lat=0.0, site_long=0.0):
    """ Calculates Heliocentric Julian Date (HJD) from DATE-OBS and coordinates. """
    try:
        # 1. Parse Time
        # Try different possible header keywords for time
        t_val = header.get('JD') or header.get('JD_SOBJ')
        if t_val:
            t = Time(float(t_val), format='jd', scale='utc')
        else:
            # Fallback to DATE-OBS
            t_str = header.get('DATE-OBS')
            if not t_str: return None
            t = Time(t_str, format='isot', scale='utc')
        
        # 2. Get Observer Location
        lon = header.get('SITELONG', site_long)
        lat = header.get('SITELAT', site_lat)
        height = header.get('SITEELEV', 0.0)
        loc = EarthLocation(lon=lon*u.deg, lat=lat*u.deg, height=height*u.m)
        
        # 3. Target Coordinates
        target = SkyCoord(ra=ra*u.deg, dec=dec*u.deg, frame='icrs')
        
        # 4. Calculate Light Travel Time to Sun
        ltt_helio = t.light_travel_time(target, 'heliocentric', location=loc)
        t_helio = t + ltt_helio
        
        return t_helio.jd
    except Exception as e:
        print(f"Warning: Could not calculate HJD: {e}")
        return None

def measure_star(image_data, wcs, ra, dec, aperture_radius, annulus_inner, annulus_outer, gain=1.0):
    """ Performs targeted aperture photometry on a specific RA/Dec. """
    try:
        # 1. Convert RA/Dec to pixel coordinates using WCS
        x_init, y_init = wcs.world_to_pixel(SkyCoord(ra=ra*u.deg, dec=dec*u.deg, frame='icrs'))
        
        # 2. Refine Centroid (in a small 15x15 box)
        size = 15
        x_int, y_int = int(np.round(x_init)), int(np.round(y_init))
        # Bounds check
        if x_int < size or y_int < size or x_int > image_data.shape[1]-size or y_int > image_data.shape[0]-size:
            return None
            
        cutout = image_data[y_int-size:y_int+size, x_int-size:x_int+size]
        # Subtract local background for centroiding
        _, median, _ = sigma_clipped_stats(cutout)
        x_rel, y_rel = centroid_2dg(cutout - median)
        
        x_refined = x_int - size + x_rel
        y_refined = y_int - size + y_rel
        
        # 3. Aperture Photometry
        pos = (x_refined, y_refined)
        aperture = CircularAperture(pos, r=aperture_radius)
        annulus = CircularAnnulus(pos, r_in=annulus_inner, r_out=annulus_outer)
        
        phot_table = aperture_photometry(image_data, aperture, method='exact')
        raw_flux = phot_table['aperture_sum'][0]
        
        # Background subtraction
        annulus_mask = annulus.to_mask(method='center')
        bkg_pixels = annulus_mask.get_values(image_data)
        bkg_pixels = bkg_pixels[~np.isnan(bkg_pixels)]
        _, bkg_median, bkg_std = sigma_clipped_stats(bkg_pixels, sigma=3.0)
        
        net_flux = raw_flux - (bkg_median * aperture.area)
        
        # Error calculation
        variance = (max(net_flux, 0) / gain) + aperture.area * (bkg_std**2) + (aperture.area**2 * bkg_std**2 / len(bkg_pixels))
        flux_err = np.sqrt(variance)
        snr = net_flux / flux_err if flux_err > 0 and net_flux > 0 else 0
        mag_err = 1.0857 / snr if snr > 0 else np.nan
        
        return {
            'x': x_refined, 'y': y_refined,
            'net_flux': net_flux,
            'flux_err': flux_err,
            'mag_inst': -2.5 * np.log10(net_flux) if net_flux > 0 else np.nan,
            'mag_err': mag_err,
            'snr': snr
        }
    except Exception as e:
        print(f"Error measuring star at {ra}, {dec}: {e}")
        return None

def run_time_series_photometry(fits_files, target_ra, target_dec, 
                               ensemble_stars, # List of dicts: {'ra', 'dec', 'mag_std', 'bv_std', 'name'}
                               check_star,     # Dict: {'ra', 'dec', 'bv_std', 'name'} or None
                               target_bv,
                               coeff_term, coeff_color, 
                               aperture_radius, annulus_inner, annulus_outer,
                               gain=1.0, k_coeff=0.15, filter_name='V',
                               observer_name="Calibra User",
                               site_lat=0.0, site_long=0.0,
                               cancel_event=None, update_progress=None,
                               use_flexible_aperture=False, 
                               aperture_fwhm_factor=2.0, annulus_inner_gap=2.0, annulus_width=5.0,
                               print_psf_fitting=False):
    """
    Main loop for time-series photometry.
    """
    results = []
    cache_hits = 0
    
    from astropy.wcs import WCS
    from photometry.psf_fitting import refine_coordinates_psf
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    import warnings
    from astropy.utils.exceptions import AstropyWarning
    warnings.simplefilter('ignore', category=AstropyWarning)

    print(f"Starting time-series analysis on {len(fits_files)} files...")
    if use_flexible_aperture:
        print(f"  -> Flexible Aperture Enabled (Factor: {aperture_fwhm_factor}x FWHM)")
    
    for i, fpath in enumerate(fits_files):
        if cancel_event and cancel_event.is_set():
            print("Operation cancelled by user.")
            break

        if update_progress:
            update_progress((i / len(fits_files)) * 100)
            
        try:
            with fits.open(fpath) as hdul:
                header = hdul[0].header
                data = hdul[0].data
                if data is None and len(hdul) > 1:
                    data = hdul[1].data
                    header = hdul[1].header
                
                if data is None:
                    continue

                if data.ndim == 3:
                    data = data[0]

                wcs = WCS(header)
                
                # Use header site info if available, else use manual site info
                lat = header.get('SITELAT', site_lat)
                lon = header.get('SITELONG', site_long)
                
                # 1. Timing and Airmass
                jd = header.get('JD')
                if not jd:
                    mjd = header.get('MJD')
                    if mjd is not None:
                        jd = mjd + 2400000.5
                
                if not jd:
                    t_obs = header.get('DATE-OBS')
                    if t_obs:
                        try:
                            from astropy.time import Time
                            jd = Time(t_obs).jd
                        except:
                            jd = 0
                
                hjd = get_hjd(None, target_ra, target_dec, header, lat, lon) or jd
                airmass = header.get('AIRMASS', 1.0)
                
                # 2. Determine Radii: Fixed or Flexible
                curr_ap = aperture_radius
                curr_ann_in = annulus_inner
                curr_ann_out = annulus_outer
                median_fwhm = None

                # To get FWHM, we run PSF fitting on the stars we care about
                fwhm_cache_key = (fpath, aperture_radius)
                is_fwhm_cached = False
                if fwhm_cache_key in _SESSION_FWHM_CACHE:
                    median_fwhm = _SESSION_FWHM_CACHE[fwhm_cache_key]
                    is_fwhm_cached = True
                else:
                    try:
                        stars_to_fit = []
                        # Target
                        tx, ty = wcs.world_to_pixel(SkyCoord(ra=target_ra*u.deg, dec=target_dec*u.deg, frame='icrs'))
                        stars_to_fit.append({'id': 'Target', 'x': tx + 1.0, 'y': ty + 1.0})
                        # Ensemble
                        for idx, s in enumerate(ensemble_stars):
                            sx, sy = wcs.world_to_pixel(SkyCoord(ra=s['ra']*u.deg, dec=s['dec']*u.deg, frame='icrs'))
                            stars_to_fit.append({'id': f"Ref_{idx}", 'x': sx + 1.0, 'y': sy + 1.0})
                        
                        # Run PSF fitting
                        median_fwhm = refine_coordinates_psf(
                            data, stars_to_fit, 15, aperture_radius, 
                            60000, 0, display_plots=False, print_psf_fitting=print_psf_fitting
                        )
                        _SESSION_FWHM_CACHE[fwhm_cache_key] = median_fwhm
                    except Exception as e:
                        if print_psf_fitting: print(f"  [{os.path.basename(fpath)}] PSF Fitting failed: {e}")
                        median_fwhm = None

                if use_flexible_aperture and median_fwhm:
                    curr_ap = median_fwhm * aperture_fwhm_factor
                    curr_ann_in = curr_ap + annulus_inner_gap
                    curr_ann_out = curr_ann_in + annulus_width
                    cache_label = " [Cached]" if is_fwhm_cached else ""
                    if print_psf_fitting:
                        print(f"  [{os.path.basename(fpath)}] Median FWHM: {median_fwhm:.2f}px -> Ap: {curr_ap:.2f}px{cache_label}")
                    elif (i+1) % 10 == 0 or i == 0:
                        print(f"  [{os.path.basename(fpath)}] Applied Flexible Ap: {curr_ap:.2f}px (FWHM: {median_fwhm:.2f}px){cache_label}")
                elif (i+1) % 10 == 0 or i == 0:
                    cache_label = " [Cached]" if is_fwhm_cached else ""
                    if median_fwhm:
                        print(f"  [{os.path.basename(fpath)}] Using Fixed Ap: {curr_ap:.2f}px (FWHM: {median_fwhm:.2f}px){cache_label}")
                    else:
                        print(f"  [{os.path.basename(fpath)}] Using Fixed Ap: {curr_ap:.2f}px")

                # 3. Measure Target and Ensemble
                def get_cached_measurement(fpath, ra, dec, ap, ann_in, ann_out, data, wcs, gain):
                    nonlocal cache_hits
                    # Round coords and ap to ensure hits despite float precision jitter
                    key = (fpath, round(ra, 6), round(dec, 6), round(ap, 2), round(ann_in, 2), round(ann_out, 2))
                    if key in _SESSION_PHOT_CACHE:
                        cache_hits += 1
                        return _SESSION_PHOT_CACHE[key]
                    res = measure_star(data, wcs, ra, dec, ap, ann_in, ann_out, gain)
                    _SESSION_PHOT_CACHE[key] = res
                    return res

                target_res = get_cached_measurement(fpath, target_ra, target_dec, curr_ap, curr_ann_in, curr_ann_out, data, wcs, gain)
                
                ensemble_res = []
                for s in ensemble_stars:
                    res = get_cached_measurement(fpath, s['ra'], s['dec'], curr_ap, curr_ann_in, curr_ann_out, data, wcs, gain)
                    if res and not np.isnan(res['mag_inst']):
                        # Calculate individual Zero Point for this ref star
                        # ZV_i = mag_std_i - (mag_inst_corr_i + Tv_bv * bv_std_i)
                        m_inst_corr = res['mag_inst'] - (k_coeff * airmass)
                        zv_i = s['mag_std'] - (m_inst_corr + coeff_term * s['bv_std'])
                        ensemble_res.append({
                            'name': s['name'],
                            'zv': zv_i,
                            'snr': res['snr'],
                            'mag_err': res['mag_err']
                        })
                
                if target_res and ensemble_res:
                    if np.isnan(target_res['mag_inst']):
                        print(f"  - {os.path.basename(fpath)}: Target measurement returned NaN")
                        continue
                        
                    # 4. Ensemble Calibration Logic
                    # We average the zero points from all valid ensemble stars
                    zvs = [r['zv'] for r in ensemble_res]
                    zv_avg = np.mean(zvs)
                    zv_std = np.std(zvs, ddof=1) if len(zvs) > 1 else 0.0
                    zv_err = zv_std / np.sqrt(len(zvs)) if len(zvs) > 1 else 0.01 # Fallback 0.01 if only 1 star
                    
                    # Target Calibration
                    # V_target_std = v_target_corr + Tv_bv * (B-V)_target + ZV_avg
                    v_target_corr = target_res['mag_inst'] - (k_coeff * airmass)
                    v_target_std = v_target_corr + coeff_term * target_bv + zv_avg
                    
                    # Total uncertainty = sqrt(photon_noise^2 + ensemble_zp_error^2)
                    total_mag_err = np.sqrt(target_res['mag_err']**2 + zv_err**2)

                    if i < 3:
                        print(f"\n--- Diagnostic (Image {i+1}: {os.path.basename(fpath)}) ---")
                        print(f"  Target Inst: {target_res['mag_inst']:.4f} | Corr: {v_target_corr:.4f}")
                        print(f"  Ensemble ({len(ensemble_res)} stars): ZP_avg = {zv_avg:.4f} +/- {zv_err:.4f} (std={zv_std:.4f})")
                        for r in ensemble_res:
                            print(f"    * {r['name']}: ZP={r['zv']:.4f}, SNR={r['snr']:.1f}")
                        print(f"  FINAL MAG:   {v_target_std:.4f} +/- {total_mag_err:.4f}")
                        print("------------------------------------------------------\n")
                    
                    # 5. Check Star Calibration
                    check_mag_std = np.nan
                    if check_star:
                        check_res = get_cached_measurement(fpath, check_star['ra'], check_star['dec'], curr_ap, curr_ann_in, curr_ann_out, data, wcs, gain)
                        if check_res and not np.isnan(check_res['mag_inst']):
                            c_inst_corr = check_res['mag_inst'] - (k_coeff * airmass)
                            check_mag_std = c_inst_corr + coeff_term * check_star['bv_std'] + zv_avg

                    results.append({
                        'file': os.path.basename(fpath),
                        'jd': jd,
                        'hjd': hjd,
                        'airmass': airmass,
                        'mag': v_target_std,
                        'mag_err': total_mag_err,
                        'check_mag': check_mag_std,
                        'snr': target_res['snr'],
                        'fwhm': median_fwhm if median_fwhm else np.nan,
                        'zp_avg': zv_avg,
                        'zp_err': zv_err,
                        'n_ensemble': len(ensemble_res)
                    })
                else:
                    if not target_res: print(f"  - {os.path.basename(fpath)}: Target star could not be centroided.")
                    if not ensemble_res: print(f"  - {os.path.basename(fpath)}: No ensemble stars could be measured.")
                    
            if (i+1) % 10 == 0:
                print(f"Processed {i+1}/{len(fits_files)} images... ({cache_hits} measurements from cache)")
                
        except Exception as e:
            print(f"Skipping {fpath}: {e}")

    # Save cache to disk for future runs
    save_session_cache()

    if update_progress:
        update_progress(100)

    if not results:
        status = "Cancelled." if cancel_event and cancel_event.is_set() else "No data successfully processed."
        return None, status
        
    # Outlier Flagging (3-sigma)
    mags = [r['mag'] for r in results]
    if len(mags) > 5:
        median_mag = np.median(mags)
        std_mag = np.std(mags, ddof=1)
        for r in results:
            if abs(r['mag'] - median_mag) > 3 * std_mag:
                r['flag'] = 'SUSPECT'
            else:
                r['flag'] = 'OK'
    else:
        for r in results:
            r['flag'] = 'OK'

    # Sort by time
    results.sort(key=lambda x: x['hjd'])
    
    return results, "Success"

def save_aavso_report(results, output_path, target_name, filter_name, obs_code, 
                      comp_name="ENSEMBLE", comp_mag="na", check_name="na", check_mag="na",
                      trans="NO"):
    """ Generates a report in AAVSO Extended Format. """
    try:
        with open(output_path, 'w', newline='') as f:
            f.write("#TYPE=Extended\n")
            f.write(f"#OBSCODE={obs_code}\n")
            f.write(f"#SOFTWARE=Calibra 2.0\n")
            f.write(f"#DELIM=,\n")
            f.write(f"#DATE=HJD\n")
            f.write(f"#OBSTYPE=CCD\n")
            f.write(f"#TRANS={trans}\n")
            f.write("NAME,DATE,MAG,MERR,FILT,TRANS,MTYPE,CNAME,CMAG,KNAME,KMAG,AMASS,NOTES\n")
            
            for r in results:
                # Format: Name, Date, Mag, Merr, Filt, Trans, Mtype, Cname, Cmag, Kname, Kmag, Amass, Notes
                f.write(f"{target_name},{r['hjd']:.6f},{r['mag']:.4f},{r['mag_err']:.4f},{filter_name},{trans},STD,{comp_name},{comp_mag},{check_name},{check_mag},{r['airmass']:.3f},na\n")
        return True
    except Exception as e:
        print(f"Error saving AAVSO report: {e}")
        return False

def plot_light_curve(results, target_name, output_path, ax=None):
    """ Plots the light curve. If ax is provided, plots to that axes. """
    if not results: return
    
    if ax is None:
        fig, ax = plt.subplots(figsize=(10, 6))
        is_standalone = True
    else:
        fig = ax.figure
        ax.clear()
        is_standalone = False
    
    times = np.array([r['hjd'] for r in results])
    mags = np.array([r['mag'] for r in results])
    errs = np.array([r['mag_err'] for r in results])
    flags = np.array([r.get('flag', 'OK') for r in results])
    
    # JD Offset for readability
    t0 = int(min(times))
    times_rel = times - t0
    
    # Plot OK points
    ok_mask = (flags == 'OK')
    if np.any(ok_mask):
        ax.errorbar(times_rel[ok_mask], mags[ok_mask], yerr=errs[ok_mask], 
                     fmt='o', color='darkblue', ecolor='gray', capsize=2, markersize=4, label='Target')
    
    # Plot SUSPECT points
    suspect_mask = (flags == 'SUSPECT')
    if np.any(suspect_mask):
        ax.errorbar(times_rel[suspect_mask], mags[suspect_mask], yerr=errs[suspect_mask], 
                     fmt='o', color='none', markeredgecolor='red', ecolor='red', capsize=2, markersize=6, label='Target (SUSPECT)')

    # Plot Check Star
    check_mags = np.array([r.get('check_mag', np.nan) for r in results])
    valid_check = ~np.isnan(check_mags)
    if np.any(valid_check):
        ax.errorbar(times_rel[valid_check], check_mags[valid_check], 
                     fmt='o', color='green', alpha=0.6, markersize=4, label='Check Star')
                     
    ax.invert_yaxis()
    
    ax.set_title(f"Light Curve: {target_name}")
    ax.set_xlabel(f"HJD - {t0}")
    ax.set_ylabel("Magnitude")
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    if is_standalone:
        plt.savefig(output_path)
        plt.close(fig)
    else:
        fig.savefig(output_path)
