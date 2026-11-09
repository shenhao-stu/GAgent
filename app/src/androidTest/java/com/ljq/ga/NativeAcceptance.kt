package com.ljq.ga

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.io.File
import org.conscrypt.Conscrypt
import javax.net.ssl.SSLContext

/** Explicit on-device checks, packaged only in the separate instrumentation APK. */
class NativeAcceptance : Instrumentation() {
    private var arguments = Bundle()
    override fun onCreate(args: Bundle?) { arguments = args ?: Bundle(); start() }

    override fun onStart() {
        val report = JSONObject()
        try {
            val ctx = targetContext
            when (arguments.getString("phase", "native")) {
                "native" -> {
                    val tls = SSLContext.getInstance("TLS", Conscrypt.newProvider())
                    tls.init(null, null, null)
                    check("TLSv1.3" in tls.supportedSSLParameters.protocols)
                    report.put("conscrypt", Conscrypt.version().let { "${it.major()}.${it.minor()}.${it.patch()}" })
                    AssetUnpacker(ctx).extractAssets()
                    if (!Python.isStarted()) Python.start(AndroidPlatform(ctx))
                    val py = Python.getInstance()
                    val scope = py.getModule("builtins").callAttr("dict")
                    scope.callAttr("__setitem__", "GA_DIR", File(ctx.filesDir, "ga").absolutePath)
                    val code = context.assets.open("native_probe.py").bufferedReader().use { it.readText() }
                    py.getModule("builtins").callAttr("exec", code, scope)
                    report.put("native", JSONObject(py.getModule("json").callAttr("dumps", scope.callAttr("__getitem__", "result")).toString()))
                }
                "download" -> {
                    OfflineAsr.download(ctx)
                    val deadline = SystemClock.elapsedRealtime() + 650_000
                    while (JSONObject(OfflineAsr.status(ctx)).optString("dlState") == "running" &&
                        SystemClock.elapsedRealtime() < deadline) Thread.sleep(500)
                    report.put("model", JSONObject(OfflineAsr.status(ctx)))
                    check(VoiceModel.verify(ctx)) { "download_or_integrity_failed" }
                }
                "voice" -> {
                    val wav = requireNotNull(arguments.getString("wav"))
                    val result = JSONObject(OfflineAsr.recognizeWav(ctx, wav))
                    report.put("voice", result)
                    check(result.optBoolean("ok") && result.optString("text").length >= 4) { "empty_transcript" }
                }
                "integrity" -> {
                    check(VoiceModel.verify(ctx))
                    val tokens = File(VoiceModel.directory(ctx), "tokens.txt")
                    val original = tokens.readBytes()
                    try {
                        val changed = original.clone().also { it[0] = (it[0].toInt() xor 1).toByte() }
                        tokens.writeBytes(changed)
                        check(VoiceModel.ready(ctx)) { "fixture_size_changed" }
                        check(!VoiceModel.verify(ctx)) { "corrupt_asset_accepted" }
                        check(!VoiceModel.ready(ctx)) { "corrupt_asset_not_invalidated" }
                    } finally { tokens.writeBytes(original) }
                    check(VoiceModel.verify(ctx))
                    report.put("sameSizeCorruptionRejected", true)
                }
                "microphone", "lifecycle", "acoustic" -> {
                    val activity = startActivitySync(Intent(ctx, MainActivity::class.java)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
                    sendStatus(1, Bundle().apply { putString("phase", "waiting_for_foreground") })
                    val foregroundDeadline = SystemClock.elapsedRealtime() + 15_000
                    while (!activity.hasWindowFocus() && SystemClock.elapsedRealtime() < foregroundDeadline)
                        Thread.sleep(100)
                    check(activity.hasWindowFocus()) { "activity_not_foreground" }
                    val start = JSONObject(activity.Bridge().offAsrStart())
                    check(start.optBoolean("ok")) { start.toString() }
                    val id = start.getInt("id")
                    try {
                        Thread.sleep(if (arguments.getString("phase") == "acoustic") 10_000 else 1200)
                        check(JSONObject(OfflineAsr.poll(id)).optDouble("sec") > 0) { "no_audio_samples" }
                        report.put("capture", JSONObject(OfflineAsr.poll(id)))
                        when (arguments.getString("phase")) {
                            "acoustic" -> {
                                OfflineAsr.stop(id)
                                val deadline = SystemClock.elapsedRealtime() + 30_000
                                var result = JSONObject(OfflineAsr.poll(id))
                                while (!result.optBoolean("done") && SystemClock.elapsedRealtime() < deadline) {
                                    Thread.sleep(100); result = JSONObject(OfflineAsr.poll(id))
                                }
                                report.put("voice", result)
                                check(result.optBoolean("done") && result.optString("text").length >= 4) { "empty_transcript" }
                            }
                            else -> {
                                if (arguments.getString("phase") == "lifecycle") {
                                    runOnMainSync { check(activity.moveTaskToBack(true)) }
                                    val deadline = SystemClock.elapsedRealtime() + 3000
                                    while (JSONObject(OfflineAsr.poll(id)).optString("error") != "session_expired" &&
                                        SystemClock.elapsedRealtime() < deadline) Thread.sleep(100)
                                } else OfflineAsr.cancel(id)
                                check(JSONObject(OfflineAsr.poll(id)).optString("error") == "session_expired")
                                check(!JSONObject(OfflineAsr.stop(id)).optBoolean("ok"))
                                report.put("staleSessionRejected", true)
                            }
                        }
                    } finally { OfflineAsr.cancel(id) }
                }
                else -> error("unknown_phase")
            }
            report.put("ok", true)
            finish(Activity.RESULT_OK, Bundle().apply { putString("report", report.toString()) })
        } catch (e: Throwable) {
            report.put("ok", false).put("error", e.javaClass.simpleName + ": " + e.message)
            finish(Activity.RESULT_CANCELED, Bundle().apply { putString("report", report.toString()) })
        }
    }
}
