"""Build standalone Windows executable for Wardrobe using PyInstaller."""
import sys
import PyInstaller.__main__

def build():
    args = [
        "organize.py",
        "--name=Wardrobe",
        "--onefile",
        "--console",
        "--add-data=taxonomy.json;.",
        "--add-data=config.example.toml;.",
        "--add-data=dashboard/templates;dashboard/templates",
        "--add-data=dashboard/static;dashboard/static",
        "--hidden-import=fitz",
        "--hidden-import=pymupdf",
        "--hidden-import=pypdf",
        "--hidden-import=PIL",
        "--hidden-import=flask",
        "--clean",
    ]
    print("Building Wardrobe.exe with PyInstaller...")
    PyInstaller.__main__.run(args)
    print("Build complete! Check the dist/ directory for Wardrobe.exe.")

if __name__ == "__main__":
    build()
