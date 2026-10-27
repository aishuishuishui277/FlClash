# R2-session-startup：Android 启动门控实验（未经验收）

本轮仅暂缓 Android VPN 首次就绪前的自动 provider/group 健康检查，成功建立 TUN 且保护回调就绪后立即恢复。配置及 provider 加载、手动节点测速不受门控；不清理已有会话，不改变握手重试、OFBS、端口跳跃、DNS 或路由。不包含 R1 的 protect 条件修改。版本及依赖 pin 不变，但构建时明确应用 `r2/sources.json` 中列出的微型源码补丁，并在 CI 缓存保存前恢复依赖源码。

包名 com.follow.clash.personal，签名沿用上一版私人 Android 0.9.2，versionCode 2026104702 可覆盖 R1。先导出配置并保留旧 APK；降级旧版本可能需要卸载后重新导入。v0.9.0 私人版独立包名可并存。默认不启用诊断；不需要 Root，不设置固定等待，不自动重启 VPN。

首次完全退出 App/VPN，按下述脚本采集一次至少 120 秒的冷启动，不再点击 VPN。手机真实 HTTPS 必须经过同一 Hy2 节点，电脑代理探测仅为辅助。明显失败一次即可交回日志；若成功，再重复两次冷启动，每次 VPN 建立后约 15 秒内真实 HTTPS 成功，连续两分钟无断流、无循环重启，才进入功能回归。不能以 DIRECT 成功或节点延迟代替验收。此包交付后停止，等实机结果，不自动进入 R3。

R2 新事件：`auto_healthcheck_gate` code=0 暂缓，1 放行，value=TUN 当前是否已启动；`auto_healthcheck_resumed` value=本次释放的 provider 数。`startup_vpn_mode` code=VPN 配置开关；`startup_tun_ready` 在原 StartTun 成功且 listener/保护回调已就绪后记录，不表示外网可达。

`hy2_session_begin/ready/reuse/failed/closed` code=匿名 client ID，value=匿名 session ID。begin 是 QUIC+认证尝试开始，ready 是认证成功并构造可复用会话；reuse 是 offer 接受现有 active 会话，不能证明该会话能完成 HTTPS。`hy2_offer_wait` code=client ID、value=0 表示复用尚未完成的共享建连尝试。每个事件同时间的 `_vpn` code=当前 TUN 就绪状态、value=session ID，`_error` code=下文粗分类。没有节点名、地址或认证信息。会话事件为观察性补丁，不改变其创建/失效条件；会话创建早于 TUN 本身仍不足以证明因果。

本轮不门控手动测速、真实代理流量或经代理下载订阅等其他拨号来源。若没有自动检查被暂缓，或其他路径仍提前创建会话，不能将结果解释为已经全面排除 H2。`StartTun` 原本仅重置 DNS 连接；本轮保持这一行为，不把 DNS 重置说成 QUIC 会话清理。

1. 安装 APK，备份现有配置。电脑安装官方 Android platform-tools，手机开启 USB 调试并授权；PowerShell 7 中确认 `adb devices`。
2. 保持同一节点、DNS、规则，手机混合端口默认 7890。运行 `pwsh -File ./Measure-AndroidStartup.ps1 -Adb C:/platform-tools/adb.exe`，多设备加 `-Serial`。脚本设置诊断开关后，手动退出并重新打开 App，确保初始化被记录。
3. 按电脑 S 键，随即点手机首页 VPN 开关。第一轮等待满 120 秒，不补点；同时用手机浏览器访问 HTTPS，记录结果。电脑探测为 ADB 转发后的显式 HTTP 代理，不能代替手机经 TUN 的浏览器实测。
4. R2 测试期间不执行原先的 60 秒补点对照，等待至少 120 秒并保留原始失败耗时。脚本仅记时间，从不操作 VPN。
5. 再分别记录 VPN 关闭/开启、Wi-Fi/移动数据切换。Hy2 和 Reality 分开测试。结束可按 Q；回传每轮生成目录及手机浏览器结果，不需要导出订阅或完整配置。

脚本只保存 `FlClashStartup` 标签及固定字段的 curl 统计；不保存原始核心日志、响应正文、节点地址、密码、UUID、Token、私钥或 Wi-Fi SSID。若厂商禁止设置调试属性，脚本会报错；不要 Root。结束恢复原日志属性（原来为空则设 SILENT），重新打开 App 后停止 Go 日志订阅；若脚本被强制终止，执行 `adb shell setprop log.tag.FlClashStartup SILENT` 并重新打开 App。

`time_ms` 是各端 UTC 毫秒，Logcat 前缀为手机时间；`elapsed_ms` 为手机开机后的单调时间。电脑标记和探测属于电脑时钟，比较前确认两端时间同步，不能混用两端时间算精确毫秒差。每个 HTTPS 样本最多 8 秒，间隔至少 2 秒；恢复时间是首次成功样本的上界，不能推导精确握手开始时刻。

事件：`ui_start_command/ui_stop_command` 是 Flutter 提交服务命令，不是物理触屏时刻；`core_init` 是初始化方法入口，不是 OS 进程创建；`config_apply_*` 为配置解析/应用；`mixed_listener_ready` 是实际监听成功日志；`vpn_establish_begin/vpn_established` 包围系统 establish（路由就绪只能得到区间）；`go_tun_start_*` 是 FD 接入核心；`network_*`、`default_network`、`underlying_network_changed` 为系统回调/观察结果；`protect_result=1` 表示 protect 成功，0 表示失败；`protect_skipped` 表示已有 hook 但保护条件未满足。首次 hook 安装前的 Socket 不可观测，不能以没有记录证明没有拨号或未保护。

网络 flags：Wi-Fi=1、移动=2、VPN=4、VALIDATED=8（按位组合），value 为网络 handle。`config_network_flags`：auto-route=1、auto-detect-interface=2、非空 interface-name=4、配置 TUN enable=8；value 为 mixed-port。Android 实际 FD TUN 在未改动的 `core/tun/tun.go` 中另行强制 auto-route/auto-detect-interface=false，由系统 VPN 安装路由；此配置事件不能冒充实际接口绑定证明。

`delay_probe_*` 是节点测速；`flow_*_connected` 是核心流建立，不代表外部 TLS 完成。`https_proxy_probe.success=true` 才证明该电脑样本通过手机 HTTP 代理完成 CONNECT、TLS 和 HTTPS 200；手机浏览器结果另外记录。探测目标是 `https://1.1.1.1/cdn-cgi/trace`，确认现有规则将其送到待测节点；若命中 DIRECT，不能证明节点可用。DNS 事件只有匿名查询/回答标记，不能与某个节点域名精确配对。R2 会话事件补充建连/认证及复用边界，但不暴露每个 UDP 包或实际绑定的底层 Network；端口跳跃仍须服务器端证据，不能由这些日志推定。

错误 code：1=回环文本，2=超时，3=无路由，4=拒绝连接，5=TLS/握手/证书，6=EOF，7=DNS，8=其他。均为粗分类，不能作为完整原始错误；只有 `dialer_loop_detected` 对应核心现有回环检测的直接事件。`trace_dropped` 表示队列溢出，`socket_trace_limit` 表示保护/Socket 细节达到 512 条，此后事件缺失不能用作否定证据。
