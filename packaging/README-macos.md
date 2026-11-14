# 在 Mac 上部署并打包（内测版）

内测版是 Python + Vue，**`.app` 只能在 macOS 上打包**，Windows 无法生成。
本文分两步：先在 Mac 上把源码跑起来，再打包成双击即用的 `.app`。

---

## 准备：把源码传到同事的 Mac

在 Windows 上执行（项目根目录）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\make-source-zip.ps1
```

生成 `release\CellArchive-internal-source.zip`（约 0.6 MB，83 个文件）。

这个包**不含** `.venv`、`node_modules`、`data/`、`config.json`、密钥，可以直接发。

传输方式任选：

| 方式 | 说明 |
| --- | --- |
| 微信 / QQ / 邮件 | 最省事，0.6 MB 没有大小问题 |
| U 盘 | 适合内网 |
| AirDrop | 同事间最快 |

> **注意**：压缩包传过去后，先在 Mac 上**解压**再操作，不要在压缩包里直接双击。

---

## 第一步：在 Mac 上运行起来

### 1. 安装两个前置软件（只需一次）

| 软件 | 下载地址 | 用途 |
| --- | --- | --- |
| Python 3.10+ | https://www.python.org/downloads/macos/ | 运行后端 |
| Node.js LTS | https://nodejs.org/zh-cn | 构建前端页面 |

都是下载 `.pkg` 双击安装，一路「继续」即可。

### 2. 双击 `start.command`

**第一次双击如果提示「无法打开，因为它来自身份不明的开发者」**：

- 在文件上 **右键 → 打开**，弹窗里再点「打开」
- 或者：终端执行一次 `chmod +x start.command`

首次运行会自动装依赖、构建前端，**需要联网，约 3-8 分钟**。之后每次启动只要几秒。

启动成功后浏览器会自动打开 `http://127.0.0.1:18600/`。

> **关掉终端窗口 = 退出程序**。使用期间请保持窗口开着。

### 3. 验证没问题再打包

建议先录入几条数据、点几个页面确认正常，再往下走。

---

## 第二步：打包成 `.app`

双击 **`packaging/build-macos-app.command`**（同样，第一次可能要用右键 → 打开）。

脚本会自动完成 6 步：

| 步骤 | 内容 |
| --- | --- |
| 1 | 检查 Python / Node / 系统架构 |
| 2 | 建 `.venv-build` 并安装 PyInstaller |
| 3 | 构建前端页面 |
| 4 | PyInstaller 打包 Python 程序 |
| 5 | 组装 `.app`（写入 Info.plist） |
| 6 | 用 `ditto` 压缩成 zip |

产物：

```
release/CellArchive.app                      ← 可直接双击运行
release/CellArchive-macOS-arm64.zip          ← 发给其他同事（Apple 芯片）
```

Intel Mac 上产物名是 `CellArchive-macOS-x86_64.zip`。

> **为什么用 `ditto` 而不是普通 zip**：`.app` 内部有可执行权限和符号链接，普通 zip 会破坏它们，解压后打不开。`ditto` 会完整保留。

---

## 把 `.app` 发给其他同事

把 `CellArchive-macOS-xxx.zip` 发过去，同事解压后：

**第一次打开会被 macOS 拦截**（因为应用未签名），提示「无法打开，Apple 无法验证」。

解决方式（任一）：

1. 在 `CellArchive.app` 上 **右键 → 打开**，弹窗里再点「打开」
2. 打开后如果还是被拦：**系统设置 → 隐私与安全性 →** 滚到底部 → **「仍要打开」**

之后就能正常双击了。

> 想彻底免掉这个提示，需要 Apple 开发者账号（$99/年）做代码签名和公证。内部小范围使用，右键打开一次就够。

---

## 数据存在哪里

`.app` 版本的数据**不在** `.app` 里面，而是在：

```
~/Library/Application Support/CellArchive/
├── cell_data.db      ← 数据库
├── backups/          ← 备份
└── config.json       ← 可选，自己创建用于改端口等
```

好处是：**删掉或替换 `.app` 不会丢数据**。

想改端口的话，在上面目录建一个 `config.json`：

```json
{
  "port": 18601,
  "open_browser": true
}
```

> 注意：`.app` 版和第一步的 `start.command` 版**用的是两份不同的数据**。如果想让 `.app` 用旧数据，把 `data/cell_data.db` 复制到上面的目录并改名为 `cell_data.db`。

---

## 常见问题

**Q：双击 `start.command` 一闪就没了**
用「终端」打开它能看到原因：`cd` 到项目目录，执行 `./start.command`。

**Q：提示「没有找到 Python」**
Python 装好后，**关掉终端再重新双击**。PATH 需要重新加载。

**Q：前端构建失败 / 卡住**
网络问题。可以临时用国内镜像：
```bash
cd frontend && npm install --registry=https://registry.npmmirror.com && npm run build
```

**Q：端口被占用**
编辑 `config.json` 把 `port` 改成 18601 之类，重新启动。

**Q：`.app` 双击没反应**
先确认打包脚本第 6 步有输出「已生成」。如果只有 `.app` 没有 zip，可能是权限问题，检查 `Contents/MacOS/CellArchive` 是否可执行。

**Q：同事的 Mac 是 Intel，我的是 Apple 芯片**
在**打包的那台机器**上只能打出对应架构的包。要同时支持两种，需要在 Intel 机器上也跑一遍打包脚本，或改用 `--target-arch universal2`（需要对应的 Python 版本支持）。

---

## 两个版本的取舍

| | 内测版（Python + Vue） | 正式版（Go） |
| --- | --- | --- |
| 细胞实验 / 待办 / 日历 | ✅ 有 | ❌ 没有 |
| Mac 支持 | 需按本文档打包 | 可用 `GOOS=darwin go build` 交叉编译 |
| 一键运行 | 需 Python/Node（或打包成 `.app`） | 单个可执行文件 |

如果同事主要用细胞实验和日程功能，就用内测版打包的 `.app`。
