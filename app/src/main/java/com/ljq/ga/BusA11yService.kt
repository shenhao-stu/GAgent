package com.ljq.ga

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Bitmap
import android.graphics.Path
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.SystemClock
import android.util.DisplayMetrics
import android.view.Display
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.random.Random

/** 无障碍服务: 被 BusHttpd 调用。移植自旧 GenericAgentAndroid/AgentA11yService。 */
class BusA11yService : AccessibilityService() {
    companion object {
        var instance: BusA11yService? = null

        /** AOSP WindowConfiguration.WINDOWING_MODE_FULLSCREEN; 公开 SDK 无此常量, 本地字面量声明(同 VdHelper 做法)。 */
        private const val WINDOWING_MODE_FULLSCREEN = 1
    }

    override fun onServiceConnected() {
        instance = this
        // 无障碍开启=手机版核心操控能力就绪(前面漏斗看不到此维度)。init 幂等, 服务可能先于 Activity 起。
        runCatching { Analytics.init(applicationContext); Analytics.track("""{"event":"a11y_enabled","props":{}}""") }
    }
    override fun onDestroy() {
        if (instance == this) instance = null
        runCatching { ActStats.flush() }   // 服务收尾前把未满批的操作统计冲出去, 不留尾巴
        runCatching { Analytics.track("""{"event":"a11y_disabled","props":{}}""") }   // 用户关掉无障碍=操控能力流失点
        super.onDestroy()
    }
    // 被动前台包名: 系统推送的 TYPE_WINDOW_STATE_CHANGED 自带 packageName, 不向目标 App 发任何节点请求。
    // 用于 act() 统计等"只要大概前台"的场合, 替代 rootInActiveWindow?.packageName —— 后者每次动作都会向前台 App
    // 拉一次根节点, 对把 a11y 访问计入风控的 App(微信)是无谓的暴露(droid.SENSITIVE_APPS 注释)。dump/ping 的精确前台仍走 getWindows。
    // a11y_config.xml 为 Files「重命名」这类对话框改了三处, 真机逐一排除后的根因是 ③:
    // ① flagIncludeNotImportantViews: 让容器层(importantForAccessibility=no)入树 —— 空壳从 1 层变 5 层, 但 EditText/按钮仍拿不到;
    // ② 订阅面 +typeWindowsChanged|typeWindowContentChanged: 节点缓存随内容失效 —— 无效(不是缓存问题); 回调体 O(1) 丢弃, 保留无害;
    // ③ isAccessibilityTool=true (API33+): Android 14 的 accessibilityDataSensitive —— App 标记的视图子树对**非工具类** a11y 服务
    //    既不暴露节点(childCount>0 但 getChild 全 null, refresh 无用), 也**丢弃其注入的触摸**(点「取消/确定」无反应, 点对话框外
    //    scrim 却能关掉——scrim 不在标记子树里); uiautomator/UiAutomation 天然按工具处理, 所以同刻看得到也点得动。
    //    Files by Google 把重命名/删除等对话框整体标了 dataSensitive。声明为工具后行为与 uiautomator 一致。
    // 敏感 App 的零注入/dump 置空策略与此无关(策略在 droid.py 按前台包名判, 不因看得到就去动)。
    private val windowPackages = WindowPackages()
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        if (event.eventType == AccessibilityEvent.TYPE_WINDOWS_CHANGED) {
            if (event.windowChanges and AccessibilityEvent.WINDOWS_CHANGE_REMOVED != 0)
                windowPackages.removed(event.windowId)
            return
        }
        val pkg = event.packageName?.toString()?.takeIf { it.isNotEmpty() } ?: return
        // An event can precede its window's visibility in getWindows(). Keep the
        // identity by ID; only current window metadata decides which one is foreground.
        windowPackages.record(event.windowId, pkg)
    }
    private fun visualOnly() = foregroundPkg().let { it.isEmpty() || it == "com.tencent.mm" }
    override fun onInterrupt() {}

    /**
     * stepOS 专用: 经 self-ADB shell 通道以 fullscreen 窗口模式启动 app。
     *
     * 为什么需要(真机实证, PZ261A / stepOS / Android 16):
     *  stepOS 的 `StepOSMiniWindowControllerImpl` 在 `ActivityStarter.computeLaunchParams` 阶段按**调用者 uid**
     *  决策: 第三方 App(uid≠shell) 拉起的 task 被主动改写为 OEM 私有的 `stepos-mini-window`(小窗),
     *  于是「GA 退后台、被测 App 却以小窗/PiP 形态出现」而非全屏。logcat 实证:
     *    WindowMode:mini: onCalculateWindowingMode ... fullscreen -> stepos-mini-window
     *    ActivityTaskManager: START ... from uid 10226 callingPackage io.github.shenhaostu.gagent.debug
     *  同一条 launch intent 由 shell(uid 2000, callingPackage com.android.shell) 发起则保持 fullscreen。
     *
     * 为何不能走 App 内 API(逐一排除, 均有实证):
     *  - `ActivityOptions.setLaunchWindowingMode` 是 @hide 且被 hidden API 策略拦截
     *    (logcat: `api=blocked ... using reflection: denied`);
     *  - 手工构造 `android.activity.windowingMode` Bundle 也会被 OEM 控制器在 computeLaunchParams 阶段覆盖;
     *  - 与悬浮窗无关(停 FloatService / 走 nofloat 分支仍复现), 也不是 task 残留偏好(删 `_op_*` 键仍复现)。
     * 唯一已验证的出口即 shell uid: `am start-activity --windowingMode 1` 可把 mini-window 打回 fullscreen。
     *
     * 返回 true = 已由 shell 成功启动(**调用方不得再调 startActivity** —— app uid 的第二次 launch
     * 会被 OEM 再次改写回小窗); false = 调用方回退原有 a11y 启动, 主流程不丢。
     *
     * 通道二选一(等价, 只是来源不同): self-ADB([AdbController], 需无线调试+配对) 或 Shizuku([ShizukuShell],
     * 需装管理器+授权)。用户不必为了全屏启动先去开发者选项开无线调试。任一可用即走, 都不依赖时保持降级。
     */
    private fun launchFullscreenViaShell(intent: android.content.Intent): Boolean {
        val component = intent.component?.flattenToShortString() ?: return false
        val cmd = "am start-activity --windowingMode $WINDOWING_MODE_FULLSCREEN " +
            "-a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n $component"
        // self-ADB 优先(已在用时零额外开销), 不可用再试 Shizuku; 两者都拿不到输出即降级
        val out = when {
            AdbController.connected ->
                runCatching { AdbController.shell(this, cmd, timeoutMs = 20_000) }.getOrNull()
            ShizukuShell.ready() -> ShizukuShell.exec(cmd)
            else -> null
        } ?: return false
        // 成败判定只用 shell 输出(真机实测过的两种成功形态), 不轮询前台:
        //   成功: "Starting: Intent {...}"(冷启/新 task) 或 "Warning: Activity not started..."(task 已在前台, 被带到前台, 窗口模式同样已应用)
        //   失败: "Error:" / "Exception" —— 与成功必须可区分, 不把失败当成功, 也不把成功当失败。
        // 为何不轮询前台做回退条件: 前台事件上报慢时若回退去调 a11y startActivity, OEM 会把已 fullscreen 的 task
        // **二次改写回小窗**(比不修更糟); 且每次 launch 白等 ~2.5s。启动成功即视为完成。
        if (out.contains("Error:", ignoreCase = true) || out.contains("Exception", ignoreCase = true)) return false
        return out.contains("Starting:", ignoreCase = true) ||
            out.contains("Activity not started", ignoreCase = true)
    }

    // --- dump ---
    fun dump(full: Boolean): String {
        if (visualOnly()) return "[]"
        val root = foregroundRoot() ?: throw RuntimeException("no active window root")
        val (sw, sh) = screenSize()
        val out = JSONArray()
        collect(root, sw, sh, out, 0, full)
        // Hollow-root fallback: Compose/Material dialogs (Files 重命名, Contacts 权限弹窗后半程) surface as a second
        // TYPE_APPLICATION window whose root, when fetched right after the transition, is a childless FrameLayout ——
        // uiautomator (system a11y) sees the full tree (EditText + 确定/取消) at the same instant. Symptom in bench
        // v6_files_rename r2: dump()==[1 node], paste "no focused input", 47 turns of blind tapping. Re-fetch the root
        // once (the first fetch often precedes the window's content refresh) then merge the trees of *all* live app
        // windows of the same package so the dialog's own nodes are visible alongside the page behind it.
        if (out.length() <= 1) {
            // ① 强制刷新: 本服务只订阅 typeWindowStateChanged, 框架给它的节点缓存不会随对话框内容变化更新,
            //    root.refresh() 绕过缓存向 App 重新取一次真节点(uiautomator 订阅全部事件所以同刻能看到完整树)。
            val refreshed = try { root.refresh() } catch (_: Exception) { false }
            if (refreshed) { val o1 = JSONArray(); collect(root, sw, sh, o1, 0, full); if (o1.length() > out.length()) return o1.toString() }
            Thread.sleep(120)
            val again = foregroundRoot()
            if (again != null) {
                try { again.refresh() } catch (_: Exception) {}
                val o2 = JSONArray(); collect(again, sw, sh, o2, 0, full); if (o2.length() > out.length()) return o2.toString()
            }
            val pkg = root.packageName?.toString()
            val merged = JSONArray()
            (try { windows } catch (_: Exception) { null })?.filter {
                it.type == AccessibilityWindowInfo.TYPE_APPLICATION && it.root?.packageName?.toString() == pkg
            }?.forEach { w -> w.root?.let { try { it.refresh() } catch (_: Exception) {}; collect(it, sw, sh, merged, 0, full) } }
            if (merged.length() > out.length()) return merged.toString()
        }
        return out.toString()
    }

    /** One window only. Legacy dump may merge dialogs; guarded actions must never use that view. */
    fun uiSnapshot(expectedPkg: String, targets: MutableList<AccessibilityNodeInfo>? = null): JSONObject {
        require(!visualOnly() && expectedPkg != "com.tencent.mm") { "visual-only app: use screenshot and coordinate gestures" }
        require(expectedPkg.isNotBlank() && expectedPkg != packageName) { "need external expected package" }
        val window = foregroundWindow() ?: error("unknown foreground window")
        val root = window.root ?: error("unknown foreground root")
        require(root.packageName?.toString() == expectedPkg) { "foreground changed" }
        require(window.type == AccessibilityWindowInfo.TYPE_APPLICATION) { "not an app window" }
        if (Build.VERSION.SDK_INT >= 30) require(window.displayId == Display.DEFAULT_DISPLAY) { "non-default display" }
        val (sw, sh) = screenSize()
        val nodes = JSONArray()
        collect(root, sw, sh, nodes, 0, true, guarded = true, visited = intArrayOf(0), targets = targets)
        val blockers = JSONArray()
        val live = windows ?: error("unknown windows")
        require(live.any { it.id == window.id }) { "window disappeared" }
        live.filter { it.id != window.id && it.layer >= window.layer }
            .sortedWith(compareBy({ it.layer }, { it.id })).forEach {
                val r = Rect(); it.getBoundsInScreen(r)
                if (!r.isEmpty) blockers.put(JSONArray(listOf(r.left, r.top, r.right, r.bottom)))
            }
        require(foregroundWindow()?.id == window.id) { "foreground changed during observation" }
        val snapshot = JSONObject().put("pkg", expectedPkg).put("window_id", window.id)
            .put("rot", rotation()).put("w", sw).put("h", sh).put("nodes", nodes)
            .put("method", "node_click").put("schema", 1)
        // Bind the app state. Unrelated overlay geometry may change; observedTap checks current occlusion.
        val digest = MessageDigest.getInstance("SHA-256").digest(snapshot.toString().toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it.toInt() and 255) }
        return snapshot.put("blockers", blockers).put("fingerprint", digest).put("captured_ms", SystemClock.elapsedRealtime())
    }

    private fun observedTap(req: JSONObject): String {
        // Recheck immediately before dispatch; Android does not offer an atomic snapshot+gesture transaction.
        val age = SystemClock.elapsedRealtime() - req.getLong("captured_ms")
        if (age !in 0L..8000L) return """{"dispatched":false,"reason":"expired_snapshot"}"""
        val targets = mutableListOf<AccessibilityNodeInfo>()
        val current = try { uiSnapshot(req.getString("expected_pkg"), targets) }
            catch (_: Exception) { return """{"dispatched":false,"reason":"unknown_foreground"}""" }
        if (current.getString("fingerprint") != req.getString("expected_ui"))
            return """{"dispatched":false,"reason":"stale_snapshot"}"""
        val node = current.getJSONArray("nodes").getJSONObject(req.getInt("node_index"))
        require(node.optInt("click") == 1 && node.optInt("disabled") == 0 && node.optInt("hidden") == 0)
        require(node.optInt("edit") == 0 && node.optInt("checkable") == 0 && node.optInt("password") == 0)
        val x = node.getInt("x"); val y = node.getInt("y")
        val blockers = current.getJSONArray("blockers")
        for (i in 0 until blockers.length()) {
            val b = blockers.getJSONArray(i)
            if (x >= b.getInt(0) && x < b.getInt(2) && y >= b.getInt(1) && y < b.getInt(3))
                return """{"dispatched":false,"reason":"occluded_target"}"""
        }
        if (SystemClock.elapsedRealtime() - req.getLong("captured_ms") > 8000)
            return """{"dispatched":false,"reason":"expired_snapshot"}"""
        val target = targets[req.getInt("node_index")]
        if (target.actionList.none { it.id == AccessibilityNodeInfo.ACTION_CLICK })
            return """{"dispatched":false,"reason":"node_click_unavailable"}"""
        val accepted = target.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        return JSONObject().put("dispatched", true).put("method", "node_click")
            .put("action_result", accepted).toString()
    }

    // rootInActiveWindow races when GA 自己的 MainActivity 残留在刚启动的目标 App 后面(同 baseLayer)
    // → 返回 GA 自己的 WebUI, 于是 dump()/ping 误报 com.ljq.ga, agent 据此臆造"GA 顶部悬浮窗拦截"。
    // 改用 getWindows()(需 flagRetrieveInteractiveWindows)确定性地取真前台窗口: 优先 active/focused,
    // 再偏好 App 窗口而非系统栏, 最后取最高层; 排除输入法与 GA 自身(让真 App/弹窗胜出, GA 在前台时仍能 dump 自己)。
    private fun foregroundWindow(): AccessibilityWindowInfo? {
        activeSystemWindow()?.let { return it }
        val wins = try { windows } catch (_: Exception) { null }
        if (wins.isNullOrEmpty()) return null
        val me = packageName
        val live = wins.filter { it.root?.packageName != null && it.type != AccessibilityWindowInfo.TYPE_INPUT_METHOD }
        if (live.isEmpty()) return null
        return live.maxWithOrNull(compareBy(
            { it.isActive }, { it.isFocused },
            { it.type == AccessibilityWindowInfo.TYPE_APPLICATION },
            { it.root!!.packageName.toString() != me },   // 同等条件下偏好非 GA(化解 GA 残留窗与目标同层竞争), 但不硬排除 → GA 真前台时仍返回自己(否则会落到状态栏 systemui)
            { it.layer }))
    }

    private fun foregroundRoot(): AccessibilityNodeInfo? = foregroundWindow()?.root ?: rootInActiveWindow

    private fun activeSystemWindow(): AccessibilityWindowInfo? = windows?.filter {
        it.type == AccessibilityWindowInfo.TYPE_SYSTEM && (it.isActive || it.isFocused)
    }?.maxByOrNull { it.layer }

    fun foregroundPkg(): String {
        val foreground = activeSystemWindow() ?: windows?.filter {
            it.type == AccessibilityWindowInfo.TYPE_APPLICATION && (it.isActive || it.isFocused)
        }?.maxWithOrNull(compareBy({ it.isActive }, { it.isFocused }, { it.layer }))
        return windowPackages.current(foreground?.id)
    }

    // 旋转正确的物理屏尺寸: Service 的 resources.displayMetrics 不随旋转可靠更新, getRealMetrics 才行(横屏修正)。
    private val wm get() = getSystemService(WINDOW_SERVICE) as WindowManager
    fun screenGeometry(): ScreenGeometry {
        val display = wm.defaultDisplay
        val m = DisplayMetrics(); display.getRealMetrics(m)
        return ScreenGeometry(m.widthPixels, m.heightPixels, display.rotation)
    }
    private fun screenSize(): Pair<Int, Int> {
        val g = screenGeometry(); return g.w to g.h
    }
    fun rotation(): Int = wm.defaultDisplay.rotation

    private fun collect(node: AccessibilityNodeInfo, sw: Int, sh: Int, out: JSONArray, depth: Int,
                        full: Boolean, guarded: Boolean = false, visited: IntArray? = null,
                        targets: MutableList<AccessibilityNodeInfo>? = null) {
        if (guarded) {
            requireNotNull(visited)
            visited[0] += 1
            require(depth <= 32 && visited[0] <= 2000) { "tree budget exceeded" }
            require(node.refresh()) { "incomplete or stale tree" }
        }
        val r = Rect(); node.getBoundsInScreen(r)
        if (r.right < 0 || r.bottom < 0 || r.left > sw || r.top > sh || r.isEmpty) {
            // offscreen: still recurse (scrollable containers may hold onscreen children)
        } else {
            val txt = node.text?.toString() ?: ""
            val rawDesc = node.contentDescription?.toString() ?: ""
            val click = node.isClickable
            val isEdit = node.isEditable
            val range = node.rangeInfo
            val desc = if (isMeaningfulDesc(rawDesc)) {
                if (txt.isNotEmpty() && rawDesc == txt) "" else rawDesc
            } else ""
            val hasInfo = txt.isNotEmpty() || desc.isNotEmpty() || isEdit || click || range != null
            if (hasInfo || full) {
                val obj = JSONObject()
                if (txt.isNotEmpty()) obj.put("t", txt)
                if (desc.isNotEmpty()) obj.put("d", desc)
                obj.put("x", (r.left + r.right) / 2); obj.put("y", (r.top + r.bottom) / 2)
                obj.put("l", depth)
                if (full || range != null || (txt.isEmpty() && desc.isEmpty() && click))
                    obj.put("b", "${r.left},${r.top},${r.right},${r.bottom}")
                if (full || range != null) obj.put("cls", node.className?.toString()?.substringAfterLast('.') ?: "")
                if (range != null) obj.put("range", JSONObject().put("min", range.min)
                    .put("max", range.max).put("current", range.current).put("type", range.type))
                if (full && !node.isEnabled) obj.put("disabled", 1)
                if (full && !node.isVisibleToUser) obj.put("hidden", 1)
                if (full && node.isCheckable) obj.put("checkable", 1)
                if (full && node.isPassword) obj.put("password", 1)
                if (click) obj.put("click", 1)
                if (isEdit) obj.put("edit", 1)
                if (node.isScrollable) obj.put("scroll", 1)
                if (node.isChecked) obj.put("chk", 1)
                if (node.isSelected) obj.put("sel", 1)
                if (hasInfo || full) { out.put(obj); targets?.add(node) }
            }
        }
        var missed = false
        for (i in 0 until node.childCount) {
            val c = node.getChild(i)
            if (c == null) missed = true else collect(c, sw, sh, out, depth + 1, full, guarded, visited, targets)
        }
        if (guarded) require(!missed) { "incomplete tree" }
        // Compose 对话框(Files 重命名): 第 5 层 FrameLayout childCount>0 但 getChild(i) 全返 null —— 子节点属于框架尚未
        // 预取的分片, 缓存里只有父壳(真机实证: uiautomator 同刻能列出 LinearLayoutCompat/EditText/确定)。refresh() 让框架
        // 向 App 重新取该节点及其子树, 再遍历一次; 仍空则放弃(不循环)。
        if (missed && depth < 24) {
            val ok = try { node.refresh() } catch (_: Exception) { false }
            if (ok) for (i in 0 until node.childCount) node.getChild(i)?.let { collect(it, sw, sh, out, depth + 1, full) }
        }
    }

    private fun isMeaningfulDesc(d: String): Boolean {
        if (d.isEmpty()) return false
        if (d.any { it in '\u4e00'..'\u9fff' || it in '\u3040'..'\u309f' || it in '\u30a0'..'\u30ff' }) return true
        if (d.contains('_')) return false
        if (d.length <= 20 && !d.startsWith("com.")) return true
        return false
    }

    // --- act ---
    // Agent 操作手机的唯一入口(droid.py tap/swipe/paste/launch... → /a11y/act → 此处)。
    // 埋点走 ActStats 内存聚合(每 50 次或 5 分钟一条 a11y_act_stats): 逐次上报会淹没
    // Analytics 本地队列(MAX_QUEUE=500)并挤掉低频关键事件。只记 op 枚举/前台包名/成败, 不碰坐标与文本。
    fun act(req: JSONObject): String {
        val op = runCatching { req.getString("op") }.getOrDefault("?")
        val pkg = foregroundPkg()   // Event package plus system-window metadata; no app nodes.
        return try { actInner(req).also { ActStats.hit(op, pkg, true) } }
        catch (e: Exception) { ActStats.hit(op, pkg, false); throw e }
    }

    private fun actInner(req: JSONObject): String {
        val geometry = if (req.getString("op") in listOf("tap", "swipe") && !req.has("expected_ui")) {
            val current = screenGeometry()
            req.optJSONObject("expected_screen")?.let {
                require(current == ScreenGeometry(it.getInt("w"), it.getInt("h"), it.getInt("rot"))) {
                    "screen geometry changed; capture and locate the target again"
                }
            }
            current
        } else null
        when (val op = req.getString("op")) {
            "tap" -> if (req.has("expected_ui")) return observedTap(req)
                else {
                    val g = requireNotNull(geometry)
                    g.requirePoint(req.getDouble("x").toFloat(), req.getDouble("y").toFloat())
                    if (req.optBoolean("human", false)) humanTap(req, g)
                    else gesture(Path().apply {
                        moveTo(req.getInt("x").toFloat(), req.getInt("y").toFloat()) }, 100, g)
                }
            "swipe" -> {   // 端点夹到"安全带"内, 避开系统手势区(底部 home/recents 带、侧边返回带、顶部状态栏)→ 实测从底部快滑会被系统当成回桌面/最近而切走 App
                val g = requireNotNull(geometry)
                g.requirePoint(req.getDouble("x1").toFloat(), req.getDouble("y1").toFloat())
                g.requirePoint(req.getDouble("x2").toFloat(), req.getDouble("y2").toFloat())
                val (x1, y1) = g.swipePoint(req.getInt("x1"), req.getInt("y1"))
                val (x2, y2) = g.swipePoint(req.getInt("x2"), req.getInt("y2"))
                gesture(Path().apply {
                    moveTo(x1, y1); lineTo(x2, y2) }, req.optLong("dur", 300), g)
            }
            "clipboard" -> setClipboard(req.getString("text"))
            "paste" -> {  // 剪贴板粘贴: WebView contenteditable 等 SET_TEXT 失效场景的标准注入
                val node = focusedEdit()
                setClipboard(req.getString("text"))
                Thread.sleep(150)
                if (req.optBoolean("replace", false)) selectAll(node)   // replace=覆盖而非追加: 先全选, PASTE 即替换(预填昵称/旧搜索词场景)
                if (!node.performAction(AccessibilityNodeInfo.ACTION_PASTE))
                    throw RuntimeException("ACTION_PASTE rejected")
            }
            "key" -> {  // 仅支持 ENTER: 对聚焦输入框触发 IME 动作(搜索/发送/换行), API30+
                val name = req.getString("name").uppercase()
                if (name != "ENTER") throw RuntimeException("unsupported key: $name (only ENTER)")
                if (Build.VERSION.SDK_INT < 30) throw RuntimeException("ACTION_IME_ENTER needs API30+")
                val node = focusedEdit()
                if (!node.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.id))
                    throw RuntimeException("IME_ENTER rejected; node=${node.className} (fallback: tap键盘右下角回车/搜索键)")
            }
            "launch" -> {  // 免adb启动app
                val pkg = req.getString("pkg")
                val intent = packageManager.getLaunchIntentForPackage(pkg)
                    ?: throw RuntimeException("no launch intent for: $pkg (not installed?)")
                intent.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
                val alwaysFloat = getSharedPreferences("ga", MODE_PRIVATE).getBoolean("float_always_on", false)
                if (req.optBoolean("nofloat", false) && !alwaysFloat) {
                    // Automatic hide requests must not override the user's explicit always-on preference.
                    runCatching { stopService(android.content.Intent(this, FloatService::class.java)) }
                } else if (android.provider.Settings.canDrawOverlays(this)) {
                    // 切走前自动起悬浮窗(有overlay权限时), 让用户能看到GA仍在工作
                    val fsi = android.content.Intent(this, FloatService::class.java).putExtra("trigger", "auto")
                    if (android.os.Build.VERSION.SDK_INT >= 26) startForegroundService(fsi) else startService(fsi)
                }
                // stepOS 按调用者 uid 把第三方 App 拉起的 task 改写成小窗; 已由 shell 成功启动并确认到前台时,
                // 绝不再走 app uid 的 startActivity(那会被 OEM 二次改写回小窗)。未连 self-ADB / 未确认到前台则回退原路径。
                val fullscreen = launchFullscreenViaShell(intent)
                if (!fullscreen) startActivity(intent)
                // 降级必须显式告知而非静默: 两条 shell 通道都不可用时, App 侧启动只能落进 stepos-mini-window
                // (小窗), 与用户预期「被测 App 全屏」不符。把通道真值和可操作下一步一并回给 agent,
                // 让它能照原话告诉用户怎么修, 而不是报一个假的 {"ok":1}。
                if (fullscreen) return JSONObject().put("ok", 1).put("fullscreen", true).toString()
                return JSONObject()
                    .put("ok", 1)
                    .put("fullscreen", false)
                    .put("shell", "self_adb=${AdbController.connected},shizuku=${ShizukuShell.ready()}")
                    .put("hint", "StepOS 上本次以小窗(stepos-mini-window)启动: 该 ROM 按调用者 uid 决定窗口模式, "
                        + "App 侧无法覆盖。要全屏需任一条 shell 通道: ① 设置里连接 self-ADB(开发者选项>无线调试, "
                        + "已授 WRITE_SECURE_SETTINGS 时 app 会自动开启); ② 安装并授权 Shizuku。"
                        + "两者都不可用时不要反复重试 launch, 照原话告知用户。")
                    .toString()
            }
            "back" -> performGlobalAction(GLOBAL_ACTION_BACK)
            "home" -> performGlobalAction(GLOBAL_ACTION_HOME)
            "notifications" -> performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS)   // 下拉通知栏: swipe 被安全带夹住够不到顶部, 用全局动作(API16+)
            "dismiss_shade" -> {   // 确定性收起通知栏/快捷设置(API31+ 全局动作): Pixel/Android16 上 home() 后面板可残留为透明层吃掉后续 tap、
                if (Build.VERSION.SDK_INT < 31) performGlobalAction(GLOBAL_ACTION_BACK)   // 且 ping 前台停在 systemui(r22 bench L1_contact 实证); 低版本回退 back
                else performGlobalAction(GLOBAL_ACTION_DISMISS_NOTIFICATION_SHADE)
            }
            "quicksettings" -> performGlobalAction(GLOBAL_ACTION_QUICK_SETTINGS)   // 展开快捷设置(AOSP语义; 部分OEM如Flyme只到通知栏够不到控制中心→改用 panel)
            "panel" -> {   // 物理下拉顶部面板: 从屏幕最顶端 raw 下滑(不夹安全带, 才能触发系统下拉手势)。side=right→控制中心(录屏/手电等磁贴, Flyme/AOSP12+ 分屏下拉在右半)/left|center→通知栏。全局动作在部分 OEM 够不到控制中心, 故提供物理下拉。
                val (sw, sh) = screenSize()
                val x = when (req.optString("side", "right")) { "left" -> sw * 0.12f; "center" -> sw * 0.5f; else -> sw * 0.9f }
                gesture(Path().apply { moveTo(x, 3f); lineTo(x, sh * 0.6f) }, req.optLong("dur", 320))
            }
            "pkgs" -> {  // 列可启动app; filter模糊匹配包名/应用名(需QUERY_ALL_PACKAGES)
                val f = req.optString("filter").lowercase()
                val intent = android.content.Intent(android.content.Intent.ACTION_MAIN)
                    .addCategory(android.content.Intent.CATEGORY_LAUNCHER)
                val arr = org.json.JSONArray()
                packageManager.queryIntentActivities(intent, 0).forEach { ri ->
                    val pkg = ri.activityInfo.packageName
                    val label = ri.loadLabel(packageManager).toString()
                    if (f.isEmpty() || pkg.lowercase().contains(f) || label.lowercase().contains(f))
                        arr.put(JSONObject().put("pkg", pkg).put("label", label))
                }
                return JSONObject().put("apps", arr).toString()
            }
            "install_apk" -> {  // 装任意 APK(APK 工厂产物): 复制到 FileProvider 覆盖的 cacheDir/ota → 拉起系统安装器(用户确认)
                val src = java.io.File(req.getString("path"))
                if (!src.exists()) throw RuntimeException("apk not found: ${src.path}")
                val dir = java.io.File(cacheDir, "ota").apply { mkdirs() }
                val dst = java.io.File(dir, "install.apk")
                src.copyTo(dst, overwrite = true)
                return Updater.installFile(this, dst)
            }
            else -> throw RuntimeException("unknown op: $op (tap|swipe|paste|key|launch|back|home|notifications|dismiss_shade|quicksettings|panel|pkgs|install_apk)")
        }
        return """{"ok":1}"""
    }

    // findFocus(FOCUS_INPUT)在WebView上常返回拒绝一切action的容器节点(edit=false,foc=true);
    // 且WebView虚节点isFocused可能为false → 收集全部isEditable, 优先focused, 否则唯一者
    private fun setClipboard(text: String) {
        val latch = CountDownLatch(1)
        var failure: Exception? = null
        android.os.Handler(mainLooper).post {
            try {
                val cm = getSystemService(CLIPBOARD_SERVICE) as android.content.ClipboardManager
                cm.setPrimaryClip(android.content.ClipData.newPlainText("ga", text))
            } catch (e: Exception) { failure = e }
            finally { latch.countDown() }
        }
        check(latch.await(3, TimeUnit.SECONDS)) { "clipboard timeout" }
        failure?.let { throw it }
    }

    private fun focusedEdit(): AccessibilityNodeInfo {
        check(!visualOnly()) { "visual-only app: use clipboard + visible paste menu / keyboard" }
        val root = rootInActiveWindow ?: throw RuntimeException("no root")
        val edits = mutableListOf<AccessibilityNodeInfo>()
        fun walk(n: AccessibilityNodeInfo) {
            if (n.isEditable) edits.add(n)
            for (i in 0 until n.childCount) n.getChild(i)?.let { walk(it) }
        }
        walk(root)
        if (edits.isEmpty()) {
            // Same partially-fetched-tree case as dump(): the EditText may sit under a node whose children came back
            // null from the cache, or in a sibling app window (dialog). Refresh-walk the focused window's root and then
            // every live application window before giving up.
            fun walkRefreshing(n: AccessibilityNodeInfo) {
                if (n.isEditable) edits.add(n)
                var missed = false
                for (i in 0 until n.childCount) { val c = n.getChild(i); if (c == null) missed = true else walkRefreshing(c) }
                if (missed && (try { n.refresh() } catch (_: Exception) { false }))
                    for (i in 0 until n.childCount) n.getChild(i)?.let { walkRefreshing(it) }
            }
            (try { windows } catch (_: Exception) { null })
                ?.filter { it.type == AccessibilityWindowInfo.TYPE_APPLICATION }
                ?.sortedByDescending { it.isFocused }
                ?.forEach { w -> w.root?.let { walkRefreshing(it) } }
        }
        return edits.firstOrNull { it.isFocused } ?: edits.singleOrNull()
            ?: root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
            ?: throw RuntimeException("no focused input (tap an edit field first); editables=${edits.size}")
    }

    // 全选编辑框现有文本(空框直接返回): 与 PASTE 组合成"替换"原语——a11y 没有退格键, 这是唯一不依赖 IME 的清空手段。
    // 选区失败=显式报错(半径大: 否则 PASTE 会静默追加, 调用方以为已替换), 报错文案给出人工兜底路径。
    private fun selectAll(node: AccessibilityNodeInfo) {
        val len = node.text?.length ?: 0
        if (len == 0 || (Build.VERSION.SDK_INT >= 26 && node.isShowingHintText)) return   // 空框/只显示占位符(text 会返回 hint, 但没有可选文本): 直接粘贴

        val args = android.os.Bundle().apply {
            putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, 0)
            putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, len)
        }
        if (!node.performAction(AccessibilityNodeInfo.ACTION_SET_SELECTION, args))
            throw RuntimeException("ACTION_SET_SELECTION rejected (field not selectable; fallback: tap the field's ✕ clear button or ask the user)")
    }

    private fun humanTap(req: JSONObject, geometry: ScreenGeometry) {
        val x = req.getDouble("x").toFloat()
        val y = req.getDouble("y").toFloat()
        val jitter = req.optDouble("jitter", 1.0).toFloat().coerceIn(0f, 2f)
        val dx = Random.nextDouble(-jitter.toDouble(), jitter.toDouble()).toFloat()
        val dy = Random.nextDouble(-jitter.toDouble(), jitter.toDouble()).toFloat()
        val wiggle = req.optDouble("wiggle", 0.6).toFloat().coerceIn(0f, 1.5f)
        val dur = req.optLong("dur", Random.nextLong(80, 121)).coerceIn(50L, 180L)
        fun cx(v: Float) = v.coerceIn(0f, (geometry.w - 1).toFloat())
        fun cy(v: Float) = v.coerceIn(0f, (geometry.h - 1).toFloat())
        gesture(Path().apply {
            moveTo(cx(x + dx), cy(y + dy))
            lineTo(cx(x + dx + Random.nextDouble(-wiggle.toDouble(), wiggle.toDouble()).toFloat()),
                cy(y + dy + Random.nextDouble(-wiggle.toDouble(), wiggle.toDouble()).toFloat()))
        }, dur, geometry)
    }

    private fun gesture(p: Path, dur: Long, expected: ScreenGeometry? = null) {
        val restore = FloatService.live?.passThroughGesture() ?: {}
        val handler = Handler(mainLooper)
        val fallback = Runnable { restore() }
        fun finish() { handler.removeCallbacks(fallback); restore() }
        var accepted = false
        try {
            require(expected == null || expected == screenGeometry()) { "screen geometry changed before gesture dispatch" }
            val callback = object : GestureResultCallback() {
                override fun onCompleted(gestureDescription: GestureDescription) = finish()
                override fun onCancelled(gestureDescription: GestureDescription) = finish()
            }
            handler.postDelayed(fallback, dur + 1000)
            accepted = dispatchGesture(GestureDescription.Builder()
                .addStroke(GestureDescription.StrokeDescription(p, 0, dur)).build(), callback, handler)
            check(accepted) { "dispatchGesture rejected" }
        } finally { if (!accepted) finish() }
    }

    // --- shot ---
    // Own overlay windows (status capsule / answer panel) are part of the composed frame but not of the
    // app under automation. Rects are sampled in display space and mapped to the frame before masking.
    private fun ownWindows(): List<Triple<List<IntArray>, Int, Int>> =
        listOfNotNull(FloatService.live?.let { runCatching { it.ownWindowRects() }.getOrNull() })

    private fun maskOwnWindows(b: Bitmap, owned: List<Triple<List<IntArray>, Int, Int>>) {
        val pad = (2 * resources.displayMetrics.density).toInt().coerceAtLeast(1)
        for ((rects, dw, dh) in owned) for (r in frameMaskRects(rects, dw, dh, b.width, b.height, pad)) {
            val x0 = (r[0] - 1).coerceAtLeast(0); val y0 = (r[1] - 1).coerceAtLeast(0)
            val x1 = (r[2] + 1).coerceAtMost(b.width); val y1 = (r[3] + 1).coerceAtMost(b.height)
            val w = x1 - x0; val h = y1 - y0
            val px = IntArray(w * h)
            b.getPixels(px, 0, w, x0, y0, w, h)
            inpaintRect(px, w, h, r[0] - x0, r[1] - y0, r[2] - x0, r[3] - y0)
            b.setPixels(px, 0, w, x0, y0, w, h)
        }
    }

    fun shot(jpegQuality: Int?): ByteArray {
        if (Build.VERSION.SDK_INT < 30) throw RuntimeException("takeScreenshot needs API30+, this=${Build.VERSION.SDK_INT}")
        if (BrowserActivity.secureForeground)   // 前台是登录浏览器: FLAG_SECURE 必涂黑, 与其返回黑图不如显式报错让 agent 换路由
            throw RuntimeException("前台是登录浏览器(FLAG_SECURE 保护密码输入), 截图必为黑屏; 网页任务请用前台任务浏览器 webcdp.open_url(url) 操作, 或先离开登录页再截图")
        val ownBefore = ownWindows()
        val latch = CountDownLatch(1)
        var bmp: Bitmap? = null
        var err: String? = null
        takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, object : TakeScreenshotCallback {
            override fun onSuccess(res: ScreenshotResult) {
                bmp = Bitmap.wrapHardwareBuffer(res.hardwareBuffer, res.colorSpace)
                    ?.copy(Bitmap.Config.ARGB_8888, true)
                res.hardwareBuffer.close()
                latch.countDown()
            }
            override fun onFailure(code: Int) { err = "takeScreenshot failed code=$code"; latch.countDown() }
        })
        if (!latch.await(5, TimeUnit.SECONDS)) throw RuntimeException("screenshot timeout")
        err?.let { throw RuntimeException(it) }
        val b = bmp ?: throw RuntimeException("screenshot null bitmap")
        maskOwnWindows(b, ownBefore + ownWindows())   // before+after: a window moved mid-capture is still covered
        val bos = ByteArrayOutputStream()
        if (jpegQuality != null) b.compress(Bitmap.CompressFormat.JPEG, jpegQuality, bos)
        else b.compress(Bitmap.CompressFormat.PNG, 100, bos)
        b.recycle()
        return bos.toByteArray()
    }
}

// Agent 模拟操作聚合埋点: act() 每次命中计数, 满 50 次或首次命中后 5 分钟上报一条 a11y_act_stats。
// 脱敏: 只记 op 枚举计数、失败数、触达 app 数与最高频包名(应用标识非 PII)——坐标/文本/剪贴板一概不碰。
private object ActStats {
    private const val FLUSH_N = 50
    private const val FLUSH_MS = 5 * 60_000L
    private val ops = HashMap<String, Int>()
    private val pkgCounts = HashMap<String, Int>()
    private var fails = 0
    private var t0 = 0L

    @Synchronized fun hit(op: String, pkg: String?, ok: Boolean) {
        if (t0 == 0L) t0 = System.currentTimeMillis()
        ops[op] = (ops[op] ?: 0) + 1
        if (!ok) fails++
        if (!pkg.isNullOrEmpty()) pkgCounts[pkg] = (pkgCounts[pkg] ?: 0) + 1
        if (ops.values.sum() >= FLUSH_N || System.currentTimeMillis() - t0 >= FLUSH_MS) flush()
    }

    @Synchronized fun flush() {
        val n = ops.values.sum()
        if (n == 0) return
        val props = JSONObject().apply {
            put("n", n)
            put("fails", fails)
            put("ops", ops.entries.sortedByDescending { it.value }
                .joinToString(",") { "${it.key}:${it.value}" })
            put("apps", pkgCounts.size)
            put("top_app", pkgCounts.entries.maxByOrNull { it.value }?.key ?: "")
            put("secs", ((System.currentTimeMillis() - t0) / 1000).toInt())
        }
        runCatching { Analytics.track(JSONObject().put("event", "a11y_act_stats").put("props", props).toString()) }
        ops.clear(); pkgCounts.clear(); fails = 0; t0 = 0L
    }
}
