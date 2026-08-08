package com.example.smsusbforwarder.domain.rules

import com.example.smsusbforwarder.domain.model.*

object CodeExtractor {
    private val hints = Regex("验证码|校验码|动态码|OTP", RegexOption.IGNORE_CASE)
    fun extract(sender: String, text: String, rules: ExtractRules): ExtractionResult {
        if (rules.allowedSenders.isNotEmpty() && rules.allowedSenders.none { sender.contains(it, true) }) return ExtractionResult.Rejected("sender_not_allowed")
        if (rules.requiredKeywords.any { !text.contains(it, true) }) return ExtractionResult.Rejected("required_keyword_missing")
        val candidateRegex = try { if (rules.allowAlphanumeric) Regex(rules.regex) else Regex("(?<!\\d)\\d{${rules.codeLength}}(?!\\d)") } catch (_: IllegalArgumentException) { return ExtractionResult.Rejected("invalid_regex") }
        val matches = candidateRegex.findAll(text).filter { rules.allowAlphanumeric || it.value.all(Char::isDigit) }.toList()
        if (matches.isEmpty()) return ExtractionResult.Rejected("no_candidate")
        val hintRanges = hints.findAll(text).map { it.range }.toList()
        val scored = matches.map { match -> match.value to (hintRanges.minOfOrNull { range -> when { match.range.last < range.first -> range.first - match.range.last; match.range.first > range.last -> match.range.first - range.last; else -> 0 } } ?: Int.MAX_VALUE) }
        val best = scored.filter { it.second == scored.minOf { pair -> pair.second } }.map { it.first }.distinct()
        return if (best.size == 1 && (hintRanges.isNotEmpty() || matches.map { it.value }.distinct().size == 1)) ExtractionResult.Success(best.single()) else ExtractionResult.Rejected("ambiguous_candidates")
    }
}
