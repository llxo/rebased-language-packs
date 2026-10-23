#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rebased Language Pack Core Packaging Engine
===========================================
Provides low-level utilities for network downloads, properties parsing & merging,
plugin.xml patching, package unpacking, and repackaging.
Pure standard library implementation with zero external dependencies.
"""

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_SINCE_BUILD = "200.0"
DEFAULT_UNTIL_BUILD = "999.*"


# ----------------------------------------------------------------------
# 1. HTTP Network & Downloader Utilities
# ----------------------------------------------------------------------

def open_url_resilient(url: str, timeout: int = 25, custom_proxy: Optional[str] = None, no_proxy: bool = False):
    """
    Resilient HTTP request opener that handles system proxies, custom proxies,
    and automatic fallback to direct connections upon network failure.
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RebasedPackBuilder/2.0"}
    handlers = []
    if no_proxy:
        handlers.append(urllib.request.ProxyHandler({}))
    elif custom_proxy:
        handlers.append(urllib.request.ProxyHandler({"http": custom_proxy, "https": custom_proxy}))
        handlers.append(urllib.request.ProxyHandler({}))
    else:
        # Default: Try environment proxy first, fall back to direct connection
        handlers.append(None)
        handlers.append(urllib.request.ProxyHandler({}))

    last_exc = None
    for h in handlers:
        for _ in range(2):
            try:
                opener = urllib.request.build_opener(h) if h is not None else urllib.request.build_opener()
                return opener.open(urllib.request.Request(url, headers=headers), timeout=timeout)
            except Exception as e:
                last_exc = e
                # Do not retry on definite HTTP client/server errors
                if isinstance(e, urllib.error.HTTPError) and e.code in (404, 403, 400):
                    raise
                continue
    raise RuntimeError(f"Request failed: {url} ({last_exc})")


def fetch_marketplace_updates(plugin_id: int, proxy: Optional[str] = None, no_proxy: bool = False) -> List[dict]:
    """Query JetBrains Marketplace updates API for a given plugin ID."""
    url = f"https://plugins.jetbrains.com/api/plugins/{plugin_id}/updates?size=150"
    try:
        with open_url_resilient(url, timeout=15, custom_proxy=proxy, no_proxy=no_proxy) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[!] Failed to fetch updates from Marketplace API (Plugin ID: {plugin_id}): {e}", file=sys.stderr)
        return []


def download_file(url: str, dest_path: Path, proxy: Optional[str] = None, no_proxy: bool = False) -> Path:
    """Download a file via HTTP with real-time progress indicators."""
    print(f"[*] Downloading: {url}")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open_url_resilient(url, timeout=60, custom_proxy=proxy, no_proxy=no_proxy) as resp, open(dest_path, "wb") as out:
        total_size = resp.headers.get("Content-Length")
        total_size = int(total_size) if total_size and total_size.isdigit() else None
        downloaded = 0
        chunk_size = 64 * 1024
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            out.write(chunk)
            downloaded += len(chunk)
            if total_size:
                pct = (downloaded / total_size) * 100
                sys.stdout.write(f"\r    -> Progress: {pct:.1f}% ({downloaded / 1048576:.2f}/{total_size / 1048576:.2f} MB)")
            else:
                sys.stdout.write(f"\r    -> Downloaded: {downloaded / 1024:.1f} KB")
            sys.stdout.flush()
    print("\n[+] Download complete!")
    return dest_path


def resolve_package(
    cfg: dict,
    lang_code: str,
    specified_version: Optional[str] = None,
    input_file: Optional[str] = None,
    cache_dir: Optional[Path] = None,
    proxy: Optional[str] = None,
    no_proxy: bool = False,
) -> Tuple[Path, str]:
    """
    Resolve and obtain the raw language package file (.zip or .jar).
    Supports local file inputs, version matching, or downloading the latest release.
    """
    if input_file:
        p = Path(input_file).resolve()
        if p.is_dir():
            jars = list(p.rglob("*.jar"))
            if not jars:
                raise FileNotFoundError(f"No jar file found in directory: {p}")
            p = jars[0]
        match = re.search(r"(\d+\.\d+[\.\d+]*)", p.name)
        ver = match.group(1) if match else "custom"
        return p, ver

    if cache_dir is None:
        cache_dir = Path("cache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    plugin_id = cfg["plugin_id"]
    xml_id = cfg["xml_id"]
    fb_ver = cfg.get("fallback_version", "242.152")
    fb_file = cfg.get("fallback_file")

    print(f"[*] Checking Marketplace updates (Plugin ID: {plugin_id}, Language: {lang_code})...")
    updates = fetch_marketplace_updates(plugin_id, proxy=proxy, no_proxy=no_proxy)

    target_update = None
    if specified_version:
        for u in updates:
            v = str(u.get("version", "")).strip()
            if v == specified_version or v.startswith(specified_version):
                target_update = u
                break
        if not target_update:
            direct_url = f"https://plugins.jetbrains.com/plugin/download?pluginId={xml_id}&version={specified_version}"
            dest = cache_dir / f"{lang_code}.{specified_version}.zip"
            if not dest.exists():
                download_file(direct_url, dest, proxy=proxy, no_proxy=no_proxy)
            return dest, specified_version
    else:
        valid = [u for u in updates if u.get("file") and u.get("version")]
        if valid:
            valid.sort(key=lambda x: [int(n) for n in re.findall(r"\d+", str(x.get("version", ""))) or [0]], reverse=True)
            target_update = valid[0]
        else:
            dest = cache_dir / f"{lang_code}.{fb_ver}.zip"
            if not dest.exists():
                url = f"https://plugins.jetbrains.com/files/{fb_file}" if fb_file else f"https://plugins.jetbrains.com/plugin/download?pluginId={xml_id}&version={fb_ver}"
                download_file(url, dest, proxy=proxy, no_proxy=no_proxy)
            return dest, fb_ver

    ver = str(target_update.get("version", "unknown"))
    file_rel = target_update.get("file", "")
    dest = cache_dir / (Path(file_rel).name if file_rel else f"{lang_code}.{ver}.zip")
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[+] Using cached archive: {dest.name} (Version: {ver})")
        return dest, ver

    url = f"https://plugins.jetbrains.com/files/{file_rel}" if file_rel else f"https://plugins.jetbrains.com/plugin/download?updateId={target_update.get('id')}"
    download_file(url, dest, proxy=proxy, no_proxy=no_proxy)
    return dest, ver


# ----------------------------------------------------------------------
# 2. Java Properties Parser & Incremental Merging
# ----------------------------------------------------------------------

def decode_java_unicode(text: str) -> str:
    """Decode Java \\uXXXX escape sequences without corrupting UTF-8 characters."""
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)


def parse_properties(text: str) -> Dict[str, str]:
    """Parse Java .properties content into key-value pairs, handling line continuations."""
    props = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        while line.endswith("\\") and i + 1 < len(lines):
            line = line[:-1] + lines[i + 1].lstrip()
            i += 1
        s = line.strip()
        if s and not s.startswith(("#", "!")):
            m = re.match(r"^([^\s:=]+)\s*[:=]?\s*(.*)$", line)
            if m:
                props[m.group(1).strip()] = decode_java_unicode(m.group(2))
        i += 1
    return props


def merge_properties(orig_text: str, overrides: Dict[str, str]) -> str:
    """
    Incrementally merge overrides into original properties text:
    - Replaces values in-place for existing keys, preserving surrounding layout & comments.
    - Appends any new keys to the end of the file.
    """
    remaining = dict(overrides)
    out_lines = []
    lines = orig_text.splitlines()
    i = 0
    while i < len(lines):
        full_line = lines[i]
        while full_line.endswith("\\") and i + 1 < len(lines):
            i += 1
            full_line = full_line[:-1] + lines[i].lstrip()
        s = full_line.strip()
        if not s or s.startswith(("#", "!")):
            out_lines.append(full_line)
            i += 1
            continue
        m = re.match(r"^([^\s:=]+)(\s*[:=]\s*)(.*)$", full_line)
        if m:
            k, sep = m.group(1).strip(), m.group(2)
            if k in remaining:
                out_lines.append(f"{k}{sep}{remaining.pop(k)}")
            else:
                out_lines.append(full_line)
        else:
            out_lines.append(full_line)
        i += 1

    if remaining:
        out_lines.append("")
        out_lines.append("# --- Rebased Custom Translations ---")
        for k, v in remaining.items():
            out_lines.append(f"{k}={v}")

    return "\n".join(out_lines) + "\n"


# ----------------------------------------------------------------------
# 3. META-INF/plugin.xml Modification & Version Relaxation
# ----------------------------------------------------------------------

def patch_plugin_xml(
    xml_text: str,
    name: str,
    plugin_id: Optional[str] = None,
    since_build: str = DEFAULT_SINCE_BUILD,
    until_build: str = DEFAULT_UNTIL_BUILD,
) -> Tuple[str, str]:
    """
    Patch plugin.xml:
    1. Relax <idea-version> bounds (since-build & until-build) to prevent incompatibility errors.
    2. Update plugin display name in <name>.
    3. Update plugin ID in <id> (if specified).
    4. Append '-rebased' suffix to the plugin version.
    5. Prepend Rebased patch note into <description>.
    Returns: (modified_xml_content, original_version_string)
    """
    ver_match = re.search(r"<version>([^<]+)</version>", xml_text)
    raw_ver = ver_match.group(1).replace("-rebased", "").strip() if ver_match else "unknown"

    content = xml_text

    # 1. Relax <idea-version> build range
    if re.search(r"<idea-version\b[^>]*>", content):
        def _replace_tag(m: re.Match) -> str:
            tag = m.group(0)
            tag = re.sub(r'until-build="[^"]*"', f'until-build="{until_build}"', tag) if 'until-build=' in tag else tag.rstrip("/>").rstrip(">") + f' until-build="{until_build}"/>'
            tag = re.sub(r'since-build="[^"]*"', f'since-build="{since_build}"', tag) if 'since-build=' in tag else tag.rstrip("/>").rstrip(">") + f' since-build="{since_build}"/>'
            return tag
        content = re.sub(r"<idea-version\b[^>]*\/?>", _replace_tag, content, count=1)
    else:
        content = re.sub(r"(<idea-plugin[^>]*>\n?)", r"\1" + f'  <idea-version since-build="{since_build}" until-build="{until_build}"/>\n', content, count=1)

    # 2. Update <name>
    if "<name>" in content:
        content = re.sub(r"<name>.*?</name>", f"<name>{name}</name>", content, count=1, flags=re.DOTALL)
    else:
        content = re.sub(r"(<idea-plugin[^>]*>\n?)", r"\1" + f"  <name>{name}</name>\n", content, count=1)

    # 3. Update <id> (if provided)
    if plugin_id:
        if "<id>" in content:
            content = re.sub(r"<id>.*?</id>", f"<id>{plugin_id}</id>", content, count=1)
        else:
            content = re.sub(r"(<idea-plugin[^>]*>\n?)", r"\1" + f"  <id>{plugin_id}</id>\n", content, count=1)

    # 4. Append version suffix
    def _add_suffix(m: re.Match) -> str:
        v = m.group(1)
        return f"<version>{v}-rebased</version>" if not v.endswith("-rebased") else m.group(0)
    content = re.sub(r"<version>([^<]+)</version>", _add_suffix, content, count=1)

    # 5. Inject Rebased note in <description>
    desc_note = f"<p><b>[Rebased Patch]</b> Compatible with build range ({since_build} ~ {until_build}), optimized for Rebased Git Client.</p><br>"
    if "<description><![CDATA[" in content:
        content = content.replace("<description><![CDATA[", "<description><![CDATA[" + desc_note, 1)
    elif "<description>" in content:
        content = content.replace("<description>", "<description>" + desc_note, 1)

    return content, raw_ver


# ----------------------------------------------------------------------
# 4. Packaging & Archive Generation Workflow
# ----------------------------------------------------------------------

def apply_platform_compatibility_hotfixes(unpacked_dir: Path) -> int:
    """
    Auto-patch known upstream language pack formatting issues when running on newer IDE platforms.

    Background:
      Newer IntelliJ platform versions (2024.3+) introduce TooltipMouseAdapter parsing on
      untrusted project trust checkboxes that expects <html> and <b> tags around '{0}' to highlight the
      path. Older official language packs (e.g. 242) lack these tags in translated strings,
      causing StringIndexOutOfBoundsException on dialog rendering.
    """
    fixed_count = 0
    for root, _, files in os.walk(unpacked_dir):
        for f in files:
            if f.endswith("Bundle.properties"):
                p_file = Path(root) / f
                try:
                    content = p_file.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue

                def _ensure_html_and_b_tags(m: re.Match) -> str:
                    nonlocal fixed_count
                    k = m.group(1)
                    sep = m.group(2)
                    v = m.group(3)
                    
                    new_v = v
                    # Wrap {0} or ''{0}'' with <b> tags if not already wrapped
                    if "<b>" not in new_v:
                        if "''{0}''" in new_v:
                            new_v = new_v.replace("''{0}''", "<b>''{0}''</b>")
                        elif "{0}" in new_v:
                            new_v = new_v.replace("{0}", "<b>''{0}''</b>")
                    
                    # Prepend <html> if missing
                    if not new_v.startswith("<html>"):
                        new_v = "<html>" + new_v

                    if new_v != v:
                        fixed_count += 1
                        return f"{k}{sep}{new_v}"
                    return m.group(0)

                new_content = re.sub(
                    r"^(untrusted\.project\.(?:warning|windows\.defender)\.trust\.location\.checkbox)(\s*[:=]\s*)(.*)$",
                    _ensure_html_and_b_tags,
                    content,
                    flags=re.MULTILINE,
                )
                if new_content != content:
                    p_file.write_text(new_content, encoding="utf-8")
    return fixed_count


def build_single_pack(
    lang_code: str,
    cfg: dict,
    version: Optional[str] = None,
    output_dir: Path = Path("dist"),
    proxy: Optional[str] = None,
    no_proxy: bool = False,
    keep_temp: bool = False,
) -> Path:
    """
    Build an official native language pack:
    Unpacks archive, patches plugin.xml, applies local overrides, and repacks into a distribution ZIP.
    """
    display_name = cfg["display_name"]
    prefix = cfg["output_prefix"]

    input_pkg, ver = resolve_package(cfg, lang_code, specified_version=version, proxy=proxy, no_proxy=no_proxy)
    out_zip = output_dir / f"{prefix}-{ver}.zip"

    temp_dir = Path(tempfile.mkdtemp(prefix=f"rebased_{lang_code}_"))
    try:
        extracted = temp_dir / "extracted"
        with zipfile.ZipFile(input_pkg, "r") as z:
            z.extractall(extracted)

        # Locate core JAR containing META-INF/plugin.xml
        core_jar = None
        for j in extracted.rglob("*.jar"):
            try:
                with zipfile.ZipFile(j, "r") as zf:
                    if "META-INF/plugin.xml" in zf.namelist():
                        core_jar = j
                        break
            except zipfile.BadZipFile:
                continue

        if not core_jar:
            raise RuntimeError(f"Could not find core jar with META-INF/plugin.xml in {input_pkg.name}")

        unpacked = temp_dir / "unpacked"
        with zipfile.ZipFile(core_jar, "r") as zf:
            zf.extractall(unpacked)

        # Modify plugin.xml
        xml_file = unpacked / "META-INF" / "plugin.xml"
        patched_xml, raw_ver = patch_plugin_xml(
            xml_file.read_text(encoding="utf-8"),
            name=display_name,
        )
        xml_file.write_text(patched_xml, encoding="utf-8")

        # Automatically hotfix cross-version compatibility issues in unpacked bundles
        apply_platform_compatibility_hotfixes(unpacked)

        # Apply overrides if available
        ov_dir = Path(cfg.get("overrides_dir", ""))
        if ov_dir.exists() and ov_dir.is_dir():
            for root, _, files in os.walk(ov_dir):
                for f in files:
                    src = Path(root) / f
                    rel = src.relative_to(ov_dir)
                    dst = unpacked / rel
                    if f.lower().endswith(".properties"):
                        props = parse_properties(src.read_text(encoding="utf-8", errors="replace"))
                        if dst.exists():
                            dst.write_text(merge_properties(dst.read_text(encoding="utf-8", errors="replace"), props), encoding="utf-8")
                        else:
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            dst.write_text("\n".join(f"{k}={v}" for k, v in props.items()) + "\n", encoding="utf-8")
                    else:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)

        # Re-pack core JAR
        new_jar = temp_dir / "core.jar"
        with zipfile.ZipFile(new_jar, "w", compression=zipfile.ZIP_DEFLATED) as jz:
            for root, _, files in os.walk(unpacked):
                for f in files:
                    fp = Path(root) / f
                    jz.write(fp, fp.relative_to(unpacked).as_posix())

        # Assemble final distribution ZIP
        out_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as oz:
            oz.write(new_jar, f"{prefix}/lib/{prefix}.jar")
            top_dirs = [p for p in extracted.iterdir() if p.is_dir()]
            if top_dirs:
                source_root = top_dirs[0]
                for item in source_root.iterdir():
                    if item.name == "lib":
                        continue
                    if item.is_dir():
                        for root, _, files in os.walk(item):
                            for f in files:
                                fp = Path(root) / f
                                oz.write(fp, f"{prefix}/{fp.relative_to(source_root).as_posix()}")
                    elif item.is_file():
                        oz.write(item, f"{prefix}/{item.name}")

        return out_zip
    finally:
        if not keep_temp:
            shutil.rmtree(temp_dir, ignore_errors=True)


def build_custom_pack(
    input_file: Path,
    output_dir: Path = Path("dist"),
    plugin_name: Optional[str] = None,
    overrides_dir: Optional[Path] = None,
    keep_temp: bool = False,
) -> Path:
    """
    Process any third-party or community language pack file without pre-configuration.
    Auto-detects plugin metadata from plugin.xml, relaxes build bounds, and repacks for Rebased.
    """
    if not input_file.exists():
        raise FileNotFoundError(f"Specified input file does not exist: {input_file}")

    print(f"[*] Analyzing local package file: {input_file.name}")
    temp_dir = Path(tempfile.mkdtemp(prefix="rebased_custom_"))
    try:
        extracted = temp_dir / "extracted"
        if input_file.suffix.lower() == ".zip":
            with zipfile.ZipFile(input_file, "r") as z:
                z.extractall(extracted)
        elif input_file.suffix.lower() == ".jar":
            lib_dir = extracted / "pkg" / "lib"
            lib_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(input_file, lib_dir / input_file.name)
        else:
            raise ValueError(f"Unsupported package file format: {input_file.suffix}")

        core_jar = None
        for j in extracted.rglob("*.jar"):
            try:
                with zipfile.ZipFile(j, "r") as zf:
                    if "META-INF/plugin.xml" in zf.namelist():
                        core_jar = j
                        break
            except zipfile.BadZipFile:
                continue

        if not core_jar:
            raise RuntimeError(f"Could not find core jar with META-INF/plugin.xml in {input_file.name}")

        unpacked = temp_dir / "unpacked"
        with zipfile.ZipFile(core_jar, "r") as zf:
            zf.extractall(unpacked)

        xml_file = unpacked / "META-INF" / "plugin.xml"
        xml_text = xml_file.read_text(encoding="utf-8")

        name_match = re.search(r"<name>([^<]+)</name>", xml_text)
        orig_name = name_match.group(1).strip() if name_match else "Community Pack"
        new_name = plugin_name or (orig_name if "Rebased" in orig_name else f"Rebased {orig_name}")

        patched_xml, raw_ver = patch_plugin_xml(xml_text, name=new_name)
        xml_file.write_text(patched_xml, encoding="utf-8")
        print(f"    -> Detected plugin name: '{orig_name}' (Version: {raw_ver})")
        print(f"    -> Adjusted plugin name: '{new_name}'")
        print(f"    -> Relaxed build range: '{DEFAULT_SINCE_BUILD}' ~ '{DEFAULT_UNTIL_BUILD}'")

        # Automatically hotfix cross-version compatibility issues in unpacked bundles
        apply_platform_compatibility_hotfixes(unpacked)

        if overrides_dir and overrides_dir.exists():
            print(f"[*] Applying translation overrides from: {overrides_dir}")
            for root, _, files in os.walk(overrides_dir):
                for f in files:
                    src = Path(root) / f
                    rel = src.relative_to(overrides_dir)
                    dst = unpacked / rel
                    if f.lower().endswith(".properties"):
                        props = parse_properties(src.read_text(encoding="utf-8", errors="replace"))
                        if dst.exists():
                            dst.write_text(merge_properties(dst.read_text(encoding="utf-8", errors="replace"), props), encoding="utf-8")
                        else:
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            dst.write_text("\n".join(f"{k}={v}" for k, v in props.items()) + "\n", encoding="utf-8")
                    else:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)

        new_jar = temp_dir / "core.jar"
        with zipfile.ZipFile(new_jar, "w", compression=zipfile.ZIP_DEFLATED) as jz:
            for root, _, files in os.walk(unpacked):
                for f in files:
                    fp = Path(root) / f
                    jz.write(fp, fp.relative_to(unpacked).as_posix())

        stem = re.sub(r"[-_.]\d+.*$", "", input_file.stem)
        prefix = f"rebased-{stem}" if not stem.startswith("rebased") else stem
        out_zip = output_dir / f"{prefix}-{raw_ver}.zip"
        output_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as oz:
            oz.write(new_jar, f"{prefix}/lib/{prefix}.jar")
            top_dirs = [p for p in extracted.iterdir() if p.is_dir()]
            if top_dirs:
                source_root = top_dirs[0]
                for item in source_root.iterdir():
                    if item.name == "lib":
                        continue
                    if item.is_dir():
                        for root, _, files in os.walk(item):
                            for f in files:
                                fp = Path(root) / f
                                oz.write(fp, f"{prefix}/{fp.relative_to(source_root).as_posix()}")
                    elif item.is_file():
                        oz.write(item, f"{prefix}/{item.name}")

        return out_zip
    finally:
        if not keep_temp:
            shutil.rmtree(temp_dir, ignore_errors=True)


def calc_sha256(file_path: Path) -> str:
    """Calculate SHA256 checksum for a file."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()
