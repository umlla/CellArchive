CellTracker 4.0.0 · 细胞培养追踪（macOS 通用版）
============================================================

一、安装
1. 解压压缩包。
2. 把 CellTracker.app 拖到“应用程序”或任意文件夹。
3. 第一次打开时，右键点击 CellTracker.app → “打开”。
   如果系统提示“无法验证开发者”，再点一次“打开”。
   （程序没有购买 Apple 开发者签名，这是正常提示。）

二、启动
1. 双击 CellTracker.app。
2. 程序会在后台启动服务，并自动打开浏览器：
   http://127.0.0.1:18600/
3. 如果浏览器没有打开，请手动访问上面的地址。
4. 程序没有主窗口，这是正常的；它只在后台提供网页界面。

三、数据在哪里
- 数据库：~/Library/Application Support/CellTracker/data/cell_data.db
- 备份：~/Library/Application Support/CellTracker/backups/
- 日志：~/Library/Application Support/CellTracker/data/celltracker.log
- 换电脑时，复制整个 CellTracker 文件夹即可。

四、停止
- 打开“活动监视器”，搜索 CellTracker，结束进程。
- 或在“终端”执行：pkill CellTracker

五、局域网共享（可选）
- 编辑 ~/Library/Application Support/CellTracker/config.json，
  把 "host" 改为 "0.0.0.0"。
- 建议同时把 auth.enabled 改为 true，并设置自己的密码。
- 对方访问 http://你的IP:18600/。

六、常见问题
- 双击没有反应：右键 → 打开；仍不行时，在“终端”执行：
  /Applications/CellTracker.app/Contents/MacOS/CellTracker
  查看错误信息。
- 浏览器没有自动打开：手动访问 http://127.0.0.1:18600/
- 想换端口：编辑 config.json 的 "port"，保存后重新启动。
