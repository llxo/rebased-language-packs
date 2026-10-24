#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rebased Language Pack Build Orchestrator
========================================
Manages language pack metadata, parses command-line arguments,
and coordinates batch build tasks for official and custom language packs.
"""

import argparse
import sys
import time
from pathlib import Path

from core import build_custom_pack, build_single_pack

# ----------------------------------------------------------------------
# 1. Official Language Configurations
# ----------------------------------------------------------------------

LANG_CONFIGS = {
    "zh-CN": {
        "name": "Simplified Chinese",
        "plugin_id": 13710,
        "xml_id": "com.intellij.zh",
        "display_name": "Rebased Chinese (Simplified) Language Pack",
        "output_prefix": "rebased-zh-CN-pack",
        "fallback_version": "242.152",
        "fallback_file": "13710/557305/zh.242.152.zip",
        "overrides_dir": "overrides/zh-CN",
    },
    "ja": {
        "name": "Japanese",
        "plugin_id": 13964,
        "xml_id": "com.intellij.ja",
        "display_name": "Rebased Japanese Language Pack",
        "output_prefix": "rebased-ja-pack",
        "fallback_version": "232.322",
        "fallback_file": "13964/575321/ja.232.322.zip",
        "overrides_dir": "overrides/ja",
    },
    "ko": {
        "name": "Korean",
        "plugin_id": 13711,
        "xml_id": "com.intellij.ko",
        "display_name": "Rebased Korean Language Pack",
        "output_prefix": "rebased-ko-pack",
        "fallback_version": "232.322",
        "fallback_file": "13711/575322/ko.232.322.zip",
        "overrides_dir": "overrides/ko",
    },
}

ALIAS_MAP = {
    "zh": "zh-CN",
    "cn": "zh-CN",
    "zh-cn": "zh-CN",
    "zh_cn": "zh-CN",
    "japanese": "ja",
    "korean": "ko",
}


# ----------------------------------------------------------------------
# 2. CLI Entry Point & Execution Workflow
# ----------------------------------------------------------------------

def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Rebased Language Pack Automated Build Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python build.py                   # Build all 3 official packs by default (zh-CN, ja, ko)
  python build.py -l zh-CN,ja       # Build specific language packs
  python build.py -v 242.152        # Specify official upstream version
  python build.py -i ./pack.zip     # Process any third-party/community pack automatically
        """,
    )
    parser.add_argument(
        "-i", "--input-file",
        dest="input_file",
        help="Path to a local language pack (.zip or .jar) to process without specifying -l",
    )
    parser.add_argument(
        "-l", "--langs", "--languages",
        dest="langs",
        default="all",
        help="Comma-separated language codes (default: 'all' for all 3 official packs)",
    )
    parser.add_argument("-v", "--version", dest="version", help="Upstream official version number (default: latest)")
    parser.add_argument("-o", "--output-dir", dest="output_dir", default="dist", help="Output directory (default: dist)")
    parser.add_argument("--proxy", dest="proxy", help="HTTP/HTTPS proxy URL")
    parser.add_argument("--no-proxy", dest="no_proxy", action="store_true", help="Force direct connection")
    parser.add_argument("--keep-temp", dest="keep_temp", action="store_true", help="Keep temporary build directories")

    args = parser.parse_args()
    out_dir = Path(args.output_dir)

    # 1. Local standalone package mode (no -l required)
    if args.input_file:
        in_p = Path(args.input_file).resolve()
        matched_cfg = None
        if args.langs != "all":
            first_lang = args.langs.split(",")[0].strip()
            matched_cfg = LANG_CONFIGS.get(first_lang) or LANG_CONFIGS.get(ALIAS_MAP.get(first_lang.lower()))

        ov_p = Path(matched_cfg["overrides_dir"]) if matched_cfg and "overrides_dir" in matched_cfg else None
        p_name = matched_cfg.get("display_name") if matched_cfg else None

        print("=" * 65)
        print("🚀 Processing local language package (Auto-detection mode)")
        print(f"   Input file: {in_p.name}")
        print("=" * 65 + "\n")

        out_file = build_custom_pack(
            input_file=in_p,
            output_dir=out_dir,
            plugin_name=p_name,
            overrides_dir=ov_p,
            keep_temp=args.keep_temp,
        )
        size_mb = out_file.stat().st_size / 1048576
        print(f"\n[√] Build succeeded: {out_file.name} ({size_mb:.2f} MB)")
        print(f"    Artifact: {out_file.resolve()}")
        sys.exit(0)

    # 2. Batch official packages build mode
    target_langs = []
    for item in [x.strip() for x in args.langs.split(",") if x.strip()]:
        lower = item.lower()
        if lower in ("all", "*", "official"):
            target_langs = list(LANG_CONFIGS.keys())
            break
        elif item in LANG_CONFIGS:
            if item not in target_langs:
                target_langs.append(item)
        elif lower in ALIAS_MAP:
            c = ALIAS_MAP[lower]
            if c not in target_langs:
                target_langs.append(c)

    if not target_langs:
        print("[!] No valid language codes specified. Available: " + ", ".join(LANG_CONFIGS.keys()), file=sys.stderr)
        sys.exit(1)

    print("=" * 65)
    print("🚀 Building Rebased Language Packs")
    lang_labels = [f"{k} ({LANG_CONFIGS[k]['name']})" for k in target_langs]
    print(f"   Target languages: {', '.join(lang_labels)}")
    if args.version:
        print(f"   Upstream version: {args.version}")
    print("=" * 65 + "\n")

    results = []
    failed = []
    start_time = time.time()

    for idx, lang in enumerate(target_langs, 1):
        cfg = LANG_CONFIGS[lang]
        print(f"[{idx}/{len(target_langs)}] Building: {cfg['name']} ({lang}) ...")
        try:
            out_file = build_single_pack(
                lang_code=lang,
                cfg=cfg,
                version=args.version,
                output_dir=out_dir,
                proxy=args.proxy,
                no_proxy=args.no_proxy,
                keep_temp=args.keep_temp,
            )
            size_mb = out_file.stat().st_size / 1048576
            print(f"[√] Success: {out_file.name} ({size_mb:.2f} MB)\n")
            results.append({"lang": lang, "name": cfg["name"], "file": out_file.name, "size": size_mb})
        except Exception as e:
            print(f"[-] Failed to build {cfg['name']} ({lang}): {e}\n", file=sys.stderr)
            failed.append(lang)

    elapsed = time.time() - start_time
    print("=" * 65)
    print(f"🎉 Build completed (Elapsed: {elapsed:.1f}s)")
    print("=" * 65)
    if results:
        print(f"{'Language':<10} | {'Name':<20} | {'Size':<10} | {'Artifact'}")
        print("-" * 65)
        for r in results:
            print(f"{r['lang']:<10} | {r['name']:<20} | {r['size']:.2f} MB   | {r['file']}")
        print(f"\nArtifacts are saved in: {out_dir.resolve()}")

    if failed:
        print(f"\n[!] Warning: Failed languages: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
