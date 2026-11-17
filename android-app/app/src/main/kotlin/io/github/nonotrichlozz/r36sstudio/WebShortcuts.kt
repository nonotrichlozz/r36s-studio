// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/** Un raccourci vers une page web, choisi par l'utilisateur. */
data class WebShortcut(val name: String, val url: String)

/**
 * Raccourcis web personnels (pendant de la tuile « Web » de la version
 * ordinateur, `config.py::personal_web_url`). Rangés uniquement dans les
 * préférences privées de l'appli sur CE téléphone : jamais dans le code, jamais
 * dans un fichier partagé. Liste vide par défaut, donc rien n'apparaît chez un
 * client. Seules les adresses https sont acceptées.
 */
object WebShortcuts {
    private const val PREFS = "web_shortcuts"
    private const val KEY = "list"
    const val MAX = 12

    fun load(context: Context): List<WebShortcut> = try {
        val raw = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, null) ?: return emptyList()
        val array = JSONArray(raw)
        (0 until array.length()).mapNotNull { i ->
            val o = array.optJSONObject(i) ?: return@mapNotNull null
            val url = o.optString("url")
            if (isSafeUrl(url)) WebShortcut(o.optString("name").ifBlank { url }, url) else null
        }
    } catch (e: Exception) {
        emptyList()
    }

    fun save(context: Context, list: List<WebShortcut>) {
        val array = JSONArray()
        for (s in list) array.put(JSONObject().put("name", s.name).put("url", s.url))
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY, array.toString()).apply()
    }

    /** https seulement, comme la version ordinateur : jamais d'adresse non sécurisée ni d'autre schéma. */
    fun isSafeUrl(url: String): Boolean {
        if (!url.startsWith("https://")) return false
        return try {
            val uri = java.net.URI(url)
            uri.scheme == "https" && !uri.host.isNullOrBlank()
        } catch (e: Exception) {
            false
        }
    }

    /** Adresse tapée sans « https:// » : on l'ajoute ; « http:// » est refusé. */
    fun normalize(typed: String): String {
        val t = typed.trim()
        if (t.startsWith("https://") || t.startsWith("http://")) return t
        return "https://$t"
    }
}
