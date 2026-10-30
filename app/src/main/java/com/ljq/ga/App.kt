package com.ljq.ga

import android.app.Application

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        Diag.init(this)   // 全局崩溃捕获 + 错误本地落盘: 最先安装, 之后的启动失败也能留下 crash-*.log
        GaNet.initNetworkMonitoring(this)
        // 总线起不来只影响设备能力, 不应让整个 App 打不开(否则连设置/诊断都看不到); 设备工具会显式报连接失败
        runCatching { Bus.start(this) }.onFailure { Diag.log("bus", "start failed: ${it.javaClass.simpleName}: ${it.message}") }
        Analytics.init(this)
        ShizukuShell.init(this)   // Shizuku binder 监听(第二条 shell 通道, stepOS 全屏启动用); 未装管理器时零副作用
    }
}
