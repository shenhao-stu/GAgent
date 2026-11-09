package com.ljq.ga

import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.*
import org.junit.Test

class PcmWavTest {
    private fun wav(): ByteArray = ByteBuffer.allocate(48).order(ByteOrder.LITTLE_ENDIAN).apply {
        put("RIFF".toByteArray()); putInt(40); put("WAVEfmt ".toByteArray()); putInt(16)
        putShort(1); putShort(1); putInt(16000); putInt(32000); putShort(2); putShort(16)
        put("data".toByteArray()); putInt(4); putShort(-32768); putShort(16384)
    }.array()

    @Test fun decodesPcm16WithoutLosingSign() {
        assertArrayEquals(floatArrayOf(-1f, 0.5f), PcmWav.samples(wav()), 0f)
    }

    @Test fun rejectsTruncatedOrOversizedChunksAndUnsupportedAudio() {
        for ((offset, value) in listOf(40 to Int.MAX_VALUE, 16 to -1, 24 to 48000)) {
            val data = wav()
            ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN).putInt(offset, value)
            assertThrows(IllegalArgumentException::class.java) { PcmWav.samples(data) }
        }
        assertThrows(IllegalArgumentException::class.java) { PcmWav.samples(wav().copyOf(47)) }
        assertThrows(IllegalArgumentException::class.java) { PcmWav.samples(ByteArray(PcmWav.MAX_BYTES + 1)) }
    }
}
