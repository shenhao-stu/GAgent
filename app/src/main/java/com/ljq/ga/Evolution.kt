package com.ljq.ga

import android.content.Context
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import org.json.JSONObject

// 演化安全(issue#1) 原生机制层: 热更新覆盖工作区前, 把本地自演化改动备份成 zip; 覆盖后刷新 baseline。
//   三路模型: base = .evolution/baseline(上次官方版) · ours = 工作区(被自演化改过) · theirs = 本次新官方版(asset)。
//   策略(逐文件 3-way 合并/冲突决议)在 Python evolution.py, 由「演化融合」按钮触发 —— 机制/策略边界清晰。
//   仅跟踪"可自演化的文本文件"(与 evolution.is_tracked 一致): 排除 models/、webui/vendor/、*.min.js。
//   首次安装(无 baseline)只建基线不备份, 避免把整树当本地改动产生噪声; 保护从下次官方更新起生效。
object Evolution {
    fun isTrackedText(rel: String): Boolean {
        val r = rel.replace('\\', '/').trimStart('/')
        if (r.startsWith(".evolution/") || r.startsWith("models/") || r.startsWith("webui/vendor/")) return false
        if (r.endsWith(".min.js")) return false
        return r.endsWith(".py") || r.endsWith(".md") || r.endsWith(".txt") || r.endsWith(".json") ||
               r.endsWith(".js") || r.endsWith(".css") || r.endsWith(".html")
    }

    // 递归列出 asset 树里的跟踪文本文件(rel 相对 ga_runtime 根); 空 list = 文件(与 copyAssetDir 约定一致)。
    private fun listAssetTracked(ctx: Context, path: String, rel: String, out: MutableSet<String>) {
        val items = ctx.assets.list(path) ?: return
        if (items.isEmpty()) { if (isTrackedText(rel)) out.add(rel); return }
        for (it in items) listAssetTracked(ctx, "$path/$it", if (rel.isEmpty()) it else "$rel/$it", out)
    }

    private fun baselineDir(gaDir: File) = File(gaDir, ".evolution/baseline")

    // 覆盖前: ours(工作区) 与 base(baseline) 不同的跟踪文件 → 连同 {base,ours} 打包 zip。返回备份文件数。
    fun backupDivergent(ctx: Context, gaDir: File, oldVer: String, newVer: String): Int {
        val base = baselineDir(gaDir)
        if (!base.isDirectory) return 0                              // 首次: 无基线不备份(仅 refreshBaseline 建基线)
        val rels = LinkedHashSet<String>()
        listAssetTracked(ctx, "ga_runtime", "", rels)             // theirs 路径集
        if (base.isDirectory) base.walkTopDown().filter { it.isFile }
            .forEach { rels.add(it.relativeTo(base).path.replace('\\', '/')) }   // ∪ baseline-only(官方删除但本地改过)
        val dir = File(gaDir, ".evolution/backups").apply { mkdirs() }
        val zip = File(dir, "pre-${sanitize(oldVer)}-${System.currentTimeMillis()}.zip")
        var count = 0
        ZipOutputStream(zip.outputStream().buffered()).use { zos ->
            for (rel in rels) {
                val ours = File(gaDir, rel); if (!ours.isFile) continue
                val baseF = File(base, rel)
                val baseBytes = if (baseF.isFile) baseF.readBytes() else ByteArray(0)
                val oursBytes = ours.readBytes()
                if (!oursBytes.contentEquals(baseBytes)) {
                    put(zos, "base/$rel", baseBytes); put(zos, "ours/$rel", oursBytes); count++
                }
            }
            val meta = JSONObject().put("oldVer", oldVer).put("newVer", newVer)
                .put("ts", System.currentTimeMillis() / 1000).put("count", count)
            put(zos, "meta.json", meta.toString().toByteArray(Charsets.UTF_8))
        }
        if (count == 0) zip.delete()                          // 无本地改动 → 不留空备份
        return count
    }

    // 官方删除传播(须在 refreshBaseline 前调): baseline 有(上次官方版) ∧ 新 assets 无(本次官方已删)
    //   ∧ ours==baseline(未被本地自演化) → 删工作区文件。删除域 ⊆ baseline: 运行时生成物
    //   (channels/mykey/memory用户数据/temp)不在 baseline 永不误删; 本地改过的官方弃件保留(backupDivergent 已兜底)。
    fun pruneRemoved(ctx: Context, gaDir: File): Int {
        val base = baselineDir(gaDir)
        if (!base.isDirectory) return 0                       // 首装无基线: 无历史官方文件可清
        val theirs = LinkedHashSet<String>()
        listAssetTracked(ctx, "ga_runtime", "", theirs)
        var n = 0
        for (bf in base.walkTopDown().filter { it.isFile }) {
            val rel = bf.relativeTo(base).path.replace('\\', '/')
            if (rel in theirs) continue
            val ours = File(gaDir, rel)
            if (ours.isFile && ours.readBytes().contentEquals(bf.readBytes()) && ours.delete()) n++
        }
        return n
    }

    // 覆盖后: baseline ← 本次官方版(工作区里已解压的跟踪文件), 供下次更新做 base。
    fun refreshBaseline(ctx: Context, gaDir: File) {
        val base = baselineDir(gaDir)
        base.deleteRecursively(); base.mkdirs()
        val rels = LinkedHashSet<String>()
        listAssetTracked(ctx, "ga_runtime", "", rels)
        for (rel in rels) {
            val src = File(gaDir, rel); if (!src.isFile) continue
            val dst = File(base, rel); dst.parentFile?.mkdirs(); src.copyTo(dst, overwrite = true)
        }
    }

    private fun put(zos: ZipOutputStream, name: String, bytes: ByteArray) {
        zos.putNextEntry(ZipEntry(name)); zos.write(bytes); zos.closeEntry()
    }
    private fun sanitize(s: String) = s.replace(Regex("[^A-Za-z0-9._-]"), "_").take(40)
}
