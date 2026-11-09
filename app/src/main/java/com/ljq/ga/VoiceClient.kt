package com.ljq.ga

import android.content.Context
import android.util.Base64
import android.util.Log
import okhttp3.*
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.*

/** User-configured streaming ASR, with normal TLS verification. */
object VoiceClient {
    private const val TAG = "VoiceClient"

    // ---- 会话状态(lock 保护) ----
    private val lock = Object()
    private var gen = 0                     // 世代号, 每次 start 递增
    @Volatile private var ws: WebSocket? = null   // 后台连接线程写, senderLoop/close/stop 跨线程读 → 必须 volatile(可见性)
    private var committed = ""              // 已确认文本(turn final)
    private var partial = ""                // 当前增量片段
    private var text = ""                   // committed + partial (展示用)
    private var done = false
    private var error = ""
    private var stopping = false
    private var finalizing = false          // 收尾单次闸(stop 路径与 bg 连上后的 stopping 路径可能同时触发)

    // sender: 单线程顺序发送, 队列满丢旧帧(实时音频容忍丢帧)
    @Volatile private var sender: ExecutorService? = null   // 后台连接线程创建, close 跨线程关闭 → volatile 防泄漏
    private val sendQueue = LinkedBlockingQueue<String>(96)

    private lateinit var appCtx: Context
    private val client: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .followRedirects(false)
            .followSslRedirects(false)
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.MINUTES)   // WS 长连接
            .writeTimeout(10, TimeUnit.SECONDS)
            .build()
    }

    fun init(ctx: Context) { appCtx = ctx.applicationContext }

    // ======================== Public API (JS Interface 调用) ========================

    /** 开始录音: 申领 token → WS 连接 → session.update. 返回 JSON {ok, error?}. */
    fun start(): String = runCatching {
        // 配置只读本地文件, 同步校验: 未配置时不申请麦克风、不开线程, 交由 WebUI 引导到可选组件
        val config = try { voiceConfig() } catch (e: Exception) { return """{"ok":false,"error":"voice_not_configured"}""" }
        close()
        val curGen: Int
        synchronized(lock) {
            gen++; committed = ""; partial = ""; text = ""; done = false; error = ""; stopping = false; finalizing = false
            curGen = gen
        }
        sendQueue.clear()
        // 后台线程做 token 申领 + WS 握手(原 connectWs 的 latch.await 会同步阻塞 JS 桥线程 1-2s → 点击卡顿).
        // 立即返回 ok; WS 就绪前 send() 把帧缓冲进 sendQueue, senderLoop 连上后一次性补发(实时 ASR 容忍短延迟).
        Thread {
            val socket = try { connectWs(config.getString("url"), curGen, config.optString("token")) }
                catch (e: Exception) { null }
            if (socket == null) { failAsync(curGen, "Streaming ASR connection failed"); return@Thread }
            synchronized(lock) {
                if (gen != curGen || done) { socket.cancel(); return@Thread }   // 期间被取消/停止
                ws = socket
            }
            // session.update: pcm16 16k mono, server_vad 250ms
            runCatching {
                socket.send(JSONObject().apply {
                    put("type", "session.update")
                    put("session", JSONObject().apply {
                        put("audio", JSONObject().apply {
                            put("input", JSONObject().apply {
                                put("format", JSONObject()
                                    .put("type", "pcm").put("codec", "pcm_s16le")
                                    .put("rate", 16000).put("bits", 16).put("channel", 1))
                                put("transcription", JSONObject()
                                    .put("model", config.optString("model").ifBlank { "step-asr-1.1-stream" })
                                    .put("language", "zh").put("enable_itn", true))
                                put("turn_detection", JSONObject()
                                    .put("type", "server_vad").put("silence_duration_ms", 250))
                            })
                        })
                    })
                }.toString())
            }
            // 启动 sender 线程(补发缓冲帧 + 后续实时帧)
            sender = Executors.newSingleThreadExecutor().also { exec ->
                exec.submit { senderLoop(curGen) }
            }
            // 连接期间用户已点停止 → 连上后立即冲刷缓冲音频再收尾(不丢词; stop() 在 ws==null 时不置 done, 交由这里处理)
            val finalizeNow = synchronized(lock) { stopping && gen == curGen }
            if (finalizeNow) Thread { finalize(curGen) }.apply { isDaemon = true }.start()
        }.apply { isDaemon = true }.start()

        """{"ok":true}"""
    }.getOrElse { errJson(it) }

    /** 后台连接失败 → 置 error/done(JS poll 取到并提示, 不再同步阻塞 UI). */
    private fun failAsync(curGen: Int, msg: String) {
        synchronized(lock) { if (gen == curGen && error.isEmpty()) { error = msg; done = true } }
    }

    /** 喂 base64 PCM 音频帧. WS 就绪前先缓冲(连上后由 senderLoop 补发); 仅会话结束/失败后拒收. */
    fun send(b64: String): String = runCatching {
        synchronized(lock) { if (done) return """{"ok":false,"error":"no_stream"}""" }
        if (!sendQueue.offer(b64)) {
            sendQueue.poll()    // 丢最旧帧
            sendQueue.offer(b64)
        }
        """{"ok":true}"""
    }.getOrElse { errJson(it) }

    /** 轮询当前文本. 返回 {text, done, error}. */
    fun poll(): String = synchronized(lock) {
        """{"text":${JSONObject.quote(text)},"done":$done,"error":${JSONObject.quote(error)}}"""
    }

    /** 停止录音: 推静音帧触发 server_vad 收尾. */
    fun stop(): String = runCatching {
        val curGen: Int; val hasWs: Boolean
        synchronized(lock) { stopping = true; curGen = gen; hasWs = (ws != null) }   // 读 ws 与 bg 线程的 ws=socket 发布同锁 → 原子决策(消除停止/握手竞态泄漏)
        if (hasWs) {
            Thread { finalize(curGen) }.apply { isDaemon = true }.start()
        }
        // ws==null(仍在后台连接): 不在此置 done — 由 bg 线程连上后检测 stopping 自行 finalize(冲刷已缓冲音频再收尾, 否则快速"说-停"丢词)
        """{"ok":true}"""
    }.getOrElse { errJson(it) }

    /** 取消: 立即关闭, 不等收尾. */
    fun cancel(): String {
        close()
        return """{"ok":true}"""
    }

    // ======================== 内部实现 ========================

    private fun close() {
        synchronized(lock) { done = true }
        runCatching { ws?.close(1000, "close") }
        runCatching { sender?.shutdownNow() }
        ws = null; sender = null; sendQueue.clear()
    }

    private fun voiceConfig(): JSONObject {
        val file = java.io.File(appCtx.filesDir, "ga/kv/ga.integrations.json")
        val config = JSONObject(file.readText()).getJSONObject("voice")
        val uri = java.net.URI(config.getString("url"))
        require(uri.scheme == "wss" && !uri.host.isNullOrBlank() && uri.userInfo == null)
        return config
    }

    /** 阻塞式 WS 握手(CountDownLatch 等连接结果). */
    private fun connectWs(url: String, curGen: Int, token: String): WebSocket {
        val latch = CountDownLatch(1)
        var connectErr: Throwable? = null
        val req = Request.Builder().url(url).apply {
            if (token.isNotEmpty()) header("Authorization", "Bearer $token")
        }.build()

        val socket = client.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) { latch.countDown() }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                val code = response?.code ?: 0
                connectErr = when (code) {
                    401 -> AuthException(t.message ?: "auth")
                    429, 503 -> BusyException(t.message ?: "busy")
                    else -> t
                }
                latch.countDown()
            }
            override fun onMessage(webSocket: WebSocket, text: String) { onWsMessage(text, curGen) }
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
                synchronized(lock) {
                    if (gen == curGen && !done) { error = "WS closed: $reason"; done = true }
                }
            }
        })

        if (!latch.await(15, TimeUnit.SECONDS)) {
            socket.cancel()
            throw IOException("WS connect timeout")
        }
        connectErr?.let { socket.cancel(); throw it }
        return socket
    }

    /** WS 消息处理(OkHttp 回调线程). */
    private fun onWsMessage(raw: String, expectedGen: Int) {
        val ev = runCatching { JSONObject(raw) }.getOrNull() ?: return
        val t = ev.optString("type").ifEmpty { ev.optString("event") }

        // 过滤 AI 回复事件(不是用户 ASR)
        if (t.startsWith("response") || t.startsWith("output_audio") || t.startsWith("output_text")) return

        val piece = extractText(ev)

        val isTurnFinal = t.endsWith(".completed") || t.endsWith(".done") || t.endsWith(".final")
                || t == "conversation.item.input_audio_transcription.completed"
        val isDelta = "delta" in t || t.endsWith(".partial") || t.endsWith(".transcript")

        if (isTurnFinal) {
            synchronized(lock) {
                if (gen != expectedGen) return
                if (piece.isNotEmpty()) {
                    val base = committed
                    val sep = if (base.isNotEmpty() && !base.endsWith(" ")) " " else ""
                    committed = if (base.isNotEmpty()) "$base$sep$piece" else piece
                }
                partial = ""
                text = committed
                if (stopping) done = true
            }
            return
        }

        if (isDelta && piece.isNotEmpty()) {
            synchronized(lock) {
                if (gen != expectedGen) return
                // 增量 delta 类型: 逐字累加到 partial
                partial = if (t in listOf("transcript.text.delta", "text.delta",
                        "conversation.item.input_audio_transcription.delta"))
                    partial + piece else piece
                val base = committed
                val sep = if (base.isNotEmpty() && !base.endsWith(" ")) " " else ""
                text = if (base.isNotEmpty()) "$base$sep$partial" else partial
            }
            return
        }

        // error 事件
        if (t == "error" || ev.has("error")) {
            val msg = ev.optJSONObject("error")?.optString("message")
                ?: ev.optString("error")
            synchronized(lock) {
                if (gen == expectedGen) { error = msg.take(120); done = true }
            }
        }
    }

    /** sender 线程: 从队列取 base64 帧发给 WS. */
    private fun senderLoop(expectedGen: Int) {
        while (true) {
            synchronized(lock) { if (gen != expectedGen) return }
            val b64 = try { sendQueue.poll(500, TimeUnit.MILLISECONDS) } catch (_: Exception) { null }
            if (b64 != null) {
                val socket = ws ?: return
                runCatching {
                    socket.send("""{"type":"input_audio_buffer.append","audio":"$b64"}""")
                }.onFailure { return }
            }
        }
    }

    /** 停止收尾: 推 800ms 静音 + 等 1.2s 让 server_vad commit 最后 utterance. */
    private fun finalize(expectedGen: Int) {
        synchronized(lock) { if (gen != expectedGen || finalizing) return; finalizing = true }   // 单次收尾闸
        val sil = Base64.encodeToString(ByteArray(3200), Base64.NO_WRAP)  // 100ms pcm16@16k
        repeat(8) {
            synchronized(lock) { if (gen != expectedGen) return }
            sendQueue.offer(sil)
            Thread.sleep(100)
        }
        Thread.sleep(1200)
        synchronized(lock) {
            if (gen != expectedGen) return
            done = true
        }
        close()
    }

    private fun extractText(ev: JSONObject): String {
        for (k in listOf("delta", "text", "transcript")) {
            val v = ev.opt(k)
            if (v is String && v.isNotBlank()) return v.trim()
            if (v is JSONObject) {
                val inner = v.optString("text").ifEmpty { v.optString("transcript") }
                if (inner.isNotBlank()) return inner.trim()
            }
        }
        return ""
    }

    private fun errJson(t: Throwable) =
        """{"ok":false,"error":${JSONObject.quote(t.toString().take(200))}}"""

    private class AuthException(msg: String) : Exception(msg)
    private class BusyException(msg: String) : Exception(msg)
}
