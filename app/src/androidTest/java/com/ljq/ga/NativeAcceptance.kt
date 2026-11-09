package com.ljq.ga

import android.app.Activity
import android.app.Instrumentation
import android.os.Bundle
import android.os.SystemClock
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.io.File

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
                "microphone" -> {
                    val start = JSONObject(OfflineAsr.start(ctx))
                    check(start.optBoolean("ok")) { start.toString() }
                    val id = start.getInt("id")
                    Thread.sleep(1200)
                    check(JSONObject(OfflineAsr.poll(id)).optDouble("sec") > 0) { "no_audio_samples" }
                    report.put("capture", JSONObject(OfflineAsr.poll(id)))
                    OfflineAsr.cancel(id)
                    check(JSONObject(OfflineAsr.poll(id)).optString("error") == "session_expired")
                    check(!JSONObject(OfflineAsr.stop(id)).optBoolean("ok"))
                    report.put("staleSessionRejected", true)
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
