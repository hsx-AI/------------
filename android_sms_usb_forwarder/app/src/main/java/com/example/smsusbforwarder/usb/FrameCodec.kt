package com.example.smsusbforwarder.usb

import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.charset.CodingErrorAction

object FrameCodec {
    const val MAX_PAYLOAD = 8192
    fun encode(json: String): ByteArray { val payload = json.toByteArray(Charsets.UTF_8); require(payload.isNotEmpty() && payload.size <= MAX_PAYLOAD); return ByteBuffer.allocate(4 + payload.size).order(ByteOrder.BIG_ENDIAN).putInt(payload.size).put(payload).array() }
}
class FrameDecoder {
    private var buffer = ByteArray(0)
    fun feed(chunk: ByteArray, count: Int = chunk.size): List<String> {
        require(count in 0..chunk.size); buffer += chunk.copyOf(count); val frames = mutableListOf<String>()
        while (buffer.size >= 4) { val length = ByteBuffer.wrap(buffer, 0, 4).order(ByteOrder.BIG_ENDIAN).int; require(length in 1..FrameCodec.MAX_PAYLOAD); if (buffer.size < 4 + length) break; val decoder = Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT); frames += decoder.decode(ByteBuffer.wrap(buffer, 4, length)).toString(); buffer = buffer.copyOfRange(4 + length, buffer.size) }
        return frames
    }
}
