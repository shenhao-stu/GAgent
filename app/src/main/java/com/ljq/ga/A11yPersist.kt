package com.ljq.ga

import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager
import android.provider.Settings

/**
 * 无障碍持久化: MIUI/Flyme 等 OEM 在 force-stop/系统杀进程时会把本 app 的无障碍服务从
 * ENABLED_ACCESSIBILITY_SERVICES 摘除, 重开要走系统开关 + ~10s 强制倒计时; 进程保活救不了
 * (OEM 策略挂在 disable 事件上)。唯一稳妥修复 = 持有 WRITE_SECURE_SETTINGS(开发级权限,
 * `adb shell pm grant` 一次, 卸载前永久有效), app 启动时把服务静默写回系统列表。
 * 单一真相源: 用户开关 = SP("ga").a11y_persist; 生效态 = 系统 secure setting 本身(不镜像不缓存)。
 */
object A11yPersist {
    private const val SP_KEY = "a11y_persist"

    /** 设备侧 shell 命令(P0 电脑 adb / P1 自连均执行它); 完整命令行由前端拼 "adb shell " 前缀展示。 */
    fun grantCmd(ctx: Context) = "pm grant ${ctx.packageName} android.permission.WRITE_SECURE_SETTINGS"

    fun hasWriteSecure(ctx: Context): Boolean =
        ctx.checkSelfPermission(android.Manifest.permission.WRITE_SECURE_SETTINGS) ==
            PackageManager.PERMISSION_GRANTED

    fun persistEnabled(ctx: Context): Boolean =
        ctx.getSharedPreferences("ga", Context.MODE_PRIVATE).getBoolean(SP_KEY, false)

    fun setPersistEnabled(ctx: Context, on: Boolean) =
        ctx.getSharedPreferences("ga", Context.MODE_PRIVATE).edit().putBoolean(SP_KEY, on).apply()

    /**
     * 无线调试自动开启(stepOS 全屏启动降门槛, 复用同一把 WRITE_SECURE_SETTINGS 钥匙)。
     *
     * 为什么: stepOS 按调用者 uid 把第三方 App 拉起的 task 收进小窗, 全屏启动只有 shell uid 的
     * `am start-activity --windowingMode 1` 可解(见 [BusA11yService.launchFullscreenViaShell])。
     * self-ADB 是两条 shell 通道之一, 但它要用户手动进开发者选项开无线调试——这一步可以省掉:
     * 已授 WRITE_SECURE_SETTINGS 时直接写 `adb_wifi_enabled=1`(DSHA-Amoo BootReceiver 同款做法)。
     *
     * 契约(与 [reEnable] 同构): 只在已授权时写; 幂等(已开=零写入); best-effort 失败静默返回 false,
     * 失败半径=维持现状(用户仍可手动开)。不在开机广播里做——那要新增 BOOT_COMPLETED 接收器,
     * 而本 app 的常驻链路(FloatService/权限协调)本就在进程活着时反复经过, 挂那里足够且零新增组件。
     */
    fun ensureWirelessDebugging(ctx: Context): Boolean {
        if (!hasWriteSecure(ctx)) return false
        return runCatching {
            val cr = ctx.contentResolver
            if (Settings.Global.getInt(cr, "adb_wifi_enabled", 0) == 1) true
            else {
                Settings.Global.putInt(cr, "adb_wifi_enabled", 1)
                Settings.Global.getInt(cr, "adb_wifi_enabled", 0) == 1   // 状态接地: 不信写入动作, 只认回读真值
            }
        }.getOrDefault(false)
    }

    /**
     * 把本包的无障碍服务写回「已启用服务」列表(幂等): 只追加本包组件、保留其他 app 的服务, 绝不整表覆盖;
     * 已在表且总开关已开 → 零写入。返回写后是否在表。无权限/写失败 → false(best-effort, 失败半径=维持现状)。
     */
    fun reEnable(ctx: Context): Boolean {
        if (!hasWriteSecure(ctx)) return false
        return runCatching {
            val cr = ctx.contentResolver
            val list = (Settings.Secure.getString(cr, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: "")
                .split(':').filter { it.isNotBlank() }
            if (list.none { it.substringBefore('/').equals(ctx.packageName, true) }) {   // 与 MainActivity.isA11yOn 同谓词(按包匹配, 兼容全称/缩写两种组件写法)
                val comp = ComponentName(ctx, BusA11yService::class.java).flattenToString()
                Settings.Secure.putString(cr, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES,
                    (list + comp).joinToString(":"))
            }
            if (Settings.Secure.getInt(cr, Settings.Secure.ACCESSIBILITY_ENABLED, 0) != 1)
                Settings.Secure.putInt(cr, Settings.Secure.ACCESSIBILITY_ENABLED, 1)
            true
        }.getOrDefault(false)
    }
}
