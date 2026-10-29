package asia.feng.aimeimei

import android.content.Context
import android.os.Build
import androidx.core.app.NotificationManagerCompat
import org.json.JSONObject
import java.util.UUID

internal object ClientDeviceInfo {
    @Synchronized fun payload(context: Context): JSONObject {
        val store = context.getSharedPreferences("client_device", Context.MODE_PRIVATE)
        val id = store.getString("installation_id", null) ?: UUID.randomUUID().toString().also {
            store.edit().putString("installation_id", it).apply()
        }
        return JSONObject().put("installation_id", id).put("platform", "android")
            .put("manufacturer", Build.MANUFACTURER).put("model", Build.MODEL)
            .put("os_version", Build.VERSION.RELEASE).put("app_version", BuildConfig.VERSION_NAME)
            .put("app_build", BuildConfig.VERSION_CODE.toString())
            .put("notification_authorization", if (NotificationManagerCompat.from(context).areNotificationsEnabled()) "authorized" else "denied")
    }
}
