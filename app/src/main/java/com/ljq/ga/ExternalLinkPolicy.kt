package com.ljq.ga

/** Schemes which must never replace the privileged local chat WebView. */
object ExternalLinkPolicy {
    fun canOpen(raw: String): Boolean {
        if (raw.any { it.code < 32 }) return false
        val scheme = Regex("^([a-zA-Z][a-zA-Z0-9+.-]*):").find(raw)?.groupValues?.get(1)?.lowercase()
            ?: return false
        return scheme !in setOf("file", "content", "javascript", "data", "about", "blob", "chrome", "view-source")
    }
}
