package com.ljq.ga

import java.io.File
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class MemoryDefaultsTest {
    @get:Rule val folder = TemporaryFolder()

    @Test fun freshAndUnchangedDefaultsReceiveTheNewVersion() {
        val target = File(folder.root, "memory/guide.md")
        assertTrue(MemoryDefaults.install(target, null, "old".toByteArray()))
        assertTrue(MemoryDefaults.install(target, hash("old"), "new".toByteArray()))
        assertEquals("new", target.readText())
    }

    @Test fun userEditsSurviveConsecutiveUpgrades() {
        val target = folder.newFile("guide.md").apply { writeText("my notes") }
        assertFalse(MemoryDefaults.install(target, hash("old"), "new".toByteArray()))
        assertFalse(MemoryDefaults.install(target, hash("new"), "next".toByteArray()))
        assertEquals("my notes", target.readText())
    }

    @Test fun existingMemoryWithoutAnOwnedBaselineIsPreserved() {
        val target = folder.newFile("guide.md").apply { writeText("existing") }
        assertFalse(MemoryDefaults.install(target, null, "new".toByteArray()))
        assertEquals("existing", target.readText())
    }

    @Test fun legacyBaselineContainingUserEditsIsNotAnOwnershipProof() {
        val target = folder.newFile("guide.md").apply { writeText("my notes") }
        val baseline = folder.newFolder("baseline")
        File(baseline, "memory").mkdirs()
        File(baseline, "memory/guide.md").writeText("my notes")
        val known = MemoryDefaults.knownHashes(baseline, mapOf("memory/guide.md" to hash("old")), false)
        assertFalse(MemoryDefaults.install(target, known["memory/guide.md"], "new".toByteArray()))
        assertFalse(MemoryDefaults.remove(target, known["memory/guide.md"]))
        assertEquals("my notes", target.readText())
    }

    @Test fun packagedBaselineSupportsLaterDefaultsAndSafeRemoval() {
        val baseline = folder.newFolder("baseline")
        File(baseline, "memory").mkdirs()
        File(baseline, "memory/guide.md").writeText("new")
        val known = MemoryDefaults.knownHashes(baseline, mapOf("memory/guide.md" to hash("old")), true)
        val target = folder.newFile("guide.md").apply { writeText("new") }
        assertTrue(MemoryDefaults.remove(target, known["memory/guide.md"]))
        assertFalse(target.exists())
        val unknown = folder.newFile("notes.md").apply { writeText("private notes") }
        assertFalse(MemoryDefaults.remove(unknown, known["memory/notes.md"]))
    }

    private fun hash(value: String) = MemoryDefaults.sha256(value.toByteArray())
}
