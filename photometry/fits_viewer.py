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
    def __init__(self, parent, fits_path, ref_catalog="ATLAS", default_zp=23.399, config=None, initial_stars=None, export_callback=None, aperture_export_callback=None):
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

        self.config = config or {}
        self.initial_stars = initial_stars
        self.export_callback = export_callback
        self.aperture_export_callback = aperture_export_callback

        # On-the-spot photometry data
        self.variable_star = None # {'x', 'y', 'id', 'markers', ...}
        self.check_star = None
        self.on_the_spot_refs = [] # List of {'x', 'y', 'id', 'markers', ...}
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

        # 1. Variable & Inspection Panel
        self.var_inspection_paned = ttk.PanedWindow(self.right_paned, orient=tk.VERTICAL)
        self.right_paned.add(self.var_inspection_paned, weight=1)
        
        self.details_frame = ttk.LabelFrame(self.var_inspection_paned, text="Live Inspection", padding=5)
        self.var_inspection_paned.add(self.details_frame, weight=1)
        
        # New Profile Plot Frame
        self.profile_frame = ttk.LabelFrame(self.var_inspection_paned, text="Radial Profile", padding=2)
        self.var_inspection_paned.add(self.profile_frame, weight=2)
        
        self.var_frame = ttk.LabelFrame(self.var_inspection_paned, text="Variable Star", padding=5)
        self.var_inspection_paned.add(self.var_frame, weight=1)

        # 2. Reference & Check Stars Panel
        self.ref_paned = ttk.PanedWindow(self.right_paned, orient=tk.VERTICAL)
        self.right_paned.add(self.ref_paned, weight=1)

        self.ref_frame = ttk.LabelFrame(self.ref_paned, text="Ref & Check Stars", padding=10)
        self.ref_paned.add(self.ref_frame, weight=4)

        self.ap_frame = ttk.LabelFrame(self.ref_paned, text="Aperture Settings", padding=5)
        self.ref_paned.add(self.ap_frame, weight=1)

        # UI Elements: Consistent width of 25 characters (approx 20 + padding)
        self.details_text = tk.Text(self.details_frame, wrap=tk.WORD, state=tk.DISABLED, 
                                    bg="#f8f9fa", font=("Courier", 10), width=25, height=12)
        self.details_text.pack(fill=tk.BOTH, expand=True)

        self.var_text = tk.Text(self.var_frame, wrap=tk.WORD, state=tk.DISABLED,
                                bg="#fff5f5", font=("Courier", 10), width=25, height=12)
        self.var_text.pack(fill=tk.BOTH, expand=True)

        self.ref_text = tk.Text(self.ref_frame, wrap=tk.WORD, state=tk.DISABLED,
                                bg="#f1f8f1", font=("Courier", 9), width=25)
        self.ref_text.pack(fill=tk.BOTH, expand=True)

        # Export Star Button
        if self.export_callback:
            self.export_btn = ttk.Button(self.ref_frame, text="Export Stars to LC Tab", command=self._on_export_click)
            self.export_btn.pack(side=tk.BOTTOM, fill=tk.X, pady=2)
            
        # Aperture Controls
        self.ap_var = tk.DoubleVar(value=self.config.get('aperture_radius', 8.0))
        self.ann_in_var = tk.DoubleVar(value=self.config.get('annulus_inner', 15.0))
        self.ann_out_var = tk.DoubleVar(value=self.config.get('annulus_outer', 20.0))
        
        def create_ap_field(label, var, row):
            ttk.Label(self.ap_frame, text=label).grid(row=row, column=0, sticky=tk.W, padx=2)
            ttk.Entry(self.ap_frame, textvariable=var, width=6).grid(row=row, column=1, sticky=tk.W, padx=2)
            
        create_ap_field("Aperture:", self.ap_var, 0)
        create_ap_field("Annulus In:", self.ann_in_var, 1)
        create_ap_field("Annulus Out:", self.ann_out_var, 2)
        
        self.export_ap_btn = ttk.Button(self.ap_frame, text="Export Aps to Settings", command=self._on_export_ap_click)
        self.export_ap_btn.grid(row=3, column=0, columnspan=2, pady=5, sticky=tk.EW)
        
        # Setup Figure
        self.fig = Figure(figsize=(8, 8))
        if self.has_wcs:
            self.ax = self.fig.add_subplot(111, projection=self.wcs)
        else:
            self.ax = self.fig.add_subplot(111)
            
        zscale = ZScaleInterval(contrast=0.15) # Slightly higher contrast for better star visibility
        vmin, vmax = zscale.get_limits(self.data)
        
        # Ensure the background is dark by flooring vmin to the median if needed
        bg_median = np.nanmedian(self.data)
        if vmin < bg_median:
            vmin = bg_median
            
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
        
        # Profile Figure
        self.profile_fig = Figure(figsize=(4, 4))
        self.profile_ax = self.profile_fig.add_subplot(111)
        self.profile_fig.subplots_adjust(left=0.15, right=0.95, top=0.9, bottom=0.15)
        self.profile_canvas = FigureCanvasTkAgg(self.profile_fig, master=self.profile_frame)
        self.profile_canvas.draw()
        self.profile_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        self.marker = None
        self.ref_markers = []
        
        # Connect Events
        self.canvas.mpl_connect('motion_notify_event', self.on_hover)
        self.canvas.mpl_connect('button_press_event', self.on_click)
        self.canvas.mpl_connect('scroll_event', self.on_scroll)
        
        # Load Initial Stars if provided
        if self.initial_stars:
            self.parent.after(500, self._auto_mark_initial_stars)
        
        # Right-click Context Menu
        self.context_menu = tk.Menu(self.parent, tearoff=0)
        self.context_menu.add_command(label="Mark as Variable Star (Red)", command=self._add_variable_star)
        self.context_menu.add_command(label="Mark as Check Star (Blue)", command=self._add_check_star)
        self.context_menu.add_command(label="Mark as Reference Star (Green)", command=self._add_on_the_spot_ref)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Remove Marker", command=self._remove_marker_at_click)
        self.context_menu.add_command(label="Clear ALL Markers", command=self._clear_all_markers)
        
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
        
        # 2. If it's a marked star (any role), we don't draw a red cross
        if is_ref:
            self.canvas.draw_idle()
            return

        for star in ([self.variable_star, self.check_star] + self.on_the_spot_refs):
            if star and np.sqrt((star['x'] - x)**2 + (star['y'] - y)**2) < 5.0:
                self.canvas.draw_idle()
                return

        # 4. Draw red cross for new inspection
        self.marker, = self.ax.plot(x, y, 'r+', markersize=15, mew=2)
        self.canvas.draw_idle()

    def _basic_fit(self, x_click, y_click, suppress_cross=False):
        res = self._fit_at(x_click, y_click)
        if not res:
            self._update_details("Fit Failed.")
            return

        # Update Profile Plot
        self._update_profile_plot(res)

        # Determine ZP if available
        active_zp = self.default_zp
        zp_label = f"ZP={self.default_zp:.3f}"
        if self.on_the_spot_zp is not None:
            active_zp = self.on_the_spot_zp
            zp_label = f"Ens ZP={self.on_the_spot_zp:.3f}"
            
        cal_mag = res['inst_mag'] + active_zp
        
        details = f"--- Real-time Fit ---\n\n"
        details += f"X:      {res['x']:.2f}\n"
        details += f"Y:      {res['y']:.2f}\n\n"
        
        if self.has_wcs:
            coord = self.wcs.pixel_to_world(res['x'], res['y'])
            details += f"RA:  {coord.ra.to_string(unit='hour', sep=':', precision=1)}\n"
            details += f"Dec: {coord.dec.to_string(unit='degree', sep=':', precision=1, alwayssign=True)}\n\n"
            
            # Identify in catalog
            cat_star = self._query_catalog(coord.ra.deg, coord.dec.deg)
            if cat_star:
                v_mag = cat_star.get('V_mag')
                v_str = f"{v_mag:.3f}" if isinstance(v_mag, (int, float)) and not np.isnan(v_mag) else "N/A"
                details += f"--- Catalog Comparison ---\n"
                details += f"ID: {cat_star.get('display_name', 'Star')}\n"
                details += f"Catalog V: {v_str}\n\n"
                if cat_star.get('is_variable'):
                    details += f"!!! VARIABLE STAR !!!\n"
                    details += f"Type: {cat_star.get('var_type', 'N/A')}\n\n"
        
        details += f"FWHM:   {res['fwhm']:.2f} px\n"
        details += f"Inst M: {res['inst_mag']:.3f}\n"
        details += f"Cal M:  {cal_mag:.3f}*\n"
        details += f"(* using {zp_label})\n"
        
        self._update_details(details)
        if not suppress_cross:
            self._draw_marker(res['x'], res['y'])

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

    def _add_variable_star(self):
        x, y = self._last_click_pos
        
        # Clear existing variable markers first (mutual exclusivity)
        if self.variable_star:
            for m in self.variable_star['markers']: m.remove()
            self.variable_star = None

        star_data = self._mark_star(x, y, "Variable", "red")
        if star_data:
            self.variable_star = star_data
            self._update_var_panel()
            self._update_ref_panel()

    def _add_check_star(self):
        x, y = self._last_click_pos
        # If there was a check star, it becomes a ref star
        old_check = self.check_star
        
        star_data = self._mark_star(x, y, "Check", "blue")
        if star_data:
            self.check_star = star_data
            if old_check:
                # Convert old check to ref (only if it wasn't the star we just clicked)
                if np.sqrt((old_check['x'] - star_data['x'])**2 + (old_check['y'] - star_data['y'])**2) > 5.0:
                    old_check['role'] = 'Reference'
                    for m in old_check['markers']: m.set_color('lime')
                    self.on_the_spot_refs.append(old_check)
                else:
                    # We clicked the existing check star, so old_check's markers were removed in _mark_star
                    pass
            
            self._update_ref_panel()
            self._update_var_panel()

    def _add_on_the_spot_ref(self):
        x, y = self._last_click_pos
        star_data = self._mark_star(x, y, "Reference", "lime")
        if star_data:
            self.on_the_spot_refs.append(star_data)
            self._update_ref_panel()
            self._update_var_panel()

    def _mark_star(self, x, y, role, color):
        # 1. Fit the star
        res = self._fit_at(x, y)
        if not res:
            messagebox.showwarning("Fit Failed", "Could not fit a star at this position.")
            return None
            
        # 2. Get catalog data
        if not self.has_wcs:
            messagebox.showwarning("WCS Required", "WCS is needed to identify stars.")
            return None
            
        coord = self.wcs.pixel_to_world(res['x'], res['y'])
        cat_star = self._query_catalog(coord.ra.deg, coord.dec.deg)
        if not cat_star:
            messagebox.showwarning("No Catalog Match", "No matching catalog star found.")
            return None

        # 3. Check for existing role and remove it
        self._remove_marker_at(res['x'], res['y'], quiet=True)

        # 4. Determine Radii
        if self.config.get('use_flexible_aperture') and res.get('fwhm'):
            ap = res['fwhm'] * self.config.get('aperture_fwhm_factor', 2.0)
            ann_in = ap + self.config.get('annulus_inner_gap', 2.0)
            ann_out = ann_in + self.config.get('annulus_width', 5.0)
            # Update local vars for visualization in controls
            self.ap_var.set(round(ap, 2))
            self.ann_in_var.set(round(ann_in, 2))
            self.ann_out_var.set(round(ann_out, 2))
        else:
            ap = self.ap_var.get()
            ann_in = self.ann_in_var.get()
            ann_out = self.ann_out_var.get()

        # 5. Draw Markers
        m1 = patches.Circle((res['x'], res['y']), radius=ap, color=color, fill=False, lw=1.5)
        m2 = patches.Circle((res['x'], res['y']), radius=ann_in, color=color, fill=False, lw=0.8, linestyle='--')
        m3 = patches.Circle((res['x'], res['y']), radius=ann_out, color=color, fill=False, lw=0.8, linestyle='--')
        self.ax.add_patch(m1)
        self.ax.add_patch(m2)
        self.ax.add_patch(m3)
        
        # 6. Data
        c_ref = SkyCoord(ra=cat_star['ra_deg']*u.deg, dec=cat_star['dec_deg']*u.deg)
        return {
            'x': res['x'], 'y': res['y'],
            'role': role,
            'id': cat_star.get('display_name', 'Star'),
            'ra_hms': c_ref.ra.to_string(unit='hour', sep=':', precision=1, pad=True),
            'dec_dms': c_ref.dec.to_string(unit='deg', sep=':', precision=1, alwayssign=True, pad=True),
            'cat_mag': cat_star.get('V_mag') if 'B' not in self.header.get('FILTER', 'V').upper() else cat_star.get('B_mag'),
            'inst_mag': res['inst_mag'],
            'is_variable': cat_star.get('is_variable', False),
            'markers': [m1, m2, m3]
        }

    def _remove_marker_at_click(self):
        x, y = self._last_click_pos
        self._remove_marker_at(x, y)

    def _remove_marker_at(self, x, y, quiet=False):
        removed = False
        # Check Variable
        if self.variable_star:
            dist = np.sqrt((self.variable_star['x'] - x)**2 + (self.variable_star['y'] - y)**2)
            if dist < 10.0:
                for m in self.variable_star['markers']: m.remove()
                self.variable_star = None
                removed = True
        
        # Check Check
        if not removed and self.check_star:
            dist = np.sqrt((self.check_star['x'] - x)**2 + (self.check_star['y'] - y)**2)
            if dist < 10.0:
                for m in self.check_star['markers']: m.remove()
                self.check_star = None
                removed = True

        # Check Refs
        if not removed:
            for i, r in enumerate(self.on_the_spot_refs):
                dist = np.sqrt((r['x'] - x)**2 + (r['y'] - y)**2)
                if dist < 10.0:
                    for m in r['markers']: m.remove()
                    self.on_the_spot_refs.pop(i)
                    removed = True
                    break
        
        if removed:
            self._update_var_panel()
            self._update_ref_panel()
            self.canvas.draw_idle()
        elif not quiet:
            messagebox.showinfo("Not Found", "No marked star found near this position.")

    def _update_var_panel(self):
        text = ""
        if self.variable_star:
            s = self.variable_star
            text += f"ID:  {s['id']}\n"
            text += f"RA:  {s['ra_hms']}\n"
            text += f"Dec: {s['dec_dms']}\n"
            text += f"Mag: {s['cat_mag']:.3f} (Catalog)\n"
            text += f"Inst:{s['inst_mag']:.3f}\n"
            text += "=" * 25 + "\n"
        else:
            text = "No variable star marked.\n"
        
        self.var_text.config(state=tk.NORMAL)
        self.var_text.delete(1.0, tk.END)
        self.var_text.insert(tk.END, text)
        self.var_text.config(state=tk.DISABLED)

    def _update_ref_panel(self):
        text = ""
        # 1. Check Star
        if self.check_star:
            s = self.check_star
            text += f"--- CHECK STAR (Blue) ---\n"
            text += f"ID:  {s['id']}\n"
            text += f"RA:  {s['ra_hms']}\n"
            text += f"Dec: {s['dec_dms']}\n"
            text += f"Mag: {s['cat_mag']:.3f}\n"
            text += "-" * 25 + "\n\n"
        
        # 2. Reference Ensemble
        if self.on_the_spot_refs:
            text += f"--- REFERENCES (Green) ---\n"
            # Calculate ZP
            zps = [r['cat_mag'] - r['inst_mag'] for r in self.on_the_spot_refs if r['cat_mag'] is not None]
            if zps:
                self.on_the_spot_zp = np.mean(zps)
                text += f"Ensemble ZP: {self.on_the_spot_zp:.3f}\n"
            
            for i, r in enumerate(self.on_the_spot_refs):
                var_tag = " [VAR!]" if r['is_variable'] else ""
                text += f"#{i+1:<2} {r['id']}{var_tag}\n"
                text += f"    RA:  {r['ra_hms']}\n"
                text += f"    Dec: {r['dec_dms']}\n"
                text += f"    Mag: {r['cat_mag']:.3f}\n"
                text += "-" * 25 + "\n"
        
        if not self.check_star and not self.on_the_spot_refs:
            text = "No reference or check stars marked."

        self.ref_text.config(state=tk.NORMAL)
        self.ref_text.delete(1.0, tk.END)
        self.ref_text.insert(tk.END, text)
        self.ref_text.config(state=tk.DISABLED)
        self.canvas.draw_idle()

    def _clear_all_markers(self):
        if self.variable_star:
            for m in self.variable_star['markers']: m.remove()
            self.variable_star = None
        if self.check_star:
            for m in self.check_star['markers']: m.remove()
            self.check_star = None
        for r in self.on_the_spot_refs:
            for m in r['markers']: m.remove()
        self.on_the_spot_refs = []
        self.on_the_spot_zp = None
        
        self._update_var_panel()
        self._update_ref_panel()
        self.canvas.draw_idle()

    def _fit_at(self, x, y):
        size = 25
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
            
            x_orig, y_orig = cutout.to_original_position((g_fit.x_mean.value, g_fit.y_mean.value))
            fwhm = abs(g_fit.x_stddev.value * 2.355)
            total_flux = g_fit.amplitude.value * 2 * np.pi * g_fit.x_stddev.value ** 2
            if total_flux <= 0: return None
            
            return {
                'x': x_orig, 'y': y_orig, 'fwhm': fwhm, 
                'inst_mag': -2.5 * np.log10(total_flux),
                'data_sub': d_fit_sub,
                'g_fit': g_fit,
                'x_grid': xx, 'y_grid': yy,
                'fit_xc': g_fit.x_mean.value,
                'fit_yc': g_fit.y_mean.value
            }
        except:
            return None

    def _update_profile_plot(self, res):
        self.profile_ax.clear()
        
        data = res['data_sub']
        xx, yy = res['x_grid'], res['y_grid']
        xc, yc = res['fit_xc'], res['fit_yc']
        g_fit = res['g_fit']
        
        distances = np.sqrt((xx - xc)**2 + (yy - yc)**2)
        
        # Limits: extend to inner annulus or 2x aperture
        ap = self.ap_var.get()
        ann_in = self.ann_in_var.get()
        rad_limit = max(ann_in, ap * 1.5, 10)
        
        mask = distances <= rad_limit
        self.profile_ax.scatter(distances[mask], data[mask], color='royalblue', alpha=0.5, s=10)
        
        # Fit curve
        r_fine = np.linspace(0, rad_limit, 100)
        self.profile_ax.plot(r_fine, g_fit(xc + r_fine, yc), color='darkorange', lw=2)
        
        # Aperture line
        self.profile_ax.axvline(x=ap, color='red', ls='--', lw=1.5, label='Ap')
        self.profile_ax.axvline(x=ann_in, color='green', ls=':', lw=1, label='Ann')
        
        self.profile_ax.set_title(f"FWHM: {res['fwhm']:.2f}px", fontsize=9)
        self.profile_ax.set_xlim(0, rad_limit)
        self.profile_ax.grid(True, alpha=0.2)
        
        self.profile_canvas.draw_idle()

    def _on_export_ap_click(self):
        if not self.aperture_export_callback: return
        data = {
            'aperture': self.ap_var.get(),
            'annulus_in': self.ann_in_var.get(),
            'annulus_out': self.ann_out_var.get()
        }
        self.aperture_export_callback(data)
        messagebox.showinfo("Exported", "Aperture settings updated in main window.")

    def _auto_mark_initial_stars(self):
        if not self.has_wcs: return
        
        # 1. Variable
        v = self.initial_stars.get('variable')
        if v and v.get('ra') is not None:
            self._mark_by_coord(v['ra'], v['dec'], "Variable")
            
        # 2. Check
        c = self.initial_stars.get('check')
        if c and c.get('ra') is not None:
            self._mark_by_coord(c['ra'], c['dec'], "Check")
            
        # 3. Refs
        for r in self.initial_stars.get('refs', []):
            if r.get('ra') is not None:
                self._mark_by_coord(r['ra'], r['dec'], "Reference")
        
        self._update_var_panel()
        self._update_ref_panel()

    def _mark_by_coord(self, ra, dec, role):
        try:
            x, y = self.wcs.world_to_pixel(SkyCoord(ra, dec, unit='deg'))
            # Check if within bounds
            if x < 0 or x >= self.data.shape[1] or y < 0 or y >= self.data.shape[0]:
                return
            
            # Use existing role handlers but mock the click position
            self._last_click_pos = (x, y)
            if role == "Variable": self._add_variable_star()
            elif role == "Check": self._add_check_star()
            elif role == "Reference": self._add_on_the_spot_ref()
        except Exception as e:
            print(f"Auto-mark failed for {role} at {ra}, {dec}: {e}")

    def _on_export_click(self):
        if not self.export_callback: return
        
        data = {
            'variable': None,
            'check': None,
            'refs': []
        }
        
        if self.variable_star and self.has_wcs:
            coord = self.wcs.pixel_to_world(self.variable_star['x'], self.variable_star['y'])
            data['variable'] = {'ra': coord.ra.deg, 'dec': coord.dec.deg, 'name': self.variable_star['id']}
            
        if self.check_star and self.has_wcs:
            coord = self.wcs.pixel_to_world(self.check_star['x'], self.check_star['y'])
            data['check'] = {'ra': coord.ra.deg, 'dec': coord.dec.deg, 'name': self.check_star['id']}
            
        for r in self.on_the_spot_refs:
            if self.has_wcs:
                coord = self.wcs.pixel_to_world(r['x'], r['y'])
                data['refs'].append({'ra': coord.ra.deg, 'dec': coord.dec.deg, 'name': r['id']})
            
        self.export_callback(data)
        messagebox.showinfo("Exported", "Star selection exported to the Light Curve tab.")

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
