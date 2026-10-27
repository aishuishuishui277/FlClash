# R3-final-attempt：首次 Android VPN 边界的 Hy2 会话代际实验

最后一轮，仅采用方案 B。基于诊断提交 611de395，不叠加 R1 保护条件修改或 R2 健康检查门控。没有创建门控；不改变配置、DNS、接口选择、OFBS、端口跳跃、QUIC 超时或正常重试。

首次 TUN 启动成功、Listener/保护回调已就绪后，代际由 0 切换为 1。之后第一次 Hy2 offer 只移除该客户端的旧代际会话/旧共享建连尝试，保留新代际对象；新请求重新拨号，旧异步结果不能覆盖新状态。实际关闭发生在下一次 offer，不提前遍历/清理所有客户端。已经在途的旧流可能失败，不能宣称无缝迁移。代际在同一进程内不重复切换；VPN 关闭/开启、网络切换不触发周期性清理。非 VPN 模式代际一直为 0。非 Android 不安装代际钩子。

包名 com.follow.clash.personal，持久私人签名沿用 R1/R2，目标 versionCode 2026104703，可覆盖 R2。安装前导出配置并保留旧 APK；回滚低版本通常需卸载再安装、导入配置。独立包名的 v0.9.0 私人版可并存，但不要同时运行两个 VPN。

## 手机验收

1. 同手机、同 Wi-Fi、同 Hy2、DNS、规则和端口范围，完全退出 App 与 VPN。沿用原 Measure-AndroidStartup.ps1，例如 `pwsh -File ./Measure-AndroidStartup.ps1 -Adb C:/platform-tools/platform-tools/adb.exe`。手机授权 USB 调试即可，不需 Root。脚本开启诊断后按提示重新打开 App。
2. 按电脑 S 键并启动手机 VPN，不再补点，至少观察 120 秒。同时用手机完成真实 HTTPS，记录首次成功时刻，确认流量确实命中待测节点。DIRECT、CONNECT 200、会话 ready 或延迟测试不构成成功。
3. 首次冷启动若仍出现明显几十秒故障，直接判定 R3 失败，停止 v0.9.2 实验并回到已验收的 v0.9.0；不增加候选、不要求额外抓包。
4. 首测成功后再做两次完全冷启动。每次要求 VPN 建立后约 15 秒内真实 HTTPS 成功、连续两分钟无断流、无 VPN 循环重启或高频拨号。逐次保留耗时，不用平均值掩盖失败。
5. 只有三次全部通过，才验收 Reality、Hy2 OFBS/服务器端端口跳跃证据、Wi-Fi/移动数据切换、VPN 开关、后台/熄屏、扫码、显式代理及耗电。构建交付后 Codex 停止等待结果。

电脑样本是 ADB 转发后的 HTTP 代理探测，不能代替手机经 TUN 的真实 HTTPS，也不能独立排除 DIRECT。目标仍为 `https://1.1.1.1/cdn-cgi/trace`，不改超时或探测条件。

## 日志判读

- `vpn_established`：Android VPN Builder establish 成功。`startup_tun_ready`：原 Go TUN 启动成功，Listener/保护回调可用，未证明外网可达。`hy2_vpn_epoch` code=1 表示首次推进代际，value=1；后续启动 code=0、value=1，不重新失效会话。
- `hy2_session_begin/ready`：QUIC+认证尝试开始/认证成功；code=匿名 client ID，value=匿名 session ID。对应 `_epoch` code=该对象创建代际，value=session ID；`_vpn` code=当时 TUN 就绪状态。真正 VPN establish 状态应结合其时间戳，不能将 `_vpn=0` 一律解释为系统 VPN 尚未建立。
- `hy2_session_reuse_candidate`：原 offer 内部发现 active 会话，尚未通过 R3 代际校验。`hy2_session_selected` 才是通过校验、将返回给上层的会话，须检查其 `_epoch`。边界期间的 candidate 可能随后失效，不等于已交付给上层复用。
- `hy2_session_invalidated`：旧代际传输在后续 offer 被移除并关闭。`hy2_offer_invalidated`：仅旧共享建连尝试被取消，session ID=0；`hy2_offer_wait` 表示共享等待。`hy2_session_closed/failed` 有对应粗错误分类。ready/selected 均不等于外部 TLS 或真实 HTTPS 成功。
- `socket_create` code=1/2 为 TCP/UDP，value=FD；`protect_result` code=1/0 为成功/失败、value=FD。新会话应与新 UDP Socket、protect 及真实 HTTPS 时间结合核对。没有实际底层 Network 绑定证据，不能把 protect 成功说成接口选择已被证明正确。
- 错误分类：1回环文本、2超时、3无路由、4拒绝连接、5TLS/握手/证书、6EOF、7DNS、8其他。R3 主动失效使用固定脱敏原因，归为8，不是等待到原超时。日志不含节点名称、地址、密码、UUID、Token 或密钥。
- `trace_dropped`/`socket_trace_limit` 表示事件可能缺失，不能以缺少事件单独证明未发生。DNS/flow/节点测速等原诊断仍保留；`https_proxy_probe.success=true` 只证明该电脑样本完成 CONNECT、TLS 和 HTTPS 200。

构建时只对锁定 sing-quic 施加 sources.json 中声明的源码补丁，版本及 go.mod/go.sum 不变；CI 在缓存保存前恢复源码并再次 go mod verify。mihomo 子模块没有行为补丁。回归测试使用回环 QUIC 验证旧/新会话、并发、边界竞争与晚到结果，不冒充 Android protect 或手机联网实测。
