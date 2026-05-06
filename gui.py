import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import os
import sys
import threading
import csv
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from astropy.coordinates import SkyCoord
import astropy.units as u

class StdoutRedirector:
    def __init__(self, text_widget):
        self.text_widget = text_widget
        self.log_file = None

    def set_log_file(self, file_path):
        self.log_file = file_path

    def write(self, string):
        self.text_widget.insert(tk.END, string)
        self.text_widget.see(tk.END)
        if self.log_file:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(string)

    def flush(self):
        pass

class ScrollableFrame(ttk.Frame):
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, bg="#f0f2f5")
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            )
        )

        def _on_mousewheel(event):
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            
        self.canvas.bind("<Enter>", lambda _: self.canvas.bind_all("<MouseWheel>", _on_mousewheel))
        self.canvas.bind("<Leave>", lambda _: self.canvas.unbind_all("<MouseWheel>"))

        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        
    def on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

def run_config_gui(pipeline_callback=None):
    """
    Launches a persistent Tkinter GUI for pipeline configuration.
    pipeline_callback: A function that takes (config) and runs the analysis.
    """
    root = tk.Tk()
    root.title("Calibra: Automated Photometric Analysis & Calibration Toolkit")
    root.geometry("950x650")
    root.resizable(True, True)
    root.configure(bg="#f0f2f5") 

    # --- MODERN STYLING ---
    style = ttk.Style()
    style.theme_use('clam') # Clam is more customizable than default
    
    # Configure Colors
    primary_blue = "#1a3a5f" # Deep space blue
    accent_green = "#2e7d32" # Forest green for "Run"
    text_dark = "#333333"
    
    style.configure("TNotebook", background="#f0f2f5", padding=5)
    style.configure("TNotebook.Tab", background="#e1e4e8", padding=[12, 4], font=("Arial", 10))
    style.map("TNotebook.Tab", background=[("selected", "white")], font=[("selected", ("Arial", 10, "bold"))])
    
    style.configure("TLabelframe", background="white", borderwidth=1, relief="solid")
    style.configure("TLabelframe.Label", background="white", font=("Arial", 10, "bold"), foreground=primary_blue)
    
    style.configure("TLabel", background="white", font=("Arial", 9))
    style.configure("TEntry", fieldbackground="#f8f9fa", borderwidth=1)
    style.configure("TCheckbutton", background="white")
    style.configure("TCombobox", fieldbackground="#f8f9fa")

    # Output dictionary
    config = None

    # Variable storage
    vars_dict = {}

    def add_entry(parent, label_text, var_name, default_val, row, col_offset=0, vtype=float, width=15):
        ttk.Label(parent, text=label_text).grid(row=row, column=col_offset*2, sticky=tk.W, padx=10, pady=5)
        if vtype == str:
            var = tk.StringVar(value=str(default_val))
        elif vtype == int:
            var = tk.IntVar(value=int(default_val))
        else:
            var = tk.DoubleVar(value=float(default_val))
        vars_dict[var_name] = (var, vtype)
        entry = ttk.Entry(parent, textvariable=var, width=width)
        entry.grid(row=row, column=col_offset*2+1, sticky=tk.W, padx=10, pady=5)
        return var

    def add_check(parent, label_text, var_name, default_val, row, col_offset=0):
        var = tk.BooleanVar(value=bool(default_val))
        vars_dict[var_name] = (var, bool)
        chk = ttk.Checkbutton(parent, text=label_text, variable=var)
        chk.grid(row=row, column=col_offset*2, columnspan=2, sticky=tk.W, padx=10, pady=5)
        return var

    def add_dropdown(parent, label_text, var_name, options, default_val, row, col_offset=0, width=13):
        ttk.Label(parent, text=label_text).grid(row=row, column=col_offset*2, sticky=tk.W, padx=10, pady=5)
        var = tk.StringVar(value=str(default_val))
        vars_dict[var_name] = (var, str)
        cb = ttk.Combobox(parent, textvariable=var, values=options, state="readonly", width=width)
        cb.grid(row=row, column=col_offset*2+1, sticky=tk.W, padx=10, pady=5)
        return var

    def save_session():
        import json
        data = {}
        for key, (var, vtype) in vars_dict.items():
            try:
                data[key] = var.get()
            except:
                pass # Skip if variable is destroyed or invalid
        
        try:
            with open("calibra_session.json", "w") as f:
                json.dump(data, f, indent=4)
            print("Session saved to calibra_session.json")
        except Exception as e:
            messagebox.showerror("Save Error", f"Could not save session: {e}")

    def load_session():
        import json
        if not os.path.exists("calibra_session.json"):
            return
        
        try:
            with open("calibra_session.json", "r") as f:
                data = json.load(f)
            
            for key, value in data.items():
                if key in vars_dict:
                    var, vtype = vars_dict[key]
                    try:
                        var.set(value)
                    except:
                        # Silently skip errors (e.g. type mismatch if session file is old)
                        pass
            print("Session loaded from calibra_session.json")
        except Exception as e:
            print(f"Error loading session: {e}")

    # Create Notebook for Tabs
    notebook = ttk.Notebook(root)
    notebook.pack(pady=10, expand=True, fill='both')

    # --- TAB 0: About ---
    tab_about = ttk.Frame(notebook)
    notebook.add(tab_about, text="About")
    
    about_container = tk.Frame(tab_about, padx=30, pady=10, bg="white")
    about_container.pack(fill="both", expand=True)
    
    # Try to load Logo
    logo_path = os.path.join(os.path.dirname(__file__), "calibra_logo.png")

    try:
        from PIL import Image, ImageTk
        img = Image.open(logo_path)
        img = img.resize((250, 250), Image.Resampling.LANCZOS)
        logo_img = ImageTk.PhotoImage(img)
        lbl_logo = tk.Label(about_container, image=logo_img, bg="white")
        lbl_logo.image = logo_img # Keep reference
        lbl_logo.pack(pady=(0, 5))
    except Exception as e:
        # Fallback if PIL is missing or file not found
        tk.Label(about_container, text="[ CALIBRA ]", font=("Arial", 24, "bold"), bg="white", fg=primary_blue).pack(pady=(0, 20))
    
    tk.Label(about_container, text="Calibra: An automated photometric analysis & calibration toolkit", font=("Arial", 16, "bold"), anchor="w", bg="white", fg=primary_blue).pack(fill="x")
#    tk.Label(about_container, text="An automated photometric analysis & calibration toolkit", font=("Arial", 11, "italic"), anchor="w", bg="white", fg="#666").pack(fill="x", pady=(0, 20))
    
    info_frame = tk.Frame(about_container, bg="white")
    info_frame.pack(fill="x", pady=10)
    tk.Label(info_frame, text="Version: 2.0 \tLatest Update: 2026-05-05", font=("Arial", 10), anchor="w", bg="white").pack(fill="x")
    #tk.Label(info_frame, text="Latest Update: 2026-04-30", font=("Arial", 10), anchor="w", bg="white").pack(fill="x")
    
    tk.Label(about_container, text="Description:", font=("Arial", 11, "bold"), anchor="w", bg="white", fg=primary_blue).pack(fill="x", pady=(10, 5))
    desc_text = (
        "Calibra is a toolkit for the automated analysis of astronomical FITS images.\n"
        "It uses star detection, sub-pixel PSF fitting, aperture photometry, \n"
        "zero-point calibration using online catalogs as ATLAS-RefCat2, APASS DR9, \n"
        "Landolt Standards Catalogue and Gaia DR3, and offers determination of color transformations between filters.\n\n"
        "Designed for astronomers and enthusiasts to explore the principles of CCD/CMOS photometry."
    )
    tk.Label(about_container, text=desc_text, justify=tk.LEFT, font=("Arial", 10), anchor="w", bg="white").pack(fill="x")

    # --- TAB 1: Settings ---
    tab_settings_outer = ttk.Frame(notebook)
    notebook.add(tab_settings_outer, text="⚙ Settings")
    
    settings_scroll = ScrollableFrame(tab_settings_outer)
    settings_scroll.pack(fill="both", expand=True)
    tab_settings = settings_scroll.scrollable_frame

    # Files & Catalog (from old TAB 1)
    lf_files = ttk.LabelFrame(tab_settings, text="Files & Reference Catalog")
    lf_files.pack(fill="x", padx=10, pady=10)
    
    ttk.Label(lf_files, text="Input Pattern:").grid(row=0, column=0, sticky=tk.W, padx=10, pady=5)
    input_var = tk.StringVar(value=r"C:\Astro\Photometry_Calibra\fitsfiles\*.fits")
    vars_dict["input_pattern"] = (input_var, str)
    ttk.Entry(lf_files, textvariable=input_var, width=65).grid(row=0, column=1, sticky=tk.W, padx=10, pady=5)
    
    def browse_input_dir():
        from tkinter import filedialog
        dirname = filedialog.askdirectory(initialdir=r"C:\Astro\Photometry_Calibra", title="Select FITS Directory")
        if dirname:
            input_var.set(os.path.join(dirname, "*.fits"))
            
    ttk.Button(lf_files, text="Browse...", command=browse_input_dir).grid(row=0, column=2, padx=5)
    
    ttk.Label(lf_files, text="Ref Catalog:").grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)
    cat_var = tk.StringVar(value="ATLAS refcat2")
    vars_dict["reference_catalog"] = (cat_var, str)
    cat_cb = ttk.Combobox(lf_files, textvariable=cat_var, values=["ATLAS refcat2", "APASS DR9", "Landolt Standard Star Catalogue", "GAIA_DR3", os.path.join('photometry_refstars', 'reference_stars.csv')], width=62)
    cat_cb.grid(row=1, column=1, sticky=tk.W, padx=10, pady=5)
    
    def browse_catalog():
        from tkinter import filedialog
        filename = filedialog.askopenfilename(initialdir="photometry_refstars", title="Select Reference Catalog", filetypes=(("CSV files", "*.csv"), ("all files", "*.*")))
        if filename:
            cat_var.set(filename)
            
    ttk.Button(lf_files, text="Browse...", command=browse_catalog).grid(row=1, column=2, padx=5)

    # Region Filtering (from old TAB 1)
    lf_filt = ttk.LabelFrame(tab_settings, text="Region Filtering")
    lf_filt.pack(fill="x", padx=10, pady=10)
    add_dropdown(lf_filt, "Filter Mode:", "filter_mode", ["all", "xy", "radec"], "all", 0)
    
    ttk.Label(lf_filt, text="XY Bounds (Pixels)").grid(row=1, column=0, columnspan=4, sticky=tk.W, padx=10, pady=(10,0))
    add_entry(lf_filt, "X Min:", "xy_x_min", 200, 2, col_offset=0, vtype=int)
    add_entry(lf_filt, "X Max:", "xy_x_max", 6000, 2, col_offset=1, vtype=int)
    add_entry(lf_filt, "Y Min:", "xy_y_min", 200, 3, col_offset=0, vtype=int)
    add_entry(lf_filt, "Y Max:", "xy_y_max", 4000, 3, col_offset=1, vtype=int)

    ttk.Label(lf_filt, text="RADEC Bounds").grid(row=4, column=0, columnspan=4, sticky=tk.W, padx=10, pady=(10,0))
    add_entry(lf_filt, "RA Min:", "ra_min", "10h34m00s", 5, col_offset=0, vtype=str)
    add_entry(lf_filt, "RA Max:", "ra_max", "10h35m00s", 5, col_offset=1, vtype=str)
    add_entry(lf_filt, "DEC Min:", "dec_min", "+43d00m00s", 6, col_offset=0, vtype=str)
    add_entry(lf_filt, "DEC Max:", "dec_max", "+43d30m00s", 6, col_offset=1, vtype=str)

    # Pre-processing (from old TAB 1.5)
    lf_calib = ttk.LabelFrame(tab_settings, text="FITS Calibration (Bias & Flats)")
    lf_calib.pack(fill="x", padx=10, pady=10)
    
    add_check(lf_calib, "Enable Pre-processing (Apply Bias/Flats)", "enable_calibration", False, 0)
    
    # Plate solving reminder - positioned to avoid overlap
    ttk.Label(lf_calib, text="* Note: Input FITS files must still be plate solved (contain WCS headers).", 
              foreground="#a00", font=("Arial", 8, "italic")).grid(row=0, column=1, sticky=tk.W, padx=(200, 10))
    
    def add_file_selector(parent, label, var_name, default, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, padx=10, pady=5)
        var = tk.StringVar(value=default)
        vars_dict[var_name] = (var, str)
        ttk.Entry(parent, textvariable=var, width=65).grid(row=row, column=1, sticky=tk.W, padx=10, pady=5)
        
        def browse():
            from tkinter import filedialog
            fname = filedialog.askopenfilename(initialdir="bias_and_flats", title=f"Select {label}")
            if fname: var.set(fname)
            
        ttk.Button(parent, text="Browse...", command=browse).grid(row=row, column=2, padx=5)
        return var

    add_file_selector(lf_calib, "Master Bias:", "bias_path", r"C:\Astro\Photometry_Calibra\bias_and_flats\Master_Bias_1x1_gain_0.fits", 1)
    add_file_selector(lf_calib, "Master Flat (V):", "flat_v_path", r"C:\Astro\Photometry_Calibra\bias_and_flats\FLAT_Vmag_1x1_gain_0.fits", 2)
    add_file_selector(lf_calib, "Master Flat (B):", "flat_b_path", r"C:\Astro\Photometry_Calibra\bias_and_flats\FLAT_Bmag_1x1_gain_0.fits", 3)


    
    # --- TAB 2: Detect & Measure ---
    tab_detect_outer = ttk.Frame(notebook)
    notebook.add(tab_detect_outer, text="Detect & Measure")
    
    detect_scroll = ScrollableFrame(tab_detect_outer)
    detect_scroll.pack(fill="both", expand=True)
    tab_detect = detect_scroll.scrollable_frame

    # Info frame for Detect & Measure
    lf_detect_info = ttk.LabelFrame(tab_detect, text="Measurement Pipeline")
    lf_detect_info.pack(fill="x", padx=10, pady=10)
    ttk.Label(lf_detect_info, text="This tab runs the full detection and zero-point calibration pipeline on your input FITS files.\nIt will produce CSV instrumental results and a calibration report for each filter.", justify=tk.LEFT).pack(padx=10, pady=10)

    # --- TAB 3: Color & Differential ---
    tab_color_diff_outer = ttk.Frame(notebook)
    notebook.add(tab_color_diff_outer, text="Color & Differential")
    
    color_diff_scroll = ScrollableFrame(tab_color_diff_outer)
    color_diff_scroll.pack(fill="both", expand=True)
    tab_color_diff = color_diff_scroll.scrollable_frame

    # --- Color Calibration Section ---
    lf_color = ttk.LabelFrame(tab_color_diff, text="1. Derive Transformation Coefficients (B-V Pairs)")
    lf_color.pack(fill="x", padx=10, pady=10)
    
    import glob
    def get_latest_csv(pattern):
        files = glob.glob(os.path.join("photometry_output", pattern))
        return max(files, key=os.path.getmtime) if files else ""
        
    recent_b_csv = get_latest_csv("*Bmag*.csv") or get_latest_csv("*_B_*.csv")
    recent_v_csv = get_latest_csv("*Vmag*.csv") or get_latest_csv("*_V_*.csv")
    
    add_file_selector(lf_color, "B-Filter Results (CSV):", "color_b_csv", recent_b_csv, 0)
    add_file_selector(lf_color, "V-Filter Results (CSV):", "color_v_csv", recent_v_csv, 1)
    
    ttk.Label(lf_color, text="Airmass B*:").grid(row=2, column=0, sticky=tk.W, padx=10, pady=5)
    air_b_var = tk.DoubleVar(value=1.0)
    vars_dict["air_b"] = (air_b_var, float)
    ttk.Entry(lf_color, textvariable=air_b_var, width=10).grid(row=2, column=1, sticky=tk.W, padx=10, pady=5)
    
    ttk.Label(lf_color, text="Airmass V*:").grid(row=3, column=0, sticky=tk.W, padx=10, pady=5)
    air_v_var = tk.DoubleVar(value=1.0)
    vars_dict["air_v"] = (air_v_var, float)
    ttk.Entry(lf_color, textvariable=air_v_var, width=10).grid(row=3, column=1, sticky=tk.W, padx=10, pady=5)

    ttk.Label(lf_color, text="* Global extinction (k_B, k_V) settings from the Settings tab will be used.", foreground="#555", font=("Arial", 8, "italic")).grid(row=2, column=2, columnspan=2, sticky=tk.W, padx=10, pady=5)

    override_airmass_var = tk.BooleanVar(value=False)
    vars_dict["override_airmass"] = (override_airmass_var, bool)
    ttk.Label(lf_color, text="* 1.0 used if FITS values not found. To override FITS airmass values, check the box below and enter new values.", foreground="#555", font=("Arial", 8, "italic")).grid(row=4, column=0, columnspan=2, sticky=tk.W, padx=10, pady=5)
    ttk.Checkbutton(lf_color, text="Override FITS Airmass", variable=override_airmass_var).grid(row=5, column=0, columnspan=2, sticky=tk.W, padx=10, pady=5)

    color_status_var = tk.StringVar(value="Select B and V result files to begin.")
    tk.Label(lf_color, textvariable=color_status_var, fg="#333", font=("Arial", 9, "italic")).grid(row=6, column=0, columnspan=4, pady=5)

    def on_run_color():
        try:
            b_csv = vars_dict["color_b_csv"][0].get()
            v_csv = vars_dict["color_v_csv"][0].get()
            
            if not os.path.exists(b_csv) or not os.path.exists(v_csv):
                messagebox.showerror("File Error", "Please select valid CSV result files for both filters.")
                return
            
            import csv
            
            color_status_var.set("Reading results and fetching catalog data...")
            root.update_idletasks()
            
            # Load results using standard csv module
            def read_csv_to_dicts(path):
                with open(path, mode='r', encoding='utf-8') as f:
                    return [row for row in csv.DictReader(f)]

            data_b = read_csv_to_dicts(b_csv)
            data_v = read_csv_to_dicts(v_csv)
            
            # Auto-extract Airmass from CSV if present (unless overridden)
            if not override_airmass_var.get():
                if data_b and 'airmass' in data_b[0]:
                    try: 
                        am_b = float(data_b[0]['airmass'])
                        air_b_var.set(am_b)
                    except: pass
                if data_v and 'airmass' in data_v[0]:
                    try: 
                        am_v = float(data_v[0]['airmass'])
                        air_v_var.set(am_v)
                    except: pass

            # Convert numeric fields
            for d in data_b:
                for k in ['ra_deg', 'dec_deg', 'mag_inst', 'snr']:
                    if k in d and d[k]: d[k] = float(d[k])
            for d in data_v:
                for k in ['ra_deg', 'dec_deg', 'mag_inst', 'snr']:
                    if k in d and d[k]: d[k] = float(d[k])

            # Get catalog (use center of V image)
            valid_coords = [d for d in data_v if isinstance(d.get('ra_deg'), float) and isinstance(d.get('dec_deg'), float)]
            ra_c = sum(d['ra_deg'] for d in valid_coords) / len(valid_coords) if valid_coords else 0
            dec_c = sum(d['dec_deg'] for d in valid_coords) / len(valid_coords) if valid_coords else 0
            
            cat_type = vars_dict["reference_catalog"][0].get()
            search_radius = float(vars_dict["catalog_search_radius"][0].get())
            from photometry.color_calibration import derive_color_terms
            from photometry.calibration import get_ref_stars
            
            catalog = get_ref_stars(cat_type, ra_c, dec_c, radius_arcmin=search_radius, verbose=True)
            
            if not catalog:
                color_status_var.set("Error: Could not fetch online catalog.")
                return
                
            res = derive_color_terms(data_b, data_v, 
                                     catalog, "photometry_output", 
                                     airmass_b=air_b_var.get(), airmass_v=air_v_var.get(),
                                     k_b=vars_dict["extinction_kb"][0].get(), k_v=vars_dict["extinction_kv"][0].get(),
                                     axes=color_axes)
            color_canvas.draw()
            color_status_var.set(res)
            
        except Exception as e:
            color_status_var.set(f"Error: {e}")
            messagebox.showerror("Analysis Error", str(e))

    tk.Button(lf_color, text="Run Color Transformation Analysis", command=on_run_color,
              bg="#673ab7", fg="white", font=("Arial", 10, "bold"), pady=8).grid(row=7, column=0, columnspan=4, pady=10)

    # --- Differential Photometry Section ---
    lf_diff = ttk.LabelFrame(tab_color_diff, text="2. Compute B/V relative to a reference star")
    lf_diff.pack(fill="x", padx=10, pady=10)
    
    add_file_selector(lf_diff, "B-Filter Results (CSV):", "diff_b_csv", recent_b_csv, 0)
    add_file_selector(lf_diff, "V-Filter Results (CSV):", "diff_v_csv", recent_v_csv, 1)
    
    ttk.Label(lf_diff, text="* Global extinction (k_B, k_V) settings from the Settings tab will be used.", foreground="#555", font=("Arial", 8, "italic")).grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=10, pady=5)
    
    ttk.Label(lf_diff, text="Color Term Tbv:").grid(row=2, column=2, sticky=tk.W, padx=10, pady=5)
    diff_tbv_var = tk.DoubleVar(value=1.0)
    vars_dict["diff_tbv"] = (diff_tbv_var, float)
    ttk.Entry(lf_diff, textvariable=diff_tbv_var, width=10).grid(row=2, column=3, sticky=tk.W, padx=10, pady=5)
    
    ttk.Label(lf_diff, text="B Correction Tb_bv:").grid(row=3, column=2, sticky=tk.W, padx=10, pady=5)
    diff_tbbv_var = tk.DoubleVar(value=0.0)
    vars_dict["diff_tbbv"] = (diff_tbbv_var, float)
    ttk.Entry(lf_diff, textvariable=diff_tbbv_var, width=10).grid(row=3, column=3, sticky=tk.W, padx=10, pady=5)
    
    ttk.Label(lf_diff, text="V Correction Tv_bv:").grid(row=4, column=2, sticky=tk.W, padx=10, pady=5)
    diff_tvbv_var = tk.DoubleVar(value=0.0)
    vars_dict["diff_tvbv"] = (diff_tvbv_var, float)
    ttk.Entry(lf_diff, textvariable=diff_tvbv_var, width=10).grid(row=4, column=3, sticky=tk.W, padx=10, pady=5)
    
    diff_status_var = tk.StringVar(value="Load coefficients and select CSV files to begin.")
    
    lf_ref = ttk.LabelFrame(tab_color_diff, text="Reference Star Selection")
    lf_ref.pack(fill="x", padx=10, pady=10)
    
    ref_mode_var = tk.StringVar(value="auto")
    vars_dict["ref_mode"] = (ref_mode_var, str)
    ttk.Radiobutton(lf_ref, text="Automatic (Brightest star with 0.4 <= B-V <= 0.8)", variable=ref_mode_var, value="auto").grid(row=0, column=0, columnspan=4, sticky=tk.W, padx=10, pady=5)
    ttk.Radiobutton(lf_ref, text="Resolve Star by Name (via Simbad)", variable=ref_mode_var, value="name").grid(row=1, column=0, columnspan=4, sticky=tk.W, padx=10, pady=5)
    
    ttk.Label(lf_ref, text="Star Name:").grid(row=2, column=0, sticky=tk.E, padx=(10, 2), pady=5)
    star_name_var = tk.StringVar(value="AE UMa")
    vars_dict["ref_star_name"] = (star_name_var, str)
    star_name_entry = ttk.Entry(lf_ref, textvariable=star_name_var, width=20)
    star_name_entry.grid(row=2, column=1, sticky=tk.W, padx=2)
    
    name_resolve_status_var = tk.StringVar(value="")
    ttk.Label(lf_ref, textvariable=name_resolve_status_var, font=("Arial", 8, "italic"), foreground="#555").grid(row=2, column=3, columnspan=4, sticky=tk.W, padx=5)

    def check_star_name(*args):
        if ref_mode_var.get() != "name": return
        star_name = star_name_var.get().strip()
        if not star_name:
            name_resolve_status_var.set("Please enter a name.")
            return
        name_resolve_status_var.set("Resolving...")
        root.update_idletasks()
        
        def resolve_thread():
            from astropy.coordinates import SkyCoord
            from astropy.coordinates.name_resolve import NameResolveError
            try:
                c = SkyCoord.from_name(star_name)
                ra_hms = c.ra.to_string(unit='hour', sep='hms', precision=1)
                dec_dms = c.dec.to_string(unit='degree', sep='dms', precision=1)
                root.after(0, lambda: name_resolve_status_var.set(f"Found: {ra_hms}, {dec_dms}"))
            except NameResolveError:
                root.after(0, lambda: name_resolve_status_var.set("Not found in Simbad."))
            except Exception:
                root.after(0, lambda: name_resolve_status_var.set("Error connecting."))
        
        import threading
        threading.Thread(target=resolve_thread, daemon=True).start()

    check_name_btn = ttk.Button(lf_ref, text="Check", command=check_star_name, width=8)
    check_name_btn.grid(row=2, column=2, sticky=tk.W, padx=2)
    star_name_entry.bind('<Return>', check_star_name)

    ttk.Radiobutton(lf_ref, text="Manual Coordinates", variable=ref_mode_var, value="manual").grid(row=3, column=0, columnspan=4, sticky=tk.W, padx=10, pady=5)
    
    # RA boxes
    ttk.Label(lf_ref, text="RA:").grid(row=4, column=0, sticky=tk.E, padx=(10, 2), pady=5)
    ra_h_var = tk.StringVar(value="14")
    vars_dict["ref_ra_h"] = (ra_h_var, str)
    ttk.Entry(lf_ref, textvariable=ra_h_var, width=4).grid(row=4, column=1, sticky=tk.W, padx=2)
    ttk.Label(lf_ref, text="h").grid(row=4, column=2, sticky=tk.W, padx=0)
    ra_m_var = tk.StringVar(value="34")
    vars_dict["ref_ra_m"] = (ra_m_var, str)
    ttk.Entry(lf_ref, textvariable=ra_m_var, width=4).grid(row=4, column=3, sticky=tk.W, padx=2)
    ttk.Label(lf_ref, text="m").grid(row=4, column=4, sticky=tk.W, padx=0)
    ra_s_var = tk.StringVar(value="00.00")
    vars_dict["ref_ra_s"] = (ra_s_var, str)
    ttk.Entry(lf_ref, textvariable=ra_s_var, width=6).grid(row=4, column=5, sticky=tk.W, padx=2)
    ttk.Label(lf_ref, text="s").grid(row=4, column=6, sticky=tk.W, padx=0)
    
    # Dec boxes
    ttk.Label(lf_ref, text="Dec:").grid(row=5, column=0, sticky=tk.E, padx=(10, 2), pady=5)
    dec_d_var = tk.StringVar(value="+43")
    vars_dict["ref_dec_d"] = (dec_d_var, str)
    ttk.Entry(lf_ref, textvariable=dec_d_var, width=4).grid(row=5, column=1, sticky=tk.W, padx=2)
    ttk.Label(lf_ref, text="d").grid(row=5, column=2, sticky=tk.W, padx=0)
    dec_m_var = tk.StringVar(value="30")
    vars_dict["ref_dec_m"] = (dec_m_var, str)
    ttk.Entry(lf_ref, textvariable=dec_m_var, width=4).grid(row=5, column=3, sticky=tk.W, padx=2)
    ttk.Label(lf_ref, text="m").grid(row=5, column=4, sticky=tk.W, padx=0)
    dec_s_var = tk.StringVar(value="00.0")
    vars_dict["ref_dec_s"] = (dec_s_var, str)
    ttk.Entry(lf_ref, textvariable=dec_s_var, width=6).grid(row=5, column=5, sticky=tk.W, padx=2)
    ttk.Label(lf_ref, text="s").grid(row=5, column=6, sticky=tk.W, padx=0)
    
    def toggle_ref_entries(*args):
        mode = ref_mode_var.get()
        name_state = tk.NORMAL if mode == "name" else tk.DISABLED
        manual_state = tk.NORMAL if mode == "manual" else tk.DISABLED
        
        star_name_entry.config(state=name_state)
        check_name_btn.config(state=name_state)
        for child in lf_ref.winfo_children():
            if isinstance(child, ttk.Entry) and child != star_name_entry:
                child.config(state=manual_state)
    
    ref_mode_var.trace("w", toggle_ref_entries)
    toggle_ref_entries()

    lf_target = ttk.LabelFrame(tab_color_diff, text="Target Star Selection")
    lf_target.pack(fill="x", padx=10, pady=10)
    
    target_mode_var = tk.StringVar(value="all")
    vars_dict["target_mode"] = (target_mode_var, str)
    ttk.Radiobutton(lf_target, text="Analyze all stars", variable=target_mode_var, value="all").grid(row=0, column=0, columnspan=4, sticky=tk.W, padx=10, pady=5)
    ttk.Radiobutton(lf_target, text="Resolve Target by Name (via Simbad)", variable=target_mode_var, value="name").grid(row=1, column=0, columnspan=4, sticky=tk.W, padx=10, pady=5)
    
    ttk.Label(lf_target, text="Star Name:").grid(row=2, column=0, sticky=tk.E, padx=(10, 2), pady=5)
    target_name_var = tk.StringVar(value="")
    vars_dict["target_star_name"] = (target_name_var, str)
    target_name_entry = ttk.Entry(lf_target, textvariable=target_name_var, width=20)
    target_name_entry.grid(row=2, column=1, sticky=tk.W, padx=2)
    
    target_resolve_status_var = tk.StringVar(value="")
    ttk.Label(lf_target, textvariable=target_resolve_status_var, font=("Arial", 8, "italic"), foreground="#555").grid(row=2, column=3, columnspan=4, sticky=tk.W, padx=5)

    def check_target_name(*args):
        if target_mode_var.get() != "name": return
        star_name = target_name_var.get().strip()
        if not star_name:
            target_resolve_status_var.set("Please enter a name.")
            return
        target_resolve_status_var.set("Resolving...")
        root.update_idletasks()
        
        def resolve_thread():
            from astropy.coordinates import SkyCoord
            from astropy.coordinates.name_resolve import NameResolveError
            try:
                c = SkyCoord.from_name(star_name)
                ra_hms = c.ra.to_string(unit='hour', sep='hms', precision=1)
                dec_dms = c.dec.to_string(unit='degree', sep='dms', precision=1)
                root.after(0, lambda: target_resolve_status_var.set(f"Found: {ra_hms}, {dec_dms}"))
            except NameResolveError:
                root.after(0, lambda: target_resolve_status_var.set("Not found in Simbad."))
            except Exception:
                root.after(0, lambda: target_resolve_status_var.set("Error connecting."))
        
        import threading
        threading.Thread(target=resolve_thread, daemon=True).start()

    check_target_btn = ttk.Button(lf_target, text="Check", command=check_target_name, width=8)
    check_target_btn.grid(row=2, column=2, sticky=tk.W, padx=2)
    target_name_entry.bind('<Return>', check_target_name)

    ttk.Radiobutton(lf_target, text="Manual Coordinates", variable=target_mode_var, value="manual").grid(row=3, column=0, columnspan=4, sticky=tk.W, padx=10, pady=5)
    
    # RA boxes
    ttk.Label(lf_target, text="RA:").grid(row=4, column=0, sticky=tk.E, padx=(10, 2), pady=5)
    target_ra_h_var = tk.StringVar(value="14")
    ttk.Entry(lf_target, textvariable=target_ra_h_var, width=4).grid(row=4, column=1, sticky=tk.W, padx=2)
    ttk.Label(lf_target, text="h").grid(row=4, column=2, sticky=tk.W, padx=0)
    target_ra_m_var = tk.StringVar(value="34")
    ttk.Entry(lf_target, textvariable=target_ra_m_var, width=4).grid(row=4, column=3, sticky=tk.W, padx=2)
    ttk.Label(lf_target, text="m").grid(row=4, column=4, sticky=tk.W, padx=0)
    target_ra_s_var = tk.StringVar(value="00.00")
    ttk.Entry(lf_target, textvariable=target_ra_s_var, width=6).grid(row=4, column=5, sticky=tk.W, padx=2)
    ttk.Label(lf_target, text="s").grid(row=4, column=6, sticky=tk.W, padx=0)
    
    # Dec boxes
    ttk.Label(lf_target, text="Dec:").grid(row=5, column=0, sticky=tk.E, padx=(10, 2), pady=5)
    target_dec_d_var = tk.StringVar(value="+43")
    ttk.Entry(lf_target, textvariable=target_dec_d_var, width=4).grid(row=5, column=1, sticky=tk.W, padx=2)
    ttk.Label(lf_target, text="d").grid(row=5, column=2, sticky=tk.W, padx=0)
    target_dec_m_var = tk.StringVar(value="30")
    ttk.Entry(lf_target, textvariable=target_dec_m_var, width=4).grid(row=5, column=3, sticky=tk.W, padx=2)
    ttk.Label(lf_target, text="m").grid(row=5, column=4, sticky=tk.W, padx=0)
    target_dec_s_var = tk.StringVar(value="00.0")
    ttk.Entry(lf_target, textvariable=target_dec_s_var, width=6).grid(row=5, column=5, sticky=tk.W, padx=2)
    ttk.Label(lf_target, text="s").grid(row=5, column=6, sticky=tk.W, padx=0)
    
    def toggle_target_entries(*args):
        mode = target_mode_var.get()
        name_state = tk.NORMAL if mode == "name" else tk.DISABLED
        manual_state = tk.NORMAL if mode == "manual" else tk.DISABLED
        
        target_name_entry.config(state=name_state)
        check_target_btn.config(state=name_state)
        for child in lf_target.winfo_children():
            if isinstance(child, ttk.Entry) and child != target_name_entry:
                child.config(state=manual_state)
    
    target_mode_var.trace("w", toggle_target_entries)
    toggle_target_entries()

    def load_color_coefficients():
        import json
        json_path = os.path.join("photometry_output", "color_coefficients.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r') as f:
                    coeffs = json.load(f)
                diff_tbv_var.set(coeffs.get('Tbv', 1.0))
                diff_tbbv_var.set(coeffs.get('Tb_bv', 0.0))
                diff_tvbv_var.set(coeffs.get('Tv_bv', 0.0))
                diff_status_var.set("Loaded coefficients from previous run.")
            except Exception as e:
                diff_status_var.set(f"Error loading JSON: {e}")
        else:
            diff_status_var.set("No previous coefficients found. Enter manually.")
            
    tk.Button(lf_diff, text="Load Last Coefficients", command=load_color_coefficients).grid(row=5, column=0, columnspan=2, pady=5)
            
    diff_status_label = tk.Label(tab_color_diff, textvariable=diff_status_var, fg="#333", font=("Arial", 9, "italic"))
    diff_status_label.pack(pady=5)

    # Plot for Color/Diff
    lf_color_plot = ttk.LabelFrame(tab_color_diff, text="Analysis Preview (Color Terms / Accuracy)")
    lf_color_plot.pack(fill="both", expand=True, padx=10, pady=5)
    
    color_fig, color_axes = plt.subplots(1, 3, figsize=(12, 4))
    color_canvas = FigureCanvasTkAgg(color_fig, master=lf_color_plot)
    color_canvas.get_tk_widget().pack(fill="both", expand=True)
    color_toolbar = NavigationToolbar2Tk(color_canvas, lf_color_plot)
    color_toolbar.update()

    # --- TAB 4: Light Curves ---
    tab_ts_outer = ttk.Frame(notebook)
    notebook.add(tab_ts_outer, text="Light Curves")
    
    ts_scroll = ScrollableFrame(tab_ts_outer)
    ts_scroll.pack(fill="both", expand=True)
    ts_container = ts_scroll.scrollable_frame
    
    lf_ts_io = ttk.LabelFrame(ts_container, text="FITS Sequence Selection")
    lf_ts_io.pack(fill="x", padx=10, pady=10)
    
    ttk.Label(lf_ts_io, text="FITS File Pattern:").grid(row=0, column=0, sticky=tk.W, padx=10, pady=5)
    ts_pattern_var = tk.StringVar(value="C:\\Astro\\Photometry_Calibra\\fitsfiles\\*.fits")
    vars_dict["ts_pattern"] = (ts_pattern_var, str)
    ttk.Entry(lf_ts_io, textvariable=ts_pattern_var, width=50).grid(row=0, column=1, columnspan=3, sticky=tk.W, padx=10, pady=5)
    
    ttk.Label(lf_ts_io, text="Filter:").grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)
    ts_filter_var = tk.StringVar(value="V")
    vars_dict["ts_filter"] = (ts_filter_var, str)
    ttk.Combobox(lf_ts_io, textvariable=ts_filter_var, values=["V", "B"], state="readonly", width=5).grid(row=1, column=1, sticky=tk.W, padx=10, pady=5)
    def get_coords_ts(mode, name, ra_s, dec_s):
        from astropy.coordinates import SkyCoord
        import astropy.units as u
        if mode == "name":
            return SkyCoord.from_name(name)
        else:
            return SkyCoord(f"{ra_s} {dec_s}", unit=(u.hourangle, u.deg))

    # --- Ensemble Reference Stars ---
    lf_ts_ensemble = ttk.LabelFrame(ts_container, text="Ensemble Reference Stars (Comparison)")
    lf_ts_ensemble.pack(fill="x", padx=10, pady=5)
    
    ts_check_star_idx_var = tk.IntVar(value=-1)
    vars_dict["ts_check_star_idx"] = (ts_check_star_idx_var, int)
    
    def create_ensemble_row(idx, container):
        row_f = ttk.Frame(container)
        row_f.pack(fill="x", pady=2)
        
        ttk.Label(row_f, text=f"Star {idx+1}:", width=6).pack(side=tk.LEFT, padx=5)
        
        name_v = tk.StringVar(value="")
        vars_dict[f"ts_ref_{idx}_name"] = (name_v, str)
        ttk.Entry(row_f, textvariable=name_v, width=15).pack(side=tk.LEFT, padx=2)
        
        ttk.Label(row_f, text="Mag:").pack(side=tk.LEFT, padx=2)
        mag_v = tk.DoubleVar(value=10.0)
        vars_dict[f"ts_ref_{idx}_mag"] = (mag_v, float)
        ttk.Entry(row_f, textvariable=mag_v, width=6).pack(side=tk.LEFT, padx=2)
        
        ttk.Label(row_f, text="B-V:").pack(side=tk.LEFT, padx=2)
        bv_v = tk.DoubleVar(value=0.5)
        vars_dict[f"ts_ref_{idx}_bv"] = (bv_v, float)
        ttk.Entry(row_f, textvariable=bv_v, width=6).pack(side=tk.LEFT, padx=2)
        
        use_v = tk.BooleanVar(value=(idx == 0))
        vars_dict[f"ts_ref_{idx}_use"] = (use_v, bool)
        ttk.Checkbutton(row_f, text="Use", variable=use_v).pack(side=tk.LEFT, padx=2)
        
        ttk.Radiobutton(row_f, text="Check", variable=ts_check_star_idx_var, value=idx).pack(side=tk.LEFT, padx=2)
        
        def on_fetch():
            name = name_v.get().strip()
            if not name: return
            ts_status_var.set(f"Fetching {name}...")
            root.update_idletasks()
            try:
                from astropy.coordinates import SkyCoord
                import astropy.units as u
                from photometry.calibration import fetch_online_catalog
                
                c = SkyCoord.from_name(name)
                cat_name = vars_dict["reference_catalog"][0].get()
                stars = fetch_online_catalog(c.ra.deg, c.dec.deg, radius_arcmin=2.0, catalog_name=cat_name)
                if not stars:
                    ts_status_var.set(f"No match for {name}")
                    return
                
                cat_coords = SkyCoord([s['ra_deg'] for s in stars], [s['dec_deg'] for s in stars], unit=u.deg)
                match_idx, d2d, _ = c.match_to_catalog_sky(cat_coords)
                
                if d2d.arcsec > 10.0:
                    ts_status_var.set(f"No match for {name} (>10\")")
                    return
                    
                star = stars[match_idx]
                filt = ts_filter_var.get().upper()
                mag = star['B_mag'] if filt == 'B' else star['V_mag']
                bv = star['B_mag'] - star['V_mag']
                
                mag_v.set(round(mag, 3))
                bv_v.set(round(bv, 3))
                ts_status_var.set(f"Updated {name} from {cat_name}")
            except Exception as e:
                ts_status_var.set(f"Fetch failed: {e}")

        ttk.Button(row_f, text="Fetch", command=on_fetch, width=6).pack(side=tk.LEFT, padx=2)

    for i in range(5):
        create_ensemble_row(i, lf_ts_ensemble)
    
    ttk.Radiobutton(lf_ts_ensemble, text="No Check Star", variable=ts_check_star_idx_var, value=-1).pack(anchor=tk.W, padx=10)

    # Light Curve Preview
    lf_ts_plot = ttk.LabelFrame(ts_container, text="Light Curve Preview")
    lf_ts_plot.pack(fill="both", expand=True, padx=10, pady=5)
    
    ts_fig, ts_ax = plt.subplots(figsize=(8, 4))
    ts_canvas = FigureCanvasTkAgg(ts_fig, master=lf_ts_plot)
    ts_canvas.get_tk_widget().pack(fill="both", expand=True)
    ts_toolbar = NavigationToolbar2Tk(ts_canvas, lf_ts_plot)
    ts_toolbar.update()

    # Target Star
    lf_ts_target = ttk.LabelFrame(ts_container, text="Target Star (Variable)")
    lf_ts_target.pack(fill="x", padx=10, pady=5)
    
    ts_target_mode_var = tk.StringVar(value="name")
    vars_dict["ts_target_mode"] = (ts_target_mode_var, str)
    ttk.Radiobutton(lf_ts_target, text="Resolve Name", variable=ts_target_mode_var, value="name").grid(row=0, column=0, sticky=tk.W, padx=10, pady=5)
    ts_target_name_var = tk.StringVar(value="AE UMa")
    vars_dict["ts_target_name"] = (ts_target_name_var, str)

    def on_check_target_ts():
        name = ts_target_name_var.get().strip()
        if not name: return
        ts_status_var.set("Resolving target...")
        root.update_idletasks()
        try:
            c = SkyCoord.from_name(name)
            ra_hms = c.ra.to_string(unit='hour', sep=':', precision=1)
            dec_dms = c.dec.to_string(unit='degree', sep=':', precision=1, alwayssign=True)
            ts_status_var.set(f"Target resolved: {ra_hms}, {dec_dms}")
        except:
            ts_status_var.set("Target resolution failed.")

    ttk.Button(lf_ts_target, text="Check", command=on_check_target_ts, width=6).grid(row=0, column=2, sticky=tk.W, padx=2)
    
    ttk.Radiobutton(lf_ts_target, text="Manual RA/Dec", variable=ts_target_mode_var, value="manual").grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)
    ts_target_ra_var = tk.StringVar(value="14:34:00")
    vars_dict["ts_target_ra"] = (ts_target_ra_var, str)
    ts_target_dec_var = tk.StringVar(value="+43:30:00")
    vars_dict["ts_target_dec"] = (ts_target_dec_var, str)
    ttk.Entry(lf_ts_target, textvariable=ts_target_ra_var, width=12).grid(row=1, column=1, sticky=tk.W, padx=2)
    ttk.Entry(lf_ts_target, textvariable=ts_target_dec_var, width=12).grid(row=1, column=2, sticky=tk.W, padx=2)
    
    ttk.Label(lf_ts_target, text="Target (B-V) [assumed]:").grid(row=2, column=0, sticky=tk.W, padx=10, pady=2)
    ts_target_bv_var = tk.DoubleVar(value=0.5)
    vars_dict["ts_target_bv"] = (ts_target_bv_var, float)
    ttk.Entry(lf_ts_target, textvariable=ts_target_bv_var, width=8).grid(row=2, column=1, sticky=tk.W, padx=2)

    # Coefficients
    lf_ts_coeff = ttk.LabelFrame(ts_container, text="Coefficients & Metadata")
    lf_ts_coeff.pack(fill="x", padx=10, pady=5)
    
    ttk.Label(lf_ts_coeff, text="Color Term (e.g. Tv_bv):").grid(row=0, column=0, sticky=tk.W, padx=10, pady=2)
    ts_coeff_var = tk.DoubleVar(value=0.0)
    vars_dict["ts_coeff"] = (ts_coeff_var, float)
    ttk.Entry(lf_ts_coeff, textvariable=ts_coeff_var, width=10).grid(row=0, column=1, sticky=tk.W, padx=2)
    
    ttk.Label(lf_ts_coeff, text="Extinction (k):").grid(row=0, column=2, sticky=tk.W, padx=10, pady=2)
    ts_k_var = tk.DoubleVar(value=0.15)
    vars_dict["ts_k"] = (ts_k_var, float)
    ttk.Entry(lf_ts_coeff, textvariable=ts_k_var, width=10).grid(row=0, column=3, sticky=tk.W, padx=2)
    
    ttk.Label(lf_ts_coeff, text="AAVSO Observer Code:").grid(row=1, column=0, sticky=tk.W, padx=10, pady=2)
    ts_obs_var = tk.StringVar(value="XXXX")
    vars_dict["ts_obs_code"] = (ts_obs_var, str)
    ttk.Entry(lf_ts_coeff, textvariable=ts_obs_var, width=10).grid(row=1, column=1, sticky=tk.W, padx=2)
    
    ttk.Label(lf_ts_coeff, text="Site Lat:").grid(row=1, column=2, sticky=tk.W, padx=10, pady=2)
    ts_lat_var = tk.DoubleVar(value=59.8)
    vars_dict["ts_lat"] = (ts_lat_var, float)
    ttk.Entry(lf_ts_coeff, textvariable=ts_lat_var, width=10).grid(row=1, column=3, sticky=tk.W, padx=2)
    
    ttk.Label(lf_ts_coeff, text="Site Long:").grid(row=2, column=0, sticky=tk.W, padx=10, pady=2)
    ts_lon_var = tk.DoubleVar(value=17.6)
    vars_dict["ts_lon"] = (ts_lon_var, float)
    ttk.Entry(lf_ts_coeff, textvariable=ts_lon_var, width=10).grid(row=2, column=1, sticky=tk.W, padx=2)

    def load_ts_coefficients():
        import json
        json_path = os.path.join("photometry_output", "color_coefficients.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r') as f:
                    coeffs = json.load(f)
                filt = ts_filter_var.get().upper()
                if filt == 'B':
                    val = coeffs.get('Tb_bv', 0.0)
                    key_name = 'Tb_bv'
                else:
                    val = coeffs.get('Tv_bv', 0.0)
                    key_name = 'Tv_bv'
                ts_coeff_var.set(val)
                ts_status_var.set(f"Loaded {key_name} for {filt} filter.")
            except Exception as e:
                ts_status_var.set(f"Error loading JSON: {e}")
        else:
            ts_status_var.set("No coefficients file found.")
            
    tk.Button(lf_ts_coeff, text="Load Last Coeffs", command=load_ts_coefficients).grid(row=2, column=2, columnspan=2, pady=5)

    ts_status_var = tk.StringVar(value="Ready to process sequence.")
    ttk.Label(ts_container, textvariable=ts_status_var, font=("Arial", 9, "italic")).pack(pady=5)
    
    # Progress Bar & Cancel (Phase 3)
    ts_progress_var = tk.DoubleVar(value=0)
    ts_progress = ttk.Progressbar(ts_container, variable=ts_progress_var, maximum=100, length=400)
    ts_progress.pack(pady=5)
    
    cancel_event = threading.Event()
    
    def on_cancel_ts():
        if messagebox.askyesno("Cancel", "Stop processing the sequence?"):
            cancel_event.set()
            ts_status_var.set("Cancelling...")

    cancel_btn = tk.Button(ts_container, text="Cancel Processing", command=on_cancel_ts, 
                           bg="#f44336", fg="white", font=("Arial", 9))
    # Packed later during execution or hidden by default
    
    def on_run_ts():
        import glob
        pattern = ts_pattern_var.get()
        files = glob.glob(pattern)
        if not files:
            messagebox.showerror("Error", f"No files found matching: {pattern}")
            return
            
        # Collect Ensemble & Check Star
        ensemble_data = []
        check_star_data = None
        cs_idx = ts_check_star_idx_var.get()
        
        for i in range(5):
            name = vars_dict[f"ts_ref_{i}_name"][0].get().strip()
            mag = vars_dict[f"ts_ref_{i}_mag"][0].get()
            bv = vars_dict[f"ts_ref_{i}_bv"][0].get()
            if name:
                s_dict = {'name': name, 'mag_std': mag, 'bv_std': bv}
                if i == cs_idx:
                    check_star_data = s_dict
                if vars_dict[f"ts_ref_{i}_use"][0].get():
                    ensemble_data.append(s_dict)
        
        if not ensemble_data:
            messagebox.showerror("Error", "Please select at least one reference star in the ensemble.")
            return

        ts_status_var.set("Resolving target coordinates...")
        root.update_idletasks()
        
        from astropy.coordinates import SkyCoord
        import astropy.units as u
        try:
            tar_c = get_coords_ts(ts_target_mode_var.get(), ts_target_name_var.get(), ts_target_ra_var.get(), ts_target_dec_var.get())
        except Exception as e:
            messagebox.showerror("Coord Error", f"Target coordinate resolution failed: {e}")
            return

        def ts_thread():
            from photometry.time_series import run_time_series_photometry, save_aavso_report, plot_light_curve
            
            # Resolve Ensemble Coords
            ts_status_var.set("Resolving ensemble coordinates...")
            resolved_ensemble = []
            # Combine ensemble and check star for resolution
            to_resolve = list(ensemble_data)
            if check_star_data and check_star_data not in to_resolve:
                to_resolve.append(check_star_data)
                
            for s in to_resolve:
                try:
                    c = SkyCoord.from_name(s['name'])
                    s['ra'] = c.ra.deg
                    s['dec'] = c.dec.deg
                    if s in ensemble_data:
                        resolved_ensemble.append(s)
                except Exception as e:
                    root.after(0, lambda: messagebox.showerror("Ensemble Error", f"Could not resolve star '{s['name']}': {e}"))
                    ts_status_var.set("Failed: Coordinate resolution error.")
                    return

            ts_status_var.set(f"Processing {len(files)} files...")
            
            # Reset Phase 3 state
            root.after(0, lambda: cancel_btn.pack(pady=5))
            root.after(0, lambda: ts_progress_var.set(0))
            cancel_event.clear()
            
            def update_prog(val):
                root.after(0, lambda: ts_progress_var.set(val))

            results, msg = run_time_series_photometry(
                files, tar_c.ra.deg, tar_c.dec.deg, 
                resolved_ensemble,
                ts_target_bv_var.get(),
                ts_coeff_var.get(), 0.0, # epsilon not used yet
                vars_dict["aperture_radius"][0].get(),
                vars_dict["annulus_inner"][0].get(),
                vars_dict["annulus_outer"][0].get(),
                gain=vars_dict["ccd_gain"][0].get(),
                k_coeff=ts_k_var.get(),
                filter_name=ts_filter_var.get(),
                site_lat=ts_lat_var.get(),
                site_long=ts_lon_var.get(),
                cancel_event=cancel_event,
                update_progress=update_prog
            )
            
            root.after(0, lambda: cancel_btn.pack_forget())
            
            if results:
                out_csv = os.path.join("photometry_output", f"light_curve_{ts_target_name_var.get().replace(' ','_')}.csv")
                out_aavso = os.path.join("photometry_output", f"aavso_{ts_target_name_var.get().replace(' ','_')}.txt")
                out_plot = os.path.join("photometry_output", f"plot_{ts_target_name_var.get().replace(' ','_')}.png")
                
                # Save CSV
                with open(out_csv, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=results[0].keys())
                    writer.writeheader()
                    writer.writerows(results)
                
                # AAVSO Metadata
                comp_name = "ENSEMBLE" if len(resolved_ensemble) > 1 else resolved_ensemble[0]['name']
                comp_mag = "na" if len(resolved_ensemble) > 1 else resolved_ensemble[0]['mag_std']
                check_name = check_star_data['name'] if check_star_data else "na"
                check_mag = check_star_data['mag_std'] if check_star_data else "na"
                is_trans = "YES" if abs(ts_coeff_var.get()) > 1e-5 else "NO"
                
                save_aavso_report(results, out_aavso, ts_target_name_var.get(), ts_filter_var.get(), ts_obs_var.get(),
                                  comp_name=comp_name, comp_mag=comp_mag, 
                                  check_name=check_name, check_mag=check_mag,
                                  trans=is_trans)
                
                # Update embedded plot
                plot_light_curve(results, ts_target_name_var.get(), out_plot, ax=ts_ax)
                root.after(0, ts_canvas.draw)
                
                ts_status_var.set(f"Complete! Results saved to {out_csv}")
                messagebox.showinfo("Success", f"Light curve generated!\nSaved to: {out_csv}\nPlot: {out_plot}")
            else:
                ts_status_var.set(f"Failed: {msg}")

        threading.Thread(target=ts_thread, daemon=True).start()

    run_ts_btn = tk.Button(ts_container, text="Generate Light Curve", command=on_run_ts,
                           bg="#00796b", fg="white", font=("Arial", 11, "bold"), pady=10)
    run_ts_btn.pack(pady=20)

    # --- END TAB 6 ---

    def on_run_diff():
        try:
            b_csv = vars_dict["diff_b_csv"][0].get()
            v_csv = vars_dict["diff_v_csv"][0].get()
            cat_type = vars_dict["reference_catalog"][0].get()
            
            if not os.path.exists(b_csv) or not os.path.exists(v_csv):
                messagebox.showerror("File Error", "Please select valid CSV result files for both filters.")
                return
                
            from photometry.diff_photometry import run_differential_photometry
            diff_status_var.set("Running differential photometry...")
            root.update_idletasks()
            
            manual_coord = None
            if ref_mode_var.get() == "manual":
                ra_str = f"{ra_h_var.get()}h{ra_m_var.get()}m{ra_s_var.get()}s"
                dec_str = f"{dec_d_var.get()}d{dec_m_var.get()}m{dec_s_var.get()}s"
                from astropy.coordinates import SkyCoord
                import astropy.units as u
                try:
                    c = SkyCoord(f"{ra_str} {dec_str}")
                    manual_coord = (c.ra.deg, c.dec.deg)
                except Exception as e:
                    messagebox.showerror("Coordinate Error", f"Invalid manual coordinates format.\n{e}")
                    diff_status_var.set("Error: Invalid manual coordinates.")
                    return
            elif ref_mode_var.get() == "name":
                star_name = star_name_var.get().strip()
                if not star_name:
                    messagebox.showerror("Name Error", "Please enter a star name.")
                    diff_status_var.set("Error: Empty star name.")
                    return
                from astropy.coordinates import SkyCoord
                from astropy.coordinates.name_resolve import NameResolveError
                diff_status_var.set(f"Resolving '{star_name}' via Simbad...")
                root.update_idletasks()
                try:
                    c = SkyCoord.from_name(star_name)
                    manual_coord = (c.ra.deg, c.dec.deg)
                    print(f"Resolved '{star_name}' to RA: {c.ra.deg:.5f}, Dec: {c.dec.deg:.5f}")
                except NameResolveError as e:
                    messagebox.showerror("Resolution Error", f"Could not resolve name '{star_name}' via Simbad.\n\nNote: AAVSO AUIDs (like 000-BJS-555) are often not recognized. Try a common catalog name (e.g., TYC, HD, or variable star name) or use Manual Coordinates.")
                    diff_status_var.set(f"Error: Could not resolve '{star_name}'.")
                    return
                except Exception as e:
                    messagebox.showerror("Resolution Error", f"Error looking up '{star_name}':\n{e}")
                    diff_status_var.set("Error during name resolution.")
                    return
            
            manual_target_coord = None
            target_mode = target_mode_var.get()
            if target_mode == "manual":
                ra_str = f"{target_ra_h_var.get()}h{target_ra_m_var.get()}m{target_ra_s_var.get()}s"
                dec_str = f"{target_dec_d_var.get()}d{target_dec_m_var.get()}m{target_dec_s_var.get()}s"
                try:
                    c = SkyCoord(f"{ra_str} {dec_str}")
                    manual_target_coord = (c.ra.deg, c.dec.deg)
                except Exception as e:
                    messagebox.showerror("Coordinate Error", f"Invalid manual target coordinates format.\n{e}")
                    diff_status_var.set("Error: Invalid target coordinates.")
                    return
            elif target_mode == "name":
                star_name = target_name_var.get().strip()
                if not star_name:
                    messagebox.showerror("Name Error", "Please enter a target star name.")
                    diff_status_var.set("Error: Empty target star name.")
                    return
                from astropy.coordinates import SkyCoord
                from astropy.coordinates.name_resolve import NameResolveError
                diff_status_var.set(f"Resolving '{star_name}' via Simbad...")
                root.update_idletasks()
                try:
                    c = SkyCoord.from_name(star_name)
                    manual_target_coord = (c.ra.deg, c.dec.deg)
                    print(f"Resolved target '{star_name}' to RA: {c.ra.deg:.5f}, Dec: {c.dec.deg:.5f}")
                except NameResolveError as e:
                    messagebox.showerror("Resolution Error", f"Could not resolve target name '{star_name}' via Simbad.\n\nNote: AAVSO AUIDs (like 000-BJS-555) are often not recognized. Try a common catalog name (e.g., TYC, HD, or variable star name) or use Manual Coordinates.")
                    diff_status_var.set(f"Error: Could not resolve target '{star_name}'.")
                    return
                except Exception as e:
                    messagebox.showerror("Resolution Error", f"Error looking up target '{star_name}':\n{e}")
                    diff_status_var.set("Error during target name resolution.")
                    return

            res = run_differential_photometry(
                csv_b=b_csv, csv_v=v_csv, ref_catalog=cat_type,
                k_b=vars_dict["extinction_kb"][0].get(), k_v=vars_dict["extinction_kv"][0].get(),
                Tbv=diff_tbv_var.get(), Tb_bv=diff_tbbv_var.get(), Tv_bv=diff_tvbv_var.get(),
                radius_arcmin=float(vars_dict["catalog_search_radius"][0].get()),
                manual_ref_coord=manual_coord,
                target_mode=target_mode,
                manual_target_coord=manual_target_coord,
                axes=color_axes
            )
            color_canvas.draw()
            diff_status_var.set(res)
        except Exception as e:
            diff_status_var.set(f"Error: {e}")
            messagebox.showerror("Analysis Error", str(e))
            
    tk.Button(tab_color_diff, text="Execute Differential Photometry", command=on_run_diff,
              bg="#1a3a5f", fg="white", font=("Arial", 10, "bold"), pady=8).pack(pady=10)

    # Camera Settings (from old TAB 2)
    lf_ccd = ttk.LabelFrame(tab_settings, text="CCD Settings (Error Analysis)")
    lf_ccd.pack(fill="x", padx=10, pady=10)
    add_entry(lf_ccd, "Gain (e-/ADU):", "ccd_gain", 1.27, 0)
    add_entry(lf_ccd, "Read Noise (e-):", "ccd_read_noise", 3.3, 1)
    add_entry(lf_ccd, "Dark Current (e-/s/px):", "ccd_dark_current", 0.0007, 2)
    add_entry(lf_ccd, "Saturation Limit (ADU):", "saturation_limit", 63000, 3, vtype=int)

    # Detection (from old TAB 2)
    lf_det = ttk.LabelFrame(tab_settings, text="Detection (DAOStarFinder)")
    lf_det.pack(fill="x", padx=10, pady=10)
    add_entry(lf_det, "Detection Sigma:", "detect_sigma", 5.0, 0)
    add_entry(lf_det, "Sharpness Low:", "dao_sharplo", 0.2, 1, col_offset=0)
    add_entry(lf_det, "Sharpness High:", "dao_sharphi", 1.0, 1, col_offset=1)
    add_entry(lf_det, "Roundness Low:", "dao_roundlo", -1.2, 2, col_offset=0)
    add_entry(lf_det, "Roundness High:", "dao_roundhi", 1.2, 2, col_offset=1)


    # Aperture Photometry (from old TAB 3)
    lf_ap = ttk.LabelFrame(tab_settings, text="Aperture Photometry")
    lf_ap.pack(fill="x", padx=10, pady=10)
    add_entry(lf_ap, "PSF Box Size (px):", "box_size", 15, 0, vtype=int)
    add_entry(lf_ap, "Aperture Radius (px):", "aperture_radius", 5.0, 1)
    add_entry(lf_ap, "Annulus Inner (px):", "annulus_inner", 7.0, 2)
    add_entry(lf_ap, "Annulus Outer (px):", "annulus_outer", 13.0, 3)

    # Zero Point Calibration (from old TAB 3)
    lf_cal = ttk.LabelFrame(tab_settings, text="Zero Point Calibration")
    lf_cal.pack(fill="x", padx=10, pady=10)
    add_entry(lf_cal, "Match Tolerance (arcsec):", "match_tolerance_arcsec", 8.0, 0)
    add_entry(lf_cal, "Default Zero Point:", "default_zero_point", 24.0, 1)
    add_entry(lf_cal, "Min SNR for Calib:", "calib_snr_threshold", 10.0, 2)
    add_entry(lf_cal, "Catalog Search Radius (arcmin):", "catalog_search_radius", 15.0, 3)
    add_check(lf_cal, "Run New ZP Calibration (Overwrite Default)", "run_new_calibration", True, 4)
    add_check(lf_cal, "Run Positional Shift Analysis", "run_shift_analysis", False, 5)

    # Global Extinction (Shared)
    lf_ext = ttk.LabelFrame(tab_settings, text="Atmospheric Extinction (Global)")
    lf_ext.pack(fill="x", padx=10, pady=10)
    add_entry(lf_ext, "k_V (Visual):", "extinction_kv", 0.20, 0)
    add_entry(lf_ext, "k_B (Blue):", "extinction_kb", 0.35, 1)


    # Output Toggles (from old TAB 4)
    lf_out = ttk.LabelFrame(tab_settings, text="Console & Plot Toggles")
    lf_out.pack(fill="x", padx=10, pady=10)
    add_check(lf_out, "Print Detailed Calibration to Console", "print_detailed_calibration", False, 0)
    add_check(lf_out, "Print Massive Aperture Photometry Table", "print_star_detection_table", False, 1)
    add_check(lf_out, "Print Individual PSF Fitting Results", "print_psf_fitting", False, 2)
    add_check(lf_out, "Display Matplotlib Plots (Blocking)", "display_plots", False, 3)
    add_entry(lf_out, "Max Plots to Show/Save per file:", "max_plots_to_show_per_file", 3, 4, vtype=int)

    # Session Management
    lf_session = ttk.LabelFrame(tab_settings, text="Session Management")
    lf_session.pack(fill="x", padx=10, pady=10)
    
    ttk.Button(lf_session, text="Save Session", command=save_session).grid(row=0, column=0, padx=10, pady=5)
    ttk.Button(lf_session, text="Load Session", command=load_session).grid(row=0, column=1, padx=10, pady=5)
    ttk.Label(lf_session, text="* Session auto-loads on startup. Settings are saved to calibra_session.json", 
              foreground="#555", font=("Arial", 8, "italic")).grid(row=0, column=2, padx=10)

    # Auto-load on startup
    load_session()

    # --- TAB 5: Help ---
    tab_help = ttk.Frame(notebook)
    notebook.add(tab_help, text="Help")
    
    help_frame = tk.Frame(tab_help, padx=20, pady=20)
    help_frame.pack(fill="both", expand=True)
    
    tk.Label(help_frame, text="Documentation & Support", font=("Arial", 12, "bold"), bg="white").pack(pady=(0,10), ipady=2)
    tk.Label(help_frame, text="For detailed instructions on how to use Calibra, please refer to the documentation files in the program directory:", justify=tk.LEFT, wraplength=550).pack(pady=5)
    
    import webbrowser
    def open_readme():
        webbrowser.open("README.md")
    def open_manual():
        webbrowser.open("photometry_user_manual.md")
        
    tk.Button(help_frame, text="Open README.md", command=open_readme, width=30).pack(pady=5)
    tk.Button(help_frame, text="Open User Manual (PDF/MD)", command=open_manual, width=30).pack(pady=5)
    
    help_info = (
        "\nQuick Tips:\n"
        "- Ensure your FITS headers have valid WCS (RA/Dec) for online calibration.\n"
        "- Set the Aperture Radius to approximately 2x the FWHM of your stars.\n"
        "- Use the 'Region Filtering' tab to focus on specific targets or avoid edges."
    )
    tk.Label(help_frame, text=help_info, justify=tk.LEFT, wraplength=550, font=("Arial", 9, "italic")).pack(pady=10)

    # Developer Info
    dev_info = (
        "\nDevelopers & Contact:\n"
        "Developed by Stephan Pomp & Google DeepMind Antigravity\n"
        "Contact: stephan.pomp@gmail.com"
    )
    tk.Label(help_frame, text=dev_info, justify=tk.LEFT, font=("Arial", 9), fg="#555").pack(side=tk.BOTTOM, anchor="w")

    # --- OUTPUT CONSOLE (Separate Window) ---
    console_win = tk.Toplevel(root)
    console_win.title("Calibra: Process Console")
    console_win.geometry("800x500")
    console_win.configure(bg="#f0f2f5")
    
    console_frame = tk.LabelFrame(console_win, text="Log Output", bg="#f0f2f5", font=("Arial", 10, "bold"))
    console_frame.pack(fill="both", expand=True, padx=10, pady=10)
    
    console = scrolledtext.ScrolledText(console_frame, font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4")
    console.pack(fill="both", expand=True, padx=5, pady=5)
    
    # Redirect stdout and stderr
    sys.stdout = StdoutRedirector(console)
    sys.stderr = StdoutRedirector(console)

    def on_run():
        vars_vals = {}
        try:
            for k, (var, vtype) in vars_dict.items():
                vars_vals[k] = vtype(var.get())
            
            # Reconstruct dictionary bounds
            config_run = {
                'input_pattern': vars_vals.pop('input_pattern'),
                'reference_catalog': vars_vals.pop('reference_catalog'),
                'detect_sigma': vars_vals.pop('detect_sigma'),
                'saturation_limit': vars_vals.pop('saturation_limit'),
                'box_size': vars_vals.pop('box_size'),
                'aperture_radius': vars_vals.pop('aperture_radius'),
                'annulus_inner': vars_vals.pop('annulus_inner'),
                'annulus_outer': vars_vals.pop('annulus_outer'),
                'match_tolerance_arcsec': vars_vals.pop('match_tolerance_arcsec'),
                'default_zero_point': vars_vals.pop('default_zero_point'),
                'calib_snr_threshold': vars_vals.pop('calib_snr_threshold'),
                'catalog_search_radius': vars_vals.pop('catalog_search_radius'),
                'run_new_calibration': vars_vals.pop('run_new_calibration'),
                'run_shift_analysis': vars_vals.pop('run_shift_analysis'),
                'ccd_gain': vars_vals.pop('ccd_gain'),
                'ccd_read_noise': vars_vals.pop('ccd_read_noise'),
                'ccd_dark_current': vars_vals.pop('ccd_dark_current'),
                'print_detailed_calibration': vars_vals.pop('print_detailed_calibration'),
                'print_star_detection_table': vars_vals.pop('print_star_detection_table'),
                'print_psf_fitting': vars_vals.pop('print_psf_fitting'),
                'display_plots': vars_vals.pop('display_plots'),
                'max_plots_to_show_per_file': vars_vals.pop('max_plots_to_show_per_file'),
                'dao_sharplo': vars_vals.pop('dao_sharplo'),
                'dao_sharphi': vars_vals.pop('dao_sharphi'),
                'dao_roundlo': vars_vals.pop('dao_roundlo'),
                'dao_roundhi': vars_vals.pop('dao_roundhi'),
                'filter_mode': vars_vals.pop('filter_mode'),
            }
            
            config_run['xy_bounds'] = {
                'x_min': vars_vals.pop('xy_x_min'),
                'x_max': vars_vals.pop('xy_x_max'),
                'y_min': vars_vals.pop('xy_y_min'),
                'y_max': vars_vals.pop('xy_y_max')
            }
            config_run['radec_bounds'] = {
                'ra_min': vars_vals.pop('ra_min'),
                'ra_max': vars_vals.pop('ra_max'),
                'dec_min': vars_vals.pop('dec_min'),
                'dec_max': vars_vals.pop('dec_max')
            }
            config_run['calibration_settings'] = {
                'enable': vars_vals.pop('enable_calibration'),
                'bias_path': vars_vals.pop('bias_path'),
                'flat_v_path': vars_vals.pop('flat_v_path'),
                'flat_b_path': vars_vals.pop('flat_b_path')
            }
            
            if pipeline_callback:
                # Run in a separate thread to keep UI alive
                run_btn.config(state=tk.DISABLED, text="Processing...")
                
                def thread_target():
                    try:
                        results = pipeline_callback(config_run)
                        # Auto-populate Color Calibration tab if B/V pairs found
                        if results:
                            for csv_path, filt in results:
                                f_upper = filt.upper()
                                if 'B' in f_upper:
                                    vars_dict['color_b_csv'][0].set(csv_path)
                                elif 'V' in f_upper:
                                    vars_dict['color_v_csv'][0].set(csv_path)
                    finally:
                        run_btn.config(state=tk.NORMAL, text="Run Pipeline")
                
                thread = threading.Thread(target=thread_target)
                thread.daemon = True
                thread.start()
            else:
                print("No pipeline callback provided.")
                
        except ValueError as e:
            messagebox.showerror("Input Error", "Please ensure all numerical fields contain valid numbers.")

    # Detect & Measure Run Button
    run_btn = tk.Button(tab_detect, text="Run Measurement Pipeline", command=on_run, 
                        bg=accent_green, fg="white", font=("Arial", 11, "bold"), 
                        width=30, relief="flat", pady=10)
    run_btn.pack(pady=20)

    # Action Buttons (Bottom Bar - only Exit now)
    btn_frame = tk.Frame(root, bg="#f0f2f5")
    btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
    
    # Repack notebook to ensure btn_frame is not pushed off
    notebook.pack_forget()
    notebook.pack(side=tk.TOP, pady=10, expand=True, fill='both')
    
    exit_btn = tk.Button(btn_frame, text="Exit Calibra", command=root.destroy, width=15, 
                           font=("Arial", 10), relief="flat", bg="#f44336", fg="white")
    exit_btn.pack(side=tk.LEFT, padx=10)

    # Ensure closing main window closes everything
    def on_closing():
        root.destroy()
        sys.exit(0)
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    console_win.protocol("WM_DELETE_WINDOW", lambda: None) # Prevent closing console individually if desired, or just let it close

    # Run the UI loop
    root.mainloop()

if __name__ == "__main__":
    # Test the GUI with a dummy callback
    def dummy_pipeline(cfg):
        import time
        print("Starting dummy pipeline...")
        for i in range(5):
            print(f"Step {i+1}/5 complete...")
            time.sleep(1)
        print("Done!")

    run_config_gui(dummy_pipeline)
