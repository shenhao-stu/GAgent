package com.ljq.ga

import org.junit.Assert.*
import org.junit.Test

class ExternalLinkPolicyTest {
    @Test fun appLinksAndStandardLinksCanLeaveTheChat() {
        for (url in listOf("https://example.test", "mailto:hello@example.test", "tel:123", "customapp://page", "intent://page#Intent;scheme=customapp;end"))
            assertTrue(url, ExternalLinkPolicy.canOpen(url))
    }
    @Test fun localAndExecutableResourcesStayBlocked() {
        for (url in listOf("file:///private/file", "content://settings", "javascript:alert(1)", "data:text/html,hello", "about:blank", "blob:https://example.test/id", "/relative", "https://example.test\n"))
            assertFalse(url, ExternalLinkPolicy.canOpen(url))
    }
}
