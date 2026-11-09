package com.ljq.ga

import android.content.Context
import android.os.Build
import android.os.PowerManager
import io.github.muntashirakon.adb.AbsAdbConnectionManager
import io.github.muntashirakon.adb.AdbConnection
import io.github.muntashirakon.adb.AdbStream
import io.github.muntashirakon.adb.android.AdbMdns
import java.io.File
import java.security.KeyFactory
import java.security.KeyPairGenerator
import java.security.PrivateKey
import java.security.PublicKey
import java.security.SecureRandom
import java.security.cert.Certificate
import java.security.cert.CertificateFactory
import java.security.spec.PKCS8EncodedKeySpec
import java.util.Date
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import android.sun.security.x509.AlgorithmId
import android.sun.security.x509.CertificateAlgorithmId
import android.sun.security.x509.CertificateExtensions
import android.sun.security.x509.CertificateIssuerName
import android.sun.security.x509.CertificateSerialNumber
import android.sun.security.x509.CertificateSubjectName
import android.sun.security.x509.CertificateValidity
import android.sun.security.x509.CertificateVersion
import android.sun.security.x509.CertificateX509Key
import android.sun.security.x509.KeyIdentifier
import android.sun.security.x509.PrivateKeyUsageExtension
import android.sun.security.x509.SubjectKeyIdentifierExtension
import android.sun.security.x509.X500Name
import android.sun.security.x509.X509CertImpl
import android.sun.security.x509.X509CertInfo

/**
 * app 内自连无线 ADB(类 LADB, 但纯 Kotlin — 无打包 adb 二进制)。
 * 走 libadb-android: SPAKE2 配对 + ADB-over-TLS 线协议, Conscrypt 供 TLSv1.3。
 *
 * 用户流程(app 不能静默开, 全程手动授权):
 *   1. 开发者选项 → 无线调试 → 打开
 *   2. 「使用配对码配对设备」弹窗给出 IP:配对端口 + 6位配对码 → 调 pair()
 *   3. 之后 connect() 无需再传端口: 优先复用上次成功端口 → 5555 → mDNS 自动发现(端口每次开关无线调试都变,
 *      但 adbd 通过 mDNS 通告 `_adb-tls-connect._tcp`, 故不再要用户手填/OCR)。本机场景 host 恒 127.0.0.1。
 * 配对一次: 证书交换后持久化 adbkey(私钥)+adbkey.pub_cert(证书), 之后仅需 connect()。
 *
 * 稳定性契约(v2.17 传输契约修复; 治 28 轮不可恢复抖动):
 *   - connected 是**派生真值**(读 libadb 捕获的 AdbConnection 的 lock-free 成员), 不再是可与库脱节的存储标志。
 *   - openStream+drain 全在限时 worker 内: 任一坏流(大输出/`|head` 提前关管道)降级为**单命令有界失败**, 不拖垮整连。
 *   - 传输死亡走幂等 teardown(close() 不吃 mLock, wedge 中仍可用) → 下次调用经 ensureConnected 透明自愈重连。
 *   - 输出超上限**显式报错**(不静默截断, 防二进制/base64 帧损坏)。
 */
object AdbController {
    private const val KEY_NAME = "adbkey"
    private const val CERT_NAME = "adbkey.pub_cert"
    private const val DEVICE_NAME = "GAgent"
    private const val PREFS = "ga"
    private const val PREF_PORT = "adb_last_port"
    const val DEFAULT_MAX_BYTES = 262144   // 256KB: 超限报错分页, 大消费者(截图 base64)显式调大

    @Volatile private var manager: Mgr? = null
    // connect 成功后在无争用时刻捕获; connected 只读它的 lock-free 成员, 绝不走 manager.isConnected()(吃 mLock, wedge 期会阻塞 status 查询)。
    @Volatile private var conn: AdbConnection? = null
    @Volatile var lastError: String? = null
        private set
    @Volatile private var pairingRequired = false   // 任一端口报过需配对即置位(后续端口的其他失败不覆盖); 连接或配对成功才清

    /** 派生存活真值(lock-free): socket 未关 ∧ CNXN 已建立。任一调用返回/抛出后, 此值恒等于 libadb 地面真相, 不存在脱节窗口。 */
    val connected: Boolean
        get() = conn?.let { it.isConnected && it.isConnectionEstablished } ?: false

    private fun mgr(ctx: Context): Mgr =
        manager ?: synchronized(this) { manager ?: Mgr(ctx.applicationContext).also { manager = it } }

    /** 幂等全量重置。依赖 AbsAdbConnectionManager.close() 不吃 mLock — 故即使某卡死线程正握 mLock 也能执行, 是 wedge 的唯一逃生口。 */
    private fun teardown() {
        try { manager?.close() } catch (_: Exception) {}
        manager = null
        conn = null
    }

    private fun prefs(ctx: Context) = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private fun loadPort(ctx: Context): Int = prefs(ctx).getInt(PREF_PORT, 0)
    private fun savePort(ctx: Context, port: Int) { prefs(ctx).edit().putInt(PREF_PORT, port).apply() }

    /** adb pair IP:配对端口 配对码。成功后证书已持久化。返回配对结果说明。 */
    @Synchronized
    fun pair(ctx: Context, host: String, port: Int, code: String): String {
        val ok = try {
            mgr(ctx).pair(host, port, code)
        } catch (e: Exception) {
            Analytics.track("""{"event":"adb_pair","props":{"ok":false,"cat":"exception"}}""")
            throw e
        }
        if (!ok) {
            Analytics.track("""{"event":"adb_pair","props":{"ok":false,"cat":"rejected"}}""")   // 配对码/端口错或弹窗关闭
            throw RuntimeException("pair 失败: 配对码/端口错, 或配对弹窗已关闭(须保持前台)")
        }
        Analytics.track("""{"event":"adb_pair","props":{"ok":true}}""")   // 证书交换成功=自连能力关键里程碑
        pairingRequired = false
        // pair 消耗/污染了 Mgr 单例(libadb 内部状态), 同实例立即 connect 必失败; 丢弃它让 connect 懒建净 Mgr
        // (复用磁盘已持久化的证书, 设备侧已信任本证书, 无需重新 pair)。
        teardown()
        return "paired $host:$port"
    }

    /**
     * adb connect。port==0 ⇒ 自动发现(复用端口→5555→mDNS)一点即连; 显式 port ⇒ 先断后连(杀掉「已连接→false→connect 失败」假象+回收弃置 socket)。
     */
    @Synchronized
    fun connect(ctx: Context, host: String, port: Int): String {
        if (port == 0) {
            require(host == "127.0.0.1") { "自动发现仅支持本机回环(host=127.0.0.1); 连外部设备请显式传 port" }
            ensureConnected(ctx)
            Analytics.track("""{"event":"adb_connect","props":{"ok":true,"auto":true}}""")
            return "connected 127.0.0.1:${loadPort(ctx)}"   // 自动发现恒回环, 如实回报实际 peer(不回显调用方 host)
        }
        teardown()   // 先断后连: 库在已连接时 connect() 返 false, 旧实现误判失败; 且丢弃旧连接不 close 会泄漏 socket/线程
        val ok = tryConnect(ctx, host, port)
        if (!ok) {
            Analytics.track("""{"event":"adb_connect","props":{"ok":false,"cat":"failed"}}""")   // 端口错/未配对/无线调试关
            throw RuntimeException("connect 失败: 端口错/未配对/无线调试已关: ${lastError ?: ""}")
        }
        Analytics.track("""{"event":"adb_connect","props":{"ok":true}}""")   // 端侧 shell 通道建立=A11y外操控能力就绪
        return "connected $host:$port"
    }

    /** 单次尝试连接指定端口: 成功则捕获 AdbConnection 引用(无争用时刻)+持久化端口; 失败一律 teardown 让下个候选从净状态起。 */
    private fun tryConnect(ctx: Context, host: String, port: Int): Boolean = try {
        val m = mgr(ctx)
        if (m.connect(host, port)) {
            conn = m.adbConnection   // 捕获引用: 之后 connected 读它的 lock-free 成员, 不再吃 mLock
            savePort(ctx, port)
            lastError = null
            pairingRequired = false
            true
        } else {
            teardown(); false
        }
    } catch (e: Exception) {
        lastError = e.toString(); if (adbNeedsRepair(lastError)) pairingRequired = true; teardown(); false
    }

    /** 已连接则直接返回; 否则 teardown 后按代价序试候选端口: 上次成功端口 → 5555(稳定明文TCP快路径) → mDNS 发现。全失败抛可行动错误。 */
    private fun ensureConnected(ctx: Context): Mgr {
        if (connected) return manager!!
        teardown()
        val candidates = LinkedHashSet<Int>().apply {
            loadPort(ctx).let { if (it > 0) add(it) }
            add(5555)
        }
        for (p in candidates) if (tryConnect(ctx, "127.0.0.1", p)) return manager!!
        val disc = discover(ctx, 5000)
        if (disc != null && tryConnect(ctx, "127.0.0.1", disc)) return manager!!
        throw RuntimeException(adbAutoConnectError(pairingRequired))
    }

    /** mDNS 自动发现连接端口(自 CountDownLatch 包住库 AdbMdns, 只取 TLS_CONNECT 服务)。忽略 host=null/port≤0 的丢失回调; 自连恒回 127.0.0.1:port。 */
    private fun discover(ctx: Context, timeoutMs: Long): Int? {
        val latch = CountDownLatch(1)
        val found = java.util.concurrent.atomic.AtomicInteger(0)
        val mdns = AdbMdns(ctx.applicationContext, AdbMdns.SERVICE_TYPE_TLS_CONNECT) { host, port ->
            if (host != null && port > 0 && found.compareAndSet(0, port)) latch.countDown()   // 首个有效回调胜出并只 countDown 一次
        }
        mdns.start()
        return try {
            if (latch.await(timeoutMs, TimeUnit.MILLISECONDS) && found.get() > 0) found.get() else null
        } finally {
            try { mdns.stop() } catch (_: Exception) {}
        }
    }

    private sealed class Outcome {
        data class Done(val out: String) : Outcome()
        data class OpenFailed(val e: Exception) : Outcome()
        data class TimedOut(val stream: AdbStream?) : Outcome()   // 携带流引用, 由 shell() probe 后再关(见 handleTimeout)
        object Overflow : Outcome()   // 输出超上限被截断且命令仍在产出: 由 shell() teardown(残留 WRTE 会背压后续命令)
    }

    /**
     * 在 worker 线程内完成 openStream + drain(旧实现 openStream 在调用线程且 open() 尾部 UNTIMED wait — loopback 丢 notify 会永久 park 且握 mLock)。
     * drain 累计超 maxBytes 即 overflow(读净流后由调用方决定报错); join(timeoutMs) 分类结局。worker 设 daemon: teardown 关 socket 后其 read 抛错自然退出。
     */
    /**
     * openStream 目标串: 命令含非 ASCII(中文等)时用 ASCII base64 信封绕开 libadb bug —
     * AdbProtocol.generateOpen 按 destination.length()(字符数)分配 buffer 却填 UTF-8 字节, 非 ASCII 必 BufferOverflowException。
     * 信封 = `echo <b64> | base64 -d | sh`(纯 ASCII 目标串, 设备侧解码执行原命令; 真机实测 CJK 命令与输出均正确)。
     * ASCII 命令走直连快路径(与旧行为逐字节一致, 零风险)。仅 shell() 走此(交互命令如 input text 中文); detached 命令恒 ASCII。
     */
    private fun shellDest(cmd: String): String {
        if (cmd.all { it.code < 128 }) return "shell:$cmd"
        val b64 = android.util.Base64.encodeToString(cmd.toByteArray(Charsets.UTF_8), android.util.Base64.NO_WRAP)
        return "shell:echo $b64 | base64 -d | sh"
    }

    private fun runStream(m: Mgr, cmd: String, timeoutMs: Long, maxBytes: Int): Outcome {
        val out = java.io.ByteArrayOutputStream()   // 仅 worker 写; 累原始字节, join 后一次性解码(否则多字节 UTF-8/CJK 在 4096 读边界被切→U+FFFD 乱码)
        val opened = java.util.concurrent.atomic.AtomicReference<AdbStream?>()
        val openErr = java.util.concurrent.atomic.AtomicReference<Exception?>()
        val overflow = java.util.concurrent.atomic.AtomicBoolean(false)
        val worker = Thread {
            val s = try { m.openStream(shellDest(cmd)) } catch (e: Exception) { openErr.set(e); return@Thread }
            opened.set(s)
            try {
                s.openInputStream().use { ins ->
                    val buf = ByteArray(4096); var total = 0
                    while (true) {
                        val n = ins.read(buf); if (n < 0) break
                        total += n
                        if (total > maxBytes) { overflow.set(true); break }
                        out.write(buf, 0, n)
                    }
                }
            } catch (_: Exception) { /* 流关闭/传输断即结束 */ }
        }.apply { isDaemon = true; name = "adb-shell" }
        worker.start()
        worker.join(timeoutMs)
        openErr.get()?.let { return Outcome.OpenFailed(it) }
        if (worker.isAlive) return Outcome.TimedOut(opened.get())   // 不在此关流: close() 是阻塞写 CLSE, wedge 中无界(见 handleTimeout probe-first)
        try { opened.get()?.close() } catch (_: Exception) {}
        if (overflow.get()) return Outcome.Overflow   // 命令仍在产出即被截断: 残留 WRTE 会背压后续命令, 交由 shell() teardown 保连接洁净
        return Outcome.Done(String(out.toByteArray(), Charsets.UTF_8))   // join 后单次解码: 字节边界对解码不可见, 仅真非法字节才成 U+FFFD
    }

    /** openStream 抛错是否「可证从未启动」(唯一安全重试条件): 仅 manager 预检 "Not connected to ADB."(OPEN 包从未发出)。open() 内部抛错可能已抵达 adbd, 重试会重复执行非幂等命令 → 不重试。 */
    private fun isNeverStarted(e: Exception): Boolean =
        e is java.io.IOException && (e.message ?: "").contains("Not connected")

    private fun overflowError(maxBytes: Int, cmd: String) = RuntimeException(
        "shell 输出超上限($maxBytes 字节, 已重置连接): 用 sed -n '起,止p' 分页 / 重定向落文件后分段读; 大输出(如截图 base64)显式调大 max_bytes: $cmd")

    /**
     * 在已建立的传输上跑一条 shell 命令, 收全部输出后返回(适合非交互命令)。断线自动重连并重试(仅限可证从未启动)。
     * 交互/长驻命令(top/logcat -f)不要走这里 — 会超时。全程持一个带超时自释的 PARTIAL_WAKE_LOCK, 防命令执行期 CPU/线程被冻结掉线(用户「上锁」诉求)。
     */
    @Synchronized
    fun shell(ctx: Context, cmd: String, timeoutMs: Long = 30_000, maxBytes: Int = DEFAULT_MAX_BYTES): String {
        require(timeoutMs > 0) {   // join(0)=永久等待, join(<0)=抛错; 0/负不表示"无限"。长驻命令走 adb_shell_detached, 慢命令加大 timeout_ms
            "timeout_ms 必须 > 0 (收到 $timeoutMs): 无 '0=无限' 语义; 长驻命令用 adb_shell_detached"
        }
        val wl = acquireWake(ctx, timeoutMs)
        try {
            val m = ensureConnected(ctx)
            return when (val r = runStream(m, cmd, timeoutMs, maxBytes)) {
                is Outcome.Done -> r.out
                is Outcome.Overflow -> { teardown(); throw overflowError(maxBytes, cmd) }   // 截断残留会背压→teardown, 下条自愈重连
                is Outcome.TimedOut -> handleTimeout(ctx, m, r, cmd, timeoutMs)
                is Outcome.OpenFailed -> {
                    if (!isNeverStarted(r.e)) {
                        lastError = r.e.toString(); teardown()
                        throw RuntimeException("shell openStream 失败(传输已断, 下次调用自动重连): ${r.e}: $cmd")
                    }
                    teardown()   // 可证从未启动 → 重连重试一次
                    val m2 = ensureConnected(ctx)
                    when (val r2 = runStream(m2, cmd, timeoutMs, maxBytes)) {
                        is Outcome.Done -> r2.out
                        is Outcome.Overflow -> { teardown(); throw overflowError(maxBytes, cmd) }
                        is Outcome.TimedOut -> handleTimeout(ctx, m2, r2, cmd, timeoutMs)
                        is Outcome.OpenFailed -> { lastError = r2.e.toString(); teardown()
                            throw RuntimeException("shell 重连后仍失败: ${r2.e}: $cmd") }
                    }
                }
            }
        } finally {
            wl?.let { runCatching { it.release() } }
        }
    }

    /** 超时分类: 先 probe(echo 1) 再决定 — probe 通=连接健康, 只是这条命令慢/长驻(关掉它, 保连接与已 detached 流); probe 死/卡=传输 wedge(teardown 自愈)。 */
    private fun handleTimeout(ctx: Context, m: Mgr, r: Outcome.TimedOut, cmd: String, timeoutMs: Long): Nothing {
        val probe = runStream(m, "echo 1", 2_000, 64)
        if (probe is Outcome.Done) {
            try { r.stream?.close() } catch (_: Exception) {}   // 连接健康: 可安全关掉这条慢命令的流(reader 线程活着, CLSE 写得出去)
            throw RuntimeException("shell 超时(${timeoutMs}ms): 命令未在时限内结束(长驻命令用 adb_shell_detached; 或分页/加大 timeout_ms): $cmd")
        }
        teardown()   // probe 死/卡 = 传输卡死: close() 无锁关 socket, 唤醒所有卡住的 worker
        lastError = "shell 超时且传输已卡死(已重置, 下次调用自动重连): $cmd"   // 记因: 唯一漏记的传输死亡路径, 补上让 status().error 能解释这次 reset
        throw RuntimeException("shell 超时且传输已卡死(已重置, 下次调用自动重连): $cmd")
    }

    // 命令执行期持一个带超时自释的 wake lock; 缺 WAKE_LOCK 权限/OEM 异常一律降级为 null 不影响 shell(零半径增强, let-it-crash #14)。
    private fun acquireWake(ctx: Context, timeoutMs: Long): PowerManager.WakeLock? = runCatching {
        val pm = ctx.applicationContext.getSystemService(Context.POWER_SERVICE) as PowerManager
        pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ga:adb-shell").apply {
            setReferenceCounted(false)
            acquire(2 * timeoutMs + 45_000)   // 覆盖最坏自愈时窗(两趟 ensureConnected≤20s×2 + 两趟命令 + probe), 防重连/重试腿上 CPU 冻结
        }
    }.getOrNull()

    /** tag → 持有中的 detached 流。不变量: 每 tag ≤1 活流; 命令进程死则流 EOF, drain 线程自清 map。 */
    private val held = java.util.concurrent.ConcurrentHashMap<String, AdbStream>()

    /**
     * 起一条 detached shell: openStream 后**不 close 不 join**, 立即返回。守护线程排水防背压。
     * 用途: 起需常驻的派生进程(如虚拟屏 VdHelper)。断线时先 ensureConnected 自愈再开流。
     * 命令须自行 `1>_LOG 2>&1 3>&-` 重定向输出并切断 adbd 泄漏给 shell 的 fd3 控制 socket——
     * 否则常驻子进程持 fd3 会令后续经同 transport 的 shell() 读不到 EOF 而超时。
     * 回收: 因 3>&- 切断了 fd3, closeDetached 关流**不**能收割子进程(脐带已断), 须由调用方 pid kill;
     * closeDetached 仅清 GA 侧 held 流引用。
     */
    fun shellDetached(ctx: Context, tag: String, cmd: String): String {
        val stream: AdbStream = synchronized(this) {
            val m = ensureConnected(ctx)
            // openStream(及旧流的阻塞 CLSE close)移入限时 worker: 与 shell() 同构, 防丢-notify 竞态永久 park 调用线程
            // (调用线程握着 @Synchronized(this) monitor, 一旦 park 会砖化 shell/connect/pair/reset/shellDetached 全部)。
            val opened = java.util.concurrent.atomic.AtomicReference<AdbStream?>()
            val openErr = java.util.concurrent.atomic.AtomicReference<Exception?>()
            val worker = Thread {
                try {
                    held.remove(tag)?.let { runCatching { it.close() } }
                    opened.set(m.openStream("shell:$cmd"))
                } catch (e: Exception) { openErr.set(e) }
            }.apply { isDaemon = true; name = "adb-detached-open-$tag" }
            worker.start(); worker.join(15_000)
            openErr.get()?.let { lastError = it.toString(); throw it }
            val s = opened.get()
            if (worker.isAlive || s == null) {   // 超时=openStream 卡死: teardown 无锁关 socket 解 park, 抛错, 下次调用自愈重连
                lastError = "shellDetached openStream 超时/传输卡死(已重置): $cmd"; teardown()
                throw RuntimeException("shellDetached openStream 超时/传输卡死(已重置, 下次调用自动重连): $cmd")
            }
            held[tag] = s
            s
        }
        Thread {   // 守护排水: 输出已重定向落文件, 流上近零字节, 此处只弃; 命令进程死→流 EOF→自清 map
            try {
                stream.openInputStream().use { ins ->
                    val buf = ByteArray(4096)
                    while (ins.read(buf) >= 0) { }
                }
            } catch (_: Exception) { }
            finally { held.remove(tag, stream); runCatching { stream.close() } }
        }.apply { isDaemon = true; name = "adb-detached-$tag" }.start()
        return tag
    }

    /** 清 GA 侧 held 流引用(幂等)。注: 因 3>&- 断 fd3, 关流不收割子进程, 真 kill 靠调用方 pid kill。 */
    fun closeDetached(tag: String): Boolean =
        held.remove(tag)?.let { runCatching { it.close() }; true } ?: false

    data class Status(val connected: Boolean, val paired: Boolean, val error: String?, val port: Int,
                      val repairNeeded: Boolean = false)


    /**
     * paired 直接查磁盘证书文件是否存在, 不依赖内存 manager 实例:
     * 证书 pair 后持久化在 filesDir, 冷启新进程 manager 尚未懒加载(=null)时,
     * 旧实现会误报 paired:false(即使证书在磁盘上), 误导调用方以为要重配。
     * connect() 复用磁盘证书免 pair 直连本就成立, 故 paired 应以磁盘证书为准。port=上次成功端口(便于展示/调试)。
     */
    fun status(ctx: Context): Status = Status(
        connected = connected,
        paired = File(ctx.filesDir, CERT_NAME).exists() && File(ctx.filesDir, KEY_NAME).exists(),
        error = lastError,
        port = loadPort(ctx),
        repairNeeded = pairingRequired || adbNeedsRepair(lastError),
    )

    /** 断开并丢弃已配对证书(下次要重新 pair)。 */
    @Synchronized
    fun reset(ctx: Context) {
        teardown()
        lastError = null
        pairingRequired = false
        savePort(ctx, 0)
        File(ctx.filesDir, KEY_NAME).delete()
        File(ctx.filesDir, CERT_NAME).delete()
    }

    /** AbsAdbConnectionManager 具体实现: 密钥/证书持久化在 app 私有 filesDir。 */
    private class Mgr(ctx: Context) : AbsAdbConnectionManager() {
        private val keyFile = File(ctx.filesDir, KEY_NAME)
        private val certFile = File(ctx.filesDir, CERT_NAME)
        private val privateKey: PrivateKey
        private val certificate: Certificate

        init {
            setApi(Build.VERSION.SDK_INT)
            setTimeout(5, TimeUnit.SECONDS)   // 否则默认 Long.MAX_VALUE → connect()/handshake 可无限阻塞(又一处 wedge)
            if (keyFile.exists() && certFile.exists()) {
                privateKey = loadKey()
                certificate = loadCert()
            } else {
                val kp = KeyPairGenerator.getInstance("RSA").apply {
                    initialize(2048, SecureRandom.getInstance("SHA1PRNG"))
                }.generateKeyPair()
                privateKey = kp.private
                certificate = generateCert(kp.public, privateKey)
                keyFile.writeBytes(PKCS8EncodedKeySpec(privateKey.encoded).encoded)
                certFile.writeBytes(certificate.encoded)
            }
        }

        private fun loadKey(): PrivateKey =
            KeyFactory.getInstance("RSA").generatePrivate(PKCS8EncodedKeySpec(keyFile.readBytes()))

        private fun loadCert(): Certificate =
            certFile.inputStream().use { CertificateFactory.getInstance("X.509").generateCertificate(it) }

        override fun getPrivateKey(): PrivateKey = privateKey
        override fun getCertificate(): Certificate = certificate
        override fun getDeviceName(): String = DEVICE_NAME
    }

    /** 生成自签 X509 证书(adbd 只校验密钥交换, 内容仅需自洽); 依赖 sun-security-android(包名 android.sun.security)。 */
    private fun generateCert(pub: PublicKey, priv: PrivateKey): X509CertImpl {
        val now = System.currentTimeMillis()
        val notBefore = Date(now)
        val notAfter = Date(now + TimeUnit.DAYS.toMillis(3650))
        val owner = X500Name("CN=GAgent, O=GA, C=CN")

        val ext = CertificateExtensions()
        ext.set("SubjectKeyIdentifier",
            SubjectKeyIdentifierExtension(KeyIdentifier(pub).identifier))
        ext.set("PrivateKeyUsage", PrivateKeyUsageExtension(notBefore, notAfter))

        val info = X509CertInfo()
        info.set("version", CertificateVersion(CertificateVersion.V3))
        info.set("serialNumber", CertificateSerialNumber((now and 0x7fffffffL).toInt()))
        info.set("algorithmID", CertificateAlgorithmId(AlgorithmId.get("SHA512withRSA")))
        info.set("subject", CertificateSubjectName(owner))
        info.set("issuer", CertificateIssuerName(owner))
        info.set("key", CertificateX509Key(pub))
        info.set("validity", CertificateValidity(notBefore, notAfter))
        info.set("extensions", ext)
        return X509CertImpl(info).apply { sign(priv, "SHA512withRSA") }
    }
}

/** 证书还在盘上不代表手机仍信任它: 系统撤销配对后连接会报 AdbPairingRequiredException, 只能由用户重新配对。纯函数, 便于单测。 */
fun adbNeedsRepair(error: String?): Boolean =
    error != null && (error.contains("PairingRequired") || error.contains("pairing is required", ignoreCase = true))

/** 自动发现全失败时的可行动错误: 有端口报过需配对 ⇒ 明说重新配对(重开开关没用), 否则才是开关/端口问题。纯函数, 便于单测。 */
fun adbAutoConnectError(pairingRequired: Boolean): String =
    if (pairingRequired) "无法建立自连: ADB pairing is required — 手机已不再信任 GAgent 的密钥, 需用户在 设置→开发者选项→无线调试→使用配对码配对设备 重新配对(droid.adb_pair(码, 配对端口)), 重开无线调试无效"
    else "无法建立自连: 无线调试可能已关(设置→开发者选项→无线调试), 或端口不可达。开着无线调试后 droid.adb_connect() 会自动发现端口重试"
