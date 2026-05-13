import subprocess
import os
import glob
import shutil
import time
from astropy.io import fits
from astropy.wcs import WCS

def solve_with_astap(fits_path, astap_exe="astap", search_radius=5.0, annotate=False):
    """
    Solves a FITS file using the ASTAP command-line interface.
    https://www.hnsky.org/astap.htm#astap_command_line
    """
    
    # 1. Read existing header for RA/Dec hints
    try:
        with fits.open(fits_path) as hdul:
            header = hdul[0].header
            # Try to find RA/Dec in common header keys
            ra_hint = header.get('RA') or header.get('OBJCTRA')
            dec_hint = header.get('DEC') or header.get('OBJCTDEC')
    except Exception as e:
        print(f"Error reading FITS header for {fits_path}: {e}")
        return None

    # 2. Build the command
    # ASTAP uses degrees for RA and Dec in the CLI.
    # -f: input file, -r: search radius, -ra/dec: position hints
    
    # Normalize paths for Windows (converts / to \ and handles absolute paths)
    astap_exe = os.path.normpath(astap_exe)
    fits_path = os.path.normpath(fits_path)
    
    # We remove -wcs to avoid conflicts with our manual merge logic
    cmd = [astap_exe, "-f", fits_path, "-r", str(search_radius)]
    if annotate:
        cmd.append("-annotate")
    
    if ra_hint and dec_hint:
        print(f"RA/Dec hints found in header. Letting ASTAP read them directly.")
    else:
        print("No RA/Dec hints found in header. Attempting blind solve...")
        # Override search radius for blind solve
        cmd[4] = "180"

    # 3. Execute ASTAP
    print(f"Running command: {' '.join(cmd)}")
    try:
        # We capture output to check for success/failure strings
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        # Give Windows a moment to release file locks
        time.sleep(1.0)
        
        # ASTAP returns 0 on success, but we check for the solution file
        wcs_file = fits_path.replace(".fits", ".wcs").replace(".fit", ".wcs")
        
        if os.path.exists(wcs_file) or "Solved" in result.stdout:
            print(f"Successfully solved: {fits_path}")
            
            # Verify FITS file is readable BEFORE merging
            try:
                with fits.open(fits_path) as test_hdul:
                    pass
            except Exception as e:
                print(f"Warning: FITS file {fits_path} is unreadable BEFORE merging: {e}")

            # If the .wcs file exists, ensure it's merged into the FITS header manually
            if os.path.exists(wcs_file):
                print(f"Merging solution from {wcs_file} into {fits_path}...")
                try:
                    with open(wcs_file, 'r') as f:
                        wcs_lines = f.readlines()
                    
                    # Safely update the FITS header
                    with fits.open(fits_path) as hdul:
                        header = hdul[0].header.copy()
                        data = hdul[0].data
                    
                    for line in wcs_lines:
                        line = line.strip()
                        if not line:
                            continue
                        
                        # Handle COMMENT or HISTORY lines first (they might contain '=')
                        line_upper = line.upper()
                        if line_upper.startswith('COMMENT'):
                            header.add_comment(line[7:].strip())
                            continue
                        if line_upper.startswith('HISTORY'):
                            header.add_history(line[7:].strip())
                            continue
                            
                        if '=' not in line:
                            continue
                        
                        # Standard key = value
                        key, rest = line.split('=', 1)
                        key = key.strip().upper()
                        
                        # Skip structural keywords that should not be overridden
                        if key in ['SIMPLE', 'BITPIX', 'NAXIS', 'NAXIS1', 'NAXIS2', 'EXTEND', 'END']:
                            continue
                            
                        if '/' in rest:
                            val, comment = rest.split('/', 1)
                            val = val.strip()
                            comment = comment.strip()
                        else:
                            val = rest.strip()
                            comment = ""
                        
                        # Type conversion for FITS values
                        if val.startswith("'") and val.endswith("'"):
                            val = val[1:-1].strip()
                        else:
                            try:
                                if '.' in val:
                                    val = float(val)
                                else:
                                    val = int(val)
                            except ValueError:
                                pass
                        
                        # Add or update the keyword (limit to 8 chars for standard FITS)
                        if len(key) <= 8:
                            header[key] = (val, comment)
                        else:
                            header[f'HIERARCH {key}'] = (val, comment)
                    
                    # Write the updated FITS file back
                    fits.writeto(fits_path, data, header, overwrite=True)
                    print(f"FITS header updated and saved successfully.")
                    
                    # Clean up the .wcs file after successful merge
                    os.remove(wcs_file)
                except Exception as e:
                    print(f"Manual header update failed: {e}")

            # 4. Load the new WCS to verify
            try:
                with fits.open(fits_path) as hdul:
                    new_wcs = WCS(hdul[0].header)
                return new_wcs
            except Exception as e:
                print(f"Verification failed: Could not read WCS from {fits_path}. Error: {e}")
                return None
        else:
            print(f"ASTAP finished but no solution was found for {fits_path}.")
            return None

    except subprocess.CalledProcessError as e:
        print(f"ASTAP failed with error code {e.returncode}")
        if e.stdout:
            print(f"STDOUT: {e.stdout}")
        if e.stderr:
            print(f"STDERR: {e.stderr}")
        return None

def plate_solvem(input_pattern, suffix="wcs", astap_exe="astap", search_radius=5.0, annotate=False):
    """
    Solves multiple FITS files matching a pattern.
    Does not overwrite original files; creates a copy with the given suffix.
    """
    files = glob.glob(input_pattern)
    if not files:
        print(f"No files found matching pattern: {input_pattern}")
        return []

    solved_files = []
    for f in files:
        if suffix in f:
            print(f"Skipping already solved file: {f}")
            continue
            
        base, ext = os.path.splitext(f)
        new_filename = f"{base}_{suffix}{ext}"
        
        print(f"Copying {f} to {new_filename}...")
        shutil.copy2(f, new_filename)
        
        # Solve the new file
        res = solve_with_astap(new_filename, astap_exe=astap_exe, search_radius=search_radius, annotate=annotate)
        if res:
            solved_files.append(new_filename)
        else:
            # If solve failed, maybe we should remove the copy?
            # Or keep it for inspection. Let's keep it for now.
            pass
            
    return solved_files

def plate_solve_files(files, suffix="wcs", astap_exe="astap", search_radius=5.0, annotate=False):
    """
    Solves a provided list of FITS file paths.
    Does not overwrite original files; creates a copy with the given suffix.
    """
    if not files:
        print("No files provided for plate solving.")
        return []

    solved_files = []
    for f in files:
        if suffix and f"_{suffix}" in f:
            print(f"Skipping potentially already solved file: {f}")
            continue
            
        base, ext = os.path.splitext(f)
        new_filename = f"{base}_{suffix}{ext}" if suffix else f
        
        if new_filename != f:
            print(f"Copying {f} to {new_filename}...")
            shutil.copy2(f, new_filename)
        
        # Solve the file
        res = solve_with_astap(new_filename, astap_exe=astap_exe, search_radius=search_radius, annotate=annotate)
        if res:
            solved_files.append(new_filename)
            
    return solved_files

# --- Example Usage ---
# Ensure 'astap' is in your system PATH, or provide full path to the .exe
# my_wcs = solve_with_astap("m42_test.fits", astap_exe="C:/Program Files/astap/astap.exe")