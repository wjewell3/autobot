#!/usr/bin/env python3
"""Scan cluster images and repo manifests to propose image pins.

Behavior:
- Uses `kubectl` to read running pods in namespace `kagent` and extract image->digest mapping.
- Scans workspace YAML files for image references with floating tags and maps them to digests when available.
- Writes `proposals/image-pins.json` with a list of proposed replacements.

This is intentionally conservative: only images currently running in the cluster will be pinned.
"""
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTDIR = Path(__file__).resolve().parent / "proposals"
OUTDIR.mkdir(exist_ok=True)

def get_running_image_digests(namespace="kagent"):
    # returns dict: image_name_with_tag -> digest (sha256...)
    cmd = ["kubectl", "get", "pods", "-n", namespace, "-o", "jsonpath={range .items[*]}{.spec.containers[*].image}{'\t'}{.status.containerStatuses[*].imageID}{'\n'}{end}"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    mapping = {}
    if out.returncode != 0:
        return mapping
    for line in out.stdout.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 2:
            continue
        image, imageid = parts[0].strip(), parts[1].strip()
        # imageID looks like: docker-pullable://ghcr.io/berriai/litellm@sha256:abcdef...
        m = re.search(r"@sha256:[0-9a-f]+", imageid)
        if m:
            digest = m.group(0).lstrip("@")
            mapping[image] = digest
    return mapping

IMAGE_RE = re.compile(r"(?P<image>[a-zA-Z0-9\-._/:]+):(?P<tag>[a-zA-Z0-9_.-]+)")

def scan_manifests_for_floating_images(path_root: Path):
    files = list(path_root.glob("**/*.yaml")) + list(path_root.glob("**/*.yml"))
    candidates = {}
    for f in files:
        try:
            text = f.read_text()
        except Exception:
            continue
        for m in IMAGE_RE.finditer(text):
            image = m.group(0)
            if "@sha256" in image:
                continue
            # skip local file references or templates containing {{
            if "{{" in text:
                continue
            candidates.setdefault(f.relative_to(path_root).as_posix(), set()).add(image)
    return candidates

def build_proposals(mapping, candidates):
    proposals = []
    for path, imgs in candidates.items():
        for img in imgs:
            # find best match in mapping by image name (without tag)
            name = img.rsplit(":", 1)[0]
            match = None
            for running, digest in mapping.items():
                if running.startswith(name + ":") or running.startswith(name + "@"):
                    match = digest
                    break
            if match:
                proposals.append({"file": path, "old": img, "new": f"{name}@{match}"})
    return proposals

def main():
    mapping = get_running_image_digests()
    candidates = scan_manifests_for_floating_images(ROOT)
    proposals = build_proposals(mapping, candidates)
    out = OUTDIR / "image-pins.json"
    out.write_text(json.dumps({"proposals": proposals}, indent=2))
    print(f"Wrote proposals: {out} ({len(proposals)} items)")

if __name__ == '__main__':
    main()
