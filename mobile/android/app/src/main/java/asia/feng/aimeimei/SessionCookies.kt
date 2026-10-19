package asia.feng.aimeimei

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class SessionCookies(context: Context, private val origin: HttpUrl) : CookieJar {
    private val prefs = context.getSharedPreferences("native_session", Context.MODE_PRIVATE)
    private val keyAlias = "aimeimei.session.v1"
    private var session: Cookie? = restore()

    @Synchronized override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
        if (url.host != origin.host || url.scheme != "https") return
        val incoming = cookies.lastOrNull { it.name == "ap_session" } ?: return
        if (incoming.expiresAt <= System.currentTimeMillis() || incoming.value.isEmpty()) { clear(); return }
        session = incoming
        runCatching {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, secretKey())
            val encrypted = cipher.iv + cipher.doFinal(incoming.toString().toByteArray(Charsets.UTF_8))
            prefs.edit().putString("cookie", Base64.encodeToString(encrypted, Base64.NO_WRAP)).apply()
        }.onFailure { prefs.edit().remove("cookie").apply() }
    }

    @Synchronized override fun loadForRequest(url: HttpUrl): List<Cookie> {
        if (url.host != origin.host || url.scheme != "https") return emptyList()
        return session?.takeIf { it.expiresAt > System.currentTimeMillis() && it.matches(url) }?.let(::listOf) ?: emptyList()
    }
    @Synchronized fun clear() { session = null;prefs.edit().remove("cookie").apply() }

    private fun restore(): Cookie? = runCatching {
        val saved = prefs.getString("cookie", null) ?: return@runCatching null
        val bytes = Base64.decode(saved, Base64.NO_WRAP)
        require(bytes.size > 28)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
        Cookie.parse(origin, cipher.doFinal(bytes.copyOfRange(12, bytes.size)).toString(Charsets.UTF_8))
            ?.takeIf { it.name == "ap_session" && it.matches(origin) && it.expiresAt > System.currentTimeMillis() }
    }.getOrElse { prefs.edit().remove("cookie").apply();null }

    private fun secretKey(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(keyAlias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(keyAlias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
}
