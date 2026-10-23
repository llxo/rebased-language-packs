#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rebased 中文汉化插件自动化构建脚本
==================================

功能：
1. 自动从 JetBrains Marketplace 下载官方 Chinese (Simplified) Language Pack 插件包（支持指定版本或默认最新版本，支持本地已有文件）；
2. 解压插件并修改 META-INF/plugin.xml：
   - 放宽 <idea-version> 兼容范围（如 until-build="999.*"）；
   - 将插件名称修改为 "Rebased Chinese Language Pack"；
3. 支持从 overrides/ 目录读取自定义翻译 properties 文件，进行键值对合并覆盖（保留原版翻译，增量替换/追加 Rebased 专属文案）；
4. 重新打包生成可直接在 Rebased 中通过 "Install Plugin from Disk..." 安装的 zip 插件包。
"""

import argparse
import io
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

# 官方中文语言包在 JetBrains Marketplace 上的插件信息
JETBRAINS_MARKETPLACE_PLUGIN_ID = 13710
JETBRAINS_MARKETPLACE_XML_ID = "com.intellij.zh"
DEFAULT_UNTIL_BUILD = "999.*"
DEFAULT_PLUGIN_NAME = "Rebased Chinese Language Pack"
DEFAULT_OUTPUT_DIR = "dist"
DEFAULT_OVERRIDES_DIR = "overrides"


# ----------------------------------------------------------------------
# 1. JetBrains Marketplace API & 弹性网络请求与下载
# ----------------------------------------------------------------------

def open_url_resilient(
    url: str,
    timeout: int = 25,
    custom_proxy: Optional[str] = None,
    no_proxy: bool = False,
    retries: int = 2,
):
    """
    弹性 HTTP 请求器：
    - 优先尝试系统/环境变量代理；
    - 若遇代理不可用、握手超时或 EOF，自动回退至直连重试；
    - 支持手动指定代理或强制直连 (--no-proxy)。
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RebasedChinesePackBuilder/1.0"}
    last_exc = None

    handlers_to_try = []
    if no_proxy:
        handlers_to_try.append(("强制直连", urllib.request.ProxyHandler({})))
    elif custom_proxy:
        handlers_to_try.append(("自定义代理", urllib.request.ProxyHandler({"http": custom_proxy, "https": custom_proxy})))
        handlers_to_try.append(("回退直连", urllib.request.ProxyHandler({})))
    else:
        # 默认：先尝试系统环境变量代理，失败则回退直连
        handlers_to_try.append(("环境默认", None))
        handlers_to_try.append(("直连(绕过代理)", urllib.request.ProxyHandler({})))

    for mode_name, handler in handlers_to_try:
        for attempt in range(retries + 1):
            try:
                opener = urllib.request.build_opener(handler) if handler is not None else urllib.request.build_opener()
                req = urllib.request.Request(url, headers=headers)
                return opener.open(req, timeout=timeout)
            except Exception as e:
                last_exc = e
                # 若是 HTTP 404 等明确的服务端错误，不需要回退重试
                if isinstance(e, urllib.error.HTTPError) and e.code in (404, 403, 400):
                    raise
                continue

    raise RuntimeError(f"请求网络资源失败: {url} (原因: {last_exc})")


def fetch_marketplace_updates(
    plugin_id: int = JETBRAINS_MARKETPLACE_PLUGIN_ID,
    size: int = 200,
    proxy: Optional[str] = None,
    no_proxy: bool = False,
) -> List[dict]:
    """获取指定插件在 Marketplace 上的更新版本列表"""
    url = f"https://plugins.jetbrains.com/api/plugins/{plugin_id}/updates?size={size}"
    try:
        with open_url_resilient(url, timeout=15, custom_proxy=proxy, no_proxy=no_proxy) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[警告] 从 Marketplace API 获取版本列表失败: {e}", file=sys.stderr)
        return []


def parse_version_tuple(v_str: str) -> Tuple[int, ...]:
    """将版本号如 '242.152' 转为可比较的元组 (242, 152)"""
    nums = re.findall(r"\d+", str(v_str))
    return tuple(int(n) for n in nums) if nums else (0,)


def get_latest_version_update(updates: List[dict]) -> Optional[dict]:
    """从更新列表中挑选版本号最高/最新的 update"""
    if not updates:
        return None
    valid = [u for u in updates if u.get("file") and u.get("version")]
    if not valid:
        return None
    # 优先按版本号 (major, minor) 倒序排列，若相同再按 cdate / id
    valid.sort(
        key=lambda x: (
            parse_version_tuple(x.get("version", "")),
            int(x.get("cdate", 0) or 0),
            int(x.get("id", 0) or 0),
        ),
        reverse=True,
    )
    return valid[0]


def find_update_by_version(updates: List[dict], target_version: str) -> Optional[dict]:
    """根据版本号精确或模糊匹配 update"""
    for u in updates:
        ver = str(u.get("version", "")).strip()
        if ver == target_version:
            return u
    for u in updates:
        ver = str(u.get("version", "")).strip()
        if ver.startswith(target_version):
            return u
    return None


def download_file(
    url: str,
    dest_path: Path,
    proxy: Optional[str] = None,
    no_proxy: bool = False,
) -> Path:
    """带进度显示的弹性 HTTP 下载器"""
    print(f"[*] 正在下载: {url}")
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    with open_url_resilient(url, timeout=60, custom_proxy=proxy, no_proxy=no_proxy) as resp, open(dest_path, "wb") as out_file:
        total_size = resp.headers.get("Content-Length")
        total_size = int(total_size) if total_size and total_size.isdigit() else None
        downloaded = 0
        chunk_size = 64 * 1024

        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            out_file.write(chunk)
            downloaded += len(chunk)
            if total_size:
                percent = (downloaded / total_size) * 100
                mb_down = downloaded / (1024 * 1024)
                mb_total = total_size / (1024 * 1024)
                sys.stdout.write(f"\r    -> 进度: {percent:.1f}% ({mb_down:.2f}/{mb_total:.2f} MB)")
            else:
                sys.stdout.write(f"\r    -> 已下载: {downloaded / 1024:.1f} KB")
            sys.stdout.flush()
    print("\n[+] 下载完成!")
    return dest_path


def resolve_plugin_package(
    specified_version: Optional[str] = None,
    input_file: Optional[str] = None,
    cache_dir: Optional[Path] = None,
    proxy: Optional[str] = None,
    no_proxy: bool = False,
) -> Tuple[Path, str]:
    """
    解析并获取官方插件包文件（返回文件路径和检测到的版本号）
    - 如果提供了 input_file，直接验证并使用；
    - 否则从 Marketplace 下载（根据 specified_version 或自动选最新）。
    """
    if input_file:
        file_path = Path(input_file).resolve()
        if not file_path.is_file():
            raise FileNotFoundError(f"指定的本地输入文件不存在: {file_path}")
        # 从文件名尝试提取版本号，如 zh.242.152.zip
        match = re.search(r"(\d+\.\d+)", file_path.name)
        ver = match.group(1) if match else "custom"
        print(f"[+] 使用本地插件包: {file_path} (识别版本: {ver})")
        return file_path, ver

    if cache_dir is None:
        cache_dir = Path("cache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    print("[*] 正在查询 JetBrains Marketplace 获取官方中文语言包版本...")
    updates = fetch_marketplace_updates(proxy=proxy, no_proxy=no_proxy)
    target_update = None

    if specified_version:
        target_update = find_update_by_version(updates, specified_version)
        if not target_update:
            # 如果从 updates API 没匹配到，构造默认下载地址
            print(f"[!] API 列表中未找到版本 '{specified_version}'，尝试通过官方下载入口直连下载...")
            direct_url = (
                f"https://plugins.jetbrains.com/plugin/download"
                f"?pluginId={JETBRAINS_MARKETPLACE_XML_ID}&version={specified_version}"
            )
            dest = cache_dir / f"zh.{specified_version}.zip"
            if not dest.exists():
                try:
                    download_file(direct_url, dest, proxy=proxy, no_proxy=no_proxy)
                except urllib.error.HTTPError as e:
                    raise RuntimeError(f"直连下载失败 (HTTP {e.code}): 无法下载版本 {specified_version}") from e
            return dest, specified_version
    else:
        target_update = get_latest_version_update(updates)
        if not target_update:
            # 备用默认版本（242.152 经过验证稳定可靠）
            default_fallback = "242.152"
            print(f"[!] 未能从 API 获取到版本信息，将使用默认推荐版本 {default_fallback}")
            dest = cache_dir / f"zh.{default_fallback}.zip"
            if not dest.exists():
                url = f"https://plugins.jetbrains.com/files/13710/557305/zh.{default_fallback}.zip"
                download_file(url, dest, proxy=proxy, no_proxy=no_proxy)
            return dest, default_fallback

    ver = str(target_update.get("version", "unknown"))
    file_rel = target_update.get("file", "")
    update_id = target_update.get("id")

    filename = Path(file_rel).name if file_rel else f"zh.{ver}.zip"
    dest = cache_dir / filename

    if dest.exists() and dest.stat().st_size > 0:
        print(f"[+] 找到已缓存的安装包: {dest} (版本: {ver})")
        return dest, ver

    # 下载 URL
    if file_rel:
        download_url = f"https://plugins.jetbrains.com/files/{file_rel}"
    else:
        download_url = f"https://plugins.jetbrains.com/plugin/download?updateId={update_id}"

    download_file(download_url, dest, proxy=proxy, no_proxy=no_proxy)
    return dest, ver


# ----------------------------------------------------------------------
# 2. Java Properties 解析与智能合并
# ----------------------------------------------------------------------

def decode_java_unicode(text: str) -> str:
    """仅解码 Java 属性中的 \\uXXXX 转义序列，不破坏已有 UTF-8 中文"""
    return re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda m: chr(int(m.group(1), 16)),
        text,
    )


def parse_properties_content(text: str) -> Tuple[Dict[str, str], List[str]]:
    """
    解析 Java .properties 文本内容。
    返回:
      - props: 键值字典 {key: value}
      - raw_lines: 保留原始行（包含多行合并展开后映射）
    """
    props: Dict[str, str] = {}
    lines = text.splitlines()
    merged_lines: List[str] = []

    # 1. 处理换行符转义（行末反斜杠连接下一行）
    i = 0
    while i < len(lines):
        line = lines[i]
        while line.endswith("\\") and i + 1 < len(lines):
            line = line[:-1] + lines[i + 1].lstrip()
            i += 1
        merged_lines.append(line)
        i += 1

    # 2. 提取键值对
    for line in merged_lines:
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("!"):
            continue
        # 匹配键值分隔符 = 或 : 或 首个空白
        m = re.match(r"^([^\s:=]+)\s*[:=]?\s*(.*)$", line)
        if m:
            k = m.group(1).strip()
            v = m.group(2)
            # 仅转换 \uXXXX 字符，保证直接编写的中文字符串原样完好
            props[k] = decode_java_unicode(v)

    return props, merged_lines


def merge_properties(original_text: str, override_props: Dict[str, str]) -> str:
    """
    将 override_props 增量合并进 original_text 中：
    - 已存在的 key 在原位替换其 value，保留原有上下文；
    - 新增的 key 在文件末尾整齐追加；
    - 原有的注释、空行完整保留。
    """
    remaining_keys = dict(override_props)
    output_lines: List[str] = []
    lines = original_text.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i]
        # 处理被反斜杠拆分的行
        full_line = line
        while full_line.endswith("\\") and i + 1 < len(lines):
            i += 1
            full_line = full_line[:-1] + lines[i].lstrip()

        stripped = full_line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("!"):
            output_lines.append(full_line)
            i += 1
            continue

        m = re.match(r"^([^\s:=]+)(\s*[:=]\s*)(.*)$", full_line)
        if m:
            k = m.group(1).strip()
            sep = m.group(2)
            if k in remaining_keys:
                new_val = remaining_keys.pop(k)
                output_lines.append(f"{k}{sep}{new_val}")
            else:
                output_lines.append(full_line)
        else:
            output_lines.append(full_line)
        i += 1

    # 如果有新增的 key，追加到末尾
    if remaining_keys:
        output_lines.append("")
        output_lines.append("# --- Rebased Custom Translations (Added by pack script) ---")
        for k, v in remaining_keys.items():
            output_lines.append(f"{k}={v}")

    return "\n".join(output_lines) + "\n"


def load_override_file(file_path: Path) -> Dict[str, str]:
    """读取 overrides 目录下的 properties 文件并解析为键值对"""
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = file_path.read_text(encoding="gbk", errors="replace")
    props, _ = parse_properties_content(content)
    return props


# ----------------------------------------------------------------------
# 3. plugin.xml 修改逻辑
# ----------------------------------------------------------------------

def modify_plugin_xml(
    xml_content: str,
    new_name: str = DEFAULT_PLUGIN_NAME,
    until_build: str = DEFAULT_UNTIL_BUILD,
    since_build: Optional[str] = None,
    version_suffix: str = "-rebased",
) -> str:
    """
    精确修改 META-INF/plugin.xml：
    1. 放宽 <idea-version until-build="..."> 限制；
    2. 修改插件显示名称 <name>；
    3. 调整 <version> 标注（加上 -rebased 标识）；
    4. 在 <description> 中追加 Rebased 适配说明。
    """
    content = xml_content

    # 1. 修改/增加 <idea-version>
    if re.search(r"<idea-version\b[^>]*>", content):
        def _replace_idea_version(match: re.Match) -> str:
            tag = match.group(0)
            # 修改 until-build
            if re.search(r'until-build="[^"]*"', tag):
                tag = re.sub(r'until-build="[^"]*"', f'until-build="{until_build}"', tag)
            else:
                tag = tag.rstrip("/>").rstrip(">") + f' until-build="{until_build}"/>'
            # 如果指定了 since_build
            if since_build:
                if re.search(r'since-build="[^"]*"', tag):
                    tag = re.sub(r'since-build="[^"]*"', f'since-build="{since_build}"', tag)
                else:
                    tag = tag.rstrip("/>").rstrip(">") + f' since-build="{since_build}"/>'
            return tag

        content = re.sub(r"<idea-version\b[^>]*\/?>", _replace_idea_version, content, count=1)
    else:
        # 在 <idea-plugin> 下插入 <idea-version>
        ver_tag = f'  <idea-version since-build="{since_build or "200.0"}" until-build="{until_build}"/>\n'
        content = re.sub(r"(<idea-plugin[^>]*>\n?)", r"\1" + ver_tag, content, count=1)

    # 2. 修改 <name>
    if re.search(r"<name>.*?</name>", content, flags=re.DOTALL):
        content = re.sub(r"<name>.*?</name>", f"<name>{new_name}</name>", content, count=1, flags=re.DOTALL)
    else:
        content = re.sub(r"(<idea-plugin[^>]*>\n?)", r"\1" + f"  <name>{new_name}</name>\n", content, count=1)

    # 3. 版本号加上标识后缀（例如 242.152 -> 242.152-rebased）
    if version_suffix:
        def _replace_version(m: re.Match) -> str:
            v = m.group(1)
            if not v.endswith(version_suffix):
                return f"<version>{v}{version_suffix}</version>"
            return m.group(0)

        content = re.sub(r"<version>([^<]+)</version>", _replace_version, content, count=1)

    # 4. 在 description 中增加 Rebased 汉化说明
    rebased_note = (
        "<p><b>[Rebased 专用汉化补丁]</b> 放宽了 IDEA 构建号兼容限制（支持 until-build="
        f"{until_build}），并已自动合并针对 Rebased Git 客户端专属界面的中文翻译。</p><br>"
    )
    if "<description><![CDATA[" in content:
        content = content.replace("<description><![CDATA[", "<description><![CDATA[" + rebased_note, 1)
    elif "<description>" in content:
        content = content.replace("<description>", "<description>" + rebased_note, 1)

    return content


# ----------------------------------------------------------------------
# 4. 核心打包处理流程
# ----------------------------------------------------------------------

def process_and_repack(
    input_pkg: Path,
    output_zip: Path,
    overrides_dir: Optional[Path] = None,
    plugin_name: str = DEFAULT_PLUGIN_NAME,
    until_build: str = DEFAULT_UNTIL_BUILD,
    since_build: Optional[str] = None,
    keep_temp: bool = False,
) -> Path:
    """
    主处理流程：解压、修改 plugin.xml、合并 overrides properties、重新打包生成 zip
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="rebased_pack_"))
    print(f"[*] 工作临时目录: {temp_dir}")

    try:
        # 第一阶段：判断并解压输入文件
        extracted_pkg_dir = temp_dir / "extracted_pkg"
        extracted_pkg_dir.mkdir(parents=True, exist_ok=True)

        if input_pkg.suffix.lower() == ".zip":
            print(f"[*] 解压插件 ZIP 包: {input_pkg.name}")
            with zipfile.ZipFile(input_pkg, "r") as z:
                z.extractall(extracted_pkg_dir)
        elif input_pkg.suffix.lower() == ".jar":
            # 如果输入直接是 jar，将其放入 lib 目录结构
            print(f"[*] 检测到输入为单独 JAR 文件: {input_pkg.name}")
            lib_dir = extracted_pkg_dir / "rebased-chinese-pack" / "lib"
            lib_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(input_pkg, lib_dir / input_pkg.name)
        else:
            raise ValueError(f"不支持的插件包文件格式: {input_pkg.suffix}")

        # 第二阶段：定位包含 META-INF/plugin.xml 的核心 jar
        target_jar: Optional[Path] = None
        for jar_path in extracted_pkg_dir.rglob("*.jar"):
            try:
                with zipfile.ZipFile(jar_path, "r") as j:
                    if "META-INF/plugin.xml" in j.namelist():
                        target_jar = jar_path
                        break
            except zipfile.BadZipFile:
                continue

        if not target_jar:
            raise RuntimeError("在解包后的插件中未找到包含 META-INF/plugin.xml 的核心 jar 文件！")

        print(f"[+] 找到核心语言包 JAR: {target_jar.relative_to(extracted_pkg_dir)}")

        # 解压 target_jar 到临时目录进行修改和合并
        jar_unpacked_dir = temp_dir / "jar_unpacked"
        jar_unpacked_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target_jar, "r") as j:
            j.extractall(jar_unpacked_dir)

        # 第三阶段：修改 META-INF/plugin.xml
        plugin_xml_path = jar_unpacked_dir / "META-INF" / "plugin.xml"
        if not plugin_xml_path.exists():
            raise FileNotFoundError("未找到 META-INF/plugin.xml 文件！")

        print("[*] 正在修改 META-INF/plugin.xml ...")
        xml_text = plugin_xml_path.read_text(encoding="utf-8")
        modified_xml = modify_plugin_xml(
            xml_text,
            new_name=plugin_name,
            until_build=until_build,
            since_build=since_build,
        )
        plugin_xml_path.write_text(modified_xml, encoding="utf-8")
        print(f"    -> 插件名称已设为: '{plugin_name}'")
        print(f"    -> until-build 已放宽为: '{until_build}'")

        # 第四阶段：合并 overrides 目录下的自定义翻译
        merged_count = 0
        added_count = 0
        if overrides_dir and overrides_dir.exists() and overrides_dir.is_dir():
            print(f"[*] 扫描自定义覆盖目录: {overrides_dir}")
            for override_file in overrides_dir.rglob("*"):
                if not override_file.is_file():
                    continue

                rel_path = override_file.relative_to(overrides_dir)
                dest_file = jar_unpacked_dir / rel_path

                if override_file.suffix.lower() == ".properties":
                    override_props = load_override_file(override_file)
                    if not override_props:
                        continue

                    if dest_file.exists():
                        # 原位合并覆盖
                        orig_text = dest_file.read_text(encoding="utf-8", errors="replace")
                        merged_text = merge_properties(orig_text, override_props)
                        dest_file.write_text(merged_text, encoding="utf-8")
                        merged_count += len(override_props)
                        print(f"    [合并覆盖] {rel_path} ({len(override_props)} 项配置)")
                    else:
                        # 新建文件
                        dest_file.parent.mkdir(parents=True, exist_ok=True)
                        dest_file.write_text(override_file.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
                        added_count += len(override_props)
                        print(f"    [新增文件] {rel_path} ({len(override_props)} 项配置)")
                else:
                    # 非 properties 资源文件（图标、说明等），直接复制覆盖
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(override_file, dest_file)
                    print(f"    [覆盖资源] {rel_path}")

            print(f"[+] 自定义文案处理完成: 共覆盖/合并 {merged_count} 项，新增 {added_count} 项")
        else:
            print("[-] 未指定 overrides 目录或目录不存在，跳过文案覆盖合并。")

        # 第五阶段：重新压缩核心 JAR
        print("[*] 重新组装核心语言包 JAR ...")
        new_jar_path = temp_dir / "rebased-chinese-pack.jar"
        with zipfile.ZipFile(new_jar_path, "w", compression=zipfile.ZIP_DEFLATED) as new_jar:
            for root, _, files in os.walk(jar_unpacked_dir):
                for f in files:
                    full_p = Path(root) / f
                    arcname = full_p.relative_to(jar_unpacked_dir).as_posix()
                    new_jar.write(full_p, arcname)

        # 第六阶段：按 JetBrains 规范打包最终的 ZIP
        # 标准结构：<plugin-folder>/lib/<plugin-jar>.jar
        print("[*] 正在构建最终分发 ZIP 包 ...")
        package_root_name = "rebased-chinese-pack"
        output_zip.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as out_zip:
            # 写入主 jar
            out_zip.write(new_jar_path, f"{package_root_name}/lib/{package_root_name}.jar")

            # 将原包内的其他附加目录（例如 dotnet/）保留进新包中（如果存在）
            # 找到原包的顶级文件夹
            top_level_dirs = [p for p in extracted_pkg_dir.iterdir() if p.is_dir()]
            if top_level_dirs:
                source_root = top_level_dirs[0]
                for item in source_root.iterdir():
                    if item.name == "lib":
                        continue
                    if item.is_dir():
                        for root, _, files in os.walk(item):
                            for f in files:
                                full_p = Path(root) / f
                                sub_arc = full_p.relative_to(source_root).as_posix()
                                out_zip.write(full_p, f"{package_root_name}/{sub_arc}")
                    elif item.is_file():
                        out_zip.write(item, f"{package_root_name}/{item.name}")

        size_mb = output_zip.stat().st_size / (1024 * 1024)
        print(f"\n=======================================================")
        print(f"[√] 汉化包制作成功！")
        print(f"    产物路径: {output_zip.resolve()}")
        print(f"    文件大小: {size_mb:.2f} MB")
        print(f"=======================================================")
        print(f"【安装指南】")
        print(f"1. 打开 Rebased；")
        print(f"2. 打开菜单 Settings (设置) -> Plugins (插件)；")
        print(f"3. 点击齿轮图标下拉菜单 -> 选择 'Install Plugin from Disk...' (从磁盘安装插件)；")
        print(f"4. 选择生成的文件: {output_zip.name}；")
        print(f"5. 重启 Rebased 即可享受完整中文界面！")
        print(f"=======================================================\n")
        return output_zip

    finally:
        if not keep_temp:
            shutil.rmtree(temp_dir, ignore_errors=True)
        else:
            print(f"[i] 临时构建文件已保留在: {temp_dir}")


# ----------------------------------------------------------------------
# 5. CLI 入口
# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Rebased 中文汉化插件自动化制作与打包工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 1. 自动下载官方最新语言包并打包:
  python build_rebased_chinese_pack.py

  # 2. 指定下载 242.152 版本:
  python build_rebased_chinese_pack.py -v 242.152

  # 3. 列出 Marketplace 上官方支持的所有可用版本:
  python build_rebased_chinese_pack.py --list-versions

  # 4. 使用本地已下载的官方 zip 或 jar 包:
  python build_rebased_chinese_pack.py -i ./zh.242.152.zip

  # 5. 指定自定义文案目录 overrides 并自定义输出路径:
  python build_rebased_chinese_pack.py -d ./my_overrides -o ./dist/my-rebased-zh.zip
        """,
    )

    parser.add_argument(
        "-v", "--version",
        dest="version",
        help="指定要下载的官方语言包版本号（如 242.152、241.271）。若不指定则自动选择最新版本",
    )
    parser.add_argument(
        "-i", "--input-file",
        dest="input_file",
        help="使用本地已有的语言包文件 (.zip 或 .jar)，跳过网络下载",
    )
    parser.add_argument(
        "-o", "--output",
        dest="output",
        help="打包生成的最终插件 zip 文件输出路径（默认：dist/rebased-chinese-pack-<version>.zip）",
    )
    parser.add_argument(
        "-d", "--overrides-dir",
        dest="overrides_dir",
        default=DEFAULT_OVERRIDES_DIR,
        help=f"存放自定义翻译 .properties 文件的目录（默认: '{DEFAULT_OVERRIDES_DIR}'）",
    )
    parser.add_argument(
        "--plugin-name",
        dest="plugin_name",
        default=DEFAULT_PLUGIN_NAME,
        help=f"修改后的插件显示名称（默认: '{DEFAULT_PLUGIN_NAME}'）",
    )
    parser.add_argument(
        "--until-build",
        dest="until_build",
        default=DEFAULT_UNTIL_BUILD,
        help=f"放宽兼容性的 until-build 范围（默认: '{DEFAULT_UNTIL_BUILD}'）",
    )
    parser.add_argument(
        "--since-build",
        dest="since_build",
        help="修改兼容性的 since-build 起始构建号（可选，如 200.0）",
    )
    parser.add_argument(
        "--keep-temp",
        dest="keep_temp",
        action="store_true",
        help="保留构建过程中的解压临时目录（方便调试排查）",
    )
    parser.add_argument(
        "--list-versions",
        dest="list_versions",
        action="store_true",
        help="仅列出 JetBrains Marketplace 上的可用版本列表并退出",
    )
    parser.add_argument(
        "--proxy",
        dest="proxy",
        help="指定 HTTP/HTTPS 代理服务器地址（如 http://127.0.0.1:7890）",
    )
    parser.add_argument(
        "--no-proxy",
        dest="no_proxy",
        action="store_true",
        help="禁用代理，强制直接连接",
    )

    args = parser.parse_args()

    if args.list_versions:
        print("[*] 正在获取 Marketplace 上官方中文语言包的全部可用版本...")
        updates = fetch_marketplace_updates(size=100, proxy=args.proxy, no_proxy=args.no_proxy)
        if not updates:
            print("[-] 未能获取到版本列表。")
            sys.exit(1)
        print("\n【官方可用版本列表】")
        print(f"{'版本号':<12} | {'兼容范围':<20} | {'Update ID':<10} | {'发布文件名'}")
        print("-" * 65)
        for u in updates:
            ver = u.get("version", "-")
            range_str = f"{u.get('since', '')} ~ {u.get('until', '')}"
            uid = u.get("id", "-")
            fn = Path(u.get("file", "")).name
            print(f"{ver:<12} | {range_str:<20} | {uid:<10} | {fn}")
        sys.exit(0)

    try:
        # 1. 获取输入包
        input_pkg, ver = resolve_plugin_package(
            specified_version=args.version,
            input_file=args.input_file,
            proxy=args.proxy,
            no_proxy=args.no_proxy,
        )

        # 2. 确定输出路径
        if args.output:
            out_path = Path(args.output).resolve()
        else:
            out_path = Path(DEFAULT_OUTPUT_DIR) / f"rebased-chinese-pack-{ver}.zip"

        overrides_path = Path(args.overrides_dir) if args.overrides_dir else None

        # 3. 处理并重新打包
        process_and_repack(
            input_pkg=input_pkg,
            output_zip=out_path,
            overrides_dir=overrides_path,
            plugin_name=args.plugin_name,
            until_build=args.until_build,
            since_build=args.since_build,
            keep_temp=args.keep_temp,
        )

    except Exception as e:
        print(f"\n[错误] 构建失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
