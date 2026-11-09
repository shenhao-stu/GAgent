package com.ljq.ga

import android.content.ContentValues
import android.content.Intent
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import android.speech.tts.TextToSpeech
import androidx.core.content.FileProvider
import java.io.File
import java.util.Locale

class MediaBridge(private val activity: MainActivity) {
    // 原生朗读: 优先于 WebView speechSynthesis(后者在多数 WebView 无可用引擎 → "当前设备无法朗读")
    fun speak(text: String, lang: String): String {
        val e = activity.tts ?: return "no-tts"
        if (activity.ttsFailed) return "no-tts"           // 无引擎 → JS 立即回退
        if (!activity.ttsReady) return "init"             // 仍在初始化 → 本次回退, 下次即就绪
        return try {
            activity.runOnUiThread {
                try {                            // shutdown 竞态: onDestroy 关闭后异步 lambda 才跑, 包住防 IllegalStateException
                    e.language = if (lang == "en") Locale.US else Locale.CHINESE
                    e.speak(text, TextToSpeech.QUEUE_FLUSH, null, "ga")
                } catch (ex: Exception) {}
            }
            "ok"
        } catch (ex: Exception) { "err" }
    }
    fun speakStop(): String { activity.runOnUiThread { runCatching { activity.tts?.stop() } }; return "ok" }   // 朗读键再次点=停止(原生 TTS 无暂停, stop 即可); onStop→gaOnSpeakEnd 复位前端键

    // 分享图: 前端 Canvas 生成 PNG(dataURL) → 存入系统相册 Pictures/GenericAgent。
    // 返回 "ok" / "err:<msg>"。API29+ 用 MediaStore RELATIVE_PATH(无需存储权限); API28- 落 Environment 公共目录(已有 MANAGE_EXTERNAL_STORAGE)。
    fun saveImageToGallery(dataUrl: String): String = runCatching {
        val bytes = decodeDataUrl(dataUrl)
        val name = "GA_${System.currentTimeMillis()}.png"
        if (android.os.Build.VERSION.SDK_INT >= 29) {
            val cv = ContentValues().apply {
                put(MediaStore.Images.Media.DISPLAY_NAME, name)
                put(MediaStore.Images.Media.MIME_TYPE, "image/png")
                put(MediaStore.Images.Media.RELATIVE_PATH, "${Environment.DIRECTORY_PICTURES}/GenericAgent")
                put(MediaStore.Images.Media.IS_PENDING, 1)
            }
            val cr = activity.contentResolver
            val uri = cr.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, cv)
                ?: return "err:insert-null"
            cr.openOutputStream(uri).use { it!!.write(bytes) }
            cv.clear(); cv.put(MediaStore.Images.Media.IS_PENDING, 0); cr.update(uri, cv, null, null)
        } else {
            val dir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES), "GenericAgent").apply { mkdirs() }
            val f = File(dir, name); f.writeBytes(bytes)
            @Suppress("DEPRECATION") activity.sendBroadcast(Intent(Intent.ACTION_MEDIA_SCANNER_SCAN_FILE, Uri.fromFile(f)))   // 让相册扫到
        }
        "ok"
    }.getOrElse { "err:${it.message ?: it.javaClass.simpleName}" }

    // 分享图: 落盘到 cacheDir/share, 经 FileProvider 拉起系统分享面板(ACTION_SEND)转发给微信/QQ 等。
    fun shareImage(dataUrl: String): String = runCatching {
        val bytes = decodeDataUrl(dataUrl)
        val dir = File(activity.cacheDir, "share").apply { mkdirs() }
        dir.listFiles()?.forEach { runCatching { it.delete() } }   // 只留本次: 避免缓存堆积
        val f = File(dir, "GA_${System.currentTimeMillis()}.png").apply { writeBytes(bytes) }
        val uri = FileProvider.getUriForFile(activity, "${activity.packageName}.fileprovider", f)
        val send = Intent(Intent.ACTION_SEND).apply {
            type = "image/png"
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        activity.runOnUiThread {
            runCatching {
                activity.startActivity(Intent.createChooser(send, "分享").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }
        }
        "ok"
    }.getOrElse { "err:${it.message ?: it.javaClass.simpleName}" }

    // data:image/png;base64,xxxx → 原始字节(供分享图存相册/转发)
    private fun decodeDataUrl(dataUrl: String): ByteArray {
        val b64 = dataUrl.substringAfterLast("base64,")
        return android.util.Base64.decode(b64, android.util.Base64.DEFAULT)
    }
}
