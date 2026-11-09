package com.ljq.ga

import java.nio.ByteBuffer
import java.nio.ByteOrder

internal object PcmWav {
    const val MAX_BYTES = 16000 * 60 * 2 + 65536

    fun samples(bytes: ByteArray): FloatArray {
        require(bytes.size in 44..MAX_BYTES) { "wav_size" }
        require(String(bytes, 0, 4) == "RIFF" && String(bytes, 8, 4) == "WAVE") { "wav_header" }
        val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        var validFormat = false
        var offset = 12
        while (offset <= bytes.size - 8) {
            val size = buffer.getInt(offset + 4)
            require(size >= 0 && size <= bytes.size - offset - 8) { "wav_chunk" }
            when (String(bytes, offset, 4)) {
                "fmt " -> {
                    require(size >= 16) { "wav_format" }
                    require(buffer.getShort(offset + 8).toInt() == 1 &&
                        buffer.getShort(offset + 10).toInt() == 1 &&
                        buffer.getInt(offset + 12) == 16000 &&
                        buffer.getShort(offset + 22).toInt() == 16) { "need_16khz_pcm16_mono" }
                    validFormat = true
                }
                "data" -> {
                    require(validFormat && size % 2 == 0 && size <= 16000 * 60 * 2) { "wav_audio" }
                    return FloatArray(size / 2) { buffer.getShort(offset + 8 + it * 2) / 32768f }
                }
            }
            offset += 8 + size + (size and 1)
        }
        error("wav_no_audio")
    }
}
