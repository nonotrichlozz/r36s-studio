// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

import java.io.IOException

/** Quelqu'un a tenté d'écrire sur une carte ouverte pour être seulement lue. */
class ReadOnlyViolation : IOException("Écriture refusée : la carte est ouverte en lecture seule")

/**
 * L'explorateur de fichiers ne passe que par ce habillage : aucune commande
 * d'écriture n'atteint la carte, quoi qu'il arrive dans le code qui l'utilise.
 * `flush` ne fait rien (rien n'a été écrit, il n'y a rien à vider).
 */
class ReadOnlyBlockDevice(private val inner: BlockDevice) : BlockDevice {
    override val blockSize: Int get() = inner.blockSize
    override val blockCount: Long get() = inner.blockCount

    override fun read(lba: Long, buffer: ByteArray, blocks: Int) = inner.read(lba, buffer, blocks)

    override fun write(lba: Long, buffer: ByteArray, blocks: Int) {
        throw ReadOnlyViolation()
    }

    override fun flush() = Unit
}
