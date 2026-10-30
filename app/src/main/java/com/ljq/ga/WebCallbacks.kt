package com.ljq.ga

import android.webkit.WebView
import org.json.JSONObject

class WebCallbacks(
    private val web: WebView,
    private val runOnUi: (() -> Unit) -> Unit,
) {
    fun raw(js: String) = runOnUi { web.evaluateJavascript(js, null) }

    fun planNeedNetworkToast() = runCatching {
        web.evaluateJavascript(
            "window.toast&&toast(" + JSONObject.quote("需要网络打开订阅页") + ")", null
        )
    }

    fun floatPermGuideAlwaysOn(onResult: (String?) -> Unit) = runOnUi {
        runCatching {
            web.evaluateJavascript("window.gaFloatPermGuide?(gaFloatPermGuide('always_on'),1):0") { r -> onResult(r) }
        }
    }

    fun floatPermGuideButton(onResult: (String?) -> Unit, onEvalFailure: () -> Unit) {
        runCatching {
            web.evaluateJavascript("window.gaFloatPermGuide?(gaFloatPermGuide('button'),1):0") { r -> onResult(r) }
        }.onFailure { onEvalFailure() }
    }

    fun cameraResult(path: String?) = runOnUi {
        val arg = if (path != null) JSONObject.quote(path) else "''"
        web.evaluateJavascript("window.gaCameraResult&&window.gaCameraResult($arg)", null)
    }

    /** PCLink 扫码结果: text 为二维码原文; null/空 = 取消或失败。 */
    fun qrResult(text: String?) = runOnUi {
        val arg = if (!text.isNullOrBlank()) JSONObject.quote(text) else "''"
        web.evaluateJavascript("window.gaQrResult&&window.gaQrResult($arg)", null)
    }

    fun onBack(onResult: (String?) -> Unit) {
        web.evaluateJavascript("window.gaOnBack?window.gaOnBack():false") { r -> onResult(r) }
    }

    fun onSpeakEnd() = runOnUi { runCatching { web.evaluateJavascript("window.gaOnSpeakEnd&&gaOnSpeakEnd()", null) } }

    fun showLoginOverlay() = runCatching {
        web.evaluateJavascript("window.showLoginOverlay&&showLoginOverlay(function(){})", null)
    }

    fun onFloatAlways(on: Boolean) = runCatching {
        web.evaluateJavascript("window.gaOnFloatAlways&&gaOnFloatAlways($on)", null)
    }

    fun onResumeSync() = runCatching { web.evaluateJavascript("window.gaOnResume&&gaOnResume()", null) }

    fun onA11y(on: Boolean) = runCatching { web.evaluateJavascript("window.gaOnA11y&&gaOnA11y($on)", null) }

    fun onAdb() = runCatching { web.evaluateJavascript("window.gaOnAdb&&gaOnAdb()", null) }

    // Shizuku 授权结果回推: 用户刚在系统对话框里决定, 前端重读 shizukuStatus 刷新设置行/红点。
    fun onShizuku() = runCatching { web.evaluateJavascript("window.gaOnShizuku&&gaOnShizuku()", null) }
}
