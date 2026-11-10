// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

/**
 * Garde-fou (CLAUDE.md §4). Sur Android, l'appli ne peut atteindre que ce qui
 * est branché sur la prise USB du téléphone : la mémoire du téléphone et sa
 * carte interne sont hors de portée par construction. Restent les règles de
 * taille : une carte de taille nulle/inconnue ou un gros disque sont refusés.
 */
object Safety {
    const val DEFAULT_MAX_BYTES: Long = 1024L * 1024 * 1024 * 1024 // 1 To

    enum class Rejection { SIZE_UNKNOWN, TOO_LARGE }

    fun rejection(sizeBytes: Long, maxBytes: Long = DEFAULT_MAX_BYTES): Rejection? = when {
        sizeBytes <= 0 -> Rejection.SIZE_UNKNOWN
        sizeBytes > maxBytes -> Rejection.TOO_LARGE
        else -> null
    }
}
