package com.example.smsusbforwarder

import com.example.smsusbforwarder.usb.*
import org.junit.Assert.assertEquals
import org.junit.Test

class FrameCodecTest {
    @Test fun handlesFragmentationAndCoalescing() { val a = FrameCodec.encode("{\"a\":1}"); val b = FrameCodec.encode("{\"b\":2}"); val all = a + b; val decoder = FrameDecoder(); assertEquals(emptyList<String>(), decoder.feed(all.copyOfRange(0, 3))); assertEquals(listOf("{\"a\":1}", "{\"b\":2}"), decoder.feed(all.copyOfRange(3, all.size))) }
    @Test(expected = IllegalArgumentException::class) fun rejectsOversize() { FrameCodec.encode("x".repeat(8193)) }
}
