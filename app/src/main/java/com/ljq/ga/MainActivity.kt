package com.ljq.ga

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.provider.Settings
import android.speech.tts.TextToSpeech
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.TextView
import android.webkit.JavascriptInterface
import android.webkit.PermissionRequest
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import java.util.Locale
import androidx.core.content.FileProvider
import androidx.webkit.WebSettingsCompat
import androidx.webkit.WebViewFeature
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import com.google.zxing.integration.android.IntentIntegrator
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.json.JSONObject
import com.journeyapps.barcodescanner.CaptureActivity

// Dedicated portrait scanner with an explicit close control in addition to system Back.
class GanetQrCaptureActivity : CaptureActivity() {
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        val density = resources.displayMetrics.density
        val close = TextView(this).apply {
            text = "关闭"
            textSize = 14f
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
            setPadding((16 * density).toInt(), (8 * density).toInt(),
                       (16 * density).toInt(), (8 * density).toInt())
            background = GradientDrawable().apply {
                setColor(0xE61D1D1F.toInt())
                cornerRadius = 999 * density
                setStroke((1 * density).toInt(), 0x33FFFFFF)
            }
            elevation = 6 * density
            setOnClickListener { setResult(Activity.RESULT_CANCELED); finish() }
        }
        addContentView(close, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT,
            Gravity.TOP or Gravity.END).apply {
                topMargin = (20 * density).toInt() + (window.decorView.rootWindowInsets?.systemWindowInsetTop ?: 0)
                marginEnd = (16 * density).toInt()
            })
    }
}

// 极薄壳: UI全在 assets/gacore/webui (随filesDir热更), 逻辑全在 android_entry.py
class MainActivity : Activity() {
    companion object {
        @Volatile var live: MainActivity? = null
        @Volatile var isForeground = false
    }
    fun evalJs(js: String) { webCallbacks.raw(js) }

    private val exec = Executors.newSingleThreadExecutor()
    private val assetUnpacker = AssetUnpacker(this)
    private val mediaBridge = MediaBridge(this)
    private val sysBridge = SysBridge(this)
    @Volatile private var bootMsg = ""
    private lateinit var web: WebView
    internal lateinit var webCallbacks: WebCallbacks
    private lateinit var permissionCoordinator: PermissionCoordinator
    internal var tts: TextToSpeech? = null            // 原生朗读: WebView 的 speechSynthesis 多无引擎, 用系统 TTS 兜底(issue#5)
    @Volatile internal var ttsReady = false
    @Volatile internal var ttsFailed = false          // 无 TTS 引擎: 立即回退 speechSynthesis, 不卡在 "init"
    private var fileCb: ValueCallback<Array<Uri>>? = null   // <input type=file> 回调: 需 WebChromeClient.onShowFileChooser 才能弹选择器(issue#5)
    private var camUri: Uri? = null                          // 本次是否走"拍照": 非空表示等相机写回此 URI(issue#1)
    private var camFile: File? = null                        // 相机输出的实际文件(cacheDir/cam/IMG_*.jpg)
    private var camForBridge = false                         // true=经 GA.openCamera 直连(回推 WebUI); false=经 onShowFileChooser(回填 fileCb)(issue#2)
    private val FILE_REQ = 4011
    private val MIC_REQ = 8
    private var pendingMicRequest: PermissionRequest? = null
    private var micPermissionInFlight = false
    private val SENSE_REQ = 9                                 // sense 采集类权限的按需申请(见 requestSensePerms)
    @Volatile private var senseLatch: CountDownLatch? = null   // 桥线程等、UI 线程放: 让"申请→用户点完"能在一次调用内闭环
    private val QR_REQ = 4012
    private val CAM_PERM_QR = 4013
    private var pendingQrAfterPerm = false
    @Volatile private var launchSrc = "launcher"             // 本次 Activity 创建的唤起来源(launcher|float|notif_task|notif_keepalive)
    @Volatile private var launchCid = ""                      // per-cid 任务通知目标；冷启动由 launchInfo 交给 JS
    // amoo(StepOS 语音助手) 派活: 服务只拉起 Activity, 真正的入队等 python boot 完再执行(见 AmooBridge)
    @Volatile private var amooTask = ""
    @Volatile private var amooCid = ""
    private var fgSince = 0L                                  // 本次前台会话起点(onResume 置位): onStop 上报 app_bg{fg_s} 会话时长
    // 悬浮窗授权往返意图(SP 持久化, key=overlay_perm_pending/overlay_perm_ts): 用户经引导弹窗去了系统授权页。
    // 存 SP 而非内存: 部分 ROM 授予 overlay 权限时会杀进程重启 app, 内存标记必丢 → 漏斗照样断。
    // onResume 据此上报 float_perm_result 闭环(46% 被拒设备从未成功的漏斗断点), 授权成功则自动接续原动作。

    // ── M1 nudge 推送通道(PLAN_MOTION_CADENCE §3-S1): Python 事件 → 50ms 合并批 → WebView「有新东西」信号 ──
    // 推的是信号不是数据: JS 收到 nudge 走现有 poll 取数(poll 仍是唯一数据源); 通道任一环失效 → JS 心跳兜底, 功能零损失。
    private val nudgeHandler = android.os.Handler(android.os.Looper.getMainLooper())
    @Volatile private var nudgeProxy: androidx.webkit.JavaScriptReplyProxy? = null   // JS 握手取得; 页面重建后旧 proxy 静默作废(M0 实证: 不抛异常), 以最新握手为准
    private var nudgeBatching = false          // 仅主线程读写(Handler 串行化) → 强制 50ms 合并批, 绝不逐事件推
    private val nudgeCb = Runnable {           // Python 会话/工具线程进来: 只投递主线程 Handler, 不在 Python 线程碰 WebView(§6 线程安全)
        nudgeHandler.post {
            if (!nudgeBatching) {
                nudgeBatching = true
                nudgeHandler.postDelayed({ nudgeBatching = false; pushNudge() }, 50)
            }
        }
    }
    private fun pushNudge() {   // 主线程。降级链: replyProxy → evaluateJavascript(JS 未定义入口则无操作) → 维持现状轮询
        nudgeProxy?.let { p ->
            try { p.postMessage("nudge"); return } catch (_: Throwable) {}
        }
        try { web.evaluateJavascript("window.gaPushNudge&&window.gaPushNudge()", null) } catch (_: Throwable) {}
    }
    private fun registerNudgeCallback() {      // Py.boot 成功后同一 exec 块内首注册(GA_DIR 已入 sys.path)
        runCatching { Python.getInstance().getModule("plugins.push_nudge_hook").callAttr("set_nudge_callback", nudgeCb) }
    }
    internal fun ensureNudgeRegistered() {     // poll 桥旁懒重试: bootstrap 缺章自愈重跑 init 会重导入插件模块 → 已注册回调丢失(§6)
        if (!Py.ready) return
        runCatching {
            val m = Python.getInstance().getModule("plugins.push_nudge_hook")
            if (m.callAttr("has_callback").toString() != "True") m.callAttr("set_nudge_callback", nudgeCb)
        }
    }

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        live = this
        // 唤起来源(回访钩子归因): 悬浮窗/通知拉起会带 ga_src extra, 桌面图标启动无 extra → launcher。
        // app_open 由 JS 在页面 boot 时上报, 与 Activity 创建一一对应, 故 onCreate 取一次即可。
        launchSrc = intent?.getStringExtra("ga_src") ?: "launcher"
        launchCid = intent?.getStringExtra("convo_cid").orEmpty()
        takeAmooTask(intent)
        ensureAllFilesAccess()
        VoiceClient.init(this)
        web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.allowFileAccess = true
            settings.domStorageEnabled = true   // 不显式开启时 file:// 下 localStorage.setItem 抛错 → 所有 LS.set 失败(头像"附件保存失败"根因); 开启后作为 LS 快取, 持久仍以设备 kv 为准
            // 页面完整自带 light/dark(data-theme + color-scheme, 由 JS applyTheme 单一掌控)。两层都要关 OS 强制变暗:
            // ① 内容层(API33+ 算法变暗) ② View 层(API29+ forceDark) — 部分 OEM(如魅族 Flyme)系统深色会在 View 层
            // 强制反相浅色页面, 仅关①仍显暗(真机 adb 实证); setForceDarkAllowed 是通用安卓接口, 一次声明本视图自管深浅。
            if (WebViewFeature.isFeatureSupported(WebViewFeature.ALGORITHMIC_DARKENING)) {
                WebSettingsCompat.setAlgorithmicDarkeningAllowed(settings, false)
            }
            if (android.os.Build.VERSION.SDK_INT >= 29) {
                @Suppress("DEPRECATION") isForceDarkAllowed = false
            }
            addJavascriptInterface(Bridge(), "GA")
            // M1 nudge 通道: 注册须在 loadUrl 前(loadUrl 在 exec 异步块, 此处必然先行); file:// origin ⇒ allowedOriginRules 只能 "*"(M0 e2e 实证)。
            // Kotlin→JS 推送只能经 JS 先 postMessage 握手取得的 JavaScriptReplyProxy; 任何页内握手都刷新为最新 proxy(页面重建重握手)。
            try {
                if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
                    androidx.webkit.WebViewCompat.addWebMessageListener(this, "GAPush", setOf("*")) { _, _, _, _, replyProxy ->
                        nudgeProxy = replyProxy
                    }
                }
            } catch (_: Throwable) {}
            // 主题由 JS applyTheme() 单一真相源决定(用户选择 system/light/dark, 存 LS)。
            // 旧 onPageFinished 按系统夜间强制 data-theme → 每次加载覆盖用户选择(浅色/跟随系统失效根因), 已移除。
            // 跟随系统由 JS 经 GA.isDark()(读系统 uiMode, 权威)解析, index.html 头部内联脚本预置避免闪白。
            webChromeClient = object : WebChromeClient() {
                // 仅在网页请求录音时申请麦克风；启动与文字输入不需要该权限。
                override fun onPermissionRequest(request: PermissionRequest?) {
                    request ?: return
                    runOnUiThread {
                        val audio = request.resources.filter { it == PermissionRequest.RESOURCE_AUDIO_CAPTURE }
                        when {
                            audio.isEmpty() || isFinishing || isDestroyed -> request.deny()
                            checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED ->
                                request.grant(audio.toTypedArray())
                            micPermissionInFlight -> request.deny()
                            else -> {
                                pendingMicRequest = request
                                micPermissionInFlight = true
                                runCatching { requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), MIC_REQ) }
                                    .onFailure { micPermissionInFlight = false; resolveMicRequest(false) }
                            }
                        }
                    }
                }
                override fun onPermissionRequestCanceled(request: PermissionRequest?) {
                    runOnUiThread {
                        if (pendingMicRequest === request) pendingMicRequest = null
                        // 系统弹框仍在途；旧结果返回前不能接管另一个网页请求。
                    }
                }
                override fun onShowFileChooser(
                    wv: WebView?, cb: ValueCallback<Array<Uri>>?, params: FileChooserParams?
                ): Boolean {
                    val prev = fileCb; fileCb = cb; prev?.onReceiveValue(null)   // 先就位再通知旧回调, 避免结果错配
                    camUri = null
                    // "拍照": 页面用 <input accept=image/* capture> 请求相机。createIntent() 只会给"选取"意图(于是出现"只能访问所选照片"),
                    // 不会真正打开相机 → 这里自行起 ACTION_IMAGE_CAPTURE。无相机/失败再落回普通选择器。(issue#1)
                    val wantCamera = try {
                        val p = params   // 局部 val 才能在 && 右侧智能转换为非空(params?.x==true 不触发智能转换)
                        p != null && p.isCaptureEnabled &&
                        (p.acceptTypes?.let { a -> a.isEmpty() || a.any { it.startsWith("image") || it == "*/*" } } ?: true)
                    } catch (e: Exception) { false }
                    if (wantCamera && launchCamera(false)) return true
                    val intent = (try { params?.createIntent() } catch (e: Exception) { null })
                        ?: Intent(Intent.ACTION_GET_CONTENT).apply { type = "*/*"; addCategory(Intent.CATEGORY_OPENABLE) }
                    // 仅当网页 <input multiple> 才允许多选: 否则 Android 13+ 系统照片选择器(PhotoPicker)进多选模式——
                    //  单选头像(无 multiple)被迫多选→结果 URI 走 clipData, 而框架 parseResult 只读 data.getData()
                    //  (所有 Chromium WebView 皆如此, 从不读 clipData)→取不到→onReceiveValue(null)→<input> 0 文件、
                    //  onchange 不触发→裁剪框永不弹。此为 Android 13+ 通用根因(非个别机型), 魅族21/Android16 实测命中。
                    if (params?.mode == FileChooserParams.MODE_OPEN_MULTIPLE) intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                    return try { startActivityForResult(Intent.createChooser(intent, "选择文件"), FILE_REQ); true }
                    catch (e: Exception) { fileCb?.onReceiveValue(null); fileCb = null; false }
                }
            }
            // 必须显式设 WebViewClient: 不设时 WebView 默认把【顶层导航】(如登录成功后 location.reload()
            //   重新跳到 file://index.html)当外部 URL 丢给系统 startActivity(Intent) → file:// URI 触发
            //   android.os.FileUriExposedException → 进程崩(华为 WebView 实证, 栈 shouldOverrideUrlLoadingExtend)。
            // 顶层外链交系统处理；不允许远端页面替换带原生桥的聊天页。
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(wv: WebView?, req: WebResourceRequest?): Boolean {
                    val url = req?.url ?: return false
                    if (url.toString() == "about:blank") return false
                    openExternalLink(url.toString())
                    return true // Remote pages never inherit the chat's native bridge.
                }
            }
        }
        setContentView(web)
        webCallbacks = WebCallbacks(web) { action -> runOnUiThread { action() } }
        permissionCoordinator = PermissionCoordinator(this, webCallbacks)
        setupGestureExclusion()                                  // 左缘留给 app 手势(右滑开抽屉), 减少被系统返回手势吞掉(issue#8)
        tts = TextToSpeech(this) { st -> if (st == TextToSpeech.SUCCESS) ttsReady = true else ttsFailed = true }
        tts?.setOnUtteranceProgressListener(object : android.speech.tts.UtteranceProgressListener() {   // 朗读自然结束/出错/被停 → 复位前端朗读键(切换态)
            override fun onStart(id: String?) {}
            override fun onDone(id: String?) = onSpeakEnded()
            @Suppress("OVERRIDE_DEPRECATION") override fun onError(id: String?) = onSpeakEnded()
            override fun onStop(id: String?, interrupted: Boolean) = onSpeakEnded()
        })
        if (android.os.Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED)
            runCatching { requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 7) }   // 任务完成通知(issue#4)
        exec.execute {
            assetUnpacker.extractAssets()
            runCatching {
                val kv = File(filesDir, "ga/kv").apply { mkdirs() }
                File(kv, "ga.android_device.json").writeText(JSONObject()
                    .put("manufacturer", android.os.Build.MANUFACTURER ?: "")
                    .put("model", android.os.Build.MODEL ?: "")
                    .toString())
            }
            runOnUiThread { web.loadUrl("file://${File(filesDir, "ga/webui/index.html").absolutePath}") }
            if (!Python.isStarted()) Python.start(AndroidPlatform(this))
            bootMsg = runCatching { Py.boot(File(filesDir, "ga").absolutePath, packageName) }.getOrElse { "ERR:" + it.toString() }   // I4: Py.boot 异常时加 ERR: 前缀 → ready() 返回值可被 webui boot 门(仅认 ok/nokey)识别为"未就绪", 退避重试而非误当已就绪跑会话恢复(临时失忆根因)
            registerNudgeCallback()   // M1: boot 成功后立即注册 nudge 回调(boot 失败时 Py.ready=false, ensureNudgeRegistered 会在其就绪后补注册)
            runAmooTaskIfPending()    // amoo 派来的任务: python 就绪后才入队(send2 异步, 秒回)
            // 契约文件: 把原生 cacheDir(应用运行时占用统计/清理用) 告诉 Python 侧, 失败半径小(不阻断启动)。
            runCatching { File(File(filesDir, "ga"), ".cache_path").writeText(cacheDir.absolutePath) }
        }
    }

    inner class Bridge {  // JS桥: 运行在WebView后台线程, 阻塞调Py安全
        @JavascriptInterface fun ready() = bootMsg
        // 系统是否深色(读 uiMode, 权威): "跟随系统"模式下 JS 据此解析主题, 不靠 WebView 的 prefers-color-scheme(部分 OEM 不准)
        @JavascriptInterface fun isDark(): Boolean =
            (resources.configuration.uiMode and android.content.res.Configuration.UI_MODE_NIGHT_MASK) ==
                android.content.res.Configuration.UI_MODE_NIGHT_YES
        // 启动上下文(app_open 埋点补充): src=唤起来源(回访钩子归因), notif=系统通知总开关是否放行
        // (P0 回访钩子的可触达面基线——推送做出来之前先知道多少设备能收到)。
        @JavascriptInterface fun launchInfo(): String = runCatching {
            val notif = getSystemService(android.app.NotificationManager::class.java).areNotificationsEnabled()
            "{\"src\":${JSONObject.quote(launchSrc)},\"notif\":$notif,\"cid\":${JSONObject.quote(launchCid)}}"
        }.getOrElse { "{\"src\":\"?\",\"notif\":false,\"cid\":\"\"}" }
        // APK 版本号(设置页"关于"显示): name+code。也是未来"检查更新"做版本比对的权威来源。
        @JavascriptInterface fun appVersion(): String = runCatching {
            val pi = packageManager.getPackageInfo(packageName, 0)
            val code = if (android.os.Build.VERSION.SDK_INT >= 28) pi.longVersionCode
                       else @Suppress("DEPRECATION") pi.versionCode.toLong()
            // channel=有效 OTA 通道(设置覆盖优先); buildChannel=构建戳(Analytics 同源)
            "{\"name\":${JSONObject.quote(pi.versionName ?: "")},\"code\":$code," +
                "\"channel\":${JSONObject.quote(Updater.channel(this@MainActivity))}," +
                "\"buildChannel\":${JSONObject.quote(BuildConfig.CHANNEL)}," +
                "\"packageName\":${JSONObject.quote(packageName)},\"repositoryUrl\":${JSONObject.quote(Endpoints.REPOSITORY_URL)}," +
                "\"updatesConfigured\":${Updater.manifestUrl(this@MainActivity).isNotBlank()}}"
        }.getOrElse { "{\"name\":\"\",\"code\":0,\"channel\":\"official\",\"buildChannel\":\"official\"}" }
        // 打开外部链接(官网/GitHub): 本壳未装 WebViewClient → 页面 <a href> 会把 file:// 页导航走,
        //  外链交系统可浏览 Activity；本地与可执行协议始终拒绝。
        @JavascriptInterface fun openUrl(url: String) {
            runOnUiThread { openExternalLink(url) }
        }

        // 可见登录浏览器(BrowserActivity, 与离屏自动化 WebView 共享 CookieManager 登录态)。
        // 固定空白起始页: 不接受任何预填 URL——"空白起始页"从调用点约定升级为 bridge 边界不变量,
        // 杜绝"预填 URL 钓鱼"原语(任何能在对话 WebView 执行 JS 的路径都无法让受信登录浏览器直落仿冒登录页)。
        // 唯一调用方(webui 顶栏按钮)本就传空; 未来若真需预填起始页, 另加白名单+确认弹层, 不复用此入口。
        @JavascriptInterface fun openBrowser() {
            runOnUiThread { runCatching { startActivity(Intent(this@MainActivity, BrowserActivity::class.java)) } }
        }
        // 应用内热更新: 机制在 Updater(取清单/下载/校验/装), 策略与 UI 在前端 app.js。
        // 双通道: otaManifest 按有效 channel 读 official/beta 清单; otaSetChannel 写设置覆盖(空串清回构建戳)。
        @JavascriptInterface fun otaManifest(): String = Updater.manifest(this@MainActivity)
        @JavascriptInterface fun otaChannel(): String = JSONObject()
            .put("channel", Updater.channel(this@MainActivity))
            .put("build", BuildConfig.CHANNEL)
            .put("url", Updater.manifestUrl(this@MainActivity)).toString()
        @JavascriptInterface fun otaSetChannel(ch: String): String = Updater.setChannel(this@MainActivity, ch)
        @JavascriptInterface fun otaDownload(url: String, sha256: String): String = Updater.download(this@MainActivity, url, sha256)
        @JavascriptInterface fun otaProgress(): String = Updater.progress()
        @JavascriptInterface fun otaInstall(): String {   // startActivity 走 UI 线程(同 openCamera 的 latch 取回结果)
            val latch = CountDownLatch(1); var r = ""
            runOnUiThread { r = Updater.install(this@MainActivity); latch.countDown() }
            runCatching { latch.await(4, TimeUnit.SECONDS) }
            return r
        }
        @JavascriptInterface fun send(t: String): String =
            if (Py.ready) runCatching { Py.call("send", t) }.getOrElse { it.toString() } else "引擎未就绪"
        @JavascriptInterface fun scanGanetQr() = runOnUiThread {
            IntentIntegrator(this@MainActivity).setDesiredBarcodeFormats(IntentIntegrator.QR_CODE)
                .setCaptureActivity(GanetQrCaptureActivity::class.java)
                .setPrompt("扫描电脑 GA 显示的设备互联二维码")
                .setBeepEnabled(false).setOrientationLocked(true).initiateScan()
        }
        @JavascriptInterface fun ganetQrStatus(jobId: String): String =
            if (Py.ready) runCatching { Py.call("ganet_qr_status", jobId) }
                .getOrDefault("{\"state\":\"security_failed\",\"message\":\"状态读取失败\"}")
            else "{\"state\":\"security_failed\",\"message\":\"引擎未就绪\"}"
        @JavascriptInterface fun poll(since: Int): String {
            ensureNudgeRegistered()   // M1: 每次 poll 桥调用旁懒重试(自愈重导入丢回调 → 心跳期内恢复推送)
            return if (Py.ready) runCatching { Py.call("poll", since.toString()) }.getOrDefault("") else ""
        }
        @JavascriptInterface fun abort() { if (Py.ready) runCatching { Py.call("abort") } }

        // ── P4a 多会话五桥（永不删旧 send/poll/abort；A13: Py 新入口缺失时回退 legacy）──
        // caps: JS 能力探测唯一锚点。返回 JSON 字符串（WebView 桥只能回 String/基本型）。
        @JavascriptInterface fun caps(): String {
            if (!Py.ready) return """{"multi":false,"version":1,"maxconc":1,"ready":false}"""
            return runCatching { Py.call("caps") }.getOrElse {
                // A13: 旧 assets 无 caps → 不宣称 multi，防前端走 sendC 而 py 无 send2
                """{"multi":false,"version":1,"maxconc":1,"ready":true,"legacy":true}"""
            }
        }
        @JavascriptInterface fun sendC(cid: String, t: String): String {
            if (!Py.ready) return "引擎未就绪"
            return runCatching { Py.call("send2", cid, t) }.getOrElse {
                // A13 回退焦点 send（可能串台，但比崩溃/静默丢消息更可观测）
                runCatching { Py.call("send", t) }.getOrElse { e -> e.toString() }
            }
        }
        @JavascriptInterface fun pollC(cid: String, since: String): String {
            ensureNudgeRegistered()   // M1: 懒重试(同 poll)
            if (!Py.ready) return ""
            return runCatching { Py.call("poll2", cid, since) }.getOrElse {
                runCatching { Py.call("poll", since) }.getOrDefault("")
            }
        }
        @JavascriptInterface fun abortC(cid: String) {
            if (!Py.ready) return
            runCatching { Py.call("abort2", cid) }.getOrElse {
                runCatching { Py.call("abort") }
            }
        }
        // pollAll: 摘要；py 返回 {"sessions":[...]}；缺 poll_all 时用 poll(-3) 包一层（A13）
        @JavascriptInterface fun pollAll(): String {
            ensureNudgeRegistered()   // M1: 懒重试(同 poll)
            if (!Py.ready) return """{"sessions":[]}"""
            return runCatching { Py.call("poll_all", "0") }.recoverCatching {
                val one = Py.call("poll", "-3")
                if (one.isNullOrBlank()) """{"sessions":[]}"""
                else """{"sessions":[$one]}"""
            }.getOrDefault("""{"sessions":[]}""")
        }

        @JavascriptInterface fun float() = runOnUiThread { toFloat() }
        // 无障碍是否已开启: 直接读 Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES 是否含本包的 BusA11yService,
        //   比依赖 BusA11yService.instance!=null 更早/更准(实例首启连接有时序滞后)。给前端横幅/红点/引导用。
        @JavascriptInterface fun a11yEnabled(): Boolean = isA11yOn()
        // 跳系统无障碍设置页(仿 overlay 权限跳转写法)。用户开完返回 app, onResume 会回推最新状态给前端。
        @JavascriptInterface fun openA11ySettings() = runOnUiThread {
            runCatching { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
        }
        // 无线调试自连状态(设置行+引导浮层用): wifi=系统「无线调试」开关是否已打开; paired/connected=AdbController(证书已持久化/传输已建立)。
        @JavascriptInterface fun adbSelfStatus(): String = sysBridge.adbSelfStatus()
        // 跳系统「开发者选项」(无线调试无独立直达 Intent)。返回是否真的拉起了某个设置页, JS 据此判断成败:
        //   1) ACTION_APPLICATION_DEVELOPMENT_SETTINGS 直达开发者选项(部分机型/高 API 已废弃或无 handler)
        //   2) 失败则回退 ACTION_SETTINGS 主设置页(用户自己进开发者选项)
        // 用 resolveActivity 预检避免 startActivity 抛 ActivityNotFound; 两者都无 handler→返回 false, JS 弹手动路径提示。
        @JavascriptInterface fun openAdbDevSettings(): Boolean = sysBridge.openAdbDevSettings()
        // ── 无障碍持久化(v2.29): 机制在 A11yPersist(WRITE_SECURE_SETTINGS 静默回写), 引导/策略 UI 在前端 ──
        // 聚合状态(设置卡渲染用); grantCmd 单一真相源在 Kotlin(前端不硬编码包名)。
        // selfAdbOn = 已连 或 可自动重连(证书在盘 + 无线调试开, AdbController.shell 会透明 ensureConnected) → 一键授权可用。
        @JavascriptInterface fun a11yPersistStatus(): String = sysBridge.a11yPersistStatus()
        // 用户开关(SP 单一真相源, 前端不落 LS); 开且已授权 → 立即恢复一次, 不等下次 onResume
        @JavascriptInterface fun setA11yPersist(on: Boolean) {
            A11yPersist.setPersistEnabled(this@MainActivity, on)
            if (on) A11yPersist.reEnable(this@MainActivity)
        }
        // 用户显式点「立即恢复」: 返回恢复后是否在表(前端 toast 成败, 失败引导手动开启)
        @JavascriptInterface fun a11yReEnableNow(): Boolean = A11yPersist.reEnable(this@MainActivity)
        // P1 一键授权: 复用既有自连通道(AdbController.shell 以 shell 身份跑 pm grant, 零新实现)。
        // 异步 jobId+轮询(仿 pdfRender): shell 是 @Synchronized 阻塞调用(可能与 agent 的 adb 使用串行排队), 不能冻结 JS 桥。
        @JavascriptInterface fun a11yGrantViaSelfAdb(): String = sysBridge.a11yGrantViaSelfAdb()
        @JavascriptInterface fun a11yGrantResult(id: String): String = jobs.resultOnce(id)   // 终态即取即清(同 pdfResult)
        // OEM 后台保活引导深链(P2): which=details(自启动/电池入口所在的应用详情)|battery(省电优化白名单)。
        // 厂商自启动管理页尽力而为(组件名随版本漂移), resolveActivity 预检+runCatching 逐个尝试, 兜底通用页(同 openAdbDevSettings 先例)。
        @JavascriptInterface fun openAppSysSettings(which: String): Boolean = sysBridge.openAppSysSettings(which)

        // ── Shizuku 第二条 shell 通道(stepOS 全屏启动用; 与 self-ADB 等价, 只是来源不同) ──
        // 状态由前端轮询/首帧读取, 单一真值源全在 Kotlin(实时读 Shizuku binder + 权限), 前端零缓存。
        @JavascriptInterface fun shizukuStatus(): String = sysBridge.shizukuStatus()
        // 请求授权(弹系统对话框)。Shizuku 内部要求主线程, 故 runOnUiThread 转入; 结果经回调回推 JS 刷新。
        @JavascriptInterface fun shizukuRequest() {
            runOnUiThread { ShizukuShell.requestPermission { webCallbacks.onShizuku() } }
        }
        // 跳 Shizuku 管理器(未安装/服务未启动时引导用户去那边操作)。返回是否真的拉起了管理器页面。
        @JavascriptInterface fun openShizukuManager(): Boolean = sysBridge.openShizukuManager()

        // 悬浮窗透明度(0.3~1.0): 存 SharedPreferences, FloatService 显示时读取并设到窗口 alpha。
        @JavascriptInterface fun setFloatOpacity(v: String) {
            val f = (v.toFloatOrNull() ?: 0.9f).coerceIn(0.3f, 1f)
            getSharedPreferences("ga", MODE_PRIVATE).edit().putFloat("float_opacity", f).apply()
            runOnUiThread { FloatService.live?.applyOpacity(f) }   // 浮窗正显示则即时生效
        }
        // 悬浮窗常开: 设置页开关。开→悬浮球常驻(即使回到 GA 前台也不收起, onResume 不再 stopService); 关→收起。
        //   状态持久化到 SharedPreferences("ga").float_always_on(FloatService/onResume 共同真值源)。
        //   返回实际生效态: 开但无 overlay 权限 → 跳授权页且不落 true, 返回 false 让前端回滚开关(与 toFloat 一致的权限门)。
        @JavascriptInterface fun setFloatAlwaysOn(on: Boolean): Boolean {
            if (on && !Settings.canDrawOverlays(this@MainActivity)) {
                // 与 toFloat 同一引导路径: 先弹说明再跳授权页; onResume 检测返回, 授权成功自动补落开关(免用户二次点开)。
                // 旧 webui 无引导函数 → 退回裸跳授权页(同 toFloat 的兜底)。
                Analytics.track("""{"event":"float_perm_denied","props":{"from":"always_on"}}""")
                webCallbacks.floatPermGuideAlwaysOn { r ->
                    if (r != "1") runCatching { startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                }
                return false   // 前端据此回滚为关; onResume 检测到授权成功会回推 gaOnFloatAlways(true) 补上
            }
            getSharedPreferences("ga", MODE_PRIVATE).edit().putBoolean("float_always_on", on).apply()
            val fsi = Intent(this@MainActivity, FloatService::class.java).putExtra("trigger", "always")
            runOnUiThread {
                if (on) { if (android.os.Build.VERSION.SDK_INT >= 26) startForegroundService(fsi) else startService(fsi) }
                else stopService(Intent(this@MainActivity, FloatService::class.java))
            }
            return on
        }
        // 常开真值读桥(仿 a11yEnabled): 前端渲染时直读 SP∧权限的有效态, 不再依赖易分叉的 kv 镜像。
        @JavascriptInterface fun floatAlwaysOn(): Boolean =
            getSharedPreferences("ga", MODE_PRIVATE).getBoolean("float_always_on", false) && Settings.canDrawOverlays(this@MainActivity)
        // 悬浮窗三元组: perm=系统授权 / always=用户意图(SP) / running=球确实在屏上(FloatService.live)。
        // 三者正交, 塌缩成一个布尔就会造出"开关显示开、屏上没球"的不可自愈假态(floatAlwaysOn 只答 perm∧always,
        // 从不看实际挂载)。一次调用返回全三元组=前端读到的是同一时刻的自洽快照, 不会三次读桥读出撕裂状态。
        @JavascriptInterface fun floatState(): String = JSONObject()
            .put("perm", Settings.canDrawOverlays(this@MainActivity))
            .put("always", getSharedPreferences("ga", MODE_PRIVATE).getBoolean("float_always_on", false))
            .put("running", FloatService.live != null)
            .put("err", FloatService.lastError ?: "")
            .toString()
        // 悬浮窗授权页跳转(引导弹窗「去开启」专用): 记录往返意图供 onResume 闭环。
        //   from=入口(button=悬浮窗按钮/always_on=常开开关), 授权成功后按 from 自动接续原动作。
        //   意图落 SP(非内存): 部分 ROM 授予 overlay 权限即杀进程重启 app, 内存标记必丢。
        @JavascriptInterface fun requestOverlayPerm(from: String) = runOnUiThread {
            val sp = getSharedPreferences("ga", MODE_PRIVATE)
            sp.edit().putString("overlay_perm_pending", if (from == "always_on") "always_on" else "button")
                .putLong("overlay_perm_ts", System.currentTimeMillis()).apply()
            runCatching { startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                .onFailure { sp.edit().remove("overlay_perm_pending").apply() }   // 设置页拉起失败(极端 ROM): 清 pending 防误报 result
        }
        // 模型运行时阻止系统息屏: 前端在 setRunning 里调 GA.keepAwake(running && 开关开)。
        //   用 FLAG_KEEP_SCREEN_ON(挂在 window, 仅本 Activity 前台时生效, 熄屏/切后台自动失效, 无需 WakeLock 也无需权限),
        //   比 WakeLock 更省心(不怕忘释放/不耗电)。任务结束或用户关开关 → on=false → 清 flag, 屏幕恢复系统超时。
        @JavascriptInterface fun keepAwake(on: Boolean) = runOnUiThread {
            if (on) window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            else window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
        // 结束任务后返回桌面: 设置页开关(通用设置 → 悬浮窗常开 下面一行)。
        //   开→任务结束(done/error)时前端调 GA.goHome() 把设备退回桌面; 关→保持现状(停在任务结束的画面,
        //   方便用户回看最后一步)。状态持久化到 SharedPreferences("ga").home_after_task, 真值走读桥
        //   homeAfterTask()(与 floatAlwaysOn 同口径: 不让 kv 镜像和 SP 分叉出"开关开但没生效")。
        @JavascriptInterface fun setHomeAfterTask(on: Boolean): Boolean {
            getSharedPreferences("ga", MODE_PRIVATE).edit().putBoolean("home_after_task", on).apply()
            Analytics.track(if (on) """{"event":"home_after_task","props":{"on":true}}"""
                            else """{"event":"home_after_task","props":{"on":false}}""")
            return on
        }
        @JavascriptInterface fun homeAfterTask(): Boolean =
            getSharedPreferences("ga", MODE_PRIVATE).getBoolean("home_after_task", false)
        // 回桌面: HOME intent 不需要任何权限, 也不受悬浮窗/无障碍授权状态影响。任务结束后一次, 幂等。
        @JavascriptInterface fun goHome() {
            runOnUiThread {
                runCatching {
                    startActivity(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                }.onFailure { Diag.log("go_home_failed", it.toString()) }
            }
        }
        // 前端埋点上报入口: GA.track(JSON.stringify({event,props})); 脱敏在 Analytics 层完成
        @JavascriptInterface fun track(eventJson: String) { Analytics.track(eventJson) }
        // 账号身份: 登录成功 GA.setUser(userId) / 登出 GA.clearUser(); 让埋点带 user_id 跨设备归并(非 PII, 不传邮箱)
        @JavascriptInterface fun setUser(uid: String?) { Analytics.setUser(uid) }
        @JavascriptInterface fun clearUser() { Analytics.clearUser() }

        // 诊断日志: WebUI 侧错误(render_error/task_error/cfg_load_fail/window.onerror)落本地滚动日志, 供用户主动上传时一并带走。
        @JavascriptInterface fun logError(tag: String, msg: String) { Diag.log(tag, msg) }
        // 三条「用户主动触发」上传通道(异步 job+轮询, 仿 renderHtmlToImage): 返回 jobId, 前端轮询 diagResult(id) 取 JSON 结果。
        @JavascriptInterface fun logsUpload(): String = Diag.uploadLogs()                                   // 功能1: 上传诊断日志(logs/ + 队列尾 + 设备画像)
        @JavascriptInterface fun feedbackSubmit(json: String): String = Diag.submitFeedback(json)           // 功能3: 提交问题反馈(正文/联系方式/可选附带日志)
        // 提问采集(功能2, 默认开启可关): 每条用户提问脱敏后 fire-and-forget 上传, 无 job/无轮询, 不阻塞发送。
        @JavascriptInterface fun promptContribute(text: String, convoId: String) { Diag.contributePrompt(text, convoId) }
        @JavascriptInterface fun diagResult(id: String): String = Diag.jobResult(id)                        // 三通道共用: 轮询上传结果
        // 附件上传: WebView 读到的文件(dataURL/base64) 落盘到 filesDir/ga/uploads, 返回绝对路径供prompt引用
        @JavascriptInterface fun saveUpload(name: String, dataUrl: String): String = runCatching {
            val b64 = dataUrl.substringAfterLast("base64,")
            val bytes = android.util.Base64.decode(b64, android.util.Base64.DEFAULT)
            val dir = File(File(filesDir, "ga"), "uploads").apply { mkdirs() }
            val safe = name.replace(Regex("[^A-Za-z0-9._-]"), "_").takeLast(48).ifEmpty { "file" }
            File(dir, "${System.currentTimeMillis()}_$safe").apply { writeBytes(bytes) }.absolutePath
        }.getOrElse { "ERROR: $it" }
        // 流式语音: OkHttp WS 直连中继(原生TLS指纹, 无 Python 依赖). JS推PCM+轮询取增量文本。
        @JavascriptInterface fun sttStart(): String = mediaBridge.sttStart()
        @JavascriptInterface fun sttSend(b64: String): String = mediaBridge.sttSend(b64)
        @JavascriptInterface fun sttStop(): String = mediaBridge.sttStop()
        @JavascriptInterface fun sttPoll(): String = mediaBridge.sttPoll()
        @JavascriptInterface fun sttCancel(): String = mediaBridge.sttCancel()
        // 拍照: 由 JS 直接调用, 必起 ACTION_IMAGE_CAPTURE(不再依赖 WebView 的 <input capture>/isCaptureEnabled——
        // 后者在部分设备/WebView 不触发→只弹相册)。结果在 onActivityResult 落盘并经 window.gaCameraResult 回推。(issue#2)
        @JavascriptInterface fun openCamera(): String {
            val latch = CountDownLatch(1)
            var r = "err"
            runOnUiThread { r = if (launchCamera(true)) "ok" else "no-camera"; latch.countDown() }
            runCatching { latch.await(4, TimeUnit.SECONDS) }
            return r
        }
        // PCLink 扫码: 应用内 ZXing 预览(需 CAMERA 运行时授权)。结果经 window.gaQrResult(text) 回推。
        // 与 openCamera 拍照路径分开——拍照仍走外置相机 App、不依赖本权限。
        @JavascriptInterface fun scanQr(): String {
            val latch = CountDownLatch(1)
            var r = "err"
            runOnUiThread { r = launchQrScan(); latch.countDown() }
            runCatching { latch.await(4, TimeUnit.SECONDS) }
            return r
        }
        // 原生朗读: 优先于 WebView speechSynthesis(后者在多数 WebView 无可用引擎 → "当前设备无法朗读")
        @JavascriptInterface fun speak(text: String, lang: String): String = mediaBridge.speak(text, lang)
        @JavascriptInterface fun speakStop(): String = mediaBridge.speakStop()   // 朗读键再次点=停止(原生 TTS 无暂停, stop 即可); onStop→gaOnSpeakEnd 复位前端键
        // 分享图: 前端 Canvas 生成 PNG(dataURL) → 存入系统相册 Pictures/GenericAgent。
        // 返回 "ok" / "err:<msg>"。API29+ 用 MediaStore RELATIVE_PATH(无需存储权限); API28- 落 Environment 公共目录(已有 MANAGE_EXTERNAL_STORAGE)。
        @JavascriptInterface fun saveImageToGallery(dataUrl: String): String = mediaBridge.saveImageToGallery(dataUrl)

        // 分享图: 落盘到 cacheDir/share, 经 FileProvider 拉起系统分享面板(ACTION_SEND)转发给微信/QQ 等。
        @JavascriptInterface fun shareImage(dataUrl: String): String = mediaBridge.shareImage(dataUrl)

        // 系统通知(应用退到后台时): 让用户不用守着屏幕也知道(issue#4 #5)。
        // 两级: "完成"=普通通道; "需要操作"(ask_user)=高优先级通道(抬头横幅+声音), 提醒级别不同(issue#5)。
        @JavascriptInterface fun notify(title: String, body: String) = notify(title, body, "default")
        @JavascriptInterface fun notify(title: String, body: String, level: String) = sysBridge.notify(title, body, level)

        // 【验证】离屏 WebView 渲染 HTML → Bitmap → PNG dataURL。
        // 目的: 证明端上可复用深皓 poster.html(系统 WebView 当渲染器代替 PC 的 Playwright)。
        // 异步设计: 立刻返回 jobId(不阻塞 JS 桥/主消息泵——同步阻塞会让离屏 WebView 的
        // 导航被 deferred ~20s), 前端轮询 renderHtmlResult(jobId) 取结果("pending"/dataURL/err:*)。
        @JavascriptInterface fun renderHtmlToImage(html: String, w: Int, h: Int): String =
            renderHtmlToImage(html, w, h, "")
        // bg(#RRGGBB, 可空): 离屏位图底色。长图深色主题下 WebView 软件层对"内容渲染高度之外、位图高度之内"
        //  的区域不落像素 → ARGB_8888 位图该区透明 → 查看器里显白(长图底部白边真因)。前端按主题传 var(--bg)
        //  解析出的实色, 这里 eraseColor 铺底(直接像素填充, 不走 Canvas.drawColor——Flyme 会强制夜间改写它)。
        @JavascriptInterface fun renderHtmlToImage(html: String, w: Int, h: Int, bg: String): String {
            val id = jobs.newId("r")
            runOnUiThread { startHtmlOffscreen(id, html, w, h, bg) }
            return id
        }
        @JavascriptInterface fun renderHtmlResult(id: String): String = jobs.resultOnce(id)   // 终态即取即清(仿 pdfResult): 多MB base64 常驻是 v2.23 二次分享黑屏(tile 内存爆)帮凶

        // 截 GA 主 WebView 的对话区(#chat)真实像素 → PNG dataURL(分享海报的主视觉)。
        // 追平深皓 poster_wall 的关键: 手机 mock 屏内放"像素级真实 app UI", 而非 CSS 重画。
        // 入参 rect = #chat 的 CSS 像素矩形(前端 getBoundingClientRect 传入); scale = 额外放大倍数(高清)。
        // 异步: 返回 jobId, 前端轮询 renderHtmlResult(jobId)。
        @JavascriptInterface fun captureChat(x: Float, y: Float, w: Float, h: Float, scale: Float): String {
            val id = jobs.newId("c")
            runOnUiThread { captureWebRegion(id, x, y, w, h, scale) }
            return id
        }

        // 生成文件"用其他应用打开"(v2.18 通用预览框架): rel 相对 GA_DIR/temp, canonical 守卫防越界(不变量 I2)。
        // targetSdk>=24 禁 file:// 跨 app → 必走 FileProvider content://(file_paths.xml files-path gatemp)+读授权。
        @JavascriptInterface fun openFile(rel: String): String {
            val f = gaTempFile(rel) ?: return "err:not-found"
            val ext = f.extension.lowercase(Locale.ROOT)
            val mime = OPEN_MIME[ext]
                ?: android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext)
                ?: "application/octet-stream"
            return runCatching {
                val uri = FileProvider.getUriForFile(this@MainActivity, "$packageName.fileprovider", f)
                val view = Intent(Intent.ACTION_VIEW).setDataAndType(uri, mime)
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                view.clipData = android.content.ClipData.newRawUri(null, uri)   // chooser 转发目标也稳拿读授权
                // 部分 OEM 播放器只注册精确/另类 MIME(实测 Flyme video/mp4 只有 QQ 接): 精确 MIME 无人接→放宽 */*
                if (packageManager.queryIntentActivities(view, 0).isEmpty()) view.setDataAndType(uri, "*/*")
                if (packageManager.queryIntentActivities(view, 0).isEmpty()) return "err:no-app"
                runOnUiThread { runCatching {
                    startActivity(Intent.createChooser(view, null).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)) } }
                "ok"
            }.getOrElse { "err:" + (it.message ?: "open") }
        }
        // 媒体产物存相册(MediaStore, API29+ 免权限): 存后系统相册/任意播放器可用——解决 content:// 直开
        // 播放器接单少的现实(用户反馈 mp4 打开方式只有 QQ)。仅 video/image/audio 走此路。
        @JavascriptInterface fun saveToGallery(rel: String): String {
            val f = gaTempFile(rel) ?: return "err:not-found"
            val ext = f.extension.lowercase(Locale.ROOT)
            val mime = android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: return "err:mime"
            val col = when (mime.substringBefore('/')) {
                "video" -> android.provider.MediaStore.Video.Media.EXTERNAL_CONTENT_URI
                "image" -> android.provider.MediaStore.Images.Media.EXTERNAL_CONTENT_URI
                "audio" -> android.provider.MediaStore.Audio.Media.EXTERNAL_CONTENT_URI
                else -> return "err:kind"
            }
            return runCatching {
                val cv = android.content.ContentValues().apply {
                    put(android.provider.MediaStore.MediaColumns.DISPLAY_NAME, f.name)
                    put(android.provider.MediaStore.MediaColumns.MIME_TYPE, mime)
                }
                val out = contentResolver.insert(col, cv) ?: return "err:insert"
                contentResolver.openOutputStream(out)!!.use { o -> f.inputStream().use { it.copyTo(o) } }
                "ok"
            }.getOrElse { "err:" + (it.message ?: "save") }
        }
        // PDF 应用内预览: WebView 无原生 PDF 渲染 → PdfRenderer 后台线程转页图(cacheDir/pdfprev, 字节不过桥,
        // 不变量 I3)。异步 jobId+轮询(仿 renderHtmlToImage 先例, 大 PDF 不阻塞 JS 桥)。
        @JavascriptInterface fun pdfRender(rel: String): String {
            val id = jobs.newId("p")
            Thread { jobs.set(id, pdfToPages(rel)) }.apply { isDaemon = true }.start()
            return id
        }
        @JavascriptInterface fun pdfResult(id: String): String {   // 终态即取即清: pdf job 不复读, 防 map 常驻泄漏
            return jobs.resultOnce(id)
        }
        // html 产物全屏预览: 独立无桥 WebView(HtmlPreviewActivity)。不可在主 WebView iframe 里渲染——
        // addJavascriptInterface 注入所有 frame, sandbox 挡不住 GA 桥(Monitor CONFIRMED must-fix)。
        @JavascriptInterface fun previewHtml(rel: String): String {
            val f = gaTempFile(rel) ?: return "err:not-found"
            runOnUiThread { runCatching {
                startActivity(Intent(this@MainActivity, HtmlPreviewActivity::class.java)
                    .putExtra("path", f.path).putExtra("name", f.name)) } }
            return "ok"
        }

        // --- 通知读取/回复/控制 (NotifService 桥接) ---
        // 获取当前所有系统通知列表 JSON: [{"key":"...", "pkg":"...", "title":"...", "text":"...", "time":..., "canReply":true}, ...]
        @JavascriptInterface fun getNotifications(): String {
            val svc = NotifService.instance ?: return """[]"""  // 服务未授权/未连接返回空数组
            return runCatching { svc.getNotifications() }.getOrElse { "[]" }
        }

        // 回复通知 (仅对支持 RemoteInput 的通知有效，如微信/Telegram 等)
        // @param key 通知的唯一标识 (从 getNotifications 返回的 "key" 字段)
        // @param text 回复内容
        // @return "ok" 或 "err:..."
        @JavascriptInterface fun replyNotification(key: String, text: String): String {
            val svc = NotifService.instance ?: return "err:service_not_connected"
            return runCatching { svc.replyNotification(key, text) }.getOrElse { "err:${it.message ?: "reply_failed"}" }
        }

        // 取消/清除单个通知
        // @param key 通知的唯一标识
        // @return "ok" 或 "err:..."
        @JavascriptInterface fun dismissNotification(key: String): String {
            val svc = NotifService.instance ?: return "err:service_not_connected"
            return runCatching { svc.dismissNotification(key) }.getOrElse { "err:${it.message ?: "dismiss_failed"}" }
        }

        // 清除指定应用的所有通知
        // @param pkg 应用包名 (如 "com.tencent.mm")
        // @return 清除数量 (字符串格式)
        @JavascriptInterface fun dismissNotificationsByPackage(pkg: String): String {
            val svc = NotifService.instance ?: return "0"
            return runCatching { svc.dismissByPackage(pkg).toString() }.getOrElse { "0" }
        }

        // 检查通知监听服务是否已授权并连接
        @JavascriptInterface fun isNotificationServiceEnabled(): String {
            return if (NotifService.instance != null) "true" else "false"
        }
    }
    internal val jobs = JobRegistry()

    // MimeTypeMap 缺失/不准的常见文本类补充(系统打开选择器按此匹配 handler)
    private val OPEN_MIME = mapOf(
        "md" to "text/markdown", "markdown" to "text/markdown", "json" to "application/json",
        "log" to "text/plain", "toml" to "text/plain", "ini" to "text/plain",
        "yaml" to "text/plain", "yml" to "text/plain", "tsv" to "text/tab-separated-values",
    )
    // rel(相对 GA_DIR/temp) → 沙盒内真实文件; canonical 前缀 + 内部命名空间谓词, 与 python _seg_hidden 同构(不变量 I2):
    // 路径段以 . 或 __ 开头 = 内部文件(写入方遵守命名约定), 仅两个历史目录名例外——读取方零枚举。
    private val FILES_SKIP = setOf("model_responses", "reflect_logs")
    private fun segHidden(s: String) = s in FILES_SKIP || s.startsWith("__") || s.startsWith(".")
    private fun gaTempFile(rel: String): File? = runCatching {
        val root = File(File(filesDir, "ga"), "temp").canonicalFile
        val f = File(root, rel).canonicalFile
        val inside = f.path.startsWith(root.path + File.separator) && f.isFile
        val public = inside && f.relativeTo(root).path.split(File.separatorChar).none(::segHidden)
        if (public) f else null
    }.getOrNull()

    // PDF → 页图(JPEG 85, 宽 1080, 白底防透明底黑屏), 上限 24 页; 缓存键=rel+mtime+size(内容变则重渲),
    // 缓存池 LRU 保 8 份文档。返回 JSON {ok,pages:[file://...],total,rendered} 或 "err:*"。
    @Synchronized private fun pdfToPages(rel: String): String {   // 串行化: 同文档并发 job 会互踩缓存目录
        val f = gaTempFile(rel) ?: return "err:not-found"
        return runCatching {
            val key = String.format("%08x", (rel + "|" + f.lastModified() + "|" + f.length()).hashCode())
            val pool = File(cacheDir, "pdfprev").apply { mkdirs() }
            val dir = File(pool, key)
            val done = File(dir, ".done")
            if (!done.isFile) {
                dir.deleteRecursively(); dir.mkdirs()
                val pfd = android.os.ParcelFileDescriptor.open(f, android.os.ParcelFileDescriptor.MODE_READ_ONLY)
                android.graphics.pdf.PdfRenderer(pfd).use { r ->
                    for (i in 0 until minOf(r.pageCount, 24)) r.openPage(i).use { pg ->
                        val w = 1080; val h = maxOf(1, w * pg.height / pg.width)
                        val bmp = android.graphics.Bitmap.createBitmap(w, h, android.graphics.Bitmap.Config.ARGB_8888)
                        bmp.eraseColor(android.graphics.Color.WHITE)   // 直接像素填充: Canvas.drawColor 会被 Flyme 强制深色改写成暗底(真机实证)
                        pg.render(bmp, null, null, android.graphics.pdf.PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                        File(dir, "page_$i.jpg").outputStream().use { o ->
                            bmp.compress(android.graphics.Bitmap.CompressFormat.JPEG, 85, o) }
                        bmp.recycle()
                    }
                    done.writeText(r.pageCount.toString())
                }
                pfd.close()
            }
            dir.setLastModified(System.currentTimeMillis())   // 命中也续期: 淘汰按真 LRU, 常看的文档不被新渲染挤掉
            pool.listFiles()?.sortedByDescending { it.lastModified() }?.drop(8)?.forEach { it.deleteRecursively() }
            val total = done.readText().trim().toIntOrNull() ?: 0
            val pages = (0 until minOf(total, 24)).map { JSONObject.quote("file://" + File(dir, "page_$it.jpg").path) }
            """{"ok":true,"total":$total,"rendered":${pages.size},"pages":[${pages.joinToString(",")}]}"""
        }.getOrElse { "err:" + (it.message ?: "pdf") }
    }

    // 离屏渲染 HTML 到 PNG dataURL: 系统 WebView 当渲染器(端上等效 Playwright)。
    // 全程在 UI 线程: 建离屏 WebView attach 到根视图布局绘制, loadUrl(data:) 灌 HTML;
    // onPageFinished 后再等一拍(CSS 渐变/字体/JS 二维码绘制完成)→ wv.draw(Canvas) 截 Bitmap → PNG base64。
    // 结果写入 jobs[id](前端轮询 renderHtmlResult 取)。
    private fun startHtmlOffscreen(id: String, html: String, w: Int, h: Int, bg: String = "") {
        if (w <= 0 || h <= 0 || w > 4096 || h > 8192) { jobs.set(id, "err:bad-size"); return }
        // bg="#RRGGBB" → 底色 Int(解析失败/空 → 0=透明, 保持海报等既有调用行为不变)
        val bgColor = runCatching { if (bg.isNotBlank()) android.graphics.Color.parseColor(bg.trim()) else 0 }.getOrDefault(0)
        var wvHolder: WebView? = null
        runCatching {
                val wv = WebView(this)
                wvHolder = wv
                // 软件渲染层: 离屏 WebView 走 GPU 合成在模拟器上会卡渲染进程; 且 wv.draw(Canvas) 只有软件层才正确。
                wv.setLayerType(android.view.View.LAYER_TYPE_SOFTWARE, null)
                if (bgColor != 0) wv.setBackgroundColor(bgColor)   // WebView 自身 base 底色 → 内容外区域不再露白(长图底部白边)
                wv.settings.javaScriptEnabled = true
                wv.settings.allowFileAccess = true
                wv.settings.loadWithOverviewMode = false
                if (WebViewFeature.isFeatureSupported(WebViewFeature.SAFE_BROWSING_ENABLE)) {
                    WebSettingsCompat.setSafeBrowsingEnabled(wv.settings, false)
                }
                if (android.os.Build.VERSION.SDK_INT >= 29) {
                    @Suppress("DEPRECATION") wv.isForceDarkAllowed = false
                }
                if (WebViewFeature.isFeatureSupported(WebViewFeature.ALGORITHMIC_DARKENING)) {
                    WebSettingsCompat.setAlgorithmicDarkeningAllowed(wv.settings, false)
                }
                // 关键: 离屏 WebView 若不入窗口层级往往不布局/不绘制(draw 出空白)。
                // 这里以 0 尺寸不可见地 attach 到根视图, 但给 WebView 显式指定精确 w×h layout 参数,
                // 让它真实布局+绘制; 截图后立即从层级移除。用 alpha=0 + 尺寸 1x1 容器避免任何可见闪烁。
                val root = window.decorView as android.view.ViewGroup
                // 注意: 把离屏 WebView 平移到 -100000 或 alpha=0 会让合成器判定其"不可见"
                // 而节流/挂起页面加载(实测 loadData 被 deferred ~20s)。这里让 holder 占据
                // 屏幕左上真实坐标(0,0)且 alpha=0.004(近乎不可见但非 0), 保证渲染进程正常提交加载。
                val holder = android.widget.FrameLayout(this).apply {
                    layoutParams = android.view.ViewGroup.LayoutParams(w, h)
                    alpha = 0.004f
                }
                wv.layoutParams = android.widget.FrameLayout.LayoutParams(w, h)
                holder.addView(wv)
                root.addView(holder)
                val cleanup = { runCatching { root.removeView(holder) }; runCatching { wv.destroy() } }
                var captured = false
                val capture = capture@{
                    if (captured) return@capture
                    captured = true
                    runCatching {
                        val bmp = android.graphics.Bitmap.createBitmap(w, h, android.graphics.Bitmap.Config.ARGB_8888)
                        if (bgColor != 0) bmp.eraseColor(bgColor)   // 先铺主题底色: 内容渲染高度之外的区域不再是透明→查看器显白(根治长图底部白边)
                        val cv = android.graphics.Canvas(bmp)
                        wv.draw(cv)
                        val bos = java.io.ByteArrayOutputStream()
                        bmp.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, bos)
                        bmp.recycle()
                        jobs.set(id, "data:image/png;base64," +
                            android.util.Base64.encodeToString(bos.toByteArray(), android.util.Base64.NO_WRAP))
                    }.onFailure { jobs.set(id, "err:draw:${it.message}") }
                    cleanup()
                }
                // 图片解码门控: data:URL 页的 progress=100/onPageFinished 都可能早于大图解码完成,
                // 固定延时在慢设备/大图下是竞速(截出空 img 区)。轮询 document.images 全 complete
                // 后再截(留 120ms 栅格余量); 3s 仍未就绪按现状截, 保证 watchdog 前必有产出。
                fun captureWhenReady(waited: Long) {
                    if (captured) return
                    if (waited >= 3000L) { capture(); return }
                    wv.evaluateJavascript(
                        "(function(){var a=document.images;for(var i=0;i<a.length;i++)if(!a[i].complete)return false;return true})()"
                    ) { v ->
                        if (captured) return@evaluateJavascript
                        if (v == "true") wv.postDelayed({ capture() }, 120)
                        else wv.postDelayed({ captureWhenReady(waited + 150) }, 150)
                    }
                }
                wv.webViewClient = object : WebViewClient() {
                    override fun onPageFinished(view: WebView?, url: String?) {
                        view?.postDelayed({ captureWhenReady(0) }, 250)
                    }
                }
                wv.webChromeClient = object : WebChromeClient() {
                    override fun onProgressChanged(view: WebView?, newProgress: Int) {
                        if (newProgress >= 100) view?.postDelayed({ captureWhenReady(0) }, 250)
                    }
                }
                // 兜底 watchdog: 8s 内没截到就置错并清理(避免离屏 WebView 泄漏)
                wv.postDelayed({
                    if (!captured) { jobs.set(id, "err:timeout"); captured = true; cleanup() }
                }, 8000)
                val b64 = android.util.Base64.encodeToString(html.toByteArray(Charsets.UTF_8), android.util.Base64.NO_WRAP)
                wv.loadUrl("data:text/html;charset=utf-8;base64,$b64")
        }.onFailure {
            jobs.set(id, "err:setup:${it.message}")
            runCatching { (wvHolder?.parent as? android.view.ViewGroup)?.let { p -> (p.parent as? android.view.ViewGroup)?.removeView(p) } }
            runCatching { wvHolder?.destroy() }
        }
    }

    // 截主 WebView 的一块 CSS 矩形区域(#chat)成高清 PNG dataURL, 写入 jobs[id]。
    // 截 WebView 上 #chat 区的真实合成帧(所见即所得): 用 PixelCopy 从 window surface 抓 GPU 合成结果,
    // 再裁出 [rect × density] 子区 → 放大 scale 倍 → PNG base64。
    // ⚠️ web.draw(Canvas) 对硬件加速 WebView 只画软件缓存(旧帧/空白), 必须走 PixelCopy 才拿到真实屏幕像素。
    private fun captureWebRegion(id: String, cssX: Float, cssY: Float, cssW: Float, cssH: Float, scale: Float) {
        runCatching {
            if (!::web.isInitialized || web.width <= 0 || web.height <= 0) { jobs.set(id, "err:no-web"); return }
            if (cssW <= 0 || cssH <= 0) { jobs.set(id, "err:bad-rect"); return }
            val density = resources.displayMetrics.density   // CSS px → 设备 px
            // WebView 在 window 中的绝对位置(PixelCopy 用 window 坐标系)
            val loc = IntArray(2); web.getLocationInWindow(loc)
            // #chat 区在 window 中的设备像素矩形(clamp 到 WebView 边界内)
            val rx = loc[0] + (cssX * density).toInt().coerceIn(0, web.width - 1)
            val ry = loc[1] + (cssY * density).toInt().coerceIn(0, web.height - 1)
            val rw = (cssW * density).toInt().coerceAtMost(web.width - (rx - loc[0])).coerceAtLeast(1)
            val rh = (cssH * density).toInt().coerceAtMost(web.height - (ry - loc[1])).coerceAtLeast(1)
            val src = android.graphics.Rect(rx, ry, rx + rw, ry + rh)
            val bmp = android.graphics.Bitmap.createBitmap(rw, rh, android.graphics.Bitmap.Config.ARGB_8888)
            android.view.PixelCopy.request(window, src, bmp,
                { result ->
                    if (result != android.view.PixelCopy.SUCCESS) { jobs.set(id, "err:pixelcopy:$result"); return@request }
                    runCatching {
                        // 放大/缩小(scale 倍); 输出宽硬上限 1440px: 海报 mock 仅 ~640px 宽, 巨图
                        // (曾 2160×4400)= 离屏软件层 tile 内存爆 + data:URL 超限 → 二次分享黑屏根因
                        val s = (if (scale > 0f) scale else 1f).coerceAtMost(1440f / rw)
                        val out = if (s == 1f) bmp else android.graphics.Bitmap.createScaledBitmap(
                            bmp, (rw * s).toInt().coerceAtLeast(1), (rh * s).toInt().coerceAtLeast(1), true)
                        val bos = java.io.ByteArrayOutputStream()
                        out.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, bos)
                        if (out !== bmp) out.recycle()
                        bmp.recycle()
                        jobs.set(id, "data:image/png;base64," +
                            android.util.Base64.encodeToString(bos.toByteArray(), android.util.Base64.NO_WRAP))
                    }.onFailure { jobs.set(id, "err:encode:${it.message}") }
                }, android.os.Handler(android.os.Looper.getMainLooper()))
        }.onFailure { jobs.set(id, "err:capture:${it.message}") }
    }

    // 起相机: 输出到 cacheDir/cam 经 FileProvider 暴露给相机 App 写入; 取回后交给 WebView。
    // 不声明 CAMERA 权限——ACTION_IMAGE_CAPTURE 由相机 App 完成; 一旦声明反而要运行时授权(issue#1)。
    // forBridge=true 表示经 GA.openCamera 直连(结果回推 WebUI), false 表示经 onShowFileChooser(回填 fileCb)。
    private fun openExternalLink(raw: String) {
        if (!ExternalLinkPolicy.canOpen(raw)) return
        try {
            val intent = if (raw.startsWith("intent:", ignoreCase = true))
                Intent.parseUri(raw, Intent.URI_INTENT_SCHEME) else Intent(Intent.ACTION_VIEW, Uri.parse(raw))
            val fallback = intent.getStringExtra("browser_fallback_url")
            intent.action = Intent.ACTION_VIEW
            intent.component = null
            intent.selector = null
            intent.addCategory(Intent.CATEGORY_BROWSABLE)
            intent.flags = 0
            intent.removeExtra("browser_fallback_url")
            if (!ExternalLinkPolicy.canOpen(intent.dataString.orEmpty())) return
            try { startActivity(intent) }
            catch (e: android.content.ActivityNotFoundException) {
                if (fallback != null && fallback.startsWith("https://"))
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(fallback)).addCategory(Intent.CATEGORY_BROWSABLE))
                else throw e
            }
        } catch (e: Exception) {
            android.widget.Toast.makeText(this, "No app can open this link / 没有可打开此链接的应用", android.widget.Toast.LENGTH_LONG).show()
        }
    }

    private fun launchCamera(forBridge: Boolean): Boolean = try {
        val dir = File(cacheDir, "cam").apply { mkdirs() }
        val f = File(dir, "IMG_${System.currentTimeMillis()}.jpg")
        val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", f)
        val intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE)
            .putExtra(MediaStore.EXTRA_OUTPUT, uri)
            .addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_READ_URI_PERMISSION)
        if (intent.resolveActivity(packageManager) == null) false
        else { camUri = uri; camFile = f; camForBridge = forBridge; startActivityForResult(intent, FILE_REQ); true }
    } catch (e: Exception) { camUri = null; camFile = null; camForBridge = false; false }

    /** 启动 ZXing 扫码页。返回 ok / need-perm / no-camera / err。 */
    private fun launchQrScan(): String {
        return try {
            if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                pendingQrAfterPerm = true
                requestPermissions(arrayOf(Manifest.permission.CAMERA), CAM_PERM_QR)
                return "need-perm"
            }
            pendingQrAfterPerm = false
            IntentIntegrator(this).apply {
                setRequestCode(QR_REQ)
                setDesiredBarcodeFormats(IntentIntegrator.QR_CODE)
                setPrompt("Scan PC QR · 扫描电脑二维码")
                setBeepEnabled(false)
                setOrientationLocked(true)
                setBarcodeImageEnabled(false)
                setCameraId(0)
            }.initiateScan()
            "ok"
        } catch (e: Exception) {
            "err:${e.message ?: "scan"}"
        }
    }

    // 拍照文件落盘到 uploads(与其他附件同目录, 持久且 Python 核心可读), 返回绝对路径供 prompt 引用(issue#2)
    private fun saveCamFile(src: File): String {
        val dir = File(File(filesDir, "ga"), "uploads").apply { mkdirs() }
        val dst = File(dir, "${System.currentTimeMillis()}_camera.jpg")
        src.copyTo(dst, overwrite = true)
        runCatching { src.delete() }
        return dst.absolutePath
    }

    // <input type=file>/拍照 结果回填: 直连相机→落盘+回推 WebUI; 选择器/拍照(经选择器)→回填 fileCb
    // QR_REQ: ZXing 扫码 → gaQrResult
    override fun onActivityResult(req: Int, res: Int, data: Intent?) {
        super.onActivityResult(req, res, data)
        if (req == QR_REQ) {
            // 三参 parseActivityResult 只认库默认 REQUEST_CODE(0x0000c0de)。
            // 这里用了自定义 QR_REQ, 必须走两参重载, 否则扫成功也会 contents=null → 前端「已取消扫码」。
            val parsed = IntentIntegrator.parseActivityResult(res, data)
            webCallbacks.qrResult(parsed?.contents)
            return
        }
        // GAnet 扫码走库默认 REQUEST_CODE(initiateScan): 三参重载仅在该码时非 null, 与 QR_REQ 互斥
        val scan = IntentIntegrator.parseActivityResult(req, res, data)
        if (scan != null) {
            val qr = scan.contents
            if (qr.isNullOrBlank()) {
                runOnUiThread { web.evaluateJavascript("window.gaGanetScanResult&&gaGanetScanResult('')", null) }
            } else {
                // The QR secret goes straight from the native scanner to the dedicated
                // controller. It is never returned to WebUI or the generic send bridge.
                Thread {
                    val job = if (Py.ready) runCatching { Py.call("ganet_qr_start", qr) }.getOrDefault("") else ""
                    runOnUiThread { web.evaluateJavascript(
                        "window.gaGanetScanResult&&gaGanetScanResult(${JSONObject.quote(job)})", null) }
                }.start()
            }
            return
        }
        if (req != FILE_REQ) return
        val cu = camUri; val cf = camFile; val bridge = camForBridge
        camUri = null; camFile = null; camForBridge = false
        if (bridge) {   // GA.openCamera 直连: 没有 fileCb, 经 evaluateJavascript 回推
            val path = if (res == Activity.RESULT_OK && cf != null && cf.exists() && cf.length() > 0)
                runCatching { saveCamFile(cf) }.getOrNull() else null
            webCallbacks.cameraResult(path)
            return
        }
        val cb = fileCb; fileCb = null
        val result: Array<Uri>? = if (cu != null)
            (if (res == Activity.RESULT_OK) arrayOf(cu) else null)        // 拍照(经选择器): data 空, 图在 EXTRA_OUTPUT
            else parseChooserResult(res, data)
        cb?.onReceiveValue(result)
    }

    // <input type=file> 结果解析: 多选(尤其 Android 13+ PhotoPicker)URI 在 clipData, 单选在 data。
    //  框架 parseResult 只读 data.getData()(所有 Chromium WebView 皆如此, 从不读 clipData)→多选/PhotoPicker 结果返回 null。
    //  invariant: 返回 URI 必在 clipData 或 data 二者之一。故优先 clipData→再 data→末回退 parseResult,
    //  单选(头像)/多选(附件)在 API24~35、各 OEM(PhotoPicker/DocumentsUI/厂商相册)皆通用拿得到 URI。
    private fun parseChooserResult(res: Int, data: Intent?): Array<Uri>? {
        if (res != Activity.RESULT_OK || data == null) return null
        data.clipData?.let { clip ->
            val uris = (0 until clip.itemCount).mapNotNull { clip.getItemAt(it).uri }
            if (uris.isNotEmpty()) return uris.toTypedArray()
        }
        data.data?.let { return arrayOf(it) }
        return WebChromeClient.FileChooserParams.parseResult(res, data)
    }

    // 把左缘细条标记为「应用手势区」, 让 WebUI 的左缘右滑能拿到触摸去开抽屉(变量手势)。
    // 右缘仍是系统返回手势→回桌面(不变量); 左/右各占一边, 不打架(魅族等左右双缘返回时仅左缘让给抽屉)。
    private fun setupGestureExclusion() {
        if (android.os.Build.VERSION.SDK_INT < 29) return
        val w = (48 * resources.displayMetrics.density).toInt()
        web.addOnLayoutChangeListener { v, _, _, _, _, _, _, _, _ ->
            v.systemGestureExclusionRects = listOf(android.graphics.Rect(0, 0, w, v.height))
        }
    }

    override fun onBackPressed() {
        // 不变量: 返回=回桌面(永不劫持)。先交 WebUI: 有弹层/抽屉→先关并 return true 留在 app;
        // 无弹层→return false, 这里 moveTaskToBack(true) 退到桌面(保留任务+无障碍/悬浮保活, 不 finish/不杀)。
        // 开抽屉改由左缘右滑手势(变量)。⚠ 本壳改动编译进 APK, 需 Mac 重新构建 APK 才生效(热更不覆盖 .kt)。
        webCallbacks.onBack { r ->
            if (r != "true") moveTaskToBack(true)
        }
    }

    // 本包的无障碍服务是否已在系统「已启用服务」列表中(冒号分隔的 ComponentName 串)。
    internal fun isA11yOn(): Boolean = runCatching {
        val flat = Settings.Secure.getString(contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: return false
        flat.split(':').any { it.substringBefore('/').equals(packageName, true) }
    }.getOrDefault(false)

    // 系统「无线调试」开关是否已打开(无公开常量, 用字符串键读取; 老设备/读取异常时视为未开)。
    internal fun adbWifiOn(): Boolean =
        runCatching { Settings.Global.getInt(contentResolver, "adb_wifi_enabled", 0) == 1 }.getOrDefault(false)

    // ── sense 采集类权限的运行时申请(唯一入口, 由 Sense.perm 调用; 触发点只有 /sense/perm 与 /sense/session start) ──
    // 只在用户显式动作之后弹框: 采集必须由用户开启, 申请权限本身也得发生在用户表达意图之后 —— 启动时静默弹一堆框是红线。
    internal fun requestSensePerms(ps: Array<String>, waitMs: Long) {
        if (ps.isEmpty()) return
        val latch = CountDownLatch(1)
        senseLatch = latch
        runOnUiThread { runCatching { requestPermissions(ps, SENSE_REQ) }.onFailure { latch.countDown() } }
        if (waitMs > 0) runCatching { latch.await(waitMs, TimeUnit.MILLISECONDS) }   // 有界等待: 等不到就如实回"还没授", 绝不无限期占着桥线程
    }

    private fun resolveMicRequest(granted: Boolean) {
        val request = pendingMicRequest ?: return
        pendingMicRequest = null
        runCatching {
            val audio = request.resources.filter { it == PermissionRequest.RESOURCE_AUDIO_CAPTURE }
            if (granted && audio.isNotEmpty() && !isFinishing && !isDestroyed)
                request.grant(audio.toTypedArray())
            else request.deny()
        }
    }

    override fun onRequestPermissionsResult(req: Int, perms: Array<out String>, res: IntArray) {
        super.onRequestPermissionsResult(req, perms, res)
        if (req == MIC_REQ) {
            micPermissionInFlight = false
            if (res.isNotEmpty()) Sense.markAsked(this, perms)
            resolveMicRequest(res.firstOrNull() == PackageManager.PERMISSION_GRANTED &&
                checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
            return
        }
        if (req == CAM_PERM_QR) {
            val ok = res.isNotEmpty() && res[0] == PackageManager.PERMISSION_GRANTED
            if (ok && pendingQrAfterPerm) {
                pendingQrAfterPerm = false
                launchQrScan()
            } else {
                pendingQrAfterPerm = false
                webCallbacks.qrResult(null)
            }
            return
        }
        if (req != SENSE_REQ) return
        // "问过了"必须记在**用户答完之后**: grantResults 为空 = 框被划走、用户没选, 不算问过。
        //  这一笔是 Sense.perm 区分「从没问过」与「已选不再询问」的唯一依据(rationale 两种情况下都是 false);
        //  记在发起时, 会在框还挂在屏幕上时就把 blocked 报成 true, 让 agent 对用户说"只能去系统设置开"。
        if (res.isNotEmpty()) Sense.markAsked(this, perms)
        // 权限真值不缓存 grantResults: 一律现读 PermissionChecker(它连 appop 一起校验, 国产 ROM 上更准)
        senseLatch?.countDown()
    }

    // 已选"不再询问"之后的唯一出路: 应用详情页(权限列表就在这一页)。不复用 SysBridge.openAppSysSettings("details") ——
    //  那条路优先跳厂商自启动管理页, 与权限无关。
    internal fun openSensePermSettings(): Boolean = runCatching {
        startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        true
    }.getOrDefault(false)

    /**
     * 保活自检(A16)的落地入口: 未加电池白名单时优先请求豁免(系统标准弹窗), 否则跳应用详情页让用户
     * 找到「电池/自启动」项。ROM 专属的自启动管理页各家路径不一, 由 Sense.keepalive 的 vendor_hint 文案指路,
     * 这里只保证「能到达一个能改的页面」, 不硬编码各家 Activity(改版即失效, 打不开反而更糟)。
     */
    internal fun openKeepaliveSettings(requestBattExempt: Boolean): Boolean = runCatching {
        if (requestBattExempt && android.os.Build.VERSION.SDK_INT >= 23) {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                Uri.parse("package:$packageName")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } else {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.parse("package:$packageName")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
        true
    }.getOrDefault(false)

    private fun ensureAllFilesAccess() {
        if (android.os.Build.VERSION.SDK_INT >= 30 && !Environment.isExternalStorageManager()) {
            startActivity(Intent(
                Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                Uri.parse("package:$packageName")
            ))
        }
    }

    private fun onSpeakEnded() { webCallbacks.onSpeakEnd() }   // TTS 结束→通知前端复位朗读键

    internal fun toFloat() {
        if (!Settings.canDrawOverlays(this)) {
            // 无权限不再裸跳系统页(v4.5 数据: 208 台被拒、46% 再未成功) → 先弹前端引导说明,
            // 用户点「去开启」经 GA.requestOverlayPerm 跳授权页, onResume 检测返回结果并自动接续。
            // 回调探测引导函数是否存在: 旧 webui(热更时序差)无 gaFloatPermGuide → 退回裸跳, 不丢功能。
            Analytics.track("""{"event":"float_perm_denied","props":{"from":"button"}}""")
            webCallbacks.floatPermGuideButton(
                onResult = { r -> if (r != "1") runCatching { startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))) } },
                onEvalFailure = { startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))) },
            )
            return
        }
        val fsi = Intent(this, FloatService::class.java).putExtra("trigger", "manual")
        if (android.os.Build.VERSION.SDK_INT >= 26) startForegroundService(fsi) else startService(fsi)
        moveTaskToBack(true)
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        launchSrc = intent?.getStringExtra("ga_src") ?: launchSrc
        launchCid = intent?.getStringExtra("convo_cid").orEmpty()
        takeAmooTask(intent)
        // 热态复用 Activity：WebView 已 boot，直接切目标会话；冷启动仍走 launchInfo.cid
        if (launchCid.isNotEmpty() && ::webCallbacks.isInitialized) {
            val jsCid = JSONObject.quote(launchCid)
            webCallbacks.raw("window.gaOpenConvo&&gaOpenConvo($jsCid)")
        }
        runAmooTaskIfPending()   // 热态: Py 已就绪, 直接入队
    }

    // amoo 派活: 取 extra 存起来(boot 未完成时先挂起), 由 runAmooTaskIfPending 在 Py.ready 后入队。
    // 另外认 ACTION_SEND(text/plain) 分享进来的句子: 那条链路不经过 amoo 能力目录, 完全端侧可控。
    private fun takeAmooTask(it: android.content.Intent?) {
        var t = it?.getStringExtra(com.ljq.ga.amoo.AmooBridge.EXTRA_TASK).orEmpty()
        var cid = it?.getStringExtra(com.ljq.ga.amoo.AmooBridge.EXTRA_CID).orEmpty()
        if (t.isBlank()) {
            val shared = com.ljq.ga.amoo.AmooBridge.taskFromShare(it)
            if (shared.isNotBlank()) { t = shared; cid = "" }
        }
        if (t.isEmpty()) return
        amooTask = t
        amooCid = cid.ifEmpty { com.ljq.ga.amoo.AmooBridge.newTaskId() }
    }

    // 把挂起的 amoo 任务交给 python 侧(AmooBridge.dispatch -> send2): 失败只记日志, 不阻断 UI。
    private fun runAmooTaskIfPending() {
        val t = amooTask
        if (t.isEmpty()) return
        val cid = amooCid.ifEmpty { com.ljq.ga.amoo.AmooBridge.newTaskId() }
        amooCid = cid
        exec.execute {
            if (!Py.ready) return@execute      // boot 还在跑: 由 boot 块收尾时再调一次
            amooTask = ""
            val r = com.ljq.ga.amoo.AmooBridge.dispatch(cid, t)
            runCatching { android.util.Log.i("GaAmoo", "dispatch cid=$cid r=$r") }
            if (r == "ok") {
                runOnUiThread { runCatching { webCallbacks.raw("window.gaOpenConvo&&gaOpenConvo(${JSONObject.quote(cid)})") } }
                // 收尾回推 amoo: 后台盯到 done 就把结论发回 amoo 聊天框(预填, 用户点一下发送)
                runCatching { com.ljq.ga.amoo.AmooBridge.watchAndReport(this, cid) }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        isForeground = true
        fgSince = System.currentTimeMillis()
        FloatService.live?.dismissAsk()
        if (!permissionCoordinator.pushResumeState()) return
        // 排空 Python agent loop 写的埋点队列(agent 可能在后台跑完一段任务), 及时补身份上报。
        runCatching { Analytics.drainAgentEvents() }
    }

    // 退出/切后台时尽量把埋点队列发出(用户随后可能杀进程,失败则保留至下次启动补发)
    override fun onStop() {
        super.onStop()
        isForeground = false
        if (!isChangingConfigurations && !exec.isShutdown) {
            exec.execute { permissionCoordinator.restoreBackgroundOverlay() }
        }
        if (fgSince > 0) {   // 前台会话时长(app_open 只有起点没有长度): 会话长度分布 = 粘性/健康度基础指标
            val s = (System.currentTimeMillis() - fgSince) / 1000
            fgSince = 0
            runCatching { Analytics.track("""{"event":"app_bg","props":{"fg_s":$s}}""") }
        }
        Analytics.flush()
    }

    override fun onDestroy() {
        resolveMicRequest(false)
        micPermissionInFlight = false
        Analytics.flush()
        runCatching { tts?.shutdown() }
        runCatching { exec.shutdown() }
        // System theme/locale/font changes recreate this Activity. Destroy the old page so its JS bridge,
        // polling and timers stop instead of running beside the new one. 配置变更重建时销毁旧 WebView, 防止旧页继续轮询与常驻内存。
        if (::web.isInitialized) runCatching { (web.parent as? ViewGroup)?.removeView(web); web.destroy() }
        super.onDestroy()
        if (live === this) live = null   // 实例重叠(新 Activity 已接管 live)时不清掉新实例
    }
}
