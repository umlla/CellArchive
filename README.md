# 🧬 CellTracker · 细胞培养追踪

记录细胞株、培养批次、传代、冻存和生长曲线的小工具。**Go 重写版**：单个可执行文件，内置网页界面和 SQLite 数据库，Windows / macOS 通用，运行时不需要 Python、Node.js 或任何其他依赖。

## 界面预览

以下截图来自独立的演示数据库，只使用 HeLa、A549、MCF-7、HEK293T、CHO-K1、NIH/3T3 等通用细胞名和虚构批次，不包含真实实验数据。

![按细胞组查看：增殖速度对比与组内生长曲线（演示数据）](docs/preview-dashboard.png)

![任选细胞株进行生长曲线对比（演示数据）](docs/preview-curve.png)

![9×9 冻存盒视图（演示数据）](docs/preview-vials.png)

## 一、直接下载使用

发布包由 `build.ps1` 生成在 `release/` 目录；如果维护者上传到 GitHub Releases，也可以从 Releases 下载。**不需要安装任何运行环境**。

### Windows 64 位

1. 解压 `CellTracker-4.0.0-win64.zip` 到有写权限的目录，例如 `D:\CellTracker` 或桌面。不要放在 `C:\Program Files` 下，否则程序无法创建数据目录。
2. 双击 `CellTracker.exe`。
3. 程序会自动打开浏览器；如果没有打开，请手动访问 <http://127.0.0.1:18600/>。
4. 黑色控制台窗口不要关闭，关闭即停止服务。

第一次运行时 Windows 可能提示“Windows 已保护你的电脑”，点 **更多信息 → 仍要运行** 即可。程序未购买代码签名证书，这是正常提示。

### macOS（Intel + Apple Silicon 通用）

1. 解压 `CellTracker-4.0.0-macos-universal.zip`。
2. 把 `CellTracker.app` 拖到“应用程序”或任意文件夹。
3. 第一次打开：右键点击 `CellTracker.app` → **打开**。如果系统提示“无法验证开发者”，再点一次 **打开**。
4. 程序在后台启动服务并自动打开浏览器：<http://127.0.0.1:18600/>。

macOS 版没有主窗口，这是正常的。数据保存在：

```text
~/Library/Application Support/CellTracker/
```

停止程序：打开“活动监视器”搜索 `CellTracker` 并结束进程，或在终端执行：

```bash
pkill CellTracker
```

也可以使用仓库里的 `start-mac.command`（会打开终端窗口，Ctrl+C 停止）。

## 二、主要功能

- **细胞株 / 培养批次 / 传代记录**：完整的增删改查，支持已终止批次恢复。
- **PD 计算**：单次 PD = `log2(本次收获 ÷ 上次接种)`；累计 PD 只累加正 PD；负 PD 保留显示。
- **生长曲线对比**：任选多个细胞株放在同一张图里，支持按日期 / 按培养天数对齐、标准化扩增倍数 `2^ΔPD`、PD/天 与倍增时间。
- **按组查看**：按细胞组顺序展示在养批次，左侧整段 PD/天 条形图，右侧组内生长曲线。
- **按组录入**：组内日期自动同步，按组内成员顺序排列，减少重复录入。
- **冻存管管理**：9×9 冻存盒视图、位置补录、状态标记（在库 / 已复苏 / 已丢弃）、Excel 批量导入。
- **Excel / CSV**：全量导出、按组导出、单批次传代记录 CSV。
- **数据与工具**：数据库体检、PD 重算、在线备份、上传恢复、旧库导入。
- **登录与局域网访问**：默认仅本机；可在 `config.json` 开启认证并监听 `0.0.0.0`。

## 三、数据位置

Windows（便携版，数据在程序旁边）：

```text
data\cell_data.db     数据库
backups\              自动备份
data\celltracker.log  运行日志
```

macOS：

```text
~/Library/Application Support/CellTracker/data/cell_data.db
~/Library/Application Support/CellTracker/backups/
~/Library/Application Support/CellTracker/data/celltracker.log
```

换电脑时复制整个数据目录即可。数据库是标准 SQLite 文件，旧版 Python 的 `data/cell_data.db` 可以直接打开；如果新位置还没有数据库，程序会自动复制项目根目录的 `cell_data.db`。

> 仓库中不包含任何真实数据库、备份或截图中的真实数据。`data/`、`backups/`、`*.db` 都在 `.gitignore` 中。

## 四、从源码运行 / 构建

需要 **Go 1.26+**。前端已经预构建在 `web/dist`，Go 编译时用 `embed` 打进去，构建过程不需要 Node.js。

```bash
# 开发运行
go run ./cmd/celltracker

# 只构建当前平台
go build -o CellTracker ./cmd/celltracker

# 运行测试
go test ./...
```

Windows 上构建全部发布包：

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

- 默认使用仓库里已构建好的 `web/dist`。
- 如果改了 Vue 前端，加 `-Frontend` 重新构建并同步：`build.ps1 -Frontend`。
- 只构建 Windows：`build.ps1 -SkipMac`；只构建 macOS：`build.ps1 -SkipWindows`。
- 输出在 `release/`：Windows zip、macOS 通用 zip、`SHA256SUMS.txt`。

macOS 通用程序由 `tools/makefat` 把 `darwin/amd64` 和 `darwin/arm64` 两个 Go 二进制合并成 FAT Mach-O，不需要在 Mac 上执行 `lipo`。

### 前端开发

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173，/api 代理到 18600
npm run build    # 输出到 frontend/dist
```

构建后把 `frontend/dist` 同步到 `web/dist`（`build.ps1 -Frontend` 会自动做），再重新编译 Go 程序。

## 五、配置

程序按以下顺序查找 `config.json`：

1. `--config` 参数
2. 环境变量 `CELLTRACKER_CONFIG`
3. 数据目录（Windows 为程序目录，macOS 为 Application Support）
4. 当前目录

常用配置：

```json
{
  "host": "127.0.0.1",
  "port": 18600,
  "open_browser": true,
  "database": "data/cell_data.db",
  "backup_dir": "backups",
  "auth": {
    "enabled": false,
    "session_days": 30,
    "bootstrap_username": "admin",
    "bootstrap_password": "celltracker"
  }
}
```

- 只给本机用：保持 `host: 127.0.0.1`、`auth.enabled: false`。
- 局域网共享：`host` 改为 `0.0.0.0`，并建议把 `auth.enabled` 改为 `true`，首次启动会自动创建 `admin` 账号，登录后请立即改密码。
- 端口被占用：把 `port` 改成 `18601` 等数字。
- 不想自动打开浏览器：`open_browser: false`，然后手动访问控制台显示的地址。

### 校园网 / 跨网络访问

校园网常启用客户端隔离，同网段也可能互相访问不了。推荐 **Tailscale**：两台电脑登录同一账号后，用 `http://100.x.x.x:18600/` 访问，不依赖校园网是否允许互访。无论用哪种方式，开启 `auth.enabled` 并设置强密码。

## 六、命令行

```bash
CellTracker --help
CellTracker --port 18601 --no-browser
CellTracker --data-dir D:\CellTrackerData
CellTracker --version
```

`--data-dir` 会把数据库、备份、日志全部放到指定目录，适合放在移动硬盘或共享目录。

## 七、旧版 Python 实现

仓库仍保留 `backend/`、`cell_tracker.py` 和 `start-python.bat`，仅用于对照和迁移验证。日常使用请用 Go 版 `CellTracker.exe` / `CellTracker.app` / `start.bat`；Python 版不再是主程序。

## 八、许可证

Apache License 2.0
