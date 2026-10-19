package asia.feng.aimeimei

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.HttpUrl.Companion.toHttpUrl
import java.io.IOException

class PlatformViewModel(application: Application) : AndroidViewModel(application) {
    private val cookies = SessionCookies(application, BuildConfig.API_BASE_URL.toHttpUrl())
    private val api = PlatformApi(BuildConfig.API_BASE_URL.toHttpUrl(), cookies)
    private val drafts = application.getSharedPreferences("chat_drafts", Application.MODE_PRIVATE)
    var account by mutableStateOf<Account?>(null); private set
    var captcha by mutableStateOf<Captcha?>(null); private set
    var conversations by mutableStateOf<List<Conversation>>(emptyList()); private set
    var models by mutableStateOf<List<ChatModel>>(emptyList()); private set
    var selected by mutableStateOf<Conversation?>(null); private set
    var messages by mutableStateOf<List<ChatMessage>>(emptyList()); private set
    var busy by mutableStateOf(false); private set
    var error by mutableStateOf<String?>(null); private set
    var draft by mutableStateOf(""); private set
    var webSearch by mutableStateOf(false); private set
    var streaming by mutableStateOf(false); private set
    var live by mutableStateOf<LiveReply?>(null); private set
    var pending by mutableStateOf<PendingSend?>(null); private set
    private var operation: Job? = null
    private var streamJob: Job? = null
    private var revision = 0
    private var generation = 0
    private var buffer: ReplyBuffer? = null

    init { restore() }
    private fun key(kind: String, id: String = selected?.id.orEmpty()) = draftKey(account?.id.orEmpty(), id, kind)
    private fun work(block: suspend (Int) -> Unit) {
        operation?.cancel(); val ticket = ++revision
        operation = viewModelScope.launch {
            busy = true; error = null
            try { block(ticket) }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (failure: Exception) {
                if (ticket == revision) {
                    error = hint(failure)
                    if (failure is ApiFailure && failure.status == 401 && account != null) clearAccount()
                }
            } finally { if (ticket == revision) busy = false }
        }
    }
    private fun hint(failure: Exception) = when (failure) {
        is ApiFailure -> failure.message
        is IOException -> "网络连接失败，请检查网络后刷新，未确认的消息不会自动重发"
        else -> "加载失败，请稍后重试"
    }
    fun restore() = work { ticket ->
        val user = api.currentAccount()
        if (ticket != revision) return@work
        account = user
        if (user == null) captcha = api.captcha() else {
            loadWorkspace(ticket)
            val last = drafts.getString(key("last", ""), null)
            conversations.firstOrNull { it.id == last }?.let { enter(it); loadMessages(ticket) }
        }
    }
    fun refreshCaptcha() = work { ticket -> val value = api.captcha(); if (ticket == revision) captcha = value }
    fun login(username: String, password: String, answer: String) {
        val challenge = captcha ?: return
        work { ticket ->
            try {
                val user = api.login(username, password, challenge, answer)
                if (ticket != revision) return@work
                account = user; captcha = null; loadWorkspace(ticket)
            } catch (failure: ApiFailure) {
                if (ticket == revision && account == null) captcha = runCatching { api.captcha() }.getOrNull()
                throw failure
            }
        }
    }
    fun refresh() {
        if (streaming) return
        work { ticket -> if (selected == null) loadWorkspace(ticket) else loadMessages(ticket) }
    }
    private suspend fun loadWorkspace(ticket: Int) {
        val list = api.conversations(); val available = api.models()
        if (ticket == revision) { conversations = list; models = available }
    }
    private fun enter(conversation: Conversation) {
        generation++
        selected = conversation; messages = emptyList(); live = null
        draft = drafts.getString(key("text"), "").orEmpty()
        webSearch = drafts.getBoolean(key("web"), false)
        pending = PendingSend.parse(drafts.getString(key("pending"), null))
        drafts.edit().putString(key("last", ""), conversation.id).apply()
    }
    private suspend fun loadMessages(ticket: Int) {
        val conversation = selected ?: return
        val waiting = pending
        // Saving after a disconnected request can lag. Recovery never replays the POST.
        for (attempt in 0..3) {
            if (attempt > 0) delay(1500L * attempt)
            val result = api.messages(conversation.id)
            if (ticket != revision) return
            messages = result
            if (waiting == null) { live = null; return }
            if (pendingReply(waiting, result) != null) {
                forgetPending(); live = null
                error = result.lastOrNull()?.takeIf { it.status in listOf("failed", "interrupted") }?.let { "本次生成已中断，服务器已保留收到的内容" }
                return
            }
        }
        error = "仍在等待服务器保存结果，请稍后刷新核对。不会自动重发，也不会把断流当作完成。"
    }
    fun open(conversation: Conversation) {
        if (streaming) return
        operation?.cancel(); revision++; enter(conversation); refresh()
    }
    fun newConversation() {
        if (streaming || busy || models.isEmpty()) return
        val modelId = selected?.modelId?.takeIf { id -> models.any { it.id == id } } ?: models.first().id
        work { ticket ->
            val created = api.createConversation(modelId, "balanced")
            if (ticket == revision) { conversations = listOf(created) + conversations; enter(created) }
        }
    }
    fun configure(modelId: String, mode: String) {
        val current = selected ?: return
        if (streaming || busy || pending != null) return
        work { ticket ->
            val updated = api.configureConversation(current.id, modelId, mode)
            if (ticket == revision) { selected = updated; conversations = conversations.map { if (it.id == updated.id) updated else it } }
        }
    }
    fun editDraft(value: String) { draft = value; drafts.edit().putString(key("text"), value).apply() }
    fun toggleWebSearch(value: Boolean) { webSearch = value; drafts.edit().putBoolean(key("web"), value).apply() }
    private fun forgetPending() { drafts.edit().remove(key("pending")).apply(); pending = null }
    fun acknowledgePending() {
        if (streaming || busy) return
        pending?.let { if (draft.isBlank() && messages.none { m -> m.role == "user" && (m.id.toLongOrNull() ?: 0) > it.baseline && m.content.trim() == it.content.trim() }) editDraft(it.content) }
        forgetPending(); live = null; error = "已解除等待，请先核对聊天记录，再决定是否发送。"
    }
    fun send() {
        val conversation = selected ?: return
        val content = draft.trim()
        if (streaming || busy || pending != null || content.isEmpty()) return
        val waiting = PendingSend(conversation.id, messages.maxOfOrNull { it.id.toLongOrNull() ?: 0 } ?: 0, content)
        // Persist the recovery marker before network side effects or clearing the editor.
        if (!drafts.edit().putString(key("pending"), waiting.toJson()).commit()) { error = "无法保存草稿，请稍后重试"; return }
        pending = waiting; editDraft(""); error = null; streaming = true
        val reply = ReplyBuffer(); buffer = reply; live = reply.snapshot()
        val run = ++generation
        streamJob = viewModelScope.launch {
            val ticker = launch { while (isActive && run == generation) { delay(80); if (run == generation) live = reply.snapshot() } }
            var failure: Exception? = null
            try { api.stream(conversation.id, content, webSearch).collect { reply.accept(it) } }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { failure = error }
            finally { ticker.cancel(); if (run == generation) { live = reply.snapshot(finish = true); streaming = false } }
            if (run != generation) return@launch
            if (reply.savedId != null) {
                val final = reply.snapshot(finish = true)
                messages = messages + ChatMessage("local-user-${waiting.baseline}", "user", content, "", "completed", emptyList()) +
                    ChatMessage(reply.savedId!!, "assistant", final.content, final.reasoning, reply.status, emptyList())
                forgetPending(); live = null
            }
            if (failure is ApiFailure && failure.status == 400) {
                forgetPending(); if (draft.isBlank()) editDraft(content)
            }
            error = if (reply.savedId == null) failure?.let(::hint) ?: "连接已结束，尚未收到保存确认，正在核对服务器记录…"
                else if (reply.status != "completed") "本次生成未完成，已保留收到的内容" else null
            refresh()
        }
    }
    fun stop() {
        if (!streaming) return
        generation++
        streamJob?.cancel(); streamJob = null
        live = buffer?.snapshot(finish = true); streaming = false
        error = "已停止接收，正在核对服务器保存的内容…"
        refresh()
    }
    fun background() { if (streaming) stop() }
    fun foreground() { if (account != null && !streaming && !busy && selected != null) refresh() }
    fun back() {
        if (streaming) return
        generation++
        operation?.cancel(); revision++; selected = null; messages = emptyList(); live = null; pending = null; busy = false; error = null
        drafts.edit().remove(key("last", "")).apply()
        refresh()
    }
    fun logout() {
        if (streaming) return
        work { ticket -> try { api.logout() } finally { if (ticket == revision) { clearAccount(); captcha = runCatching { api.captcha() }.getOrNull() } } }
    }
    private fun clearAccount() {
        generation++
        streamJob?.cancel(); cookies.clear(); account = null; selected = null; messages = emptyList(); conversations = emptyList(); models = emptyList()
        captcha = null; draft = ""; pending = null; live = null; streaming = false
    }
}
