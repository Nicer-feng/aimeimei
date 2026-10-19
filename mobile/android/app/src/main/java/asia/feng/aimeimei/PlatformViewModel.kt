package asia.feng.aimeimei

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import okhttp3.HttpUrl.Companion.toHttpUrl
import java.io.IOException

class PlatformViewModel(application: Application) : AndroidViewModel(application) {
    private val origin = BuildConfig.API_BASE_URL.toHttpUrl()
    private val cookies = SessionCookies(application, origin)
    private val api = PlatformApi(origin, cookies)
    var account by mutableStateOf<Account?>(null);private set
    var captcha by mutableStateOf<Captcha?>(null);private set
    var conversations by mutableStateOf<List<Conversation>>(emptyList());private set
    var models by mutableStateOf<List<ChatModel>>(emptyList());private set
    var selected by mutableStateOf<Conversation?>(null);private set
    var messages by mutableStateOf<List<ChatMessage>>(emptyList());private set
    var busy by mutableStateOf(false);private set
    var error by mutableStateOf<String?>(null);private set
    private var operation: Job? = null
    private var revision = 0

    init { restore() }
    private fun work(block: suspend (Int) -> Unit) {
        operation?.cancel();val ticket = ++revision
        operation = viewModelScope.launch {
            busy = true;error = null
            try { block(ticket) }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (failure: Exception) {
                if (ticket == revision) {
                    error = when (failure) { is ApiFailure -> failure.message;is IOException -> "网络连接失败，请检查网络后重试";else -> "加载失败，请稍后重试" }
                    if (failure is ApiFailure && failure.status == 401 && account != null) clearAccount()
                }
            } finally { if (ticket == revision) busy = false }
        }
    }
    fun restore() = work { ticket ->
        val user = api.currentAccount()
        if (ticket != revision) return@work
        account = user
        if (user == null) captcha = api.captcha() else loadWorkspace(ticket)
    }
    fun refreshCaptcha() = work { ticket ->
        val challenge = api.captcha();if (ticket == revision) captcha = challenge
    }
    fun login(username: String, password: String, answer: String) {
        val challenge = captcha ?: return
        work { ticket ->
            try {
                val user = api.login(username, password, challenge, answer)
                if (ticket != revision) return@work
                account = user;captcha = null;loadWorkspace(ticket)
            } catch (failure: ApiFailure) {
                if (ticket == revision && account == null) captcha = runCatching { api.captcha() }.getOrNull()
                throw failure
            }
        }
    }
    fun refresh() = work { ticket ->
        val conversation = selected
        if (conversation == null) loadWorkspace(ticket) else {
            val result = api.messages(conversation.id)
            if (ticket == revision) messages = result
        }
    }
    private suspend fun loadWorkspace(ticket: Int) {
        val list = api.conversations();val available = api.models()
        if (ticket == revision) { conversations = list;models = available }
    }
    fun open(conversation: Conversation) {
        selected = conversation;messages = emptyList()
        refresh()
    }
    fun back() { operation?.cancel();revision++;selected = null;messages = emptyList();busy = false;error = null }
    fun logout() = work { ticket ->
        try { api.logout() } finally {
            if (ticket == revision) { clearAccount();captcha = runCatching { api.captcha() }.getOrNull() }
        }
    }
    private fun clearAccount() {
        cookies.clear();account = null;selected = null;messages = emptyList();conversations = emptyList();models = emptyList();captcha = null
    }
}
