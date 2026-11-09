package com.ljq.ga

import java.io.File
import java.security.MessageDigest

internal object MemoryDefaults {
    fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes).joinToString("") { "%02x".format(it) }

    fun knownHashes(baseline: File, legacy: Map<String, String>, fromAssets: Boolean): Map<String, String> {
        // Older releases snapshotted live memory, which could already contain user edits.
        if (!fromAssets) return legacy
        val memory = File(baseline, "memory")
        return memory.walkTopDown().filter { it.isFile }.associate {
            it.relativeTo(baseline).invariantSeparatorsPath to sha256(it.readBytes())
        }
    }

    fun matches(target: File, expectedHash: String?): Boolean =
        expectedHash != null && target.isFile && sha256(target.readBytes()) == expectedHash

    fun install(target: File, expectedHash: String?, packaged: ByteArray): Boolean {
        if (target.exists() && !matches(target, expectedHash)) return false
        target.parentFile?.mkdirs()
        target.writeBytes(packaged)
        return true
    }

    fun remove(target: File, expectedHash: String?): Boolean = matches(target, expectedHash) && target.delete()
}
