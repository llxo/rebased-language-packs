# Rebased 中文语言包 (Rebased Chinese Language Pack)

专为 **[Rebased](https://github.com/DetachHead/rebased)**（基于 IntelliJ Platform 的纯粹 Git 客户端）定制的简体中文汉化包。

---

## ⚡ 安装与使用

1. **下载插件**：前往 **[Releases 页面](../../releases)** 下载最新的 `rebased-chinese-pack-xxx.zip`；
2. **安装并启用**：
   - 打开 Rebased（欢迎首页左侧直接点击 **`Plugins`**）；
   - 点击顶部 ⚙️ **齿轮图标** -> 选择 **Install Plugin from Disk(从磁盘安装插件)**；
   - 浏览并选中下载的 `.zip` 进行安装；
   - 点击 **`Customize`**，将 **`Language`** 切换为 **`Chinese`**。
   - 点击 **Restart(重启)**

>  若已经打开了项目，也可随时在设置面板中进行同样的操作。

---

## 🛠️ 自行构建与定制（面向开发者）

如果你想自己打包或补充自定义翻译：

### 1. 本地一键打包
无需安装任何额外依赖（仅需 Python 3.8+）：
```bash
python build_rebased_chinese_pack.py
```
> 脚本会自动从 JetBrains 官方下载最新语言包、放宽版本限制、合并本地翻译并打包到 `dist/` 目录。

### 2. 常用命令速查
```bash
# 查看官方所有可用历史版本
python build_rebased_chinese_pack.py --list-versions

# 指定下载特定版本（如 242.152）
python build_rebased_chinese_pack.py -v 242.152

# 使用本地已有的 zip 安装包进行二次打包
python build_rebased_chinese_pack.py -i ./zh.242.152.zip
```

### 3. 补充自定义文案
直接在 `overrides/` 目录下按相同路径修改或新建 `.properties` 文件即可，例如：
- `overrides/messages/IdeBundle.properties`：通用设置与弹窗文案
- `overrides/messages/ActionsBundle.properties`：菜单与动作按钮文案
- `overrides/messages/IndexingBundle.properties`：索引与项目分析文案

脚本打包时会**智能增量合并**，自动保留官方原有翻译，仅替换或追加你修改的内容。

---

## 📄 开源协议

本项目采用 [MIT License](LICENSE) 许可协议。  
IntelliJ 官方中文语言包版权归 JetBrains s.r.o. 所有。
