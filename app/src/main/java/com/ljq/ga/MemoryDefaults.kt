package com.ljq.ga

import java.io.File

internal object MemoryDefaults {
    fun install(target: File, baseline: File, packaged: ByteArray): Boolean {
        if (target.exists() && (!baseline.isFile ||
                    !target.readBytes().contentEquals(baseline.readBytes()))) return false
        target.parentFile?.mkdirs()
        target.writeBytes(packaged)
        return true
    }
}
