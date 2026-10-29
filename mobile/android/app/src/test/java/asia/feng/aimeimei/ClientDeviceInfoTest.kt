package asia.feng.aimeimei

import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class ClientDeviceInfoTest {
    @Test fun randomInstallationIsStableUntilApplicationDataIsReset() {
        val context = RuntimeEnvironment.getApplication()
        val first = ClientDeviceInfo.payload(context)
        val second = ClientDeviceInfo.payload(context)
        assertEquals(first.getString("installation_id"), second.getString("installation_id"))
        assertTrue(Regex("[A-Za-z0-9-]{16,80}").matches(first.getString("installation_id")))
        assertEquals("android", first.getString("platform"))
        assertEquals(BuildConfig.VERSION_NAME, first.getString("app_version"))
        assertEquals(BuildConfig.VERSION_CODE.toString(), first.getString("app_build"))
        assertEquals(setOf("installation_id","platform","manufacturer","model","os_version","app_version","app_build","notification_authorization"), first.keys().asSequence().toSet())
        context.getSharedPreferences("client_device", 0).edit().clear().commit()
        assertNotEquals(first.getString("installation_id"), ClientDeviceInfo.payload(context).getString("installation_id"))
    }
}
