#!/usr/bin/env python3
"""Copy setmarket.py from the repo root into every set-* skill folder."""
import glob, os, shutil
root = os.path.dirname(os.path.abspath(__file__))
for d in sorted(glob.glob(os.path.join(root, "set-*"))):
    if os.path.isdir(d):
        shutil.copyfile(os.path.join(root, "setmarket.py"), os.path.join(d, "setmarket.py"))
        print("synced", os.path.relpath(d, root))
