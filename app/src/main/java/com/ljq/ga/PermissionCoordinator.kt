package com.ljq.ga

import android.content.Context
import android.content.Intent
import android.provider.Settings
import org.json.JSONObject

class PermissionCoordinator(
    private val activity: MainActivity,
    private val webCallbacks: WebCallbacks,
) {
    /** Called off the UI thread after the Activity leaves; the task snapshot is read-only. */
    fun restoreBackgroundOverlay() {
        if (!Py.ready) return
        val snapshot = runCatching { JSONObject(Py.call("poll_all", "-1")) }.getOrNull() ?: return
        val sessions = snapshot.optJSONArray("sessions") ?: return
        val busy = (0 until sessions.length()).any {
            val session = sessions.optJSONObject(it)
            session != null && (session.optBoolean("running") || session.optJSONObject("ask") != null)
        }
        activity.runOnUiThread {
            if (MainActivity.live !== activity || activity.isDestroyed) return@runOnUiThread
            val always = activity.getSharedPreferences("ga", Context.MODE_PRIVATE).getBoolean("float_always_on", false)
            val suppressed = BusA11yService.instance?.foregroundPkg() == "com.tencent.mm"
            if (!needsBackgroundOverlay(Settings.canDrawOverlays(activity), MainActivity.isForeground,
                    busy, always, suppressed) || FloatService.live != null) return@runOnUiThread
            val intent = Intent(activity, FloatService::class.java).putExtra("trigger", "background")
            runCatching {
                if (android.os.Build.VERSION.SDK_INT >= 26) activity.startForegroundService(intent)
                else activity.startService(intent)
            }.onFailure {
                FloatService.lastError = it.javaClass.simpleName + ": " + it.message.orEmpty()
            }
        }
    }

    // 悬浮窗授权往返闭环: 用户从系统授权页返回 → 上报 float_perm_result(ok/from/secs, 补齐 denied 之后的漏斗断点)。
    //   授权成功自动接续原动作: button→直接进悬浮窗模式(完成用户原意图); always_on→补落开关+回推前端(免二次手点)。
    //   必须在下方 alwaysOn 读取之前处理: 补落的 SP 值要在同一趟 onResume 里生效(服务由既有分支拉起)。
    // 返回 false: 调用方(Activity.onResume)应立即 return, 不再跑后续逻辑(如 Analytics.drainAgentEvents)。
    fun pushResumeState(): Boolean {
        // 采集会话真值收敛(与下方所有分支无关, 故放最前, 任何提前 return 都不该跳过它):
        //   任务管理器手停 / OEM 杀后台后会留下"current 指针还在但服务已死"的幻影, 上层会一直以为还在录。
        //   回前台第一件事就是把幻影收敛掉并补一条显式缺口 —— 假数据比没数据危险得多。
        runCatching { Sense.reconcile(activity) }
        val sp = activity.getSharedPreferences("ga", Context.MODE_PRIVATE)
        sp.getString("overlay_perm_pending", null)?.let { from ->
            val ts = sp.getLong("overlay_perm_ts", System.currentTimeMillis())
            sp.edit().remove("overlay_perm_pending").remove("overlay_perm_ts").apply()
            val ok = Settings.canDrawOverlays(activity)
            val secs = ((System.currentTimeMillis() - ts) / 100) / 10.0   // 0.1s 精度
            Analytics.track("""{"event":"float_perm_result","props":{"ok":$ok,"from":"$from","secs":$secs}}""")
            if (ok) when (from) {
                "always_on" -> {
                    sp.edit().putBoolean("float_always_on", true).apply()
                    webCallbacks.onFloatAlways(true)
                }
                else -> { activity.toFloat(); return false }   // 悬浮窗模式会 moveTaskToBack, 后续 onResume 逻辑无需再跑
            }
        }
        // 悬浮窗常开开关关闭时: 回前台收起悬浮球(原行为)。开启且有权限时: 保持常驻(不 stop),
        //   并确保服务在跑(用户可能刚重装/冷启还没起过服务)。权限被撤销则退化为收起。
        val alwaysOn = sp.getBoolean("float_always_on", false)
        if (alwaysOn && Settings.canDrawOverlays(activity)) {
            if (FloatService.live == null) {
                val fsi = Intent(activity, FloatService::class.java).putExtra("trigger", "always")
                if (android.os.Build.VERSION.SDK_INT >= 26) activity.startForegroundService(fsi) else activity.startService(fsi)
            }
        } else {
            activity.stopService(Intent(activity, FloatService::class.java))
            // 常开开着却没权限(用户去系统撤了 overlay 权限): 真值源 SP 落 false, 假"开"由下方统一回推纠正。
            if (alwaysOn) sp.edit().putBoolean("float_always_on", false).apply()
        }
        // 无条件回推有效常开态(仿 gaOnA11y): 前端镜像(kv)可因授权往返时 WebView 未加载、登录切 kv 命名空间等
        // 与 SP 分叉(真机实证: SP=true 服务在跑而开关显示关)。每次 onResume 以 SP 真值收敛, 消灭双向假态。
        webCallbacks.onFloatAlways(sp.getBoolean("float_always_on", false))
        // 从悬浮窗/后台返回: WebView 挂起期间布局重排会把会话列表停在中部, 后台不可靠触发 visibilitychange,
        // 故主动驱动前端回底(前端 gaOnResume 仅在原本贴底/任务运行中才回底, 尊重上滑看历史)。
        webCallbacks.onResumeSync()
        // 无障碍自愈(v2.29): 持久化开 ∧ 已授 WRITE_SECURE_SETTINGS ∧ 服务被系统摘除(OEM force-stop 策略)
        //   → 静默写回。必须在下行 gaOnA11y 回推之前: 前端拿到的即恢复后状态(用户开 app 无感, 免系统开关+10s 倒计时)。
        runCatching {
            if (A11yPersist.persistEnabled(activity) && A11yPersist.hasWriteSecure(activity) && !activity.isA11yOn()) {
                val healed = A11yPersist.reEnable(activity)
                Analytics.track("""{"event":"a11y_heal","props":{"ok":$healed}}""")
            }
        }
        // 无线调试自动开启(与上行同钥匙 WRITE_SECURE_SETTINGS, 幂等 best-effort): 省掉用户手动进开发者选项,
        // 让 self-ADB 这条 shell 通道随时可连(stepOS 全屏启动的前提)。必须在下行 onAdb 回推**之前**:
        // 前端拿到的即开启后的真值, 不会出现"设置页显示关、实际已开"的分叉。失败半径=维持现状(用户仍可手动开)。
        runCatching {
            if (A11yPersist.hasWriteSecure(activity)) {
                val wifiOn = A11yPersist.ensureWirelessDebugging(activity)
                if (wifiOn && !activity.adbWifiOn()) Analytics.track("""{"event":"adb_wifi_auto","props":{"ok":true}}""")
            }
        }
        // 回推无障碍最新状态: 用户可能刚从系统无障碍设置页开完权限返回, 让前端即时更新横幅/红点/引导。
        webCallbacks.onA11y(activity.isA11yOn())
        // 回推无线调试自连最新状态: 用户可能刚从开发者选项/无线调试页返回; JS 侧自己重读 adbSelfStatus, 单一真值源(无需入参)。
        webCallbacks.onAdb()
        // 回推 Shizuku 状态: 用户可能在管理器里授权后直接切回 GA, 不会经过 GA 自己的
        // requestPermission 回调; 不在这里重读, 状态行/红点会一直停在旧值。
        webCallbacks.onShizuku()
        return true
    }
}
