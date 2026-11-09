package com.ljq.ga

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import com.k2fsa.sherpa.onnx.FeatureConfig
import com.k2fsa.sherpa.onnx.OfflineModelConfig
import com.k2fsa.sherpa.onnx.OfflineParaformerModelConfig
import com.k2fsa.sherpa.onnx.OfflineRecognizer
import com.k2fsa.sherpa.onnx.OfflineRecognizerConfig
import org.json.JSONObject
import android.os.SystemClock
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** On-device recognition adapted from GAndroid; sessions own their microphone and results. */
object OfflineAsr {
    private const val SR = 16000
    private const val MAX_SEC = 60
    private const val MODEL = "model.int8.onnx"
    private const val TOKENS = "tokens.txt"
    private const val IDLE_MS = 5 * 60_000L   // 识别器空闲多久释放(约省 100MB+ 常驻内存, 代价是下次首用多 ~1.3s)

    private val lock = Any()
    @Volatile private var recognizer: OfflineRecognizer? = null
    private val loadLock = Any()
    private var gen = 0
    private var recording = false
    private var captureActive = false
    private var done = true
    private var text = ""
    private var error = ""
    private var samples = FloatArray(0)
    private var nSamples = 0
    private var lastMs = 0L      // 最近一次解码耗时
    private var audioSec = 0f
    private var peak = 0f        // 本次录音音量峰值(0~1), 判断是否真录到声音
    @Volatile private var lastUse = 0L
    private val idleExec = Executors.newSingleThreadScheduledExecutor { Thread(it, "asr-idle").apply { isDaemon = true } }
    fun modelDir(ctx: Context) = VoiceModel.directory(ctx)
    private fun modelReady(ctx: Context) = VoiceModel.ready(ctx)
    fun status(ctx: Context): String = VoiceModel.status(ctx)
        .put("loaded", recognizer != null)
        .put("micPerm", ctx.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
        .toString()
    fun download(ctx: Context): String = VoiceModel.download(ctx)

    /** 记录使用并排一次空闲检查; 到点时若期间没再用且不在录音则释放识别器。 */
    private fun touch() {
        lastUse = SystemClock.elapsedRealtime()
        idleExec.schedule({ maybeRelease() }, IDLE_MS, TimeUnit.MILLISECONDS)
    }

    private fun maybeRelease() = synchronized(loadLock) {   // 锁序: loadLock -> lock(与 decode 一致)
        if (SystemClock.elapsedRealtime() - lastUse < IDLE_MS - 1_000) return@synchronized
        if (synchronized(lock) { recording }) return@synchronized
        recognizer?.let { runCatching { it.release() }; recognizer = null }
    }

    /** 懒加载识别器(线程安全, 只加载一次)。 */
    private fun ensureRecognizer(ctx: Context): OfflineRecognizer {
        recognizer?.let { return it }
        synchronized(loadLock) {
            recognizer?.let { return it }
            check(modelReady(ctx)) { "model_missing" }
            check(VoiceModel.verify(ctx)) { "model_integrity_failed" }
            val d = modelDir(ctx)
            val cfg = OfflineRecognizerConfig(
                featConfig = FeatureConfig(sampleRate = SR, featureDim = 80),
                modelConfig = OfflineModelConfig(
                    paraformer = OfflineParaformerModelConfig(model = File(d, MODEL).absolutePath),
                    tokens = File(d, TOKENS).absolutePath,
                    numThreads = 4,
                    modelType = "paraformer",
                ),
            )
            return OfflineRecognizer(null, cfg).also { recognizer = it; touch() }
        }
    }

    // 整段持 loadLock: 防止空闲释放与解码并发(释放中的 native 指针被用 -> 崩溃)
    private fun decode(ctx: Context, pcm: FloatArray, n: Int): String = synchronized(loadLock) {
        val r = ensureRecognizer(ctx)
        val t0 = System.currentTimeMillis()
        val s = r.createStream()
        try {
            s.acceptWaveform(if (n == pcm.size) pcm else pcm.copyOf(n), SR)
            r.decode(s)
            r.getResult(s).text.trim()
        } finally {
            s.release(); touch()
            synchronized(lock) { lastMs = System.currentTimeMillis() - t0; audioSec = n / SR.toFloat() }
        }
    }

    /** 开始录音。立即返回; 结果经 poll 取。 */
    fun start(ctx: Context): String = runCatching {
        val app = ctx.applicationContext
        if (app.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) return err("no_mic_permission")
        if (!modelReady(app)) return err("model_missing")
        val curGen: Int
        synchronized(lock) {
            if (!done || captureActive) return err("busy")
            gen++; curGen = gen
            recording = true; captureActive = true; done = false; text = ""; error = ""; lastMs = 0; audioSec = 0f; peak = 0f
            samples = FloatArray(SR * 8); nSamples = 0
        }
        Thread({ runCatching { ensureRecognizer(app) } }, "asr-load").start()
        Thread({ recordLoop(app, curGen) }, "asr-rec").start()
        JSONObject().put("ok", true).put("id", curGen).toString()
    }.getOrElse { errJson(it) }

    private fun recordLoop(app: Context, curGen: Int) {
        var rec: AudioRecord? = null
        try {
            val minBuf = AudioRecord.getMinBufferSize(SR, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
            rec = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, SR, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, maxOf(minBuf, SR / 5 * 2))
            check(rec.state == AudioRecord.STATE_INITIALIZED) { "audiorecord_init" }
            rec.startRecording()
            val buf = ShortArray(SR / 10)
            while (true) {
                val keep = synchronized(lock) { gen == curGen && recording && nSamples < SR * MAX_SEC }
                if (!keep) break
                val n = rec.read(buf, 0, buf.size)
                if (n < 0) throw IllegalStateException("read=$n")
                synchronized(lock) {
                    if (gen != curGen) return
                    if (nSamples + n > samples.size) samples = samples.copyOf(maxOf(samples.size * 2, nSamples + n))
                    for (i in 0 until n) { val v = buf[i] / 32768f; samples[nSamples + i] = v; if (v > peak) peak = v else if (-v > peak) peak = -v }
                    nSamples += n
                }
            }
        } catch (t: Throwable) {
            synchronized(lock) { if (gen == curGen && !done) { error = "record: $t"; done = true; recording = false } }
            return
        } finally {
            runCatching { rec?.stop() }; runCatching { rec?.release() }
            synchronized(lock) { captureActive = false }
        }
        // 录音结束(stop 或到上限): 解码
        val (pcm, n) = synchronized(lock) {
            if (gen != curGen || done) return
            recording = false
            samples to nSamples
        }
        val res = runCatching { if (n < SR / 5) "" else decode(app, pcm, n) }
        synchronized(lock) {
            if (gen == curGen) {
                res.onSuccess { text = it }.onFailure { error = "decode: $it" }
                done = true; samples = FloatArray(0)
            }
        }
    }

    fun poll(session: Int): String = synchronized(lock) {
        if (session != gen) return@synchronized err("session_expired")
        JSONObject().put("text", text).put("done", done).put("error", error).put("engine", "offline")
            .put("recording", recording).put("sec", nSamples / SR.toFloat())
            .put("peak", peak.toDouble()).put("decodeMs", lastMs).put("audioSec", audioSec).toString()
    }

    /** 说完了: 停止录音并开始识别(done=true 时出结果)。 */
    fun stop(session: Int): String {
        synchronized(lock) { if (session != gen) return err("session_expired"); recording = false }
        return """{"ok":true}"""
    }

    fun cancel(session: Int): String {
        synchronized(lock) { if (session != gen) return err("session_expired"); gen++; recording = false; done = true; samples = FloatArray(0); nSamples = 0 }
        return """{"ok":true}"""
    }

    /** 开发自测: 识别一个 16bit 单声道 PCM wav 文件(同步, 不碰麦克风)。 */
    fun recognizeWav(ctx: Context, path: String): String = runCatching {
        val file = File(path)
        require(file.length() <= PcmWav.MAX_BYTES) { "wav_size" }
        val pcm = PcmWav.samples(file.readBytes())
        val t = decode(ctx.applicationContext, pcm, pcm.size)
        JSONObject().put("ok", true).put("text", t).put("decodeMs", lastMs).put("audioSec", audioSec).toString()
    }.getOrElse { errJson(it) }

    private fun err(code: String) = """{"ok":false,"error":"$code"}"""
    private fun errJson(t: Throwable) =
        """{"ok":false,"error":${JSONObject.quote(t.toString().take(200))}}"""
}
