"""
CI helper: downloads latest sing-box.exe for Windows amd64 from GitHub releases.
Run: python scripts/download_singbox.py [output_dir]
"""

import json
import os
import sys
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

API_URL = "https://api.github.com/repos/SagerNet/sing-box/releases/latest"


def main():
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get latest release
    req = Request(API_URL)
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "SingBoxGUI-CI/1.0")

    with urlopen(req, timeout=15) as resp:
        release = json.loads(resp.read())

    tag = release["tag_name"]
    print(f"Latest sing-box: {tag}")

    # Find windows-amd64 .zip (prefer non-legacy)
    windows_asset = None
    for asset in release["assets"]:
        name = asset["name"].lower()
        if "windows" in name and "amd64" in name and name.endswith(".zip"):
            # Skip legacy builds if we have a choice
            if "legacy" not in name:
                windows_asset = asset
                break
            if windows_asset is None:
                windows_asset = asset

    if not windows_asset:
        print("Available assets:")
        for a in release["assets"]:
            print(f"  {a['name']}")
        raise SystemExit("No windows-amd64 .zip found in release")

    download_url = windows_asset["browser_download_url"]
    print(f"Downloading: {windows_asset['name']} ({windows_asset['size']} bytes)")

    # Download
    zip_path = output_dir / "sing-box-tmp.zip"
    req2 = Request(download_url)
    req2.add_header("User-Agent", "SingBoxGUI-CI/1.0")
    with urlopen(req2, timeout=120) as resp:
        zip_path.write_bytes(resp.read())

    print(f"Downloaded to {zip_path}")

    # Extract
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            if member.lower().endswith("sing-box.exe"):
                zf.extract(member, output_dir)
                extracted = output_dir / member
                target = output_dir / "sing-box.exe"
                if extracted != target:
                    if target.exists():
                        target.unlink()
                    extracted.rename(target)
                print(f"Extracted: {target} ({target.stat().st_size} bytes)")
                break
        else:
            raise SystemExit("sing-box.exe not found in archive")

    # Cleanup
    zip_path.unlink()
    print("Done!")


if __name__ == "__main__":
    main()
