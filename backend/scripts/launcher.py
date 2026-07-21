#!/usr/bin/env python3
"""AisleOne Desktop Launcher Dashboard."""

import sys
import os
import threading
import webbrowser
import time
import socket
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

# Resolve path mapping for PyInstaller or direct python run
if getattr(sys, 'frozen', False):
    bundle_dir = sys._MEIPASS
    # In bundle, write database to User's App Support directory so it's writable
    app_data_dir = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "AisleOne")
    os.makedirs(app_data_dir, exist_ok=True)
    os.environ["AISLEONE_DB_PATH"] = os.path.join(app_data_dir, "grocery.db")
else:
    bundle_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, bundle_dir)
os.chdir(bundle_dir)

# Import local modules after path configuration
from utils.db_helpers import DB_PATH, init_db
from ingest.seed_market_data import main as seed_db
import uvicorn

PORT = 8000
SERVER_URL = f"http://127.0.0.1:{PORT}"

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

class AisleOneLauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AisleOne Launcher")
        self.root.geometry("450x320")
        self.root.resizable(False, False)
        
        # Dark premium color palette (Matching AisleOne Web UI)
        self.bg_color = "#111827"      # Dark background
        self.card_bg = "#1F2937"       # Card color
        self.primary_color = "#10B981"  # Neon green accent
        self.text_color = "#F9FAFB"     # White text
        self.text_muted = "#9CA3AF"    # Gray text
        self.hover_color = "#059669"   # Hover button green
        
        self.root.configure(bg=self.bg_color)
        
        # Setup self-healing database initialization/seeding
        self.ensure_database_ready()
        
        self.server_thread = None
        self.server_running = False
        
        self.create_widgets()
        self.start_backend_server()
        
    def ensure_database_ready(self):
        db_file = Path(DB_PATH)
        if not db_file.exists() or db_file.stat().st_size == 0:
            print(f"Database not found or empty at {DB_PATH}. Initializing and seeding default market data...")
            try:
                # Ensure parent directories exist
                db_file.parent.mkdir(parents=True, exist_ok=True)
                seed_db()
            except Exception as e:
                print(f"Error seeding database: {e}")
                
    def create_widgets(self):
        # Header container
        header_frame = tk.Frame(self.root, bg=self.bg_color)
        header_frame.pack(fill=tk.X, pady=(25, 10), padx=20)
        
        # Application Title
        title_label = tk.Label(
            header_frame, text="AisleOne", 
            fg=self.primary_color, bg=self.bg_color,
            font=("Outfit", 26, "bold")
        )
        title_label.pack()
        
        tagline_label = tk.Label(
            header_frame, text="Smart Grocery Price Optimizer", 
            fg=self.text_muted, bg=self.bg_color,
            font=("Outfit", 12, "italic")
        )
        tagline_label.pack(pady=(2, 0))
        
        # Divider Line
        divider = tk.Frame(self.root, bg="#374151", height=2)
        divider.pack(fill=tk.X, padx=20, pady=10)
        
        # Status Card Box
        self.status_card = tk.Frame(self.root, bg=self.card_bg, bd=1, relief=tk.FLAT)
        self.status_card.pack(fill=tk.X, padx=25, pady=15, ipady=8)
        
        self.status_title = tk.Label(
            self.status_card, text="SERVICE STATUS",
            fg=self.text_muted, bg=self.card_bg,
            font=("Helvetica", 9, "bold")
        )
        self.status_title.pack(anchor="w", padx=15, pady=(8, 2))
        
        self.status_label = tk.Label(
            self.status_card, text="Starting API server...",
            fg="#F59E0B", bg=self.card_bg,
            font=("Helvetica", 14, "bold")
        )
        self.status_label.pack(anchor="w", padx=15, pady=(2, 2))
        
        self.ip_label = tk.Label(
            self.status_card, text="Resolving network interfaces...",
            fg=self.text_muted, bg=self.card_bg,
            font=("Helvetica", 10), justify=tk.LEFT
        )
        self.ip_label.pack(anchor="w", padx=15, pady=(0, 8))
        
        # Button layout (custom styled Flat tk.Labels with hovers for premium macOS rendering)
        self.browser_btn = tk.Label(
            self.root, text="Open AisleOne Dashboard ⚡",
            bg=self.primary_color, fg=self.text_color, font=("Outfit", 13, "bold"),
            relief=tk.FLAT, bd=0, height=2, cursor="hand2"
        )
        self.browser_btn.pack(fill=tk.X, padx=25, pady=(10, 5))
        self.browser_btn.bind("<Button-1>", lambda e: self.open_browser())
        self.browser_btn.bind("<Enter>", lambda e: self.browser_btn.configure(bg=self.hover_color))
        self.browser_btn.bind("<Leave>", lambda e: self.browser_btn.configure(bg=self.primary_color))
        
        self.quit_btn = tk.Label(
            self.root, text="Quit Application",
            bg="#374151", fg=self.text_muted, font=("Outfit", 11),
            relief=tk.FLAT, bd=0, height=1, cursor="hand2"
        )
        self.quit_btn.pack(fill=tk.X, padx=25, pady=(5, 10))
        self.quit_btn.bind("<Button-1>", lambda e: self.quit_application())
        self.quit_btn.bind("<Enter>", lambda e: self.quit_btn.configure(bg="#4B5563", fg=self.text_color))
        self.quit_btn.bind("<Leave>", lambda e: self.quit_btn.configure(bg="#374151", fg=self.text_muted))
        
    def start_backend_server(self):
        if is_port_in_use(PORT):
            # Server is already running or port occupied
            self.update_running_status()
            self.server_running = True
            return
            
        def run_uvicorn():
            try:
                # Avoid signal handler registration issues in a daemon thread:
                # Bind to 0.0.0.0 to enable mobile, iPad, and other PC network access
                config = uvicorn.Config("api.app:app", host="0.0.0.0", port=PORT, log_level="info")
                server = uvicorn.Server(config)
                config.setup_event_loop()
                server.run()
            except Exception as e:
                print(f"Uvicorn error: {e}")
                
        self.server_thread = threading.Thread(target=run_uvicorn, daemon=True)
        self.server_thread.start()
        
        # Periodically check if server has started
        self.check_server_startup()
        
    def get_local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return '127.0.0.1'

    def update_running_status(self):
        local_ip = self.get_local_ip()
        self.status_label.configure(text="Server Running", fg=self.primary_color)
        self.ip_label.configure(
            text=f"Local: http://127.0.0.1:{PORT}\nNetwork: http://{local_ip}:{PORT}",
            fg=self.primary_color
        )

    def check_server_startup(self, attempt=0):
        if is_port_in_use(PORT):
            self.update_running_status()
            self.server_running = True
        elif attempt < 20:
            self.root.after(200, lambda: self.check_server_startup(attempt + 1))
        else:
            self.status_label.configure(text="Startup Timeout Error", fg="#EF4444")
            self.ip_label.configure(text="Could not launch local API server.", fg="#EF4444")
            
    def open_browser(self):
        if self.server_running:
            webbrowser.open(SERVER_URL)
        else:
            messagebox.showwarning("Server Starting", "The API server is still starting. Please wait.")
            
    def quit_application(self):
        # Shutdown Tkinter
        self.root.destroy()
        sys.exit(0)

def main():
    # Fix icon path for dock on macOS if available
    root = tk.Tk()
    
    # Apply app icon if exists (PyInstaller unpacks resources to _MEIPASS)
    try:
        icon_file = "assets/app_icon.icns"
        if getattr(sys, 'frozen', False):
            icon_file = os.path.join(sys._MEIPASS, icon_file)
        if os.path.exists(icon_file):
            # macOS uses BUNDLE icon, but tk can use it for window title bar if needed
            pass
    except Exception:
        pass
        
    app = AisleOneLauncherApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
