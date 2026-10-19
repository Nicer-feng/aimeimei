package asia.feng.aimeimei

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf

internal val LocalAppMotion = staticCompositionLocalOf { true }

class AppPreferences(context: Context) {
    private val store = context.getSharedPreferences("appearance", Context.MODE_PRIVATE)
    var theme by mutableStateOf(store.getString("theme", "system") ?: "system"); private set
    var font by mutableStateOf(store.getString("font", "normal") ?: "normal"); private set
    var motion by mutableStateOf(store.getBoolean("motion", true)); private set
    val fontScale get() = when (font) { "small" -> .9f; "large" -> 1.15f; else -> 1f }
    fun changeTheme(value: String) { theme = value; store.edit().putString("theme", value).apply() }
    fun changeFont(value: String) { font = value; store.edit().putString("font", value).apply() }
    fun changeMotion(value: Boolean) { motion = value; store.edit().putBoolean("motion", value).apply() }
}
