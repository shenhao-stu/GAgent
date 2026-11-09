package com.ljq.ga

internal fun needsBackgroundOverlay(permission: Boolean, foreground: Boolean,
                                    busy: Boolean, always: Boolean): Boolean =
    permission && !foreground && (busy || always)

internal fun overlayPosition(x: Int, y: Int, width: Int, height: Int,
                             screenWidth: Int, screenHeight: Int, dock: Boolean): Pair<Int, Int> {
    val maxX = (screenWidth - width).coerceAtLeast(0)
    val maxY = (screenHeight - height).coerceAtLeast(0)
    val nextX = if (dock) { if (x + width / 2 < screenWidth / 2) 0 else maxX } else x.coerceIn(0, maxX)
    return nextX to y.coerceIn(0, maxY)
}
