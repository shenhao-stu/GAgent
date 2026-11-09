package com.ljq.ga

import java.util.concurrent.ConcurrentHashMap

/** Node-read permission keyed by a live window id, never a cached foreground identity. */
internal class WindowNodePolicy {
    private val allowed = ConcurrentHashMap<Int, Boolean>()
    fun observe(id: Int, pkg: String?) {
        allowed[id] = !pkg.isNullOrBlank() && pkg != "com.tencent.mm"
    }
    fun retain(ids: Set<Int>) { allowed.keys.retainAll(ids) }
    fun allows(id: Int?): Boolean = id != null && allowed[id] == true
}
