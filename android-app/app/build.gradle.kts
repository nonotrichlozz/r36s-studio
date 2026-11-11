// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// Une seule source pour la version (CLAUDE.md §5) : APP_VERSION de
// r36s_studio/__init__.py, relue ici plutôt que recopiée.
val appVersion: String = run {
    val init = rootProject.file("../r36s_studio/__init__.py")
    val match = if (init.isFile) Regex("APP_VERSION\\s*=\\s*\"([^\"]+)\"").find(init.readText()) else null
    match?.groupValues?.get(1) ?: "0.0.0"
}
val appVersionCode: Int = run {
    val parts = appVersion.split(".").map { it.toIntOrNull() ?: 0 }
    val major = parts.getOrElse(0) { 0 }
    val minor = parts.getOrElse(1) { 0 }
    val patch = parts.getOrElse(2) { 0 }
    maxOf(1, major * 1_000_000 + minor * 1_000 + patch)
}

// Construit par GitHub Actions : numéro croissant à chaque construction, pour
// que la mise à jour automatique sache laquelle est la plus récente.
val buildVersionCode: Int = System.getenv("GITHUB_RUN_NUMBER")?.toIntOrNull()?.let { 100_000 + it } ?: appVersionCode

// Clé de signature stable (secret GitHub ANDROID_KEYSTORE_BASE64, jamais dans
// le dépôt) : sans elle, chaque construction est signée différemment et ne
// peut pas remplacer la précédente. Le mot de passe n'est pas un secret :
// c'est le fichier de clé qui l'est.
val stableKeystore: String? = System.getenv("ANDROID_KEYSTORE_FILE")?.takeIf { it.isNotBlank() }

android {
    namespace = "io.github.nonotrichlozz.r36sstudio"
    compileSdk = 35

    signingConfigs {
        if (stableKeystore != null) {
            create("stable") {
                storeFile = file(stableKeystore)
                storePassword = "r36sstudio"
                keyAlias = "r36sstudio"
                keyPassword = "r36sstudio"
            }
        }
    }

    defaultConfig {
        applicationId = "io.github.nonotrichlozz.r36sstudio"
        minSdk = 28
        targetSdk = 35
        versionCode = buildVersionCode
        versionName = appVersion
        // Affiché sous le titre : savoir quelle construction tourne pendant les essais.
        buildConfigField("String", "BUILD_ID", "\"" + (System.getenv("GITHUB_SHA") ?: "local").take(7) + "\"")
    }

    buildTypes {
        debug {
            if (stableKeystore != null) signingConfig = signingConfigs.getByName("stable")
        }
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.04.00"))
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    // XZ for Java (0BSD / domaine public) : décompression .img.xz en flux.
    implementation("org.tukaani:xz:1.10")

    testImplementation("junit:junit:4.13.2")
}
