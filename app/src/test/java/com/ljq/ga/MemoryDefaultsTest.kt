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
        val baseline = File(folder.root, "baseline.md")
        assertTrue(MemoryDefaults.install(target, baseline, "old".toByteArray()))
        baseline.writeText("old")
        assertTrue(MemoryDefaults.install(target, baseline, "new".toByteArray()))
        assertEquals("new", target.readText())
    }

    @Test fun userEditsSurviveConsecutiveUpgrades() {
        val target = folder.newFile("guide.md").apply { writeText("my notes") }
        val baseline = folder.newFile("baseline.md").apply { writeText("old") }
        assertFalse(MemoryDefaults.install(target, baseline, "new".toByteArray()))
        baseline.writeText("new")
        assertFalse(MemoryDefaults.install(target, baseline, "next".toByteArray()))
        assertEquals("my notes", target.readText())
    }

    @Test fun existingMemoryWithoutAnOwnedBaselineIsPreserved() {
        val target = folder.newFile("guide.md").apply { writeText("existing") }
        assertFalse(MemoryDefaults.install(target, File(folder.root, "missing"), "new".toByteArray()))
        assertEquals("existing", target.readText())
    }
}
