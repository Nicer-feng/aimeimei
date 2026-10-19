package asia.feng.aimeimei

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class AdminFormsTest {
    @Test fun editAccountPreservesIdentityAndDoesNotSubmitAnEmptyPassword() {
        val form = adminForm("users", JSONObject("""{"id":"u1","username":"family","display_name":"家人","role":"family","phone":"","is_active":true}"""))
        val values = form.initialValues()
        assertNull(form.validate(values, emptyList()))
        val body = form.payload(values, emptyList())
        assertEquals(listOf("users", "u1"), form.path); assertEquals("PUT", form.method)
        assertFalse(body.has("username")); assertFalse(body.has("password"))
        assertTrue(body.get("is_active") is Boolean)
    }
    @Test fun createAccountValidatesPasswordPhoneAndRole() {
        val form = adminForm("users")
        val valid = form.initialValues() + mapOf("username" to "family2", "password" to "test-only-pass", "role" to "family")
        assertNull(form.validate(valid, emptyList()))
        assertNotNull(form.validate(valid + ("username" to "bad name"), emptyList()))
        assertNotNull(form.validate(valid + ("password" to "123"), emptyList()))
        assertNotNull(form.validate(valid + ("phone" to "123"), emptyList()))
        assertNotNull(form.validate(valid + ("phone_verified" to "true"), emptyList()))
        assertNotNull(form.validate(valid + ("role" to "root"), emptyList()))
    }
    @Test fun modelCapabilitiesAndPricesUseExpectedTypes() {
        val form = adminForm("models", JSONObject("""{"id":"m1","name":"模型","model":"test","base_url":"https://example.com/v1","input_price_per_million":2.4,"supports_reasoning_control":true,"has_api_key":true}"""))
        val values = form.initialValues()
        assertNull(form.validate(values, emptyList()))
        val body = form.payload(values, emptyList())
        assertTrue(body.getBoolean("supports_reasoning_control")); assertEquals(2.4, body.getDouble("input_price_per_million"), 0.0)
        assertFalse(body.has("api_key")); assertFalse(body.has("has_api_key")); assertTrue(body.getBoolean("cost_enabled"))
        assertNotNull(form.validate(values + ("output_price_per_million" to "NaN"), emptyList()))
        assertNotNull(form.validate(values + ("input_price_per_million" to "-1"), emptyList()))
    }
    @Test fun keyReplacementAndClearAreMutuallyExclusive() {
        val form = adminForm("model-key", JSONObject("""{"id":"m1","has_api_key":true}"""))
        assertEquals("PUT", form.method)
        val values = form.initialValues()
        assertFalse(form.payload(values, emptyList()).has("api_key"))
        assertNotNull(form.validate(values + mapOf("api_key" to "test-only-key", "clear_api_key" to "true"), emptyList()))
        assertEquals(setOf("clear_api_key"), form.payload(values + ("clear_api_key" to "true"), emptyList()).keys().asSequence().toSet())
    }
    @Test fun voiceEditorRejectsDuplicateOrMissingDefaultsAndPreservesResourceIds() {
        val form = adminForm("tts")
        val voices = listOf(mapOf("id" to "v1", "name" to "测试音色", "resource_id" to "resource-test"))
        val values = form.initialValues() + ("default_voice" to "v1")
        assertNull(form.validate(values, voices))
        assertNotNull(form.validate(values, voices + voices))
        assertNotNull(form.validate(values + ("default_voice" to "missing"), voices))
        assertNotNull(form.validate(values, emptyList()))
        val body = form.payload(values, voices)
        assertEquals("resource-test", body.getJSONArray("voices").getJSONObject(0).getString("resource_id"))
        assertEquals(1.0, body.getDouble("default_volume"), 0.0)
    }
    @Test fun featureFlagsAreWrappedAndSmsIntervalsAreBounded() {
        val features = adminForm("features")
        assertFalse(features.payload(features.initialValues() + ("side_discussion" to "false"), emptyList()).getJSONObject("features").getBoolean("side_discussion"))
        val sms = adminForm("sms-auth")
        assertNotNull(sms.validate(sms.initialValues() + ("enabled" to "true"), emptyList()))
        assertNotNull(sms.validate(sms.initialValues() + ("valid_seconds" to "1"), emptyList()))
        assertNotNull(sms.validate(sms.initialValues() + ("resend_seconds" to "60.5"), emptyList()))
        assertNotNull(sms.validate(sms.initialValues() + ("code_param_name" to "bad name"), emptyList()))
    }
    @Test fun statisticsUseCorrectServerFilters() {
        fun query(section: String, view: String) = AdminStatsQuery(section, view, "家人&测试", "tokens", "2026-10-19", "2026-10-01", "2026-10-19", "30d")
        assertEquals(listOf("token-stats", "daily"), query("tokens", "daily").endpoint().first)
        assertEquals("家人&测试", query("tokens", "models").endpoint().second["model_q"])
        assertEquals("2026-10-01", query("usage", "users").endpoint().second["start"])
        assertEquals(mapOf("range" to "30d"), query("costs", "users").endpoint().second)
    }
}
