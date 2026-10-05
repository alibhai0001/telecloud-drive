import os
import sys
import time
import subprocess
import threading
import urllib.request
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def run_uvicorn():
    """Start uvicorn in background thread"""
    import uvicorn
    import config
    uvicorn.run("app:app", host="0.0.0.0", port=8000, log_level="info")

def start_public_tunnel():
    """Start free Cloudflare Tunnel or localtunnel for public URL"""
    time.sleep(2)
    print("\n" + "="*60)
    print("  🚀 TELECLOUD DRIVE & BOT IS STARTING...")
    print("  Local Dashboard: http://127.0.0.1:8000")
    print("="*60 + "\n")
    
    # Try Localtunnel / Cloudflare
    print("Generating secure public HTTPS link...")
    try:
        # Check if npx is available for instant localtunnel / cloudflared
        cmd = "npx --yes localtunnel --port 8000"
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        public_url = None
        for line in iter(proc.stdout.readline, ''):
            if not line:
                break
            line_str = line.strip()
            print(f"[Tunnel] {line_str}")
            if "your url is:" in line_str.lower():
                public_url = line_str.split("is:")[-1].strip()
                break
                
        if public_url:
            print("\n" + "="*60)
            print(f"  🎉 LIVE PUBLIC URL: {public_url}")
            print(f"  (Share this link or open on Mobile / Telegram!)")
            print("="*60 + "\n")
            with open(BASE_DIR / "public_url.txt", "w", encoding="utf-8") as f:
                f.write(public_url)
    except Exception as e:
        print(f"Tunnel notice: {e}. Access locally at http://127.0.0.1:8000")

if __name__ == "__main__":
    t = threading.Thread(target=start_public_tunnel, daemon=True)
    t.start()
    run_uvicorn()
