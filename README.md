# 🧬 CellTracker · 细胞培养追踪

记录细胞株、培养批次、传代、冻存和生长曲线。Flask 后端 + Vue 3 前端，本地运行、数据留在自己电脑上。

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

## 快速开始

### Windows

双击 `start.bat`。首次运行会自动创建虚拟环境并安装依赖。

浏览器打开 <http://127.0.0.1:18600/>。数据保存在 `data/cell_data.db`。

### macOS / Linux

```bash
git clone https://github.com/umlla/celltracker.git
cd celltracker
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python -m backend.serve
```

前端已构建产物在 `frontend/dist`，后端会直接托管，无需单独启动 Node。

### 修改前端

```bash
cd frontend
npm install
npm run build     # 产物输出到 frontend/dist
```

## 配置

复制 `config.example.json` 为 `config.json` 后按需修改（`config.json` 不会被提交）：

| 字段 | 说明 |
| --- | --- |
| `host` | 监听地址，`127.0.0.1` 仅本机；局域网访问改 `0.0.0.0` |
| `port` | 端口，默认 18600 |
| `database` | 数据库路径，默认 `data/cell_data.db` |
| `auth.enabled` | 是否启用登录认证 |

## 自定义标签与配色

细胞株的「标签」是自由文本，不预设任何选项——填物种、细胞类型、项目代号、来源都可以。

配色规则：

- **同一标签 → 同一色系**：标签相同的细胞株在图表里用相近色相，一眼看出属于一组
- **不同标签 → 颜色明显区分**：每个标签独占一段色相区间，不会撞色
- **颜色只由标签名决定**：新增或改名标签不会让已有标签的颜色变化，刷新页面也不变
- 不填标签的细胞株统一用中性灰色

标签可以在「细胞株」页面逐个编辑，也可以点「批量标注标签」一次性给多株填写；输入时只会提示你已经用过的标签。

## 数据迁移

旧版 Streamlit 应用的数据库可直接使用：把旧的 `.db` 放到 `data/cell_data.db`（或改 `config.json` 的 `database`）后启动即可，表结构完全兼容，并会自动补齐新增字段。

迁移前建议先在旧库里备份一份。

## 更新软件

- 拉取新代码后重启服务；`data` 和 `backups` 文件夹不要删除。
- 更新前可点页面左下角「备份数据库」下载一份快照，需要时在「数据与工具 → 恢复备份」上传恢复。

## 许可

见 [LICENSE](LICENSE)。
