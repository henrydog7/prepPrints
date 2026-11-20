"""
prepPrints.py - Automated 3MF Print Preparation for APSC 101
Target Printer: Bambu Lab P2S (0.4 nozzle)
Target Material: Bambu PLA Basic (Red, 0.20mm Standard)

Usage:
  1. Install required packages (one-time setup):
     pip install pillow numpy
  2. Download the assignment submission folder from onQ / Brightspace.
  3. Unzip the main assignment folder.
  4. Place this `prepPrints.py` file into that folder.
  5. Run it by double-clicking it or running `python prepPrints.py`.
  5. It will:
     - Automatically unzip any student .zip submissions.
     - Group files by team (e.g., Group 167, Group 173, etc.).
     - Parse the number of copies from the filename (_Nx or _xx).
     - Generate a clean 1-layer (0.2mm) group number tag for each team.
     - Feed everything into Bambu Studio CLI to arrange across plates.
     - Save the final assembled project as `print3_<timestamp>.3mf`.
     - Display a detailed summary report and keep the window open.
"""

import os
import sys
import re
import glob
import zipfile
import shutil
import struct
import datetime
import subprocess
from pathlib import Path

# Try importing PIL for generating the 1-layer 3D text tag
try:
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


def pause_before_exit():
    """Keeps the console open if run interactively, exits immediately if automated."""
    try:
        if sys.stdin and sys.stdin.isatty():
            pause_before_exit()
    except (EOFError, KeyboardInterrupt):
        pass

BAMBU_CANDIDATE_PATHS = [
    r"C:\Program Files\Bambu Studio\bambu-studio.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Bambu Studio\bambu-studio.exe"),
    r"C:\Program Files (x86)\Bambu Studio\bambu-studio.exe",
]

def find_bambu_studio():
    """Locate the Bambu Studio CLI executable."""
    for path in BAMBU_CANDIDATE_PATHS:
        if os.path.isfile(path):
            return path
    which_path = shutil.which("bambu-studio") or shutil.which("bambu-studio.exe")
    if which_path and os.path.isfile(which_path):
        return which_path
    return None

def find_bambu_profiles(bambu_exe):
    """Find default Bambu Lab P2S and PLA profiles."""
    install_dir = os.path.dirname(bambu_exe)
    profiles_dir = os.path.join(install_dir, "resources", "profiles", "BBL")
    
    machine_profile = os.path.join(profiles_dir, "machine", "Bambu Lab P2S 0.4 nozzle.json")
    process_profile = os.path.join(profiles_dir, "process", "0.20mm Standard @BBL P2S.json")
    filament_profile = os.path.join(profiles_dir, "filament", "Bambu PLA Basic @BBL P2S.json")

    # Verify presence
    settings = []
    if os.path.isfile(machine_profile) and os.path.isfile(process_profile):
        settings.append(f"{machine_profile};{process_profile}")
    else:
        settings.append(None)

    filaments = filament_profile if os.path.isfile(filament_profile) else None
    return settings[0], filaments


# ==============================================================================
# 1-Layer 3D Text Tag Generator (0.20 mm height)
# ==============================================================================

def generate_1layer_text_stl(text: str, output_path: str, scale_mm: float = 0.5, layer_height_mm: float = 0.20):
    """
    Generates a simple 3D STL file consisting of 1-layer (0.20mm) tall text.
    Uses PIL to render the text to bitmap, then converts pixel spans to 3D boxes.
    """
    if not PIL_AVAILABLE:
        return False

    try:
        try:
            # Arial or standard sans font
            font = ImageFont.truetype("arial.ttf", 28)
        except Exception:
            font = ImageFont.load_default()

        # Measure text
        dummy = Image.new("L", (1, 1), 0)
        draw = ImageDraw.Draw(dummy)
        bbox = draw.textbbox((0, 0), text, font=font)
        pad = 2
        w = (bbox[2] - bbox[0]) + pad * 2
        h = (bbox[3] - bbox[1]) + pad * 2

        img = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(img)
        draw.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=255)

        arr = np.array(img) > 128
        H, W = arr.shape

        triangles = []
        def add_box(x0, y0, x1, y1, z0, z1):
            pts = [
                [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]
            ]
            faces = [
                [0, 1, 2], [0, 2, 3], # bottom
                [4, 6, 5], [4, 7, 6], # top
                [0, 4, 5], [0, 5, 1], # front
                [2, 6, 7], [2, 7, 3], # back
                [0, 3, 7], [0, 7, 4], # left
                [1, 5, 6], [1, 6, 2]  # right
            ]
            for f in faces:
                triangles.append([pts[f[0]], pts[f[1]], pts[f[2]]])

        for y in range(H):
            y_mm0 = (H - 1 - y) * scale_mm
            y_mm1 = y_mm0 + scale_mm
            x = 0
            while x < W:
                if arr[y, x]:
                    x_start = x
                    while x < W and arr[y, x]:
                        x += 1
                    x_end = x
                    add_box(x_start * scale_mm, y_mm0, x_end * scale_mm, y_mm1, 0.0, layer_height_mm)
                else:
                    x += 1

        # Write binary STL
        with open(output_path, "wb") as f:
            f.write(b"\0" * 80)
            f.write(struct.pack("<I", len(triangles)))
            for t in triangles:
                f.write(struct.pack("<3f", 0.0, 0.0, 0.0))
                for pt in t:
                    f.write(struct.pack("<3f", float(pt[0]), float(pt[1]), float(pt[2])))
                f.write(struct.pack("<H", 0))

        return True
    except Exception as e:
        print(f"Warning: Failed to generate text tag for '{text}': {e}")
        return False


# ==============================================================================
# File Scanning & Parsing
# ==============================================================================

def extract_group_number(file_path: str) -> str:
    """
    Extracts group number from folder or file name.
    Examples:
      - '... - Group 167 2026 - ...' -> '167'
      - '172_ScraperPegMK43_PanzaM_N3.3mf' -> '172'
      - 'Group_174/model.3mf' -> '174'
    """
    # 1. Look for 'Group <digits>' anywhere in path
    m = re.search(r"Group[_\s]+(\d{1,3})", file_path, re.IGNORECASE)
    if m:
        return m.group(1).lstrip("0") or "0"

    # 2. Look for leading '<digits>_' in the filename
    base_name = os.path.basename(file_path)
    m = re.match(r"^(\d{1,3})_", base_name)
    if m:
        return m.group(1).lstrip("0") or "0"

    return "Unknown"

def extract_quantity(file_name: str):
    """
    Extracts quantity (Nx or xx) from filename.
    Returns (count, concern_message or None).
    """
    # Clean file name from common Brightspace / Windows duplicate suffixes like ' (2)' or '(3)'
    name_no_ext = os.path.splitext(file_name)[0]
    cleaned = re.sub(r"\s*\(\d+\)$", "", name_no_ext).strip()

    # Pattern 1: Standard _N<count> or -N<count> or N<count> at the end
    m = re.search(r"[_\s-]N(\d+)$", cleaned, re.IGNORECASE)
    if m:
        return int(m.group(1)), None

    # Pattern 2: Flexible _<count>x or -<count>x or <count>x at the end
    m = re.search(r"[_\s-](\d+)x$", cleaned, re.IGNORECASE)
    if m:
        count = int(m.group(1))
        return count, f"Used flexible '{count}x' naming instead of standard '_N{count}'"

    # Pattern 3: Embedded _N<count>_ anywhere
    m = re.search(r"[_\s-]N(\d+)[_\s-]", cleaned, re.IGNORECASE)
    if m:
        count = int(m.group(1))
        return count, f"Found '_N{count}' embedded within filename"

    # Default to 1 if missing
    return 1, "Missing '_Nx' copy count in filename (defaulted to 1 copy)"


# ==============================================================================
# Main Preparation Process
# ==============================================================================

def main():
    root_dir = os.path.abspath(os.path.dirname(__file__))
    os.chdir(root_dir)

    print("=" * 70)
    print(" APSC 101 - Bambu P2S Print Preparation Tool")
    print("=" * 70)
    print(f"Working Directory: {root_dir}\n")

    # Locate Bambu Studio
    bambu_exe = find_bambu_studio()
    if not bambu_exe:
        print("[ERROR] Bambu Studio executable was not found on this system!")
        print("Please ensure Bambu Studio is installed in 'C:\\Program Files\\Bambu Studio'.")
        pause_before_exit()
        return

    print(f"[OK] Bambu Studio found: {bambu_exe}")
    settings_arg, filament_arg = find_bambu_profiles(bambu_exe)
    if settings_arg:
        print("[OK] Loaded Bambu Lab P2S (0.4 nozzle) and 0.20mm Standard profiles.")
    if filament_arg:
        print("[OK] Loaded Bambu PLA Basic filament profile.")

    # Working folder for extracted files and tags
    temp_work_dir = os.path.join(root_dir, "_prep_prints_temp")
    if os.path.exists(temp_work_dir):
        shutil.rmtree(temp_work_dir, ignore_errors=True)
    os.makedirs(temp_work_dir, exist_ok=True)

    # 1. Unpack any .zip files
    zip_files = [f for f in glob.glob("*.zip") if not f.startswith("test_")]
    print(f"\n[INFO] Found {len(zip_files)} student zip submission(s). Extracting...")
    
    for z in zip_files:
        group_id = extract_group_number(z)
        target_dir = os.path.join(temp_work_dir, f"Group_{group_id}" if group_id != "Unknown" else "Zips")
        os.makedirs(target_dir, exist_ok=True)
        try:
            with zipfile.ZipFile(z, "r") as zf:
                zf.extractall(target_dir)
        except Exception as e:
            print(f"  [WARNING] Failed to extract {z}: {e}")

    # 2. Gather all files in root and extracted folders
    all_found_files = []
    # Root files (excluding scripts, output 3mf, temp dirs)
    for f in os.listdir(root_dir):
        full_p = os.path.join(root_dir, f)
        if os.path.isfile(full_p) and not f.endswith(".py") and not f.startswith("print3_") and not f.startswith("test_"):
            all_found_files.append(full_p)

    # Extracted files
    for dirpath, _, filenames in os.walk(temp_work_dir):
        for fn in filenames:
            all_found_files.append(os.path.join(dirpath, fn))

    # 3. Categorize files
    models_by_group = {}   # group_id -> list of (file_path, count, original_name)
    ignored_files = []     # list of (file_path, reason)
    concerns = []          # list of (group_id, file_name, message)

    for fp in all_found_files:
        ext = os.path.splitext(fp)[1].lower()
        base = os.path.basename(fp)
        rel_path = os.path.relpath(fp, root_dir)

        # Skip zip files (already extracted), html index, text tags
        if ext in [".zip", ".html", ".txt", ".py"]:
            continue

        if ext != ".3mf":
            ignored_files.append((rel_path, f"Unsupported format '{ext}' (only .3mf files are prepared for printing)"))
            continue

        # Valid 3MF model
        group_id = extract_group_number(rel_path)
        count, note = extract_quantity(base)

        if note:
            concerns.append((group_id, base, note))

        if group_id not in models_by_group:
            models_by_group[group_id] = []
        models_by_group[group_id].append((fp, count, base))

    # Sort groups numerically
    sorted_group_keys = sorted(models_by_group.keys(), key=lambda g: int(g) if g.isdigit() else 9999)

    if not sorted_group_keys:
        print("\n[ERROR] No valid .3mf files found to prepare!")
        shutil.rmtree(temp_work_dir, ignore_errors=True)
        pause_before_exit()
        return

    # 4. Generate 1-layer group tags and prepare Bambu Studio file list
    bambu_input_files = []
    tags_created = 0

    print("\n[INFO] Generating 1-layer group tags and building model list...")
    for group_id in sorted_group_keys:
        files = models_by_group[group_id]
        
        # Generate 1-layer group tag STL
        tag_stl = os.path.join(temp_work_dir, f"Tag_Group_{group_id}.stl")
        tag_label = f"Group {group_id}" if group_id.isdigit() else group_id
        if generate_1layer_text_stl(tag_label, tag_stl, scale_mm=0.45, layer_height_mm=0.20):
            bambu_input_files.append(tag_stl)
            tags_created += 1

        # Add models for this group (repeated by quantity count)
        for fp, count, _ in files:
            for _ in range(count):
                bambu_input_files.append(fp)

    # 5. Execute Bambu Studio CLI to arrange and save
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    output_filename = f"print3_{timestamp}.3mf"
    output_filepath = os.path.join(root_dir, output_filename)

    cmd = [bambu_exe]
    if settings_arg:
        cmd.extend(["--load-settings", settings_arg])
    if filament_arg:
        cmd.extend(["--load-filaments", filament_arg])
    
    cmd.extend([
        "--arrange", "1",
        "--export-3mf", output_filename,
        "--outputdir", root_dir,
    ])
    cmd.extend(bambu_input_files)

    print(f"\n[INFO] Running Bambu Studio auto-arrange across plates ({len(bambu_input_files)} total items)...")
    print("This may take 15-30 seconds depending on mesh complexity...")

    try:
        # Note: We avoid capture_output=True on Windows GUI executables (like Bambu Studio)
        # to prevent subprocess pipe deadlocks.
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        success = (proc.returncode == 0) and os.path.isfile(output_filepath)
    except Exception as e:
        success = False
        print(f"[ERROR] Failed to run Bambu Studio: {e}")

    # Inspect generated plates if successful
    plate_count = 0
    if success:
        try:
            with zipfile.ZipFile(output_filepath, "r") as z:
                plate_imgs = [n for n in z.namelist() if n.startswith("Metadata/plate_") and not "small" in n and not "no_light" in n]
                plate_count = len(plate_imgs)
        except Exception:
            plate_count = 1

    # Cleanup temp directory
    shutil.rmtree(temp_work_dir, ignore_errors=True)

    # 6. Summary Report
    print("\n" + "=" * 70)
    print(" PREPARATION SUMMARY REPORT")
    print("=" * 70)

    if success:
        print(f" Status: SUCCESS")
        print(f" Output File: {output_filename}")
        print(f" Estimated Plates Required: {plate_count}")
    else:
        print(" Status: FAILED (Bambu Studio did not produce the expected 3MF file)")

    print(f"\n Groups Processed ({len(sorted_group_keys)} total):")
    total_parts = 0
    total_instances = 0
    for gid in sorted_group_keys:
        items = models_by_group[gid]
        parts_in_group = len(items)
        instances_in_group = sum(c for _, c, _ in items)
        total_parts += parts_in_group
        total_instances += instances_in_group
        print(f"   * Group {gid:3s}: {parts_in_group:2d} unique 3MF file(s), {instances_in_group:2d} total part(s) to print")
        for _, c, base_name in items:
            print(f"       - {base_name} (x{c})")

    print(f"\n Totals: {total_parts} unique 3MF files, {total_instances} printed parts + {tags_created} group tags")

    if concerns:
        print(f"\n Concerns / Warnings ({len(concerns)}):")
        for gid, base_name, note in concerns:
            print(f"   [!] Group {gid}: '{base_name}' -> {note}")

    if ignored_files:
        print(f"\n Non-3MF / Ignored Files ({len(ignored_files)}):")
        for r_path, reason in ignored_files:
            print(f"   [-] {r_path}: {reason}")

    print("\n" + "=" * 70)
    print(" Preparation complete! You can open the generated .3mf file in Bambu Studio.")
    print("=" * 70)
    pause_before_exit()

if __name__ == "__main__":
    main()
