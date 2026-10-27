# R1-hook-window：Android 启动实验候选

本轮只取消 Android protect 对 TUN Listener 已赋值的依赖；保护回调仍须先在系统 VPN establish 成功后注册。未证明它是手机故障根因，不能标记稳定或修复成功。包名及签名沿用上一版私人 Android 0.9.2，可覆盖安装。默认不启用诊断；不需要 Root，不设置固定等待，不自动重启 VPN。

本轮只测试 R1，构建交付后等待实机结果，不能自动开始 R2。三轮均从 611de395 独立起步，不叠加失败补丁。

新增事件：`socket_hook_ready` 的 code=1 表示有效保护回调已注册，value=0 表示 Listener 尚未赋值；`protect_before_tun_ready` 表示这个窗口内的 Socket 将实际调用 protect，同 FD 的后续 `protect_result` 给出结果。R1 的 `protect_skipped` 仅表示回调缺失，不能把 hook 安装前不可观测的 Socket 当作已经保护。TCP/UDP 仍由 `socket_create` 的 code=1/2 区分。若失败但未出现 `protect_before_tun_ready`，只能说明本轮未命中 H1 窗口，不能排除其他 Android 保护路径。

保持与基线一致的探测参数：240 秒、连接超时 4 秒、每次最多 8 秒，目标和规则不变。只在待测节点承载真实手机 HTTPS 的前提下评价结果。一次有效失败即可报告；首测成功再做两次完全冷启动，每次 VPN 后约 15 秒内成功、持续两分钟无断流或异常重启，才进入最终回归。电脑 CONNECT 成功或 DIRECT 成功不算修复通过。

1. 安装 APK，备份现有配置。电脑安装官方 Android platform-tools，手机开启 USB 调试并授权；PowerShell 7 中确认 `adb devices`。
2. 保持同一节点、DNS、规则，手机混合端口默认 7890。运行 `pwsh -File ./Measure-AndroidStartup.ps1 -Adb C:/platform-tools/platform-tools/adb.exe -Seconds 240`，多设备加 `-Serial`。脚本设置诊断开关后，完全停止并重新启动 App/VPN，确保初始化被记录。手机未连接前无法通过 ADB 备份配置；先在 App 内导出，覆盖升级不要清除数据。
3. 开启手机首页 VPN 开关，同时用手机浏览器访问 HTTPS，记录首次成功时刻，至少观察 120 秒，全程不补点。App 的 `ui_start_command` 与 `vpn_established` 提供启动标记，电脑 S 键可不操作。电脑探测为 ADB 转发后的显式 HTTP 代理，不能代替手机经 TUN 的浏览器实测。
4. 若仍明显复现，一次有效失败即可提交结果；若首测成功，再完成两次相同条件的完全冷启动，逐次记录耗时，不以平均值代替。
5. 本次构建后停止，等待实机结果；只有三次冷启动通过，才安排 Reality、切网、后台、端口跳跃及扫码等最终回归。回传每轮生成目录及手机浏览器结果，不需要导出订阅或完整配置给他人。

脚本只保存 `FlClashStartup` 标签及固定字段的 curl 统计；不保存原始核心日志、响应正文、节点地址、密码、UUID、Token、私钥或 Wi-Fi SSID。若厂商禁止设置调试属性，脚本会报错；不要 Root。结束恢复原日志属性（原来为空则设 SILENT），完全停止并重启 App 后停止 Go 日志订阅；若脚本被强制终止，执行 `adb shell setprop log.tag.FlClashStartup SILENT` 并完全停止、重启 App。仅返回前台不保证重新初始化。

`time_ms` 是各端 UTC 毫秒，Logcat 前缀为手机时间；`elapsed_ms` 为手机开机后的单调时间。电脑标记和探测属于电脑时钟，比较前确认两端时间同步，不能混用两端时间算精确毫秒差。每个 HTTPS 样本最多 8 秒，间隔至少 2 秒；恢复时间是首次成功样本的上界，不能推导精确握手开始时刻。

事件：`ui_start_command/ui_stop_command` 是 Flutter 提交服务命令，不是物理触屏时刻；`core_init` 是初始化方法入口，不是 OS 进程创建；`config_apply_*` 为配置解析/应用；`mixed_listener_ready` 是实际监听成功日志；`vpn_establish_begin/vpn_established` 包围系统 establish（路由就绪只能得到区间）；`go_tun_start_*` 是 FD 接入核心；`network_*`、`default_network`、`underlying_network_changed` 为系统回调/观察结果；`protect_result=1` 表示 protect 成功，0 表示失败；`protect_skipped` 表示已有 hook 但保护条件未满足。首次 hook 安装前的 Socket 不可观测，不能以没有记录证明没有拨号或未保护。

网络 flags：Wi-Fi=1、移动=2、VPN=4、VALIDATED=8（按位组合），value 为网络 handle。`config_network_flags`：auto-route=1、auto-detect-interface=2、非空 interface-name=4、配置 TUN enable=8；value 为 mixed-port。Android 实际 FD TUN 在未改动的 `core/tun/tun.go` 中另行强制 auto-route/auto-detect-interface=false，由系统 VPN 安装路由；此配置事件不能冒充实际接口绑定证明。

`delay_probe_*` 是节点测速；`flow_*_connected` 是核心流建立，不代表外部 TLS 完成。`https_proxy_probe.success=true` 才证明该电脑样本通过手机 HTTP 代理完成 CONNECT、TLS 和 HTTPS 200；手机浏览器结果另外记录。探测目标是 `https://1.1.1.1/cdn-cgi/trace`，确认现有规则将其送到待测节点；若命中 DIRECT，不能证明节点可用。DNS 事件只有匿名查询/回答标记，不能与某个节点域名精确配对。核心日志不暴露每次 Hy2 内部 UDP 包及握手边界；需要服务器端脱敏时间戳/抓包才能确认首次拨号、握手和端口跳跃。

错误 code：1=回环文本，2=超时，3=无路由，4=拒绝连接，5=TLS/握手/证书，6=EOF，7=DNS，8=其他。均为粗分类，不能作为完整原始错误；只有 `dialer_loop_detected` 对应核心现有回环检测的直接事件。`trace_dropped` 表示队列溢出，`socket_trace_limit` 表示保护/Socket 细节达到 512 条，此后事件缺失不能用作否定证据。
