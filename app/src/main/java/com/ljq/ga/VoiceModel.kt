package com.ljq.ga

import android.content.Context
import android.os.SystemClock
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import org.json.JSONObject

internal object VoiceModel {
    private const val BASE = "https://huggingface.co/csukuangfj/sherpa-onnx-paraformer-zh-small-2024-03-09/resolve/63ddc3cd0f2810b68289a7b3876e62ef5d53d6df/"
    private val files = listOf(
        Triple("tokens.txt", 75352L, "4b2d964e18b9cf139b473003b6698fb2ed9a2a5ec55b93daa677b28f578897aa"),
        Triple("model.int8.onnx", 81828675L, "3ef6c19369b912f7caf3cef8e545c5ccd1a33d9d7ec792a46668dc41c4b229ec"),
    )
    @Volatile private var state = "idle"
    @Volatile private var received = 0L
    @Volatile private var error = ""

    fun directory(ctx: Context) = File(ctx.filesDir, "asr/paraformer-zh-small")
    fun ready(ctx: Context) = files.all { File(directory(ctx), it.first).length() == it.second }
    fun verify(ctx: Context): Boolean {
        var valid = true
        for ((name, size, sha) in files) {
            val file = File(directory(ctx), name)
            if (!file.isFile || file.length() != size || digest(file) != sha) {
                // These fixed app-owned assets are replaceable. Make the next
                // user attempt offer a verified download instead of retrying bad bytes.
                if (file.isFile) file.delete()
                valid = false
            }
        }
        return valid
    }

    fun status(ctx: Context) = JSONObject().put("modelReady", ready(ctx))
        .put("dlState", state).put("dlGot", received).put("dlTotal", files.sumOf { it.second })
        .put("dlErr", error)

    @Synchronized fun download(ctx: Context): String {
        if (state == "running") return """{"ok":true,"already":true}"""
        state = "running"; received = 0; error = ""
        val app = ctx.applicationContext
        Thread({
            try { fetch(app); state = "done" }
            catch (e: Exception) { error = e.javaClass.simpleName; state = "error" }
        }, "voice-model-download").start()
        return """{"ok":true}"""
    }

    private fun fetch(ctx: Context) {
        val dir = directory(ctx).apply { mkdirs() }
        val deadline = SystemClock.elapsedRealtime() + 10 * 60_000L
        var base = 0L
        for ((name, size, sha) in files) {
            val target = File(dir, name)
            if (target.length() == size && digest(target) == sha) {
                base += size; received = base; continue
            }
            val part = File(dir, "$name.part")
            if (part.length() >= size) part.delete()
            var failure: IOException? = null
            for (attempt in 0 until 5) {
                try {
                    transfer(URL(BASE + name), part, size, base, deadline)
                    failure = null; break
                } catch (e: IOException) {
                    failure = e
                    if (SystemClock.elapsedRealtime() >= deadline) break
                    Thread.sleep((attempt + 1) * 1000L)
                }
            }
            failure?.let { throw it }
            if (part.length() != size || digest(part) != sha) {
                part.delete(); throw IOException("model_integrity_failed")
            }
            if (!part.renameTo(target)) throw IOException("model_install_failed")
            base += size; received = base
        }
    }

    private fun transfer(initial: URL, part: File, size: Long, base: Long, deadline: Long) {
        var url = initial
        repeat(5) {
            require(url.protocol == "https" && url.userInfo == null) { "https_required" }
            val connection = url.openConnection() as HttpURLConnection
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 15_000; connection.readTimeout = 30_000
            val offset = part.length()
            if (offset > 0) connection.setRequestProperty("Range", "bytes=$offset-")
            try {
                val code = connection.responseCode
                if (code in listOf(301, 302, 303, 307, 308)) {
                    val location = connection.getHeaderField("Location") ?: throw IOException("redirect_missing")
                    url = URL(url, location)
                    return@repeat
                }
                if (code != 200 && code != 206) throw IOException("download_http_$code")
                val append = code == 206
                if (append && connection.getHeaderField("Content-Range")?.startsWith("bytes $offset-") != true)
                    throw IOException("invalid_range")
                var count = if (append) offset else 0L
                FileOutputStream(part, append).use { out -> connection.inputStream.use { input ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        if (SystemClock.elapsedRealtime() >= deadline) throw IOException("download_timeout")
                        val n = input.read(buffer)
                        if (n < 0) break
                        if (count + n > size) throw IOException("download_too_large")
                        out.write(buffer, 0, n); count += n; received = base + count
                    }
                } }
                if (count != size) throw IOException("download_incomplete")
                return
            } finally { connection.disconnect() }
        }
        throw IOException("too_many_redirects")
    }

    private fun digest(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(256 * 1024)
            while (true) { val n = input.read(buffer); if (n < 0) break; digest.update(buffer, 0, n) }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }
}
