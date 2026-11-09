package com.ljq.ga

import android.content.Context
import android.os.SystemClock
import java.io.File
import org.json.JSONObject

class AssetUnpacker(private val ctx: Context) {

    private data class AssetCopyStat(val enc: Int = 0, val plain: Int = 0) {
        operator fun plus(o: AssetCopyStat) = AssetCopyStat(enc + o.enc, plain + o.plain)
    }

    // ---------- assets解压: 版本变更才覆盖, 保留memory/temp/mykey; 覆盖前备份本地自演化改动(issue#1) ----------
    fun extractAssets() {
        val gaDir = File(ctx.filesDir, "ga")
        val stamp = File(gaDir, ".ver")
        val ver = ctx.packageManager.getPackageInfo(ctx.packageName, 0).let { "${it.versionName}-${it.lastUpdateTime}" }
        val oldVer = stamp.takeIf { it.exists() }?.readText()
        if (oldVer == ver) return
        val t0 = SystemClock.elapsedRealtime()
        try {
            // 演化安全: 覆盖工作区为官方版前, 把 ours≠baseline 的本地自演化改动连同 {base,ours} 备份成 zip。
            // 失败半径小(备份失败不应阻断更新): 记埋点后继续覆盖, 保证永远能落地干净官方版。
            var evoBak = 0
            runCatching { evoBak = Evolution.backupDivergent(ctx, gaDir, oldVer ?: "?", ver) }
                .onFailure { Analytics.track("{\"event\":\"evo_backup_fail\",\"props\":{\"msg\":${JSONObject.quote(it.message ?: it.javaClass.simpleName)}}}") }
            // UI 资源允许整目录刷新；避免旧 filesDir/webui 中 index.html 等残留导致 APK 内新版未生效。
            File(gaDir, "webui").deleteRecursively()
            val stat = copyAssetDir("ga_runtime", gaDir)
            // 官方删除传播: APK 已移除的文件(如 v2.16 删 weixin_native)从存量设备同步清掉。
            // 必须先 prune 再 refreshBaseline: prune 以旧 baseline 为"曾是官方文件"的证据。
            var pruned = 0
            runCatching { pruned = Evolution.pruneRemoved(ctx, gaDir) }
                .onFailure { Analytics.track("{\"event\":\"evo_prune_fail\",\"props\":{\"msg\":${JSONObject.quote(it.message ?: it.javaClass.simpleName)}}}") }
            stamp.writeText(ver)
            runCatching { Evolution.refreshBaseline(ctx, gaDir) }   // baseline ← 本次官方版(供下次更新做 base)
                .onFailure { Analytics.track("{\"event\":\"evo_baseline_fail\",\"props\":{\"msg\":${JSONObject.quote(it.message ?: it.javaClass.simpleName)}}}") }
            val ms = SystemClock.elapsedRealtime() - t0
            Analytics.track("{\"event\":\"assets_extract_ok\",\"props\":{\"enc\":${stat.enc},\"plain\":${stat.plain},\"evoBak\":$evoBak,\"pruned\":$pruned,\"ms\":$ms}}")
        } catch (e: Exception) {
            Analytics.track("{\"event\":\"assets_extract_fail\",\"props\":{\"stage\":\"copy\",\"msg\":${JSONObject.quote(e.message ?: e.javaClass.simpleName)}}}")
            throw e
        }
    }

    private fun copyAssetDir(path: String, dst: File): AssetCopyStat {
        val items = ctx.assets.list(path) ?: return AssetCopyStat()
        if (items.isEmpty()) {
            dst.parentFile?.mkdirs()
            val blob = ctx.assets.open(path).use { it.readBytes() }
            if (path.startsWith("ga_runtime/memory/")) {
                val rel = path.removePrefix("ga_runtime/")
                val baseline = File(ctx.filesDir, "ga/.evolution/baseline/$rel")
                return AssetCopyStat(plain = if (MemoryDefaults.install(dst, baseline, blob)) 1 else 0)
            }
            dst.writeBytes(blob)
            return AssetCopyStat(plain = 1)
        }
        var stat = AssetCopyStat()
        items.forEach { stat += copyAssetDir("$path/$it", File(dst, it)) }
        return stat
    }

}
