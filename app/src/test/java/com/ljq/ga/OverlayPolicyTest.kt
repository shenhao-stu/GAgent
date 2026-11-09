package com.ljq.ga

import org.junit.Assert.*
import org.junit.Test

class OverlayPolicyTest {
    @Test fun backgroundOverlayDependsOnlyOnPermissionForegroundAndTaskState() {
        for (permission in listOf(false, true)) for (foreground in listOf(false, true)) {
            for (busy in listOf(false, true)) for (always in listOf(false, true)) {
                val expected = permission && !foreground && (busy || always)
                assertEquals(expected, needsBackgroundOverlay(permission, foreground, busy, always))
            }
        }
    }

    @Test fun rotationFoldAndFreeDragCannotLeaveTheHandleOutsideTheScreen() {
        for ((sw, sh) in listOf(320 to 480, 1080 to 2424, 2424 to 1080, 1840 to 2208)) {
            for ((x, y) in listOf(-80 to -90, 2200 to 2300, 800 to 1200)) {
                for (dock in listOf(true, false)) {
                    val (nextX, nextY) = overlayPosition(x, y, 90, 144, sw, sh, dock)
                    assertTrue(nextX >= 0 && nextX + 90 <= sw)
                    assertTrue(nextY >= 0 && nextY + 144 <= sh)
                    if (dock) assertTrue(nextX == 0 || nextX == sw - 90)
                }
            }
        }
    }
}
