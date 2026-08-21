import os
import sys
import argparse
import importlib
from typing import Optional
from bundles.validator import validate_all_bundles
from bundles.distributor import BundleDistributor

BUNDLES_DIR = os.path.dirname(os.path.abspath(__file__))

def list_bundles():
    distributor = BundleDistributor(BUNDLES_DIR)
    bundles = distributor.list_bundles()

    print("\n" + "="*80)
    print("📦 INSTALLED DATAHARBOR BUNDLES:")
    print("="*80)

    if not bundles:
        print("No bundles currently installed in 'bundles/' directory.")
        print("Install a bundle using: harbor bundle install <git-url | tar.gz | path>\n")
        return

    for b in bundles:
        status = "✅ VALID" if b["is_valid"] else "❌ INVALID"
        git_str = f" (Git: {b['git_url']})" if b.get("git_url") else ""
        print(f"• {b['name']} (v{b['version']}) - [{status}]{git_str}")
        print(f"  Description: {b['description']}")
        print(f"  Path:        {b['path']}")
        if b["errors"]:
            print("  Errors:")
            for err in b["errors"]:
                print(f"    - {err}")
        print("-" * 80)
    print("")

def validate_bundles():
    print(f"🔍 Validating all bundles in: {BUNDLES_DIR}\n")
    results = validate_all_bundles(BUNDLES_DIR)

    if not results:
        print("No bundles found to validate.")
        return

    has_errors = False
    for bundle_name, (is_valid, errors) in results.items():
        if is_valid:
            print(f"✅ Bundle '{bundle_name}': VALID")
        else:
            has_errors = True
            print(f"❌ Bundle '{bundle_name}': INVALID")
            for err in errors:
                print(f"   - {err}")

    if has_errors:
        print("\n⚠️ Validation failed for one or more bundles.")
        sys.exit(1)
    else:
        print("\n✨ All bundles passed validation successfully!")

def install_bundle(source: str, force: bool = False):
    distributor = BundleDistributor(BUNDLES_DIR)
    try:
        res = distributor.install_bundle(source, force=force)
        print(f"\n🎉 {res['message']}")
    except Exception as e:
        print(f"\n❌ Bundle Installation Failed: {e}")
        sys.exit(1)

def pack_bundle(bundle_name: str, output_dir: Optional[str] = None):
    distributor = BundleDistributor(BUNDLES_DIR)
    try:
        archive_path = distributor.pack_bundle(bundle_name, output_dir)
        print(f"\n📦 Bundle '{bundle_name}' packed successfully!")
        print(f"   Archive path: file://{os.path.abspath(archive_path)}")
    except Exception as e:
        print(f"\n❌ Bundle Packaging Failed: {e}")
        sys.exit(1)

def remove_bundle(bundle_name: str):
    distributor = BundleDistributor(BUNDLES_DIR)
    try:
        distributor.remove_bundle(bundle_name)
        print(f"\n🗑️ Bundle '{bundle_name}' removed successfully.")
    except Exception as e:
        print(f"\n❌ Bundle Removal Failed: {e}")
        sys.exit(1)

def export_bundles(target_bundle: Optional[str] = None):
    print(f"📦 Exporting bundle cards datasets...\n")
    if target_bundle:
        bundle_names = [target_bundle]
    else:
        bundle_names = [d for d in os.listdir(BUNDLES_DIR) if os.path.isdir(os.path.join(BUNDLES_DIR, d)) and not d.startswith((".", "_"))]

    for bname in bundle_names:
        try:
            mod = importlib.import_module(f"bundles.{bname}.exporter")
            res = mod.export_bundle()
            print(f"✅ Bundle '{bname}' Exported: {res}")
        except Exception as e:
            print(f"⚠️ Could not run exporter for '{bname}': {e}")

def main():
    parser = argparse.ArgumentParser(prog="harbor bundle", description="DataHarbor Bundle Manager CLI")
    subparsers = parser.add_subparsers(dest="subcommand")

    subparsers.add_parser("list", help="List all installed bundles and their status")
    subparsers.add_parser("validate", help="Validate manifest schema and syntax for installed bundles")

    install_parser = subparsers.add_parser("install", help="Install a bundle from Git URL, local archive, or folder")
    install_parser.add_argument("source", help="Git repository URL, local .tar.gz/.zip archive, or folder path")
    install_parser.add_argument("--force", action="store_true", help="Overwrite existing installed bundle")

    pack_parser = subparsers.add_parser("pack", help="Pack an installed bundle into a .tar.gz distribution archive")
    pack_parser.add_argument("bundle_name", help="Name of the bundle directory to pack")
    pack_parser.add_argument("--output", help="Target output directory for the archive")

    remove_parser = subparsers.add_parser("remove", help="Remove an installed bundle")
    remove_parser.add_argument("bundle_name", help="Name of the bundle directory to remove")

    export_parser = subparsers.add_parser("export", help="Export dataset cards for installed bundles")
    export_parser.add_argument("bundle_name", nargs="?", help="Optional specific bundle name")

    args = parser.parse_args()

    if args.subcommand == "list":
        list_bundles()
        
    elif args.subcommand == "install":
        install_bundle(args.source, force=args.force)

    elif args.subcommand == "pack":
        pack_bundle(args.bundle_name, output_dir=args.output)

    elif args.subcommand == "remove":
        remove_bundle(args.bundle_name)

    elif args.subcommand == "export":
        export_bundles(args.bundle_name)

    else:
        validate_bundles()

if __name__ == "__main__":
    main()
