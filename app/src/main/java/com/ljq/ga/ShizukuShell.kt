package com.ljq.ga

import android.content.Context
import android.content.pm.PackageManager
import android.util.Log
import rikka.shizuku.Shizuku

/**
 * Shizuku shell 通道: 用户在 Shizuku 管理器里授权本 app 后, 即取得 shell(uid 2000) 执行能力。
 *
 * 为什么需要第二条通道(stepOS 真机实证):
 *  stepOS 的 `StepOSMiniWindowControllerImpl` 在 `ActivityStarter.computeLaunchParams` 阶段按**调用者 uid**
 *  决策——第三方 App(uid≠shell) 拉起的 task 被改写成 OEM 私有的 `stepos-mini-window`(小窗),
 *  而 App 侧无解: `ActivityOptions.setLaunchWindowingMode` 是 @hide 且被 hidden API 策略拦截
 *  (logcat 实证 `api=blocked ... denied`); 手工构造 `android.activity.windowingMode` Bundle 也被该钩子覆盖。
 *  已验证的出口只有 shell uid 的 `am start-activity --windowingMode 1`。
 *  self-ADB([AdbController]) 与 Shizuku 在这条路径上等价, 只是通道来源不同——用户不必为了全屏启动
 *  先去开发者选项开无线调试并配对。
 *
 * 实现取舍: 只用 `Shizuku.newProcess` 直起单条命令, **不**走 DSHA-Amoo 那套 UserService + AIDL +
 * provider 依赖(那套要 AIDL 文件、manifest 声明 Service、provider 收 Binder, 对「跑一条 am start」过重)。
 *  代价是没有跨进程的命令队列与超时管控, 由本对象的读净 + destroyForcibly 兜住。
 */
object ShizukuShell {
    private const val TAG = "ShizukuShell"

    private val main = android.os.Handler(android.os.Looper.getMainLooper())
    @Volatile private var listening = false
    @Volatile private var appCtx: Context? = null

    /**
     * 注册 binder 监听。**必须调用**——不注册时管理器启动服务后本 app 收不到 binder 分发,
     * `available()` 恒 false, 通道等于不存在(真机实证: 只加 api/provider 依赖但不注册监听, 管理器列表里能看到 GA,
     * 授权后 GA 侧仍 pingBinder=false)。
     * 幂等; 未装管理器时零副作用(监听回调永不触发)。放在 [App.onCreate] 尽早注册。
     */
    fun init(ctx: Context) {
        appCtx = ctx.applicationContext
        if (listening) return
        listening = true
        runCatching {
            Shizuku.addBinderReceivedListenerSticky { main.post { /* 通道就绪: 无本地状态可刷新, 状态面均实时读 */ } }
            Shizuku.addBinderDeadListener { main.post { /* 通道断开: 同上, 无缓存可清 */ } }
        }.onFailure { listening = false }
    }

    /** 管理器是否已安装(用于 UI 区分「未安装」与「未授权」两种引导)。 */
    fun installed(ctx: Context): Boolean = runCatching {
        ctx.packageManager.getLaunchIntentForPackage("moe.shizuku.privileged.api") != null
    }.getOrDefault(false)

    /**
     * 请求授权(弹系统对话框)。已授权则立即回调 GRANTED; 未授权时异步等用户决定。
     * 必须在主线程调用(Shizuku 内部要求); 由 JS 桥经 runOnUiThread 转入。
     */
    fun requestPermission(onResult: (Boolean) -> Unit) {
        main.post {
            if (hasPermission()) { onResult(true); return@post }
            val code = REQUEST_CODE
            // object 表达式而非 SAM 转换: lambda 在构造期求值, 拿不到尚未赋值的 listener 引用( Kotlin 报 Unresolved reference)
            val listener = object : Shizuku.OnRequestPermissionResultListener {
                override fun onRequestPermissionResult(requestCode: Int, grantResult: Int) {
                    if (requestCode != code) return
                    runCatching { Shizuku.removeRequestPermissionResultListener(this) }
                    onResult(grantResult == PackageManager.PERMISSION_GRANTED)
                }
            }
            runCatching {
                Shizuku.addRequestPermissionResultListener(listener)
                Shizuku.requestPermission(code)
            }.onFailure { onResult(false) }
        }
    }

    private const val REQUEST_CODE = 9527

    /**
     * `Shizuku.newProcess` 在 api 13.1.5 里是 **private**(javap 实证), 公开面只有 UserService 那一套
     * (bindUserService + 自带 AIDL Service + manifest 声明, 对「跑一条 am start」过重)。
     * 但其返回类型 `ShizukuRemoteProcess` 是 public 且 `extends java.lang.Process`, 故反射调用后按 Process 用。
     * ⚠ 反射的是**第三方库类**而非框架类: Android 的 hidden-API 策略只拦框架的非 SDK 接口
     * (stepOS 上 `ActivityOptions.setLaunchWindowingMode` 正是那样被 `api=blocked` 拒的), 库类反射不受此限。
     * 探测结果缓存; 库升级致签名漂移时 exec 返回 null, 调用方降级——不打断主流程。
     */
    private val newProcess: java.lang.reflect.Method? by lazy {
        runCatching {
            Shizuku::class.java
                .getDeclaredMethod("newProcess", Array<String>::class.java, Array<String>::class.java, String::class.java)
                .apply { isAccessible = true }
        }.getOrNull()
    }

    /** Shizuku binder 是否活着(管理器在跑且服务已启动)。不抛异常, 未装管理器时为 false。 */
    fun available(): Boolean = runCatching { Shizuku.pingBinder() }.getOrDefault(false)

    /** 本 app 是否已被用户授权(API_V23 权限)。 */
    fun hasPermission(): Boolean = runCatching {
        available() && Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED
    }.getOrDefault(false)

    /** 通道是否就绪: binder 活着 ∧ 已授权。 */
    fun ready(): Boolean = hasPermission()

    /** 只读状态串, 供 /adb/status 之类的诊断面如实反映「哪条 shell 通道可用」。 */
    fun status(): String = "shizuku(binder=${available()},permission=${hasPermission()})"

    /**
     * 跑一条非交互 shell 命令, 收全部输出后返回(适合 `am start` 这类短命令)。
     * 未授权 / binder 死 / 反射不可用 / 读流失败一律返回 null, 由调用方决定降级——不抛异常打断调用方主流程。
     * 失败原因一律记 logcat(TAG), 便于真机定位"通道就绪却没跑成"。
     */
    fun exec(cmd: String, timeoutMs: Long = 20_000): String? {
        if (!ready()) { Log.w(TAG, "exec skipped: channel not ready"); return null }
        val method = newProcess ?: run { Log.w(TAG, "exec skipped: newProcess reflection unavailable"); return null }
        val process = runCatching {
            // env/dir 传 null: 继承 Shizuku 服务进程的环境; 命令是纯 ASCII 的 am 调用, 无编码协商问题
            method.invoke(null, arrayOf("sh", "-c", cmd), null, null) as? java.lang.Process
        }.getOrNull() ?: run { Log.w(TAG, "exec skipped: newProcess invoke failed for: $cmd"); return null }
        return try {
            val out = process.inputStream.bufferedReader().use { it.readText() }
            // 不把 waitFor 超时当失败: 输出已到手即命令已执行完(am 的输出在进程退出前才 flush, 能读到就说明跑完了);
            // 超时只说明进程句柄还没回收(极少见), 输出内容本身足以判定成败。等退出码只为兜底回收, 不作为成功条件。
            runCatching { process.waitFor(timeoutMs, java.util.concurrent.TimeUnit.MILLISECONDS) }
            Log.i(TAG, "exec ok (${out.length} chars): ${out.take(300)}")
            out
        } catch (e: Exception) {
            Log.w(TAG, "exec read failed: ${e.javaClass.simpleName}: ${e.message}")
            null
        } finally {
            runCatching { process.destroyForcibly() }
        }
    }
}
