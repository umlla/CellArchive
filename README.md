# 🧬 CellTracker · 细胞培养追踪

记录细胞株、培养批次、传代、冻存和生长曲线。Windows 解压即用；macOS 使用源码启动。

## 界面预览

![按细胞组查看](docs/preview-dashboard.png)

![生长曲线对比](docs/preview-curve.png)

![冻存盒 9×9 视图](docs/preview-vials.png)

## 下载

- **Windows 64 位**：`CellTracker-4.0.0-win64.zip`

## Windows

1. 解压到有写权限的目录，例如 `D:\CellTracker` 或桌面，不要放在 `C:\Program Files`。
2. 双击 `CellTracker.exe`。
3. 浏览器打开 <http://127.0.0.1:18600/>；没有自动打开时手动访问即可。
4. 数据保存在程序旁的 `data\cell_data.db`。关闭黑色控制台窗口，或在页面左下角点「退出程序」即可停止。

首次运行若提示“Windows 已保护你的电脑”，点 **更多信息 → 仍要运行**。

## macOS（源码启动）

需要 Go 1.26+。不提供 `.app` 安装包。

```bash
git clone https://github.com/umlla/celltracker.git
cd celltracker
go run ./cmd/celltracker
```

浏览器打开 <http://127.0.0.1:18600/>。数据保存在项目目录的 `data/cell_data.db`。

退出：在页面左下角点击「退出程序」，或在终端按 `Ctrl+C`。

## 更新软件

- **Windows**：下载新版本，解压后只替换 `CellTracker.exe`，保留 `data` 和 `backups` 文件夹。
- **macOS**：在源码目录执行 `git pull`，然后重新 `go run ./cmd/celltracker`；`data` 文件夹不要删除。
- 更新前可以点页面左下角「备份数据库」，把 `.db` 下载到“下载”文件夹；需要时在「数据与工具 → 恢复备份」上传恢复。
