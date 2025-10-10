import sys
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

if sys.platform.startswith("win"):
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

root = tk.Tk()
root.title("Downloader")
root.geometry("1120x960")
root.minsize(1120, 960)
root.resizable(True, True)

root.update_idletasks()
w, h = 1120, 960
sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
x, y = (sw - w) // 2, (sh - h) // 2
root.geometry(f"{w}x{h}+{x}+{y}")

root.columnconfigure(0, weight=1)
root.rowconfigure(0, weight=1)

# Use a modern ttk theme and tweak default fonts/padding
style = ttk.Style(root)
try:
    # Prefer 'vista' on Windows if available, else fallback
    style.theme_use("vista")
except Exception:
    try:
        style.theme_use("clam")
    except Exception:
        pass

# Harmonize base fonts for readability
try:
    base = tkfont.nametofont("TkDefaultFont")
    base.configure(family="Segoe UI", size=11)
    text = tkfont.nametofont("TkTextFont")
    text.configure(family="Segoe UI", size=11)
    heading = tkfont.nametofont("TkHeadingFont")
    heading.configure(family="Segoe UI", size=12, weight="bold")
except Exception:
    pass

# Slightly larger, comfy controls
style.configure("TButton", padding=(12, 8))
style.configure("TEntry", padding=(8, 6))
style.configure("TProgressbar", thickness=14)
style.configure("Horizontal.TProgressbar", thickness=14)

main = ttk.Frame(root, padding=24)
main.grid(row=0, column=0, sticky="nsew")
main.columnconfigure(0, weight=0)
main.columnconfigure(1, weight=1)
main.columnconfigure(2, weight=0)
main.rowconfigure(1, weight=0)
main.rowconfigure(2, weight=0)
main.rowconfigure(3, weight=1)

link_var = tk.StringVar()
status_var = tk.StringVar(value="Ready")
progress_var = tk.IntVar(value=0)

def on_download():
    status_var.set("Preparing...")
    progress_var.set(0)

lbl_link = ttk.Label(main, text="Enter Link")
entry = ttk.Entry(main, textvariable=link_var)
btn = ttk.Button(main, text="Download", command=on_download)

lbl_link.grid(row=0, column=0, sticky="w", padx=(0, 10), pady=(0, 14))
entry.grid(row=0, column=1, sticky="ew", pady=(0, 14))
btn.grid(row=0, column=2, sticky="e", padx=(12, 0), pady=(0, 14))

progress = ttk.Progressbar(
    main,
    orient="horizontal",
    mode="determinate",
    maximum=100,
    variable=progress_var,
)
progress.grid(row=1, column=0, columnspan=3, sticky="ew")

status = ttk.Label(main, textvariable=status_var, anchor="w")
status.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 0))

entry.bind("<Return>", lambda e: on_download())

root.mainloop()
