# FlClash v0.9.2 Android ARM64 私人 Release

保留已验收 R3（e4c8af2d）的网络行为，只有启动诊断开关固定关闭、构建号及发布验收元数据变化。Go Core、mihomo/sing-quic源码补丁、依赖和工具链均与R3一致。不增加行为修复，不发布上游PR。

包名 com.follow.clash.personal，持久私人签名与R3一致，versionCode2026104801，可覆盖R3。安装前在App导出配置。安装后正常开启VPN，做一次联网确认；不要再运行旧诊断脚本，本包不接受DEBUG属性重新启用启动采集。正常App错误日志保留。

用户已确认：vivo Y300i / Android15三次冷启动均15秒内联网、Google Play正常；Hy2 OFBS及服务端端口跳跃、Wi-Fi/移动数据切换、VPN重开、后台/熄屏恢复均通过。一轮240秒原始采集显示VPN到首次电脑代理HTTPS为2.856秒，87/92探测成功，首次成功后无失败；S标记晚于首次成功，不作起点。

未报告的回归：Reality真实HTTPS、扫码、显式HTTP代理、耗电/高频重拨。本次关闭诊断后的成品仍需用户安装后确认，不能将继承的R3实机验收说成本APK已在手机运行过。

Firebase Analytics/Crashlytics保持移除，ML Kit扫码及其已批准的指标/DataTransport残留保留。所有原生组件仍按原项目流程编译，ARM64-only Release；CI检查签名、Manifest、DEX、native libraries、源码与R3一致性，并执行Go/竞态、Flutter和Android JVM测试。

原R3提交、原始日志及安装包保留；本分支为personal-android-0.9.2，不修改personal-stable或Windows成果。回滚到较低versionCode可能需先卸载、重新安装并导入配置；独立包名的已验收v0.9.0可并存，先停用当前VPN再启用旧版。不要同时运行两个VPN。
