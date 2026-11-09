package com.ljq.ga

import org.junit.Assert.*
import org.junit.Test

class WindowNodePolicyTest {
    @Test fun unknownWindowIsDeniedEvenAfterAnotherAppEvent() {
        val p = WindowNodePolicy()
        p.observe(1, "com.android.settings")
        assertTrue(p.allows(1))
        assertFalse(p.allows(2))
        assertFalse(p.allows(null))
    }
    @Test fun protectedAndMissingIdentitiesAreDenied() {
        val p = WindowNodePolicy()
        for (pkg in listOf("com.tencent.mm", "", null)) {
            p.observe(1, pkg)
            assertFalse(p.allows(1))
        }
    }
    @Test fun removedWindowPermissionCannotBeReused() {
        val p = WindowNodePolicy()
        p.observe(7, "com.android.settings")
        p.retain(emptySet())
        assertFalse(p.allows(7))
        p.observe(7, "com.tencent.mm")
        assertFalse(p.allows(7))
    }
}
