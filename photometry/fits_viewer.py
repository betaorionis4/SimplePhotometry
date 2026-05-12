import numpy as np
import os
import csv
import tkinter as tk
from tkinter import ttk, messagebox
import matplotlib.patches as patches
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from astropy.io import fits
from astropy.wcs import WCS
from astropy.modeling import models, fitting
from astropy.nddata import Cutout2D
from astropy.visualization import ZScaleInterval
from astropy.coordinates import SkyCoord
import astropy.units as u

class FITSViewer:
    def __init__(self, parent, fits_path, ref_catalog="ATLAS", default_zp=23.399):
        self.parent = parent
        self.fits_path = fits_path
        self.ref_catalog = ref_catalog
        self.default_zp = default_zp
        self.base_name = os.path.splitext(os.path.basename(fits_path))[0]
        
        # Load Data and WCS
        try:
            with fits.open(fits_path) as hdul:
                self.data = hdul[0].data.astype(float)
                self.header = hdul[0].header
                self.wcs = WCS(self.header)
                self.has_wcs = self.wcs.has_celestial
        except Exception as e:
            messagebox.showerror("Error", f"Could not load FITS file: {e}")
            self.parent.destroy()
            return

        # On-the-spot photometry data
        self.on_the_spot_refs = [] # List of {'inst_flux': float, 'cat_mag': float, 'filt': str}
        self.on_the_spot_zp = None

        # Try to load pipeline results
        self.results_data = self._load_results()
        
        # UI Setup
        self.parent.title(f"FITS Viewer: {os.path.basename(fits_path)}")
        
        # Set Window Icon
        logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "calibra_logo.png")
        if os.path.exists(logo_path):
            try:
                from PIL import Image, ImageTk
                icon_img = Image.open(logo_path)
                icon_img = icon_img.resize((32, 32), Image.Resampling.LANCZOS)
                self._icon = ImageTk.PhotoImage(icon_img) # Keep reference
                self.parent.iconphoto(True, self._icon)
            except:
                pass
        
        # Calculate aspect ratio and initial window size
        ny, nx = self.data.shape
        aspect = nx / ny
        base_h = 750
        panel_w = 200 # 1 unit
        canvas_w = 800 # 4 units (4:1:1 ratio)
        win_w = canvas_w + (panel_w * 2)
        self.parent.geometry(f"{win_w}x{base_h}")
        
        # Bottom status bar for coordinates
        self.status_var = tk.StringVar(value="Hover for coordinates | Scroll to zoom | Click to inspect star")
        self.status_bar = ttk.Label(self.parent, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Main layout: Horizontal PanedWindow
        self.main_paned = ttk.PanedWindow(self.parent, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True)

        # Left side: Matplotlib Canvas
        self.canvas_frame = ttk.Frame(self.main_paned)
        self.main_paned.add(self.canvas_frame, weight=4)

        # Right side: Another PanedWindow for the two detail panels
        self.right_paned = ttk.PanedWindow(self.main_paned, orient=tk.HORIZONTAL)
        self.main_paned.add(self.right_paned, weight=2)

        # 1. Star Details Panel
        self.details_frame = ttk.LabelFrame(self.right_paned, text="Star Details", padding=10)
        self.right_paned.add(self.details_frame, weight=1)
        self.details_frame.config(width=panel_w)

        # 2. Reference Stars Panel
        self.ref_frame = ttk.LabelFrame(self.right_paned, text="Reference Stars (Ensemble)", padding=10)
        self.right_paned.add(self.ref_frame, weight=1)
        self.ref_frame.config(width=panel_w)

        # Details UI Elements
        self.details_text = tk.Text(self.details_frame, wrap=tk.WORD, state=tk.DISABLED, 
                                    bg="#f8f9fa", font=("Courier", 10), width=25)
        self.details_text.pack(fill=tk.BOTH, expand=True)

        self.ref_text = tk.Text(self.ref_frame, wrap=tk.WORD, state=tk.DISABLED,
                                bg="#f1f8f1", font=("Courier", 9), width=28)
        self.ref_text.pack(fill=tk.BOTH, expand=True)
        
        # Setup Figure
        self.fig = Figure(figsize=(8, 8))
        if self.has_wcs:
            self.ax = self.fig.add_subplot(111, projection=self.wcs)
        else:
            self.ax = self.fig.add_subplot(111)
            
        zscale = ZScaleInterval()
        vmin, vmax = zscale.get_limits(self.data)
        self.im = self.ax.imshow(self.data, origin='lower', cmap='Greys_r', vmin=vmin, vmax=vmax)
        self.ax.set_title(os.path.basename(fits_path))
        
        # Adjust margins to ensure labels are visible
        self.fig.subplots_adjust(left=0.15, right=0.95, top=0.92, bottom=0.12)
        
        # Add RA/Dec Grid Lines
        if self.has_wcs:
            try:
                # Color coded grid lines
                self.ax.coords[0].grid(color='red', alpha=0.3, linestyle='-', linewidth=0.5)   # RA
                self.ax.coords[1].grid(color='green', alpha=0.3, linestyle='-', linewidth=0.5) # Dec
                
                # Ensure labels are shown on all sides if possible, or just standard
                self.ax.coords[0].set_axislabel('Right Ascension', color='red')
                self.ax.coords[1].set_axislabel('Declination', color='green')
            except:
                pass
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.canvas_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        self.marker = None
        self.ref_markers = []
        
        # Connect Events
        self.canvas.mpl_connect('motion_notify_event', self.on_hover)
        self.canvas.mpl_connect('button_press_event', self.on_click)
        self.canvas.mpl_connect('scroll_event', self.on_scroll)
        
        # Right-click Context Menu
        self.context_menu = tk.Menu(self.parent, tearoff=0)
        self.context_menu.add_command(label="Mark as Reference Star", command=self._add_on_the_spot_ref)
        self.context_menu.add_command(label="Remove as Reference Star", command=self._remove_on_the_spot_ref)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Clear ALL Reference Stars", command=self._clear_on_the_spot_refs)
        
        self._last_click_pos = (0, 0) # Store for right-click context
        
        # Cleanup on close
        self.parent.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        self.fig.clear()
        self.ref_markers = []
        self.parent.destroy()

    def _load_results(self):
        # The pipeline saves results to targets_auto_[base_name].csv
        csv_path = os.path.join('photometry_output', f'targets_auto_{self.base_name}.csv')
        if not os.path.exists(csv_path):
            return None
        
        results = []
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Convert necessary fields to float
                    try:
                        # The CSV uses 1-based FITS coordinates
                        row['refined_x'] = float(row['refined_x']) if row.get('refined_x') else float(row['raw_x'])
                        row['refined_y'] = float(row['refined_y']) if row.get('refined_y') else float(row['raw_y'])
                        results.append(row)
                    except:
                        continue
        except Exception as e:
            print(f"Error loading CSV results: {e}")
            return None
        return results

    def _update_details(self, text):
        self.details_text.config(state=tk.NORMAL)
        self.details_text.delete(1.0, tk.END)
        self.details_text.insert(tk.END, text)
        self.details_text.config(state=tk.DISABLED)

    def on_hover(self, event):
        if event.inaxes == self.ax:
            x, y = event.xdata, event.ydata
            # x, y in matplotlib are 0-based pixel coords
            status = f"X: {x+1:.1f} Y: {y+1:.1f}"
            if self.has_wcs:
                try:
                    coord = self.wcs.pixel_to_world(x, y)
                    ra_str = coord.ra.to_string(unit='hour', sep=':', precision=2)
                    dec_str = coord.dec.to_string(unit='deg', sep=':', precision=2)
                    status += f" | RA: {ra_str} Dec: {dec_str}"
                except:
                    pass
            self.status_var.set(status)

    def on_click(self, event):
        if event.inaxes != self.ax:
            return
        
        if event.button == 3: # Right click
            self._last_click_pos = (event.xdata, event.ydata)
            self.context_menu.post(int(event.guiEvent.x_root), int(event.guiEvent.y_root))
            return
            
        if event.button != 1:
            return

        # event.xdata/ydata are 0-based coordinates in Matplotlib
        x_click, y_click = event.xdata, event.ydata
        
        # 1. Search in CSV results if available
        found_in_csv = False
        if self.results_data:
            # Find nearest star in results (pixel space, CSV is 1-based)
            min_dist = 10.0 # Search radius in pixels
            nearest_star = None
            
            for star in self.results_data:
                dist = np.sqrt((star['refined_x'] - (x_click + 1))**2 + (star['refined_y'] - (y_click + 1))**2)
                if dist < min_dist:
                    min_dist = dist
                    nearest_star = star
            
            if nearest_star:
                found_in_csv = True
                details = f"--- Pipeline Result ---\n\n"
                details += f"ID:     {nearest_star['id']}\n"
                details += f"X:      {nearest_star['refined_x']:.2f}\n"
                details += f"Y:      {nearest_star['refined_y']:.2f}\n\n"
                
                if nearest_star.get('ra_hms'):
                    details += f"RA: {nearest_star['ra_hms']}\n"
                    details += f"Dec:{nearest_star['dec_dms']}\n\n"
                
                details += f"SNR:    {nearest_star.get('snr', 'N/A')}\n"
                details += f"Peak:   {nearest_star.get('peak_adu', 'N/A')} ADU\n\n"
                
                # Query catalog for comparison
                if self.has_wcs:
                    try:
                        ra_deg = float(nearest_star['ra_deg'])
                        dec_deg = float(nearest_star['dec_deg'])
                        cat_star = self._query_catalog(ra_deg, dec_deg)
                        if cat_star:
                            v_mag = cat_star.get('V_mag')
                            v_str = f"{v_mag:.3f}" if isinstance(v_mag, (int, float)) and not np.isnan(v_mag) else "N/A"
                            b_mag = cat_star.get('B_mag')
                            b_str = f"{b_mag:.3f}" if isinstance(b_mag, (int, float)) and not np.isnan(b_mag) else "N/A"
                            details += f"--- Catalog Comparison ---\n"
                            details += f"ID: {cat_star.get('display_name', 'Star')}\n"
                            details += f"Catalog V: {v_str}\n"
                            details += f"Catalog B: {b_str}\n\n"
                            
                            if cat_star.get('is_variable'):
                                details += f"!!! VARIABLE STAR !!!\n"
                                details += f"Type: {cat_star.get('var_type', 'N/A')}\n\n"
                            
                            # Overwrite the pipeline's variability flag with the fresh one
                            nearest_star['is_variable'] = cat_star.get('is_variable', False)
                    except:
                        pass

                mag_err = nearest_star.get('mag_calibrated_err', '')
                if mag_err:
                    details += f"Error:     ±{mag_err}\n"
                
                # Zero Point Logic
                active_zp = self.default_zp
                zp_label = f"ZP={self.default_zp:.3f}"

                if self.on_the_spot_zp is not None:
                    active_zp = self.on_the_spot_zp
                    zp_label = f"Ens ZP={self.on_the_spot_zp:.3f}"

                inst_f = float(nearest_star.get('net_flux', 0))
                if inst_f > 0:
                    inst_m = -2.5 * np.log10(inst_f)
                    cal_m = inst_m + active_zp
                    details += f"\nMeas Mag:  {cal_m:.3f}*\n"
                    details += f"(* using {zp_label})\n"

                details += f"\nVariable:  {nearest_star.get('is_variable', 'Unknown')}\n"
                
                self._update_details(details)
                # Draw marker at 0-based coord
                self._draw_marker(nearest_star['refined_x'] - 1, nearest_star['refined_y'] - 1)

        # 2. Fallback to basic fit if not found or no CSV
        if not found_in_csv:
            self._basic_fit(x_click, y_click)

    def _draw_marker(self, x, y, is_ref=False):
        # 1. Clear any existing inspection marker
        if self.marker:
            self.marker.remove()
            self.marker = None
        
        # 2. If it's a reference star, we don't draw a red cross
        if is_ref:
            self.canvas.draw_idle()
            return

        # 3. Check if this position is already a reference star
        # If so, don't draw the red cross on top of the green circle
        for r in self.on_the_spot_refs:
            if np.sqrt((r['x'] - x)**2 + (r['y'] - y)**2) < 5.0:
                self.canvas.draw_idle()
                return

        # 4. Draw red cross for new inspection
        self.marker, = self.ax.plot(x, y, 'r+', markersize=15, mew=2)
        self.canvas.draw_idle()

    def _basic_fit(self, x_click, y_click, suppress_cross=False):
        size = 21
        try:
            cutout = Cutout2D(self.data, (x_click, y_click), (size, size), mode='partial')
            d_fit = cutout.data
            bg = np.nanmedian(d_fit)
            d_fit_sub = d_fit - bg
            
            y_init, x_init = np.unravel_index(np.argmax(d_fit_sub), d_fit_sub.shape)
            g_init = models.Gaussian2D(amplitude=np.max(d_fit_sub), x_mean=x_init, y_mean=y_init, x_stddev=2.0, y_stddev=2.0, theta=0)
            
            fitter = fitting.LevMarLSQFitter()
            yy, xx = np.mgrid[:size, :size]
            g_fit = fitter(g_init, xx, yy, d_fit_sub)
            
            # x_final, y_final are 0-based
            x_final = cutout.to_original_position((g_fit.x_mean.value, g_fit.y_mean.value))[0]
            y_final = cutout.to_original_position((g_fit.x_mean.value, g_fit.y_mean.value))[1]
            fwhm = abs(g_fit.x_stddev.value * 2.355)
            peak = g_fit.amplitude.value
            total_flux = peak * 2 * np.pi * g_fit.x_stddev.value ** 2
            
            details = f"--- Basic Star Fit ---\n"
            details += f"(No pipeline data found)\n\n"
            details += f"X: {x_final + 1:.2f}\n"
            details += f"Y: {y_final + 1:.2f}\n\n"
            
            if self.has_wcs:
                coord = self.wcs.pixel_to_world(x_final, y_final)
                ra_deg, dec_deg = coord.ra.deg, coord.dec.deg
                
                # Try to query the catalog on the fly
                cat_star = self._query_catalog(ra_deg, dec_deg)
                if cat_star:
                    details = f"--- Catalog Match ({self.ref_catalog}) ---\n"
                    details += f"ID: {cat_star.get('display_name', 'Star')}\n\n"
                    details += f"Ref RA:  {coord.ra.to_string(unit='hour', sep=':', precision=2)}\n"
                    details += f"Ref Dec: {coord.dec.to_string(unit='deg', sep=':', precision=2)}\n\n"
                    
                    v_mag = cat_star.get('V_mag')
                    v_str = f"{v_mag:.3f}" if isinstance(v_mag, (int, float)) and not np.isnan(v_mag) else "N/A"
                    b_mag = cat_star.get('B_mag')
                    b_str = f"{b_mag:.3f}" if isinstance(b_mag, (int, float)) and not np.isnan(b_mag) else "N/A"
                    
                    details += f"V Mag:   {v_str}\n"
                    details += f"B Mag:   {b_str}\n\n"
                    
                    if cat_star.get('is_variable'):
                        details += f"!!! VARIABLE STAR !!!\n"
                        details += f"Type: {cat_star.get('var_type', 'N/A')}\n\n"

                    details += f"--- Fit Details ---\n"
                else:
                    details += f"RA:  {coord.ra.to_string(unit='hour', sep=':', precision=2)}\n"
                    details += f"Dec: {coord.dec.to_string(unit='deg', sep=':', precision=2)}\n\n"
            
            details += f"X (FITS): {x_final + 1:.2f}\n"
            details += f"Y (FITS): {y_final + 1:.2f}\n"
            details += f"FWHM:  {fwhm:.2f} px\n"
            details += f"Peak:  {peak:.1f} ADU\n"
            
            if total_flux > 0:
                inst_mag = -2.5 * np.log10(total_flux)
                details += f"Inst Mag:  {inst_mag:.3f}*\n"
                
                # Zero Point Logic
                active_zp = self.default_zp
                zp_label = f"ZP={self.default_zp:.3f}"
                
                if self.on_the_spot_zp is not None:
                    active_zp = self.on_the_spot_zp
                    zp_label = f"Ens ZP={self.on_the_spot_zp:.3f}"
                
                cal_mag = inst_mag + active_zp
                details += f"Meas Mag:  {cal_mag:.3f}**\n"
                
                details += f"\n(* estimated from PSF fit)\n"
                details += f"(** using {zp_label})\n"
                if self.on_the_spot_zp is not None:
                    details += f"(Ensemble of {len(self.on_the_spot_refs)} stars)\n"
            
            self._update_details(details)
            self._draw_marker(x_final, y_final, is_ref=suppress_cross)
            
        except Exception as e:
            self._update_details(f"Fitting failed:\n{e}")

    def _query_catalog(self, ra, dec):
        # Only query if it looks like an online catalog name
        if not self.ref_catalog or not any(k in self.ref_catalog.upper() for k in ["ATLAS", "APASS", "GAIA", "LANDOLT"]):
            return None
            
        try:
            from photometry.calibration import fetch_online_catalog, get_vsx_stars
            # Use a slightly larger search radius for matching (5 arcseconds)
            radius_arcmin = 5.0 / 60.0
            stars = fetch_online_catalog(ra, dec, radius_arcmin=radius_arcmin, catalog_name=self.ref_catalog, verbose=False)
            if stars:
                # Find the nearest star in the catalog results
                from astropy.coordinates import SkyCoord
                import astropy.units as u
                cat_coords = SkyCoord(ra=[s['ra_deg'] for s in stars]*u.deg, dec=[s['dec_deg'] for s in stars]*u.deg)
                target_coord = SkyCoord(ra=ra*u.deg, dec=dec*u.deg)
                idx_cat, d2d_cat, _ = target_coord.match_to_catalog_sky(cat_coords)
                star = stars[idx_cat]

                # Check variability and VSX name (AUID)
                # Use a larger query radius (1 arcmin) to ensure we capture the star even with slight WCS offsets
                vsx = get_vsx_stars(ra, dec, radius_arcmin=1.0, verbose=False)
                if vsx:
                    # Find the nearest VSX star
                    vsx_coords = SkyCoord(ra=[s['ra_deg'] for s in vsx]*u.deg, dec=[s['dec_deg'] for s in vsx]*u.deg)
                    idx_v, d2d_v, _ = target_coord.match_to_catalog_sky(vsx_coords)
                    nearest_vsx = vsx[idx_v]
                    
                    var_type = nearest_vsx.get('Type', '')
                    star['vsx_name'] = nearest_vsx.get('id', '')
                    star['var_type'] = var_type
                    
                    # Only mark as variable if within 5 arcsec and NOT a constant star
                    dist_v = d2d_v[0].arcsec if hasattr(d2d_v, '__len__') else d2d_v.arcsec
                    if dist_v < 5.0 and var_type and 'CST' not in str(var_type).upper():
                        star['is_variable'] = True
                    else:
                        star['is_variable'] = False
                else:
                    star['is_variable'] = False
                    star['vsx_name'] = ''
                    star['var_type'] = ''

                # Determine best display name: AUID > Catalog ID > Gaia Fallback
                display_name = star.get('vsx_name', '')
                if not display_name:
                    display_name = star.get('cat_id', '')
                
                # Debug logging
                try:
                    with open("debug_log.txt", "a") as f:
                        f.write(f"--- Query @ {ra:.5f}, {dec:.5f} ---\n")
                        dist_c = d2d_cat[0].arcsec if hasattr(d2d_cat, '__len__') else d2d_cat.arcsec
                        f.write(f"Catalog ({self.ref_catalog}): {star.get('cat_id', 'None')} (dist: {dist_c:.2f}\")\n")
                        if vsx:
                            dist_v = d2d_v[0].arcsec if hasattr(d2d_v, '__len__') else d2d_v.arcsec
                            f.write(f"VSX Match: {nearest_vsx['id']} (dist: {dist_v:.2f}\", type: {var_type})\n")
                        else:
                            f.write(f"VSX: No results in 1 arcmin\n")
                        f.write(f"Final display_name: {display_name}\n\n")
                except:
                    pass
                
                # Gaia Fallback if still no name and we're not already using Gaia
                if not display_name and "GAIA" not in self.ref_catalog.upper():
                    try:
                        # Use 15 arcsec radius for query to ensure we find it
                        g_stars = fetch_online_catalog(ra, dec, radius_arcmin=15.0/60.0, catalog_name="GAIA_DR3", verbose=False)
                        if g_stars:
                            # Use nearest Gaia star
                            g_coords = SkyCoord(ra=[s['ra_deg'] for s in g_stars]*u.deg, dec=[s['dec_deg'] for s in g_stars]*u.deg)
                            idx_g, d2d_g, _ = target_coord.match_to_catalog_sky(g_coords)
                            dist_g = d2d_g[0].arcsec if hasattr(d2d_g, '__len__') else d2d_g.arcsec
                            if dist_g < 5.0:
                                display_name = g_stars[idx_g].get('cat_id', '')
                    except:
                        pass
                
                star['display_name'] = display_name if display_name else "Star"
                return star
        except Exception as e:
            print(f"Online query failed: {e}")
        return None

    def _add_on_the_spot_ref(self):
        x, y = self._last_click_pos
        # 1. Fit the star to get instrumental magnitude
        res = self._fit_at(x, y)
        if not res:
            messagebox.showwarning("Fit Failed", "Could not fit a star at this position.")
            return
            
        inst_mag = res['inst_mag']
        
        # 2. Get catalog magnitude
        if not self.has_wcs:
            messagebox.showwarning("WCS Required", "Cannot perform on-the-spot photometry without WCS.")
            return
            
        coord = self.wcs.pixel_to_world(res['x'], res['y'])
        cat_star = self._query_catalog(coord.ra.deg, coord.dec.deg)
        
        if not cat_star:
            messagebox.showwarning("No Catalog Match", "Could not find a matching catalog star for reference.")
            return
            
        # Check if already in list
        for r in self.on_the_spot_refs:
            dist = np.sqrt((r['x'] - res['x'])**2 + (r['y'] - res['y'])**2)
            if dist < 5.0:
                messagebox.showinfo("Duplicate", "This star is already in your reference ensemble.")
                return

        # Determine which magnitude to use
        filt = self.header.get('FILTER', 'V').upper()
        if 'B' in filt:
            cat_mag = cat_star.get('B_mag')
        else:
            cat_mag = cat_star.get('V_mag')
            
        if cat_mag is None or np.isnan(cat_mag):
            messagebox.showwarning("No Magnitude", f"No {filt} magnitude available in catalog for this star.")
            return
            
        # Get coordinates for display
        c_ref = SkyCoord(ra=cat_star['ra_deg']*u.deg, dec=cat_star['dec_deg']*u.deg)
        ra_hms = c_ref.ra.to_string(unit='hour', sep=':', precision=1, pad=True)
        dec_dms = c_ref.dec.to_string(unit='deg', sep=':', precision=1, alwayssign=True, pad=True)

        # 3. Add to list
        if not hasattr(self, 'on_the_spot_refs'): self.on_the_spot_refs = []
        self.on_the_spot_refs.append({
            'inst_mag': inst_mag,
            'cat_mag': cat_mag,
            'id': cat_star.get('id', 'Ref'),
            'display_name': cat_star.get('display_name', 'Star'),
            'ra_hms': ra_hms,
            'dec_dms': dec_dms,
            'is_variable': cat_star.get('is_variable', False),
            'vsx_name': cat_star.get('vsx_name', ''),
            'x': res['x'],
            'y': res['y']
        })
        
        # 4. Recalculate ZP
        zps = [r['cat_mag'] - r['inst_mag'] for r in self.on_the_spot_refs]
        self.on_the_spot_zp = np.mean(zps)
        
        # 5. Draw persistent green circle
        circ = patches.Circle((res['x'], res['y']), radius=12, color='lime', fill=False, lw=1.5, alpha=0.8)
        self.ax.add_patch(circ)
        self.ref_markers.append(circ)
        
        # 6. Update Ref Panel
        self._update_ref_panel()
        
        # 7. Refresh details to show this is now a ref star (pass True to suppress cross)
        self._basic_fit(x, y, suppress_cross=True)

    def _remove_on_the_spot_ref(self):
        x, y = self._last_click_pos
        # Find nearest ref star
        idx_to_remove = -1
        min_dist = 15.0
        for i, r in enumerate(self.on_the_spot_refs):
            dist = np.sqrt((r['x'] - x)**2 + (r['y'] - y)**2)
            if dist < min_dist:
                min_dist = dist
                idx_to_remove = i
        
        if idx_to_remove != -1:
            # Remove from lists
            self.on_the_spot_refs.pop(idx_to_remove)
            m = self.ref_markers.pop(idx_to_remove)
            m.remove()
            
            # Recalculate ZP
            if self.on_the_spot_refs:
                zps = [r['cat_mag'] - r['inst_mag'] for r in self.on_the_spot_refs]
                self.on_the_spot_zp = np.mean(zps)
            else:
                self.on_the_spot_zp = None
            
            self._update_ref_panel()
            self._basic_fit(x, y)
        else:
            messagebox.showinfo("Not Found", "No reference star found near this position to remove.")

    def _update_ref_panel(self):
        if not self.on_the_spot_refs:
            text = "No reference stars selected."
        else:
            text = f"Ensemble ZP: {self.on_the_spot_zp:.3f}\n"
            text += f"Stars: {len(self.on_the_spot_refs)}\n"
            text += "=" * 23 + "\n\n"
            for i, r in enumerate(self.on_the_spot_refs):
                var_tag = " [VAR!]" if r['is_variable'] else ""
                disp_name = r.get('display_name', 'Star')
                
                # Use fixed width for alignment
                text += f"#{i+1:<2} RA:  {r['ra_hms']}{var_tag}\n"
                text += f"    Dec: {r['dec_dms']}\n"
                text += f"    ID:  {disp_name}\n"
                text += f"    Mag: {r['cat_mag']:.3f}\n"
                text += "-" * 23 + "\n"
        self.ref_text.config(state=tk.NORMAL)
        self.ref_text.delete(1.0, tk.END)
        self.ref_text.insert(tk.END, text)
        self.ref_text.config(state=tk.DISABLED)
        self.canvas.draw_idle()

    def _clear_on_the_spot_refs(self):
        self.on_the_spot_refs = []
        self.on_the_spot_zp = None
        for m in self.ref_markers:
            m.remove()
        self.ref_markers = []
        
        self.ref_text.config(state=tk.NORMAL)
        self.ref_text.delete(1.0, tk.END)
        self.ref_text.config(state=tk.DISABLED)
        
        messagebox.showinfo("Cleared", "On-the-spot reference stars cleared.")
        self._update_details("Reference stars cleared. Left-click to inspect stars.")
        self.canvas.draw_idle()

    def _fit_at(self, x, y):
        size = 21
        try:
            cutout = Cutout2D(self.data, (x, y), (size, size), mode='partial')
            d_fit = cutout.data
            bg = np.nanmedian(d_fit)
            d_fit_sub = d_fit - bg
            y_init, x_init = np.unravel_index(np.argmax(d_fit_sub), d_fit_sub.shape)
            g_init = models.Gaussian2D(amplitude=np.max(d_fit_sub), x_mean=x_init, y_mean=y_init, x_stddev=2.0, y_stddev=2.0, theta=0)
            fitter = fitting.LevMarLSQFitter()
            yy, xx = np.mgrid[:size, :size]
            g_fit = fitter(g_init, xx, yy, d_fit_sub)
            x_orig = cutout.to_original_position((g_fit.x_mean.value, g_fit.y_mean.value))[0]
            y_orig = cutout.to_original_position((g_fit.x_mean.value, g_fit.y_mean.value))[1]
            total_flux = g_fit.amplitude.value * 2 * np.pi * g_fit.x_stddev.value ** 2
            if total_flux <= 0: return None
            return {'x': x_orig, 'y': y_orig, 'inst_mag': -2.5 * np.log10(total_flux)}
        except:
            return None

    def on_scroll(self, event):
        if event.inaxes != self.ax: return
        base_scale = 1.2
        cur_xlim = self.ax.get_xlim()
        cur_ylim = self.ax.get_ylim()
        
        if event.button == 'up':
            scale_factor = 1 / base_scale
        else:
            scale_factor = base_scale
            
        new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor
        new_height = (cur_ylim[1] - cur_ylim[0]) * scale_factor
        
        rel_x = (cur_xlim[1] - event.xdata) / (cur_xlim[1] - cur_xlim[0])
        rel_y = (cur_ylim[1] - event.ydata) / (cur_ylim[1] - cur_ylim[0])
        
        self.ax.set_xlim([event.xdata - new_width * (1 - rel_x), event.xdata + new_width * rel_x])
        self.ax.set_ylim([event.ydata - new_height * (1 - rel_y), event.ydata + new_height * rel_y])
        self.canvas.draw_idle()
