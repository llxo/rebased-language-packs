# Rebased 语言包 (Rebased Language Packs)

专为 **[Rebased](https://github.com/DetachHead/rebased)**（基于 IntelliJ Platform 的纯粹 Git 客户端）定制的官方多语言本地化语言包集合。

---

## 🌐 支持的语言包

本项目适配了 JetBrains 官方维护的 3 款原生语言包：

| 语言代码 | 语言名称 | 基础来源 | 产物文件名 |
| :--- | :--- | :--- | :--- |
| **`zh-CN`** | 简体中文 | JetBrains 官方中文语言包 | `rebased-zh-CN-pack-*.zip` |
| **`ja`** | 日本語 | JetBrains 官方日本語言語パック | `rebased-ja-pack-*.zip` |
| **`ko`** | 한국어 | JetBrains 官方한국어 언어 팩 | `rebased-ko-pack-*.zip` |

### ✨ 解决的核心问题
- **双向放宽版本号限制**：解除 `until-build` 与 `since-build` 限制，彻底解决直接安装时报错“版本不兼容 / Incompatible”的问题；
- **修复报错**：修复了官方语言包旧版本在新版 IDE 中因缺失 HTML 标签导致的 `IndexOutOfBoundsException` 报错；
- **Rebased 专属界面本地化**：补充 Rebased 独有设置项与文案调整。

> 由于 JetBrains 官方未开放新版语言包的外部下载，自动化构建会选用 242 稳定版本，已足以覆盖绝大多数界面。

---

## ⚡ 安装与使用

1. **下载插件**：前往 **[Releases 页面](../../releases)** 下载对应语言的 `rebased-*-pack-*.zip`；
2. **安装并启用**：
   - 打开 Rebased（欢迎首页左侧直接点击 **`Plugins`**，或者在设置中打开 `Plugins`）；
   - 点击右上角 ⚙️ **齿轮图标** -> 选择 **Install Plugin from Disk (从磁盘安装插件)**；
   - 选中下载的 `.zip` 文件安装；
   - 在左侧菜单点击 **`Customize`**，将 **`Language`** 切换为对应语言；
   - 点击 **Restart (重启)** 即可生效。

---

## 🛠️ 自行构建（面向开发者）

### 1. 一键构建全部官方语言包
纯 Python 标准库实现，**零第三方依赖**。脚本自动从 JetBrains Marketplace 获取最新版本并批量输出至 `dist/`：
```bash
python build.py
```
> 一键生成 `zh-CN`, `ja`, `ko` 全部 3 个语言包及对应的 `.sha256` 校验和。

### 2. 常用构建参数
```bash
# 自由指定语言（支持逗号分隔）
python build.py -l zh-CN,ja
python build.py -l ko

# 指定官方语言包版本号（如 242.152）
python build.py -v 242.152

# 处理任意本地第三方/社区语言包
python build.py -i ./path/to/community-pack.zip
```

### 3. 项目结构
```text
rebased-language-packs/
  ├── build.py                 # 构建入口（语言配置、CLI 解析与任务调度）
  ├── core.py                  # 核心引擎（网络下载、XML放宽与重新打包）
  └── overrides/               # 自定义文案覆盖目录
      └── zh-CN/               # 简体中文补丁
          └── messages/
```

---

## 📄 开源协议

本项目采用 [MIT License](LICENSE) 许可协议。  
JetBrains 官方语言包版权归 JetBrains s.r.o. 所有。
