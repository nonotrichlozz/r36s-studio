// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

import java.io.IOException

/** Accès brut à une carte, bloc par bloc. Aucun système de fichiers ici. */
interface BlockDevice {
    val blockSize: Int
    val blockCount: Long
    val sizeBytes: Long get() = blockSize.toLong() * blockCount

    /** Lit `blocks` blocs à partir de `lba` dans `buffer` (à partir de l'indice 0). */
    @Throws(IOException::class)
    fun read(lba: Long, buffer: ByteArray, blocks: Int)

    /** Écrit `blocks` blocs à partir de `lba` depuis `buffer` (à partir de l'indice 0). */
    @Throws(IOException::class)
    fun write(lba: Long, buffer: ByteArray, blocks: Int)

    /** Demande à la carte de vider son cache d'écriture. */
    @Throws(IOException::class)
    fun flush()
}

/** Annulation coopérative : consultée entre deux blocs, jamais au milieu d'un. */
class CancelToken {
    @Volatile
    var cancelled: Boolean = false
}

class OperationCancelled : IOException("Opération annulée")
