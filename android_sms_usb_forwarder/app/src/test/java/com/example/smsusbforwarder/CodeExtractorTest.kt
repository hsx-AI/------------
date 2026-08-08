package com.example.smsusbforwarder

import com.example.smsusbforwarder.domain.model.*
import com.example.smsusbforwarder.domain.rules.CodeExtractor
import org.junit.Assert.*
import org.junit.Test

class CodeExtractorTest {
    @Test fun extractsCodeNearHint() { assertEquals(ExtractionResult.Success("583921"), CodeExtractor.extract("1069", "订单 123456789012，验证码 583921，5 分钟有效", ExtractRules(codeLength = 6))) }
    @Test fun rejectsAmbiguousNumbersWithoutHint() { assertTrue(CodeExtractor.extract("1069", "参考 123456 或 654321", ExtractRules(codeLength = 6)) is ExtractionResult.Rejected) }
    @Test fun obeysSenderAndKeyword() { assertTrue(CodeExtractor.extract("other", "验证码 583921", ExtractRules(listOf("1069"), listOf("验证码"), codeLength = 6)) is ExtractionResult.Rejected) }
}
