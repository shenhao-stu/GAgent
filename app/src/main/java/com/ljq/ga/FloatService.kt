package com.ljq.ga

import android.app.Service
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Intent
import android.content.pm.ServiceInfo
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Rect
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.InsetDrawable
import android.hardware.input.InputManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.view.*
import android.widget.TextView
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.math.abs
import android.text.InputType
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import android.widget.LinearLayout
import org.json.JSONArray

// 可拖动状态悬浮窗(还原原版): 点击循环三态(小球→单行→近三步), 长按>450ms 回主界面, 可拖到角落。
// 用户可点击/拖动；Agent 派发手势期间保持可见并暂时穿透，避免手势拖动自己的浮窗。
class FloatService : Service() {
    private lateinit var wm: WindowManager
    private lateinit var tv: TextView
    private lateinit var lp: WindowManager.LayoutParams
    private val ui = Handler(Looper.getMainLooper())
    private val exec = Executors.newSingleThreadExecutor()
    private var alive = true
    private var gestureWindowFlags = 0
    private var gestureWindowAlpha = 1f
    private val gestureLeases = OverlayGestureLeases { active ->
        if (alive && ::tv.isInitialized && tv.isAttachedToWindow) {
            val oldFlags = lp.flags
            val oldAlpha = lp.alpha
            if (active) {
                check(askView == null) { "answer panel open; finish or dismiss it before gestures" }
                val limit = if (Build.VERSION.SDK_INT >= 31)
                    getSystemService(InputManager::class.java).maximumObscuringOpacityForTouch else 1f
                check(limit > 0f) { "system does not allow visible overlay touch passthrough" }
                gestureWindowFlags = oldFlags
                gestureWindowAlpha = oldAlpha
                lp.flags = oldFlags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
                lp.alpha = minOf(oldAlpha, limit)
            } else {
                lp.flags = gestureWindowFlags
                lp.alpha = gestureWindowAlpha
            }
            try { wm.updateViewLayout(tv, lp) }
            catch (e: Exception) { lp.flags = oldFlags; lp.alpha = oldAlpha; throw e }
        }
    }
    private var mode = 1   // 三态循环(点浮窗切换): 0=竖丸(贴边 vertical pill, 最小态, 取代旧小球) / 1=单行(S号·摘要) / 2=近三步多行
    private var dockOverride = false // 本轮用户手动切换后，不再强制贴边。
    private val displayMode get() = if (codeRuns.get() > 0 && !dockOverride) 0 else mode
    private var last: JSONObject? = null                 // 当前聚合焦点会话，供既有渲染/语言逻辑复用
    private var lastPollSnap: JSONObject? = null         // poll_all 的 1s 聚合快照
    private val wasRunningByCid = mutableMapOf<String, Boolean>()
    private val askQueue = linkedMapOf<String, JSONObject>()
    private var askCid: String? = null
    // 悬浮片状态配色(参考 main 的状态着色, 调成 iOS 精致色; 取代旧"墨黑恒不变色")
    private val C_IDLE = Color.parseColor("#1C1C1E")   // 待命: 墨黑(沿用旧风格)
    private val C_RUN  = Color.parseColor("#0A84FF")   // 运行: iOS 蓝
    private val C_DONE = Color.parseColor("#30D158")   // 完成: iOS 绿
    private val SOLID_BODY = 0.8f                       // 完成绿底不透明度 ≥0.8 时深字对任意壁纸 ≥4.5:1(黑/白壁纸实算 5.6/9.6); 更透明改白字+光晕
    private val C_ERR  = Color.parseColor("#D70015")   // 出错: 深红, 实底白字 5.4:1; 用户中止用待命墨黑(非警报)
    private val C_ASK  = Color.parseColor("#FF9F0A")   // 待回答: iOS 橙；与“完成”绿色严格区分
    // 贴边竖丸(vertical pill)尺寸(dp): BAR_W=可见条宽(细, 仅此条着色); DOCK_W=窗口/触控宽(宽出可见条→抓取区伸出系统边缘返回手势带); PILL_H=竖丸高(48: 用户反馈 72 太长, 细度 OK; 仍 ≥ 触控目标)。
    // DOCK_W 30dp 让抓取区超出默认 ~20dp 手势带; 再配 render() setSystemGestureExclusionRects 在竖丸矩形夺回横向拖拽(双保险)。不变量: 可见条恒细且贴屏幕边; 抓取窗恒 DOCK_W。变量: 贴左/右、机型手势带宽 → "窗口宽出条 + 排除矩形"通用兜底, 不写死机型。
    private val BAR_W = 6f; private val DOCK_W = 30f; private val PILL_H = 48f
    // 竖丸运行态"颜色随时长加深"(参考 tuiapp_v2 _heat_color/_mix: 久=色深): 浅蓝起步 → RAMP_SECS 内加深到深蓝; 完成→绿(C_DONE); 待命→墨黑(C_IDLE)。仅竖丸态生效(展开态仍用固定状态色)。

    // Ask panel: expanded overlay opened from the original floating window while ask_user is pending
    private var askView: View? = null
    private var lastAskKey: String? = null
    private var askInput: EditText? = null   // 聚焦/有草稿时 render() 不重建面板(防打字中被拆)
    private var lastOutsideDownTime = -1L     // 面板 ACTION_OUTSIDE 的手势 downTime: 供点丸 DOWN 辨认"这次按下刚收了面板"(F1 竞态, OUTSIDE 先于本 App 的丸 DOWN 派发)
    private val C_RUN_LIGHT = Color.parseColor("#5AC8FA")   // 运行起步: 浅蓝
    private val C_RUN_DEEP  = Color.parseColor("#0A3D91")   // 运行已久: 深蓝
    private val RAMP_SECS = 180f                            // 加深到底时长(3min, 同 tuiapp _HEAT_RAMP "久=醒目"阈值)

    override fun onBind(i: Intent?): IBinder? = null

    // 悬浮窗透明度: 设置页经 GA.setFloatOpacity 写入 SharedPreferences("ga"); 显示时读取(默认 0.9, 不再"完全不透明")
    private fun floatOpacity(): Float =
        getSharedPreferences("ga", MODE_PRIVATE).getFloat("float_opacity", 0.9f).coerceIn(0.3f, 1f)
    // 透明度作用在 View 内(而非 window lp.alpha): window 半透明时 Flyme/Android 会过滤悬浮窗触摸
    // (低不透明度遮挡触摸缓解机制)→ 30% 时拖不动也点不了; View 内的 alpha 纯视觉, 永不影响触摸派发, 窗口保持完全可触。
    // 偏好只淡化胶囊底色, 不淡化文字: 低透明度(如 30%)时底色几乎透出壁纸, 文字可读性不能依赖底色 →
    // 文字恒不透明; 底色足够实(≥SOLID_BODY)时完成态保留深字配绿底, 否则一律白字 + 深色光晕(字幕式), 任意壁纸可读。偏好值本身不改。
    fun applyOpacity(f: Float) { ui.post { styleBody(f.coerceIn(0.3f, 1f)) } }
    private var lastDone = false
    private fun styleBody(f: Float, done: Boolean = lastDone) {
        lastDone = done
        tv.alpha = 1f
        tv.background?.alpha = (f * 255).toInt()
        val darkText = done && f >= SOLID_BODY
        tv.setTextColor(if (darkText) Color.parseColor("#0B1F12") else Color.WHITE)
        if (darkText) tv.setShadowLayer(0f, 0f, 0f, 0)
        else tv.setShadowLayer(3f * resources.displayMetrics.density, 0f, 0f, Color.parseColor("#E6000000"))
    }
    // live = 悬浮球确实挂上屏了(addView 成功后才赋值, onDestroy 清) —— 唯一能代表"实际运行态"的信号;
    // lastError = 最近一次上屏失败的原因, 供设置页/菜单如实说明"开关是开的但球没上去"。
    companion object {
        @Volatile var live: FloatService? = null
        @Volatile var lastError: String? = null
        private val codeRuns = java.util.concurrent.atomic.AtomicInteger()
        @JvmStatic fun codeRunDelta(delta: Int) {
            val count = codeRuns.addAndGet(delta) // 全局计数：并发会话和 Service 重建均不提前展开。
            val s = live ?: return
            val done = java.util.concurrent.CountDownLatch(1)
            val update = Runnable {
                try {
                    if (s.alive) {
                        if (count == 0 || (delta > 0 && count == 1)) s.dockOverride = false
                        s.render()
                        if (s.displayMode == 0 && s.last?.optJSONObject("ask") == null) s.snapEdge()
                    }
                } finally { done.countDown() }
            }
            if (Looper.myLooper() == Looper.getMainLooper()) update.run() else {
                s.ui.post(update)
                if (delta > 0) done.await(500, java.util.concurrent.TimeUnit.MILLISECONDS)
            }
        }
        /** GA 自己悬浮层(状态胶囊/ask 面板)当前屏幕矩形 [[x1,y1,x2,y2],...], 物理 px; 供 droid.look 标 self.
         *  主线程读坐标(拖动中也准), 200ms 超时返回空, 不阻塞 bus。 */
        fun overlayRects(): List<IntArray> {
            val s = live ?: return emptyList()
            val out = java.util.concurrent.CopyOnWriteArrayList<IntArray>()
            val done = java.util.concurrent.CountDownLatch(1)
            s.ui.post {
                runCatching {
                    val views = listOfNotNull(if (s::tv.isInitialized) s.tv else null, s.askView)
                    for (v in views) {
                        if (!v.isAttachedToWindow || v.visibility != View.VISIBLE || v.width <= 0) continue
                        val p = IntArray(2); v.getLocationOnScreen(p)
                        out.add(intArrayOf(p[0], p[1], p[0] + v.width, p[1] + v.height))
                    }
                }
                done.countDown()
            }
            done.await(200, java.util.concurrent.TimeUnit.MILLISECONDS)
            // 前台声明 HIDE_NON_SYSTEM_OVERLAY_WINDOWS(设置页等)时系统强制隐藏悬浮窗但不通知 View → 用 a11y 窗口边界核实确实上屏;
            // 只比 bounds 不取 root, 不触碰前台 App 节点。
            val wins = runCatching { BusA11yService.instance?.windows }.getOrNull() ?: return out.toList()
            val bs = wins.map { android.graphics.Rect().also { r -> it.getBoundsInScreen(r) } }
            return out.filter { r ->
                val area = (r[2] - r[0]).toLong() * (r[3] - r[1])
                bs.any { b -> b.left <= r[0] + 2 && b.top <= r[1] + 2 && b.right >= r[2] - 2 && b.bottom >= r[3] - 2 &&
                    b.width().toLong() * b.height() <= area * 4 }
            }
        }
    }

    /** Screen rects (l,t,r,b) of this service's visible windows plus the display size they live in.
     *  Sampled on the UI thread because window position changes only settle there. */
    fun ownWindowRects(): Triple<List<IntArray>, Int, Int> {
        fun sample(): Triple<List<IntArray>, Int, Int> {
            val metrics = android.util.DisplayMetrics().also { wm.defaultDisplay.getRealMetrics(it) }
            val rects: List<IntArray> = if (!alive) emptyList() else listOfNotNull<View>(tv, askView)
                .filter { it.isAttachedToWindow && it.isShown && it.width > 0 && it.height > 0 }
                .map { v -> val p = IntArray(2); v.getLocationOnScreen(p); intArrayOf(p[0], p[1], p[0] + v.width, p[1] + v.height) }
            return Triple(rects, metrics.widthPixels, metrics.heightPixels)
        }
        if (Looper.myLooper() == Looper.getMainLooper()) return sample()
        val done = CountDownLatch(1)
        var out: Triple<List<IntArray>, Int, Int>? = null
        var failure: Throwable? = null
        ui.post { try { out = sample() } catch (e: Throwable) { failure = e } finally { done.countDown() } }
        check(done.await(1, TimeUnit.SECONDS)) { "overlay geometry timeout" }
        failure?.let { throw it }
        return out!!
    }

    /** Called off the UI thread, before dispatch. Keep the lease until gesture completion. */
    fun passThroughGesture(): () -> Unit {
        check(Looper.myLooper() != Looper.getMainLooper()) { "gesture preparation needs a worker thread" }
        val ready = CountDownLatch(1)
        var release: (() -> Unit)? = null
        var failure: Exception? = null
        val finish = {
            ui.post {
                runCatching { release?.invoke() }.onFailure {
                    lastError = "overlay input restore failed: ${it.javaClass.simpleName}"
                    stopSelf()
                }
            }
            Unit
        }
        fun failed(e: Exception) { failure = e; ready.countDown() }
        fun commitInputFrame() {
            try {
                check(alive && tv.isAttachedToWindow) { "overlay detached before input commit" }
                if (Build.VERSION.SDK_INT >= 33 && tv.isHardwareAccelerated) {
                    SurfaceControl.Transaction().use { transaction ->
                        transaction.addTransactionCommittedListener(mainExecutor) { ready.countDown() }
                        check(tv.rootSurfaceControl?.applyTransactionOnDraw(transaction) == true) {
                            "overlay input transaction rejected"
                        }
                    }
                    tv.invalidate()
                } else ready.countDown()
            } catch (e: Exception) { failed(e) }
        }
        ui.post {
            try {
                check(alive && tv.isAttachedToWindow) { "overlay detached before gesture" }
                release = gestureLeases.acquire()
                // An animation callback can precede the new input window. After layout,
                // submit a drawn frame before dispatching a gesture through this overlay.
                tv.postOnAnimation { ui.post {
                    try {
                        check(alive && tv.isAttachedToWindow) { "overlay detached before frame commit" }
                        if (Build.VERSION.SDK_INT >= 29 && tv.isHardwareAccelerated) {
                            // Submission alone is too early on asynchronous window updates.
                            tv.viewTreeObserver.registerFrameCommitCallback { ui.post { commitInputFrame() } }
                            tv.invalidate()
                        } else {
                            tv.postOnAnimation { ui.post { ready.countDown() } }
                        }
                    } catch (e: Exception) { failed(e) }
                } }
            } catch (e: Exception) { failed(e) }
        }
        try {
            check(ready.await(3, TimeUnit.SECONDS)) { "overlay gesture preparation timeout" }
            failure?.let { throw it }
        } catch (e: Exception) { finish(); throw e }
        return finish
    }

    private var shownTracked = false
    // 浮窗弹出埋点: trigger=manual(用户点「悬浮窗」按钮) / auto(A11y 切到别的 App 时自动弹)。
    // 放 onStartCommand(能拿到 Intent extra)而非 onCreate, 仅首次上报一次。
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!shownTracked) {
            shownTracked = true
            val trig = intent?.getStringExtra("trigger") ?: "manual"
            Analytics.track("""{"event":"float_shown","props":{"trigger":"$trig"}}""")
        }
        return START_STICKY
    }

    override fun onCreate() {
        super.onCreate()
        startFg()
        wm = getSystemService(WINDOW_SERVICE) as WindowManager
        val d = resources.displayMetrics.density
        tv = TextView(this).apply {
            text = "GA"; setTextColor(Color.WHITE); textSize = 12.5f
            maxWidth = (260 * d).toInt(); ellipsize = android.text.TextUtils.TruncateAt.END
            setPadding((12 * d).toInt(), (8 * d).toInt(), (12 * d).toInt(), (8 * d).toInt())
            background = GradientDrawable().apply {
                cornerRadius = 20 * d; setColor(C_IDLE)                                      // 圆角更润(iOS); 实际颜色按运行态在 render() 切换
                setStroke((1 * d).toInt().coerceAtLeast(1), Color.parseColor("#22FFFFFF"))   // 极淡描边, 浅底上也分明
            }
            elevation = 6 * d                                                                // 投影=悬浮感(旧纯墨黑无阴影发飘)
        }
        styleBody(floatOpacity())                                                             // 透明度只淡化底色(纯视觉, 不影响触摸), 默认 0.9
        lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE, PixelFormat.TRANSLUCENT
        ).apply { gravity = Gravity.TOP or Gravity.START; x = (10 * d).toInt(); y = (200 * d).toInt() }
        var sx = 0; var sy = 0; var tx = 0f; var ty = 0f; var t0 = 0L; var panelOpenAtDown = false
        tv.setOnTouchListener { _, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> { sx = lp.x; sy = lp.y; tx = e.rawX; ty = e.rawY; t0 = e.eventTime
                    panelOpenAtDown = askView != null || e.downTime == lastOutsideDownTime   // 起点面板态: 面板窗 FLAG_WATCH_OUTSIDE_TOUCH 在本 DOWN *前*派发 OUTSIDE 已收面板(askView 已 null)→ 按同手势 downTime 辨认"这次按下刚收了面板", 仍判起点为开→UP 走收(dismissAsk 幂等), 不误重开
                    true }
                MotionEvent.ACTION_MOVE -> {
                    lp.x = sx + (e.rawX - tx).toInt(); lp.y = sy + (e.rawY - ty).toInt()
                    wm.updateViewLayout(tv, lp); true
                }
                MotionEvent.ACTION_UP -> {
                    if (abs(e.rawX - tx) < 12 && abs(e.rawY - ty) < 12) {             // 位移<12px=点击(非拖动)
                        if (e.eventTime - t0 > 450) backToApp()                       // 长按>450ms=回主界面
                        else {
                            val askObj = last?.optJSONObject("ask")
                            if (askObj != null && !MainActivity.isForeground) {        // 待回答且 GA 在后台: 浮窗是唯一入口(前台入口=应用内 askBox, 面板会被 render 秒关)
                                if (!panelOpenAtDown) showAsk(askObj, last?.optString("cid").orEmpty()) else dismissAsk()   // 开关按手势起点态判定(见 DOWN 处): 起点开→收, 起点关→展(dismissAsk 幂等, OUTSIDE 已先收也无害)
                                Analytics.track("""{"event":"float_tap","props":{"action":"ask"}}""")
                            } else {
                                mode = if (codeRuns.get() > 0 && !dockOverride) 1 else (mode + 1) % 3
                                dockOverride = codeRuns.get() > 0
                                render()                        // 普通状态: 循环三态(0竖丸/1单行/2近三步)
                                if (mode == 0) tv.post { snapEdge() }                   // 切到竖丸→吸附最近横向边(tv.post: render 后读最终窗宽再贴边)
                                Analytics.track("""{"event":"float_tap","props":{"mode":$mode}}""")
                            }
                        }
                    } else { render(); tv.post { constrainPosition(displayMode == 0) }
                        Analytics.track("""{"event":"float_drag","props":{"mode":$mode}}""") }
                    true
                }
                else -> false
            }
        }
        // addView 是本服务唯一的"上屏"动作, 失败半径=整个悬浮窗功能: 裸调则 onCreate 抛出→进程崩溃,
        // 且 live 停在 null 让上层看不出所以然。收敛为服务自身失败: 记错因 + stopSelf, live 保持 null
        // → PermissionCoordinator 的 live==null 重试与前端 floatState().running 都能如实看到"没上屏"。
        // 失败真实存在: canDrawOverlays 与 addView 之间权限可被撤(BadToken), 部分 ROM 对 overlay 数量另有配额。
        val added = runCatching { wm.addView(tv, lp) }
        if (added.isFailure) {
            lastError = added.exceptionOrNull()?.let { it::class.java.simpleName + ": " + (it.message ?: "") } ?: "addView failed"
            Analytics.track("""{"event":"float_add_failed","props":{"err":${JSONObject.quote(lastError ?: "")}}}""")
            stopSelf(); return
        }
        lastError = null
        ui.post(loop)
        live = this
        if (codeRuns.get() > 0) render()
    }

    private val loop = object : Runnable {
        override fun run() {
            if (!alive) return
            exec.execute {
                // -1=只读摘要：浮窗观察所有会话但不消费 ask/cmd_error；旧核无 poll_all 时回退单会话 poll。
                val s = runCatching { Py.call("poll_all", "-1") }
                    .recoverCatching { JSONObject().put("sessions", JSONArray().put(JSONObject(Py.call("poll", "-3")))).toString() }
                    .getOrNull() ?: return@execute
                ui.post { if (alive) { lastPollSnap = JSONObject(s); render() } }
            }
            ui.postDelayed(this, 1000)
        }
    }

    // 吸附到最近横向边(贴边): 用当前窗口宽(竖丸 mode0=固定 DOCK_W>0; 展开=取已测视图宽)算左/右贴边, 并夹 y 防竖丸超出屏幕上下。
    private fun snapEdge() {
        constrainPosition(true)
    }

    private fun constrainPosition(dock: Boolean = false) {
        val w = if (lp.width > 0) lp.width else if (tv.width > 0) tv.width else (60 * resources.displayMetrics.density).toInt()
        val metrics = android.util.DisplayMetrics().also { wm.defaultDisplay.getRealMetrics(it) }
        val h = if (lp.height > 0) lp.height else tv.height
        val (x, y) = overlayPosition(lp.x, lp.y, w, h, metrics.widthPixels, metrics.heightPixels, dock)
        lp.x = x; lp.y = y
        runCatching { wm.updateViewLayout(tv, lp) }
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        if (::tv.isInitialized && tv.isAttachedToWindow) {
            tv.maxWidth = minOf((260 * resources.displayMetrics.density).toInt(), resources.displayMetrics.widthPixels)
            tv.post { if (alive) constrainPosition(displayMode == 0) }
        }
    }
    // 仅在尺寸变化时 updateViewLayout(loop 每秒 render → 避免无谓重排闪烁)。bg/text 是 View 属性, 设置即生效, 不经此。
    private fun setWinSize(w: Int, h: Int) {
        if (lp.width == w && lp.height == h) return
        lp.width = w; lp.height = h
        runCatching { wm.updateViewLayout(tv, lp) }
        tv.post { if (alive) constrainPosition(displayMode == 0) }
    }
    // 给状态色叠加透明度(0..1)→ ARGB int(GradientDrawable.setColor 需 ARGB): 竖丸半透明用
    private fun withAlpha(c: Int, a: Float): Int =
        Color.argb((a.coerceIn(0f, 1f) * 255).toInt(), Color.red(c), Color.green(c), Color.blue(c))
    // 线性插值两色(RGB, t∈0..1) → 竖丸按运行时长在浅/深蓝间取色(同 tuiapp _mix); 通用, 无 API 依赖
    private fun mixColor(a: Int, b: Int, t: Float): Int {
        val u = t.coerceIn(0f, 1f)
        return Color.rgb(
            (Color.red(a)   * (1 - u) + Color.red(b)   * u).toInt(),
            (Color.green(a) * (1 - u) + Color.green(b) * u).toInt(),
            (Color.blue(a)  * (1 - u) + Color.blue(b)  * u).toInt())
    }

    // 文案跟随 UI 语言: 读 poll 的 lang 键(单一真相源=android_entry._LANG, UI /lang 设置);
    // last 即 poll 快照, 不另存字段; 键缺省(旧核)或首拉前 → 中文(与 _LANG 默认一致)。
    private fun s(zh: String, en: String): String =
        if (last?.optString("lang") == "en") en else zh

    private fun render() {
        val mode = displayMode
        val snap = lastPollSnap ?: JSONObject()
        val a = snap.optJSONArray("sessions") ?: JSONArray().put(snap)   // legacy fallback is one synthetic session
        val sessions = (0 until a.length()).mapNotNull { a.optJSONObject(it) }
        if (sessions.isEmpty()) return
        val active = sessions.firstOrNull()?.optString("active_convo").orEmpty()
        fun rank(x: JSONObject): Int = when {
            x.optJSONObject("ask") != null -> 3
            x.optBoolean("running") -> 2
            else -> 1
        }
        // pending ask > running > completed；同级优先当前焦点，再按后端 generation 取最近。
        val j = sessions.maxWithOrNull(compareBy<JSONObject>({ rank(it) }, { if (it.optString("cid") == active) 1 else 0 }, { it.optLong("gen", 0L) })) ?: return
        last = j
        askQueue.clear()
        sessions.forEach { x -> x.optJSONObject("ask")?.let { askQueue[x.optString("cid")] = it } }
        val liveCids = sessions.map { it.optString("cid") }.toSet()
        sessions.forEach { x ->
            val cid = x.optString("cid")
            val now = x.optBoolean("running")
            val before = wasRunningByCid[cid]
            val ended = !now && (x.optJSONObject("ask") != null || x.optInt("nsteps") > 0)
            if (before == true && ended && x.optString("end") != "stopped") notifyTaskEnd(x, cid)   // 用户自己按停不再响铃振动报「完成」
            wasRunningByCid[cid] = now
        }
        wasRunningByCid.keys.retainAll(liveCids)
        val cid = j.optString("cid")
        val steps = j.optJSONArray("steps")
        val tail = steps?.optJSONObject((steps.length()) - 1)
        val run = j.optBoolean("running")
        val askObj = j.optJSONObject("ask")
        val asking = askObj != null
        val end = j.optString("end")                                         // done/stopped/error; 旧核无此键 → "" 按完成处理(兼容)
        val ended = !run && !asking && j.optInt("nsteps") > 0
        val stopped = ended && end == "stopped"
        val failed = ended && end == "error"
        val done = ended && !stopped && !failed                              // ask 是待回答而非完成；只有真完成允许绿色(中止/出错不冒充完成)
        val d = resources.displayMetrics.density
        if (mode == 0 && !asking) {
            // 竖丸(vertical pill, 最小态, 取代旧小球): 细、半透明、贴屏幕边、无文字 → 极简、极大减少遮挡。颜色: 运行态按时长由浅蓝加深到深蓝(深=久, 参考 tuiapp _heat_color); 完成→绿; 待命→墨黑。
            // 可见条 BAR_W 细; 窗口(触控区)宽到 DOCK_W: 让出系统边缘返回手势带 + 满足抓取目标(纯细条贴边会被手势吞/难点中, 不鲁棒)。
            val barW = (BAR_W * d).toInt(); val dockW = (DOCK_W * d).toInt(); val pillH = (PILL_H * d).toInt()
            val sw = resources.displayMetrics.widthPixels
            val onLeft = lp.x + dockW / 2 < sw / 2                       // 与 snapEdge 同判据 → 渲染贴边侧恒等于吸附侧
            val pillColor = when {                                       // 运行时长→颜色深度: 越久越深蓝; 完成绿; 待命墨黑(elapsed 来自后端 poll, 真机准, 浮窗中途打开也对)
                done -> C_DONE
                failed -> C_ERR
                run  -> mixColor(C_RUN_LIGHT, C_RUN_DEEP, j.optDouble("elapsed", 0.0).toFloat() / RAMP_SECS)
                else -> C_IDLE
            }
            val bar = GradientDrawable().apply {
                setColor(withAlpha(pillColor, 0.72f))                    // 半透明: 既显状态又不挡背后(用户要的"透明颜色")
                cornerRadius = barW / 2f                                  // 全圆端 = 竖胶囊
                setStroke((1 * d).toInt().coerceAtLeast(1), Color.parseColor("#33FFFFFF"))   // 极淡描边: 任意壁纸都分明(鲁棒)
            }
            // 可见细条贴【屏幕】边: 左吸附→条置窗口左侧(右侧留触控空白); 右吸附→条置窗口右侧。
            tv.background = if (onLeft) InsetDrawable(bar, 0, 0, dockW - barW, 0)
                            else InsetDrawable(bar, dockW - barW, 0, 0, 0)
            styleBody(floatOpacity(), done)
            tv.text = ""; tv.setPadding(0, 0, 0, 0); tv.maxLines = 1
            setWinSize(dockW, pillH)
            if (Build.VERSION.SDK_INT >= 29) tv.systemGestureExclusionRects = listOf(Rect(0, 0, dockW, pillH))   // 竖丸矩形内夺回横向拖拽优先级, 不被系统边缘返回手势抢走(尽力而为, 配合 DOCK_W 宽出条双保险)
        } else {
            // 展开态(单行/近三步，或 ask 强制提示态): ask 橙 / 运行蓝 / 真完成绿 / 待命墨黑。
            val state = when {
                asking -> C_ASK
                done -> C_DONE
                failed -> C_ERR
                run -> C_RUN
                else -> C_IDLE
            }
            tv.background = GradientDrawable().apply {
                cornerRadius = 20 * d; setColor(state)
                setStroke((1 * d).toInt().coerceAtLeast(1), Color.parseColor("#22FFFFFF"))
            }
            styleBody(floatOpacity(), done)   // 实底: 浅绿底配深字、ask/墨黑/蓝底配白字; 低透明度: 白字 + 光晕
            tv.setPadding((12 * d).toInt(), (8 * d).toInt(), (12 * d).toInt(), (8 * d).toInt())
            tv.maxLines = if (!asking && mode == 2) 4 else 1
            val badge = if (askQueue.size > 1) "[${askQueue.size}] " else ""
            tv.text = when {
                asking -> badge + s("需要你回复 · 点击回答", "Reply needed · Tap to answer")
                done && mode == 1 -> s("✔ 完成", "✔ Done")
                stopped && mode == 1 -> s("■ 已停止", "■ Stopped")
                failed && mode == 1 -> s("⚠ 出错", "⚠ Error")
                mode == 1 -> tail?.let { "S${it.optInt("n")} · ${it.optString("summary")}" } ?: j.optString("status", "GA")
                else -> buildString {                                                 // mode==2 近三步
                    for (k in 0 until (steps?.length() ?: 0)) steps!!.optJSONObject(k)
                        .let { appendLine("S${it.optInt("n")} ${it.optString("summary").take(20)}") }
                    append("〔${j.optString("status")}〕")
                }
            }
            setWinSize(WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT)
            if (Build.VERSION.SDK_INT >= 29) tv.systemGestureExclusionRects = emptyList()   // 展开态不在边缘抓取 → 撤销手势排除
        }
        // 每个 cid 的运行→结束跳变已在聚合循环中独立检测，避免一个会话覆盖另一个会话状态。
        // 旧浮窗是 ask 的唯一提示入口，不自动创建第二个气泡。仅在面板已打开且问题变化时刷新内容;
        // 输入框聚焦/有草稿时不重建(lastAskKey 留旧值, 草稿清空后自然补刷)。
        val askKey = askObj?.let(::askKeyOf)
        if (askView != null) {
            if (askObj == null || MainActivity.isForeground) dismissAsk()
            else if (lastAskKey != askKey && askInput?.let { it.hasFocus() || it.text.isNotEmpty() } != true) showAsk(askObj, cid)
        }
    }

    private fun backToApp() {
        Analytics.track("""{"event":"float_back","props":{"via":"longpress"}}""")   // 长按浮窗回主界面
        startActivity(Intent(this, MainActivity::class.java)
            .putExtra("ga_src", "float").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        stopSelf()   // onResume 也会 stopService(本服务), 双停幂等无害
    }

    // 任务结束(完成/待答/出错)时发高优先级系统通知: 横幅 + 提示音 + 振动。
    // 必须由原生发: GA 退后台驱动他 App 时 WebView 被挂起, 其 onTaskDone/通知不会触发(旧 bug: 只有切回 GA 才响)。
    private fun notifyTaskEnd(j: JSONObject, cid: String) {
        val askObj = j.optJSONObject("ask")
        val ask = askObj != null && (askObj.optString("question").isNotEmpty() ||
            (askObj.optJSONArray("candidates")?.length() ?: 0) > 0)
        val chId = "ga_taskend"
        val nm = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val ch = NotificationChannel(chId, s("GA 任务提醒", "GA task alerts"), NotificationManager.IMPORTANCE_HIGH)
            ch.enableVibration(true)
            nm.createNotificationChannel(ch)
        }
        val pi = android.app.PendingIntent.getActivity(this, cid.hashCode(),
            Intent(this, MainActivity::class.java)
                .setAction("com.ljq.ga.OPEN_TASK.$cid")   // PendingIntent identity 按 cid 隔离，避免 UPDATE_CURRENT 串改其他会话 extra
                .putExtra("ga_src", "notif_task").putExtra("convo_cid", cid).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            android.app.PendingIntent.FLAG_IMMUTABLE or android.app.PendingIntent.FLAG_UPDATE_CURRENT)
        val status = j.optString("status")
        val b = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) Notification.Builder(this, chId)
            else @Suppress("DEPRECATION") Notification.Builder(this)
                .setPriority(Notification.PRIORITY_HIGH)
                .setDefaults(Notification.DEFAULT_SOUND or Notification.DEFAULT_VIBRATE)
        val n = b.setContentTitle(when {
                ask -> s("GenericAgent 需要你的操作", "GenericAgent needs your input")
                j.optString("end") == "error" -> s("GenericAgent 任务出错", "GenericAgent task failed")
                else -> s("GenericAgent 任务完成", "GenericAgent task complete")
            })
            .setContentText(if (status.isNotEmpty()) status.take(80) else if (ask) s("点此返回回答", "Tap to reply") else s("点此查看结果", "Tap to view the result"))
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setAutoCancel(true).setContentIntent(pi).build()
        nm.notify(cid, 2001, n)   // tag=cid：各会话通知互不覆盖
    }


    // ── Ask Panel ──────────────────────────────────────────────────────────────
    // ask 内容键(question+candidates, 与 app.js askKey 同构): 不依赖 JSONObject.toString() 键序这一跨层隐式契约
    private fun askKeyOf(askObj: JSONObject): String =
        askObj.optString("question") + "|" + (askObj.optJSONArray("candidates")?.join("|") ?: "")

    fun dismissAsk() {
        val v = askView ?: return
        askView = null
        lastAskKey = null
        askInput = null
        v.animate().alpha(0f).translationY(8 * resources.displayMetrics.density)
            .setDuration(150L)
            .setInterpolator(android.view.animation.PathInterpolator(0.3f, 0f, 0.8f, 0.15f))
            .withEndAction { runCatching { wm.removeView(v) } }.start()
    }

    private fun showAsk(askObj: JSONObject, cid: String) {
        dismissAsk()
        askCid = cid
        var sent = false   // 单次提交闸(候选点按/自定义发送共用): 退场动画期内二次触发不重复送(答案=会话唯一新回合)
        val d = resources.displayMetrics.density
        val sw = resources.displayMetrics.widthPixels
        val sh = resources.displayMetrics.heightPixels

        fun dp(value: Float): Int = (value * d + 0.5f).toInt()
        val medium = android.graphics.Typeface.create("sans-serif-medium", android.graphics.Typeface.NORMAL)
        fun shape(fill: Int, radiusDp: Float, stroke: Int = Color.TRANSPARENT, strokeDp: Float = 1f): GradientDrawable =
            GradientDrawable().apply {
                cornerRadius = radiusDp * d
                setColor(fill)
                if (Color.alpha(stroke) > 0) setStroke(dp(strokeDp).coerceAtLeast(1), stroke)
            }
        fun ripple(content: GradientDrawable, radiusDp: Float, color: Int): android.graphics.drawable.Drawable =
            android.graphics.drawable.RippleDrawable(
                android.content.res.ColorStateList.valueOf(color),
                content,
                shape(Color.WHITE, radiusDp)
            )

        val accent = Color.parseColor("#FFFFB547")
        val accentText = Color.parseColor("#FF241708")
        val accentSoft = Color.parseColor("#29FFB547")
        val panelColor = Color.parseColor("#F5191A1F")
        val surfaceColor = Color.parseColor("#FF25272E")
        val surfaceRaised = Color.parseColor("#FF2C2E36")
        val borderColor = Color.parseColor("#2EFFFFFF")
        val textPrimary = Color.parseColor("#FFF7F7F8")
        val textSecondary = Color.parseColor("#A8FFFFFF")
        val textMuted = Color.parseColor("#80FFFFFF")
        val question = askObj.optString("question", "").trim().ifEmpty {
            s("\u9700\u8981\u4f60\u786e\u8ba4\u4e0b\u4e00\u6b65\u64cd\u4f5c", "Please confirm the next step")
        }
        val sourceCandidates: JSONArray? = askObj.optJSONArray("candidates")
        val candidates = mutableListOf<String>()
        if (sourceCandidates != null) {
            for (i in 0 until sourceCandidates.length()) {
                sourceCandidates.optString(i).trim().takeIf { it.isNotEmpty() }?.let(candidates::add)
            }
        }

        val shadowSpace = dp(16f)
        val desiredPanelY = maxOf(dp(24f), (sh * 0.12f).toInt())
        val panelY = minOf(desiredPanelY, (sh - shadowSpace * 2 - 1).coerceAtLeast(0))
        val bottomClearance = minOf(
            dp(24f),
            (sh - panelY - shadowSpace * 2 - 1).coerceAtLeast(0)
        )
        val maxCardHeight = (sh - panelY - bottomClearance - shadowSpace * 2).coerceAtLeast(1)

        // Transparent breathing room prevents the elevated card shadow from being clipped.
        // 面板窗可聚焦(EditText 要 IME)→ 打开期间 key 事件归它: BACK 必须收面板而非被吞; 面板外点击也收起。
        val root = object : LinearLayout(this) {
            override fun dispatchKeyEvent(e: KeyEvent): Boolean =
                if (e.keyCode == KeyEvent.KEYCODE_BACK) { if (e.action == KeyEvent.ACTION_UP) dismissAsk(); true }
                else super.dispatchKeyEvent(e)
        }.apply {
            orientation = LinearLayout.VERTICAL
            setPadding(shadowSpace, shadowSpace, shadowSpace, shadowSpace)
        }
        root.setOnTouchListener { _, e ->
            if (e.actionMasked == MotionEvent.ACTION_OUTSIDE) { lastOutsideDownTime = e.downTime; dismissAsk(); true } else false   // 记本次手势 downTime: 点丸收面板时丸 DOWN 据此不误重开(F1)
        }
        val panel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val horizontal = dp(20f)
            setPadding(horizontal, dp(20f), horizontal, dp(20f))
        }

        // Header: a compact action signal, clear owner, and a full-size close target.
        val headerRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        val askMark = TextView(this).apply {
            text = "?"
            setTextColor(accent)
            textSize = 16f
            gravity = Gravity.CENTER
            includeFontPadding = false
            setTypeface(typeface, android.graphics.Typeface.BOLD)
            background = shape(accentSoft, 14f)
            contentDescription = s("\u9700\u8981\u56de\u590d", "Reply needed")
        }
        headerRow.addView(askMark, LinearLayout.LayoutParams(dp(28f), dp(28f)).apply {
            rightMargin = dp(12f)
        })

        val headerCopy = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        headerCopy.addView(TextView(this).apply {
            text = s("\u9700\u8981\u4f60\u7684\u56de\u590d", "Your reply is needed")
            setTextColor(textPrimary)
            textSize = 14f
            includeFontPadding = false
            typeface = medium
        })
        headerCopy.addView(TextView(this).apply {
            text = s("GenericAgent \u6b63\u5728\u7b49\u5f85\u4f60\u7684\u51b3\u5b9a", "GenericAgent is waiting for your decision")
            setTextColor(textSecondary)
            textSize = 12f
            includeFontPadding = false
            setPadding(0, dp(4f), 0, 0)
        })
        headerRow.addView(headerCopy, LinearLayout.LayoutParams(0,
            LinearLayout.LayoutParams.WRAP_CONTENT, 1f))

        val closeBtn = TextView(this).apply {
            text = "\u00d7"
            setTextColor(textSecondary)
            textSize = 22f
            gravity = Gravity.CENTER
            includeFontPadding = false
            isClickable = true
            isFocusable = true
            background = ripple(shape(Color.TRANSPARENT, 22f), 22f,
                Color.parseColor("#24FFFFFF"))
            contentDescription = s("\u5173\u95ed\u56de\u7b54\u9762\u677f", "Close reply panel")
            setOnClickListener { dismissAsk() }
        }
        headerRow.addView(closeBtn, LinearLayout.LayoutParams(dp(44f), dp(44f)).apply {
            leftMargin = dp(6f)
        })
        panel.addView(headerRow, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        ).apply { bottomMargin = dp(20f) })

        // The question is the visual anchor rather than another decorated card.
        panel.addView(TextView(this).apply {
            text = question
            setTextColor(textPrimary)
            textSize = 17f
            setLineSpacing(0f, 1.3f)
            typeface = medium
        }, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        ).apply { bottomMargin = dp(20f) })

        fun sectionLabel(label: String): TextView = TextView(this).apply {
            text = label
            setTextColor(textSecondary)
            textSize = 11f
            includeFontPadding = false
            typeface = medium
            letterSpacing = 0.08f
        }

        fun candidateView(index: Int, label: String): View {
            val option = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                minimumHeight = dp(52f)
                val horizontal = dp(12f)
                setPadding(horizontal, dp(12f), horizontal, dp(12f))
                isClickable = true
                isFocusable = true
                background = ripple(
                    shape(surfaceColor, 16f),
                    16f,
                    Color.parseColor("#30FFB547")
                )
                contentDescription = s("\u9009\u9879 ${index + 1}\uff1a$label", "Option ${index + 1}: $label")
                setOnClickListener { if (!sent) { sent = true; submitAnswer(label); dismissAsk() } }
            }
            option.addView(TextView(this).apply {
                text = (index + 1).toString()
                setTextColor(accent)
                textSize = 11f
                gravity = Gravity.CENTER
                includeFontPadding = false
                setTypeface(typeface, android.graphics.Typeface.BOLD)
                background = shape(accentSoft, 12f)
            }, LinearLayout.LayoutParams(dp(24f), dp(24f)).apply {
                rightMargin = dp(8f)
            })
            option.addView(TextView(this).apply {
                text = label
                setTextColor(textPrimary)
                textSize = 14f
                gravity = Gravity.START or Gravity.CENTER_VERTICAL
                setLineSpacing(0f, 1.2f)
            }, LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            return option
        }

        if (candidates.isNotEmpty()) {
            panel.addView(sectionLabel(s("\u5feb\u901f\u9009\u62e9", "Quick replies")), LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = dp(8f) })

            val choices = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
            val useTwoColumns = candidates.size > 1 && candidates.all { it.length <= 14 }
            if (useTwoColumns) {
                var i = 0
                while (i < candidates.size) {
                    val row = LinearLayout(this).apply {
                        orientation = LinearLayout.HORIZONTAL
                        gravity = Gravity.TOP
                    }
                    if (i == candidates.lastIndex) {
                        row.addView(candidateView(i, candidates[i]), LinearLayout.LayoutParams(
                            LinearLayout.LayoutParams.MATCH_PARENT,
                            LinearLayout.LayoutParams.WRAP_CONTENT
                        ))
                    } else {
                        row.addView(candidateView(i, candidates[i]), LinearLayout.LayoutParams(
                            0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f
                        ))
                        row.addView(candidateView(i + 1, candidates[i + 1]), LinearLayout.LayoutParams(
                            0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f
                        ).apply { leftMargin = dp(8f) })
                    }
                    choices.addView(row, LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT
                    ).apply { if (i + 2 < candidates.size) bottomMargin = dp(8f) })
                    i += 2
                }
            } else {
                candidates.forEachIndexed { index, label ->
                    choices.addView(candidateView(index, label), LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT
                    ).apply { if (index < candidates.lastIndex) bottomMargin = dp(8f) })
                }
            }
            panel.addView(choices, LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = dp(20f) })
        }

        // Custom reply is a complete composer with focus and disabled/enabled feedback.
        panel.addView(sectionLabel(s("\u81ea\u5b9a\u4e49\u56de\u590d", "Custom reply")), LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        ).apply { bottomMargin = dp(8f) })

        fun inputBackground(focused: Boolean): GradientDrawable = shape(
            surfaceRaised,
            16f,
            if (focused) Color.parseColor("#B8FFB547") else borderColor,
            if (focused) 2f else 1f
        )
        val input = EditText(this).apply {
            hint = s("\u8f93\u5165\u4f60\u7684\u56de\u590d\u2026", "Type your reply\u2026")
            setHintTextColor(textMuted)
            setTextColor(textPrimary)
            textSize = 14f
            background = inputBackground(false)
            val horizontal = dp(16f)
            setPadding(horizontal, dp(12f), horizontal, dp(12f))
            minHeight = dp(56f)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_SENTENCES or
                InputType.TYPE_TEXT_FLAG_MULTI_LINE
            imeOptions = android.view.inputmethod.EditorInfo.IME_ACTION_SEND or
                android.view.inputmethod.EditorInfo.IME_FLAG_NO_EXTRACT_UI
            maxLines = 4
            gravity = Gravity.TOP or Gravity.START
            setOnFocusChangeListener { _, focused -> background = inputBackground(focused) }
        }
        panel.addView(input, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        ))

        val sendButton = TextView(this).apply {
            text = s("\u53d1\u9001\u56de\u590d", "Send reply")
            textSize = 14f
            gravity = Gravity.CENTER
            includeFontPadding = false
            typeface = medium
            minimumHeight = dp(48f)
            contentDescription = s("\u53d1\u9001\u81ea\u5b9a\u4e49\u56de\u590d", "Send custom reply")
        }
        fun updateSendState() {
            val enabled = input.text.toString().trim().isNotEmpty()
            sendButton.isEnabled = enabled
            sendButton.setTextColor(if (enabled) accentText else textMuted)
            sendButton.background = if (enabled) {
                ripple(shape(accent, 24f), 24f, Color.parseColor("#35FFFFFF"))
            } else {
                shape(Color.parseColor("#FF30323A"), 24f, Color.parseColor("#18FFFFFF"))
            }
        }
        fun sendCustomReply(): Boolean {
            val answer = input.text.toString().trim()
            if (answer.isEmpty()) return false
            if (sent) return false        // 单次提交闸: send 键与 IME_ACTION_SEND 双入口, 退场期不重复送
            sent = true
            submitAnswer(answer)
            dismissAsk()
            return true
        }
        sendButton.setOnClickListener { sendCustomReply() }
        input.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == android.view.inputmethod.EditorInfo.IME_ACTION_SEND) {
                sendCustomReply()
            } else false
        }
        input.addTextChangedListener(object : android.text.TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) = Unit
            override fun afterTextChanged(s: android.text.Editable?) = updateSendState()
        })
        updateSendState()
        panel.addView(sendButton, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            dp(48f)
        ).apply { topMargin = dp(12f) })

        val card = object : android.widget.ScrollView(this) {
            override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
                val parentLimit = when (MeasureSpec.getMode(heightMeasureSpec)) {
                    MeasureSpec.UNSPECIFIED -> maxCardHeight
                    else -> minOf(MeasureSpec.getSize(heightMeasureSpec), maxCardHeight)
                }
                super.onMeasure(
                    widthMeasureSpec,
                    MeasureSpec.makeMeasureSpec(parentLimit, MeasureSpec.AT_MOST)
                )
            }
        }.apply {
            isFillViewport = false
            isVerticalScrollBarEnabled = true
            overScrollMode = View.OVER_SCROLL_IF_CONTENT_SCROLLS
            background = shape(panelColor, 28f, borderColor)
            elevation = 12f * d
            clipToOutline = true
        }
        card.addView(panel, android.widget.FrameLayout.LayoutParams(
            android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
            android.widget.FrameLayout.LayoutParams.WRAP_CONTENT
        ))
        root.addView(card, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        ))

        val panelWidth = minOf((sw - dp(16f)).coerceAtLeast(1), dp(420f))
        val params = WindowManager.LayoutParams(
            panelWidth,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
            y = panelY
            softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
        }

        root.alpha = 0f
        root.scaleX = 0.98f
        root.scaleY = 0.98f
        root.translationY = dp(12f).toFloat()
        runCatching { wm.addView(root, params) }.onSuccess {
            askView = root
            lastAskKey = askKeyOf(askObj)
            askInput = input
            root.animate()
                .alpha(1f)
                .scaleX(1f)
                .scaleY(1f)
                .translationY(0f)
                .setDuration(250L)
                .setInterpolator(android.view.animation.PathInterpolator(0.05f, 0.7f, 0.1f, 1f))
                .start()
        }
    }

    // JOINT CONTRACT(app.js gaFloatAnswer): 参数必须是合法 JS 字符串字面量 — JSONObject.quote 全量转义;
    // U+2028/29 是 JS 行终止符但 Android JSONStringer 只转义 <=0x1F, 手动补。JS 侧只 String() 不 JSON.parse。
    // Activity 已死(live==null): 不原生直送(会绕过 startTask 建气泡/单发闸 → 冷启对账错位+可能重发),
    //   改为拉起 GA; 待答 ask 由 app.js 冷启对账自动重现, 用户在应用内正常作答(此分支极少: 前台服务存活但 Activity 已销毁)。
    private fun submitAnswer(ans: String) {
        val q = JSONObject.quote(ans).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
        val c = JSONObject.quote(askCid.orEmpty())
        val m = MainActivity.live
        if (m != null) m.evalJs("window.gaFloatAnswer&&gaFloatAnswer($q,$c)")
        else runCatching {   // Activity 已死: 无 WebView 承接草稿, 明确提示后拉起 GA(待答 ask 应用内重现), 不静默吞答案
            android.widget.Toast.makeText(this, s("请在 GA 内完成回答", "Please finish answering in GA"), android.widget.Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, MainActivity::class.java)
                .putExtra("ga_src", "float").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))   // 与埋点约定一致: 悬浮窗→GA 唤起标记 ga_src=float
        }
    }

    override fun onDestroy() {
        alive = false
        live = null
        ui.removeCallbacks(loop)
        exec.shutdown()
        Analytics.track("""{"event":"float_dismissed","props":{}}""")   // 浮窗关闭(配合 float_shown 算停留时长)
        runCatching { askView?.let { wm.removeView(it) } }; askView = null; askInput = null
        runCatching { wm.removeView(tv) }
        super.onDestroy()
    }

    // 前台化保活: IMPORTANCE_MIN 渠道, 状态栏不显图标, 仅通知栏底部低调一条, 换取进程不被杀(a11y稳定)
    private fun startFg() {
        val chId = "ga_keepalive"
        val nm = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val ch = NotificationChannel(chId, "GA 后台保活", NotificationManager.IMPORTANCE_MIN)
            ch.setShowBadge(false)
            nm.createNotificationChannel(ch)
        }
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
            Notification.Builder(this, chId) else @Suppress("DEPRECATION") Notification.Builder(this)
        val pi = android.app.PendingIntent.getActivity(this, 0,
            Intent(this, MainActivity::class.java)
                .putExtra("ga_src", "notif_keepalive").addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            android.app.PendingIntent.FLAG_IMMUTABLE or android.app.PendingIntent.FLAG_UPDATE_CURRENT)
        val n = builder
            .setContentTitle("GenericAgent 运行中")
            .setContentText("点此返回 GA")            // 长按浮窗可回主界面; 这条通知是次要返回路径(onResume 会停掉浮窗)
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setOngoing(true)
            .setContentIntent(pi)
            .build()
        if (Build.VERSION.SDK_INT >= 34)
            startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        else startForeground(1, n)
    }
}
