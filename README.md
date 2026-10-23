# Rebased Chinese Language Pack 自动化汉化插件构建工具

专为 **[Rebased](https://github.com/DetachHead/rebased)**（基于 IntelliJ Platform 的现代 Git 客户端）打造的中文汉化插件自动化制作与打包工具。

---

## 📖 背景与原理

Rebased 是基于 IntelliJ 源码构建的独立 Git 客户端。由于其特殊的版本分支与构建号（如 `262.*` / `263.*`），直接安装 JetBrains Marketplace 官方的中文语言包会因构建号检查限制（`<idea-version until-build="...">`）而被拦截并提示不兼容。此外，Rebased 对大量界面文案进行了定制（去除了 "IDE" 等字样，增加了 Rebased 专属设置项）。

本项目脚本自动完成以下工作：
1. **自动下载官方中文语言包**：直接从 JetBrains Marketplace 获取官方 `Chinese (Simplified) Language Pack` 插件包（支持指定版本，或自动匹配最新版本）；
2. **解锁版本兼容范围**：修改 `META-INF/plugin.xml`，将 `<idea-version until-build="...">` 放宽为 `999.*`，确保在 Rebased 的任何当前及未来版本中均能正常载入；
3. **更名为专用语言包**：将插件名替换为 `Rebased Chinese Language Pack`，并在描述中附带说明；
4. **智能键值对合并覆盖（Overrides）**：扫描 `overrides/` 目录下的 `.properties` 文件，**原位覆盖或追加** Rebased 专属文案，原版中已有的数十万字翻译完整保留，实现真正的无缝增量汉化；
5. **打包为即装即用 ZIP**：重新封装为符合 IntelliJ 平台规范的插件 Zip 包，可直接通过 `Install Plugin from Disk...` 一键安装。

---

## 🚀 快速上手

### 方式一：直接下载现成插件包（推荐普通用户）

前往本项目仓库的 **[Releases 页面](../../releases)**：
1. 下载最新的 `rebased-chinese-pack-xxx.zip`；
2. 按照下方[安装指南](#-在-rebased-中安装插件)直接安装，无需安装 Python。

---

### 方式二：本地脚本一键构建（适合开发者）

#### 环境要求
- Python 3.8+（仅使用 Python 标准库，**无需安装任何额外 pip 依赖**）

#### 一键构建
在项目根目录下直接运行：

```bash
python build_rebased_chinese_pack.py
```

脚本将自动：
- 从 JetBrains Marketplace 下载官方最新中文包；
- 应用兼容补丁；
- 合并 `overrides/` 目录中的 Rebased 专属翻译；
- 输出打包产物至 `dist/rebased-chinese-pack-<version>.zip`。

---

## 🛠️ 常用命令与选项

### 1. 列出官方全部可用版本
```bash
python build_rebased_chinese_pack.py --list-versions
```

### 2. 指定下载某个版本（如 242.152）
```bash
python build_rebased_chinese_pack.py -v 242.152
```

### 3. 使用本地已有安装包（离线构建）
```bash
python build_rebased_chinese_pack.py -i ./path/to/zh.242.152.zip
```

### 4. 指定自定义 overrides 目录与输出路径
```bash
python build_rebased_chinese_pack.py -d ./my_overrides -o ./dist/my-rebased-zh.zip
```

### 5. CLI 参数完整参考

| 参数 | 缩写 | 默认值 | 作用说明 |
| :--- | :--- | :--- | :--- |
| `--version` | `-v` | 最新可用版本 | 指定从 Marketplace 下载的官方语言包版本（如 `242.152`） |
| `--input-file` | `-i` | `None` | 本地已有的插件包路径（`.zip` 或 `.jar`），指定后跳过网络下载 |
| `--output` | `-o` | `dist/rebased-chinese-pack-<version>.zip` | 打包生成的最终插件 zip 路径 |
| `--overrides-dir`| `-d` | `overrides` | 自定义文案 `.properties` 文件的目录路径 |
| `--plugin-name` | 无 | `Rebased Chinese Language Pack` | 修改后的插件显示名称 |
| `--until-build` | 无 | `999.*` | 放宽后的兼容最大版本构建号 |
| `--since-build` | 无 | 保持原版 | 修改兼容起始构建号（如 `200.0`） |
| `--list-versions`| 无 | `False` | 仅列出 Marketplace 上的历史版本列表并退出 |
| `--keep-temp` | 无 | `False` | 保留构建临时目录（排查调试使用） |

---

## 📂 自定义文案覆盖（Overrides 规范）

`overrides/` 目录采用与插件 JAR 内部**相同的相对路径结构**。

例如：
```
overrides/
└── messages/
    ├── IdeBundle.properties        # 覆盖 IDE 核心/通用设置文案
    ├── ActionsBundle.properties    # 覆盖主菜单、全局动作等文案
    └── IndexingBundle.properties   # 覆盖索引、项目分析等文案
```

### 键值对合并逻辑：
- **精准覆盖**：如果官方包已存在该文件和该 Key，脚本会在该 Key 所在位置精准替换为新文案，保留周围的原版注释与排版；
- **智能追加**：如果该 Key 是 Rebased 独有的新增词条（如 `badge.text.rebased.setting`），脚本会自动在文件末尾追加；
- **无感合并**：用户只需在 `overrides/` 中写想要修改或新增的几行，无需把整个几千行的原版文件拷过来！

当前项目中已预置了针对 Rebased 专属文案的翻译，包括：
- `badge.text.rebased.setting=Rebased 设置`
- `checkbox.confirm.application.exit=退出 Rebased 前确认`
- `checkbox.indexing=启用搜索文件索引`
- `action.CallSaul.text=修复 Rebased`
- 以及各处的更新检查、存储清理与项目分析等专属说明。

---

## 📥 在 Rebased 中安装插件

1. 启动 **Rebased**；
2. 进入设置：
   - Windows/Linux：点击主菜单 `File` -> `Settings`（或按快捷键 `Ctrl + Alt + S`）；
   - macOS：点击菜单栏 `Rebased` -> `Settings`（或按快捷键 `Cmd + ,`）；
3. 在左侧列表选择 **Plugins**（插件）；
4. 点击插件页面顶部的 ⚙️ **齿轮图标** 下拉菜单，选择 **Install Plugin from Disk...**（从磁盘安装插件）；
5. 浏览并选中 `dist/rebased-chinese-pack-xxx.zip`；
6. 点击确定并按照提示 **Restart Rebased**（重启客户端）；
7. 重启后即可畅享完全适配的简体中文界面！

---

## 🤖 自动化 CI/CD 与发版

本项目已配置完整的 **GitHub Actions 自动化流水线**：
- **Tag 触发自动发版**：每当向仓库推送形如 `v*` 的 Git Tag（如 `v1.0.0`），GitHub Actions 将自动完成插件构建、生成 SHA256 校验和并创建 GitHub Release；
- **手动触发与版本定制**：支持在 GitHub Actions 页面使用 `workflow_dispatch` 手动触发并指定官方语言包版本；
- **PR 质量检查**：社区提交 PR 时会自动运行构建检查，确保文案格式与脚本正常。

---

## 📄 开源协议

本项目采用 [MIT License](LICENSE) 许可协议。
官方中文语言包版权归 JetBrains s.r.o. 所有。

