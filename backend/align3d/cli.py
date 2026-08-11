"""CLI entry point for align3d."""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import cv2

# Ensure backend is on path when run as module
_BACKEND = Path(__file__).parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from align3d import (
    align_batch_3d,
    build_profile_from_checkerboard,
    load_config,
    preview_depth,
    save_profile,
)
from align3d.calibration.profile_store import list_profiles


def cmd_align(args):
    ref = args.reference
    targets = args.targets
    band_map = {}
    if args.bands:
        all_paths = [ref] + targets
        bands = args.bands.split(",")
        for p, b in zip(all_paths, bands):
            band_map[p] = b.strip()

    overrides = {}
    if args.depth_min:
        overrides["depth_min"] = args.depth_min
    if args.depth_max:
        overrides["depth_max"] = args.depth_max
    if args.num_planes:
        overrides["num_planes"] = args.num_planes
    if args.rig_profile:
        overrides["rig_profile"] = args.rig_profile
    if args.backend:
        overrides["depth_backend"] = args.backend

    debug_dir = args.debug_dir or str(Path(args.output).parent / "align3d")
    result = align_batch_3d(
        ref,
        targets,
        band_map=band_map,
        config_overrides=overrides,
        debug_dir=debug_dir,
    )

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    for path, res in result.results.items():
        if res.success and res.aligned_image is not None:
            name = Path(path).stem + "_aligned.jpg"
            out_path = out_dir / name
            cv2.imwrite(str(out_path), res.aligned_image)
            print(f"  Saved: {out_path} ({res.message})")
        else:
            print(f"  Failed: {path} - {res.message}")

    print(f"\nSummary: {result.success_count}/{len(result.results)} aligned")
    print(f"Method: {result.method_used}")
    print(f"Notes: {result.notes}")
    if args.debug:
        print(f"Debug dir: {debug_dir}")


def cmd_calib(args):
    bands_raw = args.bands.split(",")
    band_dirs = args.dirs.split(",")
    if len(bands_raw) != len(band_dirs):
        print("Error: --bands and --dirs must have same length")
        sys.exit(1)

    band_images = {}
    for band, dirpath in zip(bands_raw, band_dirs):
        paths = sorted(Path(dirpath.strip()).glob("*.jpg")) + sorted(Path(dirpath.strip()).glob("*.png"))
        band_images[band.strip()] = [str(p) for p in paths]
        print(f"  {band}: {len(band_images[band.strip()])} images")

    profile = build_profile_from_checkerboard(
        band_images,
        reference_band=args.reference_band,
        profile_name=args.name,
    )
    path = save_profile(profile, args.upload_root)
    print(f"Profile saved: {path}")
    print(f"Bands: {list(profile.intrinsics.keys())}")
    print(f"Errors: {profile.metadata.get('reprojection_errors', {})}")


def cmd_preview(args):
    ref = args.reference
    targets = args.targets
    colormap, depth_result, method = preview_depth(ref, targets)
    out = args.output or "depth_preview.png"
    cv2.imwrite(out, colormap)
    print(f"Depth preview saved: {out}")
    print(f"Method: {method}, confidence: {depth_result.confidence:.3f}")


def cmd_list_profiles(args):
    profiles = list_profiles(args.upload_root)
    print(json.dumps(profiles, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="align3d - 3D reconstruction alignment tool")
    sub = parser.add_subparsers(dest="command")

    p_align = sub.add_parser("align", help="Align images using 3D reconstruction")
    p_align.add_argument("--reference", "-r", required=True, help="Reference image path")
    p_align.add_argument("--targets", "-t", nargs="+", required=True, help="Target image paths")
    p_align.add_argument("--bands", help="Comma-separated band names matching ref+targets")
    p_align.add_argument("--output", "-o", default="./aligned_output", help="Output directory")
    p_align.add_argument("--debug-dir", help="Debug artifacts directory")
    p_align.add_argument("--debug", action="store_true")
    p_align.add_argument("--rig-profile", help="Rig profile name")
    p_align.add_argument("--depth-min", type=float)
    p_align.add_argument("--depth-max", type=float)
    p_align.add_argument("--num-planes", type=int)
    p_align.add_argument("--backend", choices=["auto", "plane_sweep", "sgbm", "torch_stereo"])
    p_align.set_defaults(func=cmd_align)

    p_calib = sub.add_parser("calib", help="Build calibration profile from checkerboard images")
    p_calib.add_argument("--bands", required=True, help="Comma-separated band names")
    p_calib.add_argument("--dirs", required=True, help="Comma-separated directories per band")
    p_calib.add_argument("--reference-band", default="rgb")
    p_calib.add_argument("--name", default="default")
    p_calib.add_argument("--upload-root", default=None)
    p_calib.set_defaults(func=cmd_calib)

    p_preview = sub.add_parser("preview", help="Preview depth map")
    p_preview.add_argument("--reference", "-r", required=True)
    p_preview.add_argument("--targets", "-t", nargs="+", required=True)
    p_preview.add_argument("--output", "-o")
    p_preview.set_defaults(func=cmd_preview)

    p_list = sub.add_parser("list-profiles", help="List calibration profiles")
    p_list.add_argument("--upload-root", default=None)
    p_list.set_defaults(func=cmd_list_profiles)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
