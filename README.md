# 细胞档案 CellArchive · 细胞培养管理追踪

<img src="assets/app.png" width="96" alt="CellArchive 图标">

**细胞档案（CellArchive）** 用于记录细胞株、培养批次、传代、冻存和生长曲线。程序跑在你自己电脑上，数据只存在本地。

## 界面预览

![按细胞组查看](docs/preview-dashboard.png)

![生长曲线对比](docs/preview-curve.png)

![冻存盒 9×9 视图](docs/preview-vials.png)

> 预览图为演示数据，细胞株名称为通用的 HEK293T / CHO-K1 等。

## 功能

- **在养细胞**：按细胞株或细胞组查看，组内汇总增殖速率、生长曲线对比
- **传代记录**：录入收获/接种细胞数，自动计算单次 PD、累计 PD、PD/天 与倍增时间
- **生长曲线**：累计 PD 随日期变化，支持标准化（2^ΔPD）后跨批次比较
- **冻存管理**：9×9 冻存盒视图、孔位点击录入、Excel 批量导入
- **自定义标签与配色**：给细胞株打任意标签（物种、项目、来源都行），同一标签自动使用同一色系，同一细胞株颜色全局一致
- **数据安全**：一键备份 / 恢复，SQLite 单文件存储，兼容旧版数据

---

## Windows 用户：一键使用（推荐）

**不需要安装 Python，也不需要安装 Node.js。**

1. 打开 <https://github.com/umlla/celltracker/releases/latest>
2. 下载 **`CellArchive-4.0.0-win64.zip`**
3. 解压到一个**有写入权限**的文件夹，例如 `D:\CellArchive` 或桌面
   > ⚠️ 不要解压到 `C:\Program Files`，程序需要在同目录下创建数据文件
4. 双击 **`CellArchive.exe`**
5. 浏览器会自动打开；没有自动打开时，手动访问 <http://127.0.0.1:18600/>

首次运行时如果弹出「Windows 已保护你的电脑」，点 **更多信息 → 仍要运行** 即可。

### 以后怎么用

每次只需**双击同一个 `CellArchive.exe`**。

**用完怎么关**：关闭黑色命令行窗口，或在页面左下角点「退出程序」。

**数据在哪**：程序目录下的 `data\cell_data.db`。**备份这个文件夹就等于备份了全部数据**，也可以点页面左下角「备份数据库」。

### 更新版本

下载新版 zip，解压后**只替换 `CellArchive.exe`**，保留 `data` 和 `backups` 文件夹即可。

---

## 从源码运行（开发者）

需要 Python 3.10+ 和 Node.js 18+。

### Windows

双击 **`start.bat`**。首次运行会自动创建虚拟环境、安装依赖、构建前端页面，之后每次直接启动。

> 仓库里的 `frontend/dist` 是构建产物、不进版本库，所以首次运行需要 Node.js 生成页面。装过一次以后就不再需要它了。

### 手动步骤

```bash
git clone https://github.com/umlla/celltracker.git
cd celltracker

python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r backend/requirements.txt

cd frontend && npm install && npm run build && cd ..

python -m backend.serve
```

### 修改前端

```bash
cd frontend
npm install
npm run dev      # 开发模式，改代码自动刷新
npm run build    # 构建到 frontend/dist，由后端托管
```

### 构建 Windows 一键版

需要 Go 1.26+（放在 PATH 里，或解压到 `.tools\go`）：

```powershell
.\build.ps1 -Frontend     # 构建前端 + 打包 exe 到 release\
.\build.ps1               # 只重新打包（前端已构建过）
```

### 运行测试

```bash
pytest                              # Python 后端测试
go test ./...                       # Go 版测试
```

---

## 配置（可选）

程序默认就能用，**不需要任何配置**。只有需要改端口、开放局域网访问、开启登录时才需要建配置文件。

复制 `config.example.json`，改名为 `config.json`，按需修改：

| 字段 | 说明 |
| --- | --- |
| `host` | 监听地址。`127.0.0.1` 只有本机能访问；改成 `0.0.0.0` 后同一局域网的其他设备也能访问 |
| `port` | 端口，默认 18600。若提示端口被占用，改成 18601 等 |
| `database` | 数据库文件位置，默认 `data/cell_data.db` |
| `auth.enabled` | 是否启用登录认证，默认关闭 |

> `config.json` 里有你自己的设置，不会被提交到仓库。

## 自定义标签与配色

细胞株的「标签」是自由文本，不预设任何选项——填物种、细胞类型、项目代号、来源都可以。

配色规则：

- **同一标签 → 同一色系**：标签相同的细胞株在图表里用相近色相，一眼看出属于一组
- **不同标签 → 颜色明显区分**：每个标签独占一段色相区间，不会撞色
- **颜色只由标签名决定**：新增或改名标签不会让已有标签的颜色变化，刷新页面也不变
- 不填标签的细胞株统一用中性灰色

标签可以在「细胞株」页面逐个编辑，也可以点「批量标注标签」一次性给多株填写；输入时只会提示你已经用过的标签。

## 数据迁移

旧版应用的数据库可直接使用：把旧的 `.db` 放到 `data/cell_data.db`（或改 `config.json` 的 `database`）后启动即可，表结构完全兼容，并会自动补齐新增字段。

迁移前建议先在旧库里备份一份。

> 用 Go 版和源码版打开同一个数据库时，颜色完全一致，可以随时互换。

## 常见问题

**exe 版：提示「Windows 已保护你的电脑」**
点「更多信息 → 仍要运行」。这是 Windows 对未签名程序的通用提示。

**源码版：提示「未找到 Python 3.10 或更高版本」**
Python 没装好或版本太旧。重装时记得勾选 **Add python.exe to PATH**。

**源码版：提示「未找到 Node.js / npm」**
还没装 Node.js，去 <https://nodejs.org/> 下载 LTS 版本后重新双击 `start.bat`。

**提示端口已被占用**
改 `config.json` 的 `port`（例如改成 18601），或关掉占用该端口的程序。

**页面打不开**
确认那个黑色命令行窗口还开着——窗口一关服务就停了。

**想换电脑**
把整个文件夹（至少 `data` 目录）拷过去即可。

## 许可

见 [LICENSE](LICENSE)。
