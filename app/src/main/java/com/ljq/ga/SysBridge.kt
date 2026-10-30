package com.ljq.ga

import android.net.Uri
import android.provider.Settings

class SysBridge(private val activity: MainActivity) {
    // 无线调试自连状态(设置行+引导浮层用): wifi=系统「无线调试」开关是否已打开; paired/connected=AdbController(证书已持久化/传输已建立)。
    fun adbSelfStatus(): String {
        val st = AdbController.status(activity)
        return org.json.JSONObject().put("wifi", activity.adbWifiOn()).put("paired", st.paired).put("connected", st.connected)
            .put("repair", st.repairNeeded).toString()
    }
    // 跳系统「开发者选项」(无线调试无独立直达 Intent)。返回是否真的拉起了某个设置页, JS 据此判断成败:
    //   1) ACTION_APPLICATION_DEVELOPMENT_SETTINGS 直达开发者选项(部分机型/高 API 已废弃或无 handler)
    //   2) 失败则回退 ACTION_SETTINGS 主设置页(用户自己进开发者选项)
    // 用 resolveActivity 预检避免 startActivity 抛 ActivityNotFound; 两者都无 handler→返回 false, JS 弹手动路径提示。
    fun openAdbDevSettings(): Boolean {
        val pm = activity.packageManager
        val intents = listOf(
            android.content.Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS),
            android.content.Intent(Settings.ACTION_SETTINGS),
        )
        for (it in intents) {
            it.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
            if (it.resolveActivity(pm) == null) continue
            val ok = runCatching { activity.startActivity(it); true }.getOrDefault(false)
            if (ok) return true
        }
        return false
    }
    // ── 无障碍持久化(v2.29): 机制在 A11yPersist(WRITE_SECURE_SETTINGS 静默回写), 引导/策略 UI 在前端 ──
    // 聚合状态(设置卡渲染用); grantCmd 单一真相源在 Kotlin(前端不硬编码包名)。
    // selfAdbOn = 已连 或 可自动重连(证书在盘 + 无线调试开, AdbController.shell 会透明 ensureConnected) → 一键授权可用。
    fun a11yPersistStatus(): String = runCatching {
        val st = AdbController.status(activity)
        org.json.JSONObject()
            .put("a11yOn", activity.isA11yOn())
            .put("hasWriteSecure", A11yPersist.hasWriteSecure(activity))
            .put("persistEnabled", A11yPersist.persistEnabled(activity))
            .put("selfAdbOn", st.connected || (st.paired && !st.repairNeeded && activity.adbWifiOn()))   // 手机已撤销信任时一键授权不可用
            .put("grantCmd", "adb shell " + A11yPersist.grantCmd(activity))
            .toString()
    }.getOrElse { """{"a11yOn":false,"hasWriteSecure":false,"persistEnabled":false,"selfAdbOn":false}""" }
    // ── Shizuku 第二条 shell 通道(stepOS 全屏启动用; 与 self-ADB 等价, 只是来源不同) ──
    // installed = 管理器是否已装(用于 UI 区分「未安装」与「未授权」两种引导);
    // ready = binder 活着 ∧ 已授权(真值源全在 Kotlin, 前端零缓存零镜像)。
    fun shizukuStatus(): String = org.json.JSONObject()
        .put("installed", ShizukuShell.installed(activity))
        .put("ready", ShizukuShell.ready())
        .toString()

    /** 跳 Shizuku 管理器(未安装/服务未启动时引导用户去那边操作)。返回是否真的拉起了管理器页面。 */
    fun openShizukuManager(): Boolean {
        val pm = activity.packageManager
        val intent = pm.getLaunchIntentForPackage("moe.shizuku.privileged.api")
            ?.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK) ?: return false
        return runCatching { activity.startActivity(intent); true }.getOrDefault(false)
    }
    // P1 一键授权: 复用既有自连通道(AdbController.shell 以 shell 身份跑 pm grant, 零新实现)。
    // 异步 jobId+轮询(仿 pdfRender): shell 是 @Synchronized 阻塞调用(可能与 agent 的 adb 使用串行排队), 不能冻结 JS 桥。
    fun a11yGrantViaSelfAdb(): String {
        val id = activity.jobs.newId("g")
        Thread {
            activity.jobs.set(id, runCatching {
                AdbController.shell(activity, A11yPersist.grantCmd(activity), 20_000)
                // shell 未抛 → 先落 persist 开关(一键持久化 = 授权+开启), 不卡在 hasWriteSecure 门后:
                //   部分 OEM 进程内权限缓存(PropertyInvalidatedCache)对刚授予的开发级权限可能到进程重启才刷新,
                //   若等真值才置位, 授权实际成功却因此永不 auto-heal(静默失效); 反之真没授上,
                //   onResume 自愈门禁 hasWriteSecure 自然短路 → 乐观置位零副作用。
                A11yPersist.setPersistEnabled(activity, true)
                var ok = A11yPersist.hasWriteSecure(activity)   // 状态接地: 不信命令输出, 只认权限真值
                if (!ok) { Thread.sleep(300); ok = A11yPersist.hasWriteSecure(activity) }   // 权限缓存可能滞后, 稍候重读一次再定成败(后台线程, 不冻结桥)
                Analytics.track("""{"event":"a11y_persist_grant","props":{"ok":$ok,"via":"self_adb"}}""")
                if (ok) {
                    A11yPersist.reEnable(activity)
                    "ok"
                } else "err:not-granted"
            }.getOrElse {
                Analytics.track("""{"event":"a11y_persist_grant","props":{"ok":false,"via":"self_adb","cat":"exception"}}""")
                "err:" + (it.message ?: it.javaClass.simpleName)
            })
        }.apply { isDaemon = true; name = "a11y-grant" }.start()
        return id
    }
    // OEM 后台保活引导深链(P2): which=details(自启动/电池入口所在的应用详情)|battery(省电优化白名单)。
    // 厂商自启动管理页尽力而为(组件名随版本漂移), resolveActivity 预检+runCatching 逐个尝试, 兜底通用页(同 openAdbDevSettings 先例)。
    fun openAppSysSettings(which: String): Boolean {
        val pm = activity.packageManager
        val pkgUri = Uri.parse("package:${activity.packageName}")
        val intents = when (which) {
            "battery" -> listOf(android.content.Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS),
                                android.content.Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, pkgUri))
            else -> OemAutostart.oemAutostartIntents() + listOf(android.content.Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, pkgUri),
                                                   android.content.Intent(Settings.ACTION_SETTINGS))
        }
        for (i in intents) {
            i.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
            if (i.resolveActivity(pm) == null) continue
            if (runCatching { activity.startActivity(i); true }.getOrDefault(false)) return true
        }
        return false
    }
    // 系统通知(应用退到后台时): 让用户不用守着屏幕也知道(issue#4 #5)。
    // 两级: "完成"=普通通道; "需要操作"(ask_user)=高优先级通道(抬头横幅+声音), 提醒级别不同(issue#5)。
    fun notify(title: String, body: String, level: String) {
        runCatching {
            val nm = activity.getSystemService(android.content.Context.NOTIFICATION_SERVICE) as android.app.NotificationManager
            val high = level == "high"
            val chId = if (high) "ga_alert" else "ga_done"
            if (android.os.Build.VERSION.SDK_INT >= 26)
                nm.createNotificationChannel(android.app.NotificationChannel(chId,
                    if (high) "GenericAgent · 需要操作" else "GenericAgent",
                    if (high) android.app.NotificationManager.IMPORTANCE_HIGH
                    else android.app.NotificationManager.IMPORTANCE_DEFAULT))
            val pi = android.app.PendingIntent.getActivity(activity, 0,
                android.content.Intent(activity, MainActivity::class.java).addFlags(android.content.Intent.FLAG_ACTIVITY_SINGLE_TOP),
                android.app.PendingIntent.FLAG_IMMUTABLE or android.app.PendingIntent.FLAG_UPDATE_CURRENT)
            val n = android.app.Notification.Builder(activity, chId)
                .setSmallIcon(android.R.drawable.ic_popup_reminder)
                .setContentTitle(title).setContentText(body)
                .setPriority(if (high) android.app.Notification.PRIORITY_HIGH else android.app.Notification.PRIORITY_DEFAULT)
                .setAutoCancel(true).setContentIntent(pi).build()
            nm.notify(if (high) 1002 else 1001, n)
        }
    }
}
