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

android {
    namespace = "io.github.nonotrichlozz.r36sstudio"
    compileSdk = 35

    defaultConfig {
        applicationId = "io.github.nonotrichlozz.r36sstudio"
        minSdk = 28
        targetSdk = 35
        versionCode = appVersionCode
        versionName = appVersion
    }

    buildTypes {
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
