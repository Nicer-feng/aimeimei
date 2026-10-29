package asia.feng.aimeimei

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.HttpUrl.Companion.toHttpUrl
import java.io.IOException

class PlatformViewModel(private val application: Application, apiOverride: PlatformApi? = null,
                        private val startGeneration: suspend (Int) -> Unit = { GenerationService.begin(application, it) },
                        private val endGeneration: (Int) -> Unit = { GenerationService.end(application, it) },
                        dispatcher: CoroutineDispatcher = Dispatchers.Main.immediate) {
    // App-scoped state survives Activity destruction while the generation service is running.
    private val viewModelScope = CoroutineScope(SupervisorJob() + dispatcher)
    private var visible = true
    internal val cookies = SessionCookies(application, BuildConfig.API_BASE_URL.toHttpUrl())
    private val api = apiOverride ?: PlatformApi(BuildConfig.API_BASE_URL.toHttpUrl(), cookies) { ClientDeviceInfo.payload(application) }
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
    var preferredModelId by mutableStateOf(""); private set
    var preferredReasoningMode by mutableStateOf("balanced"); private set
    val currentModelId get() = selected?.modelId ?: preferredModelId
    val currentReasoningMode get() = selected?.reasoningMode ?: preferredReasoningMode
    val currentModel get() = models.firstOrNull { it.id == currentModelId }
    var streaming by mutableStateOf(false); private set
    var live by mutableStateOf<LiveReply?>(null); private set
    var pending by mutableStateOf<PendingSend?>(null); private set
    private var operation: Job? = null
    private var deviceReport: Job? = null
    private var streamJob: Job? = null
    private var revision = 0
    private var generation = 0
    private var searchedConversation = false
    internal val activeGeneration get() = generation
    private var buffer: ReplyBuffer? = null
    internal val tools = ChatTools(application, api, viewModelScope) { returnedFromWeb() }
    internal val sms = SmsLoginState(api, viewModelScope)
    internal val incomingShares = IncomingShareController(application, viewModelScope)
    var focusMessageId by mutableStateOf(""); private set

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
        if (user == null) { tools.bind("", ""); captcha = api.captcha() } else {
            loadWorkspace(ticket)
            restoreWelcomeDraft()
            // 只有尚待核对的发送才恢复旧会话；正常冷启动展示新聊天。
            val last = drafts.getString(key("last", ""), null)
            conversations.firstOrNull { it.id == last && PendingSend.parse(drafts.getString(key("pending", it.id), null)) != null }
                ?.let { enter(it); loadMessages(ticket) }
        }
    }
    fun refreshCaptcha() = work { ticket -> val value = api.captcha(); if (ticket == revision) captcha = value }
    fun login(username: String, password: String, answer: String) {
        val challenge = captcha ?: return
        work { ticket ->
            try {
                val user = api.login(username, password, challenge, answer)
                if (ticket != revision) return@work
                account = user; captcha = null; sms.verified(); loadWorkspace(ticket); restoreWelcomeDraft()
            } catch (failure: ApiFailure) {
                if (ticket == revision && account == null) captcha = runCatching { api.captcha() }.getOrNull()
                throw failure
            }
        }
    }
    internal fun loginSms(code: String) {
        val phone = normalizedPhone(sms.phone); val challenge = sms.challenge
        if (account != null || busy || sms.loading || sms.sending || sms.config?.available != true || phone.isBlank() || challenge.isBlank() || !Regex("\\d{6}").matches(code)) return
        work { ticket ->
            val user = api.loginSms(phone, code, challenge)
            if (ticket != revision) return@work
            account = user; captcha = null; sms.verified(); loadWorkspace(ticket); restoreWelcomeDraft()
        }
    }
    fun refresh() {
        if (streaming) return
        work { ticket ->
            loadWorkspace(ticket)
            if (ticket != revision) return@work
            val current = selected
            if (current != null) {
                selected = conversations.firstOrNull { it.id == current.id } ?: if (searchedConversation) {
                    try { api.conversationDetail(current.id) }
                    catch (failure: ApiFailure) { if (failure.status == 404) null else throw failure }
                } else null
                if (selected != null) loadMessages(ticket)
                else { messages = emptyList(); pending = null; live = null; restoreWelcomeDraft() }
            }
        }
    }
    private suspend fun loadWorkspace(ticket: Int) {
        reportCurrentDevice(ticket)
        val list = api.conversations(); val available = api.models()
        if (ticket == revision) {
            incomingShares.bindAccount(account?.id.orEmpty())
            conversations = list; models = available
            if (available.none { it.id == preferredModelId }) preferredModelId = available.firstOrNull()?.id.orEmpty()
        }
    }
    private fun reportCurrentDevice(ticket: Int = revision) {
        deviceReport?.cancel()
        val owner = account?.id
        deviceReport = viewModelScope.launch {
            if (owner == null || owner != account?.id || ticket != revision) return@launch
            try { api.reportClientDevice() }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { /* 补报不阻断登录和原有功能。 */ }
        }
    }
    private fun restoreWelcomeDraft() {
        tools.bind(account?.id.orEmpty(), "")
        draft = drafts.getString(key("text", ""), "").orEmpty()
        webSearch = drafts.getBoolean(key("web", ""), false)
        preferredModelId = drafts.getString(key("model", ""), null)?.takeIf { id -> models.any { it.id == id } }
            ?: models.firstOrNull()?.id.orEmpty()
        preferredReasoningMode = drafts.getString(key("mode", ""), "balanced").orEmpty()
    }
    private fun enter(conversation: Conversation) {
        searchedConversation = false
        generation++
        selected = conversation; messages = emptyList(); live = null
        focusMessageId = ""; tools.bind(account?.id.orEmpty(), conversation.id)
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
                tools.sent(); forgetPending(); live = null
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
        if (streaming || busy) return
        generation++; selected = null; messages = emptyList(); live = null; pending = null; error = null
        drafts.edit().remove(key("last", "")).apply()
        restoreWelcomeDraft()
    }
    fun configure(modelId: String, mode: String) {
        if (streaming || busy || pending != null) return
        if (selected == null) {
            preferredModelId = modelId; preferredReasoningMode = mode
            drafts.edit().putString(key("model", ""), modelId).putString(key("mode", ""), mode).apply()
            return
        }
        val current = selected ?: return
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
        pending?.let {
            val saved = messages.any { m -> m.role == "user" && (m.id.toLongOrNull() ?: 0) > it.baseline && m.content.trim() == it.content.trim() }
            if (draft.isBlank() && !saved) editDraft(it.draftText)
            if (saved) tools.sent()
        }
        forgetPending(); live = null; error = "已解除等待，请先核对聊天记录，再决定是否发送。"
    }
    internal suspend fun importShared(payload: IncomingSharePayload): Boolean {
        val owner = account?.id ?: return false
        if (busy || streaming || pending != null || tools.uploading || payload.owner != owner) return false
        val ticket = revision
        busy = true
        try {
            if (!tools.stageSharedImages(payload.images) || ticket != revision || account?.id != owner) return false
            if (payload.text.isNotBlank()) editDraft(if (draft.isBlank()) payload.text else draft + "\n\n" + payload.text)
            return true
        } finally { if (ticket == revision) busy = false }
    }
    fun send() {
        val question = draft.trim()
        val content = quoteMessage(question, tools.quotes).ifBlank {
            if (tools.attachments.any { !it.image }) "请根据这些材料分析。" else if (tools.attachments.isNotEmpty()) "请分析这些图片。" else ""
        }
        if (streaming || busy || pending != null || content.isEmpty() || !tools.canSend) return
        if (tools.attachments.any { it.image } && currentModel?.vision != true) { error = "当前模型不支持图片，请先切换支持图片的模型"; return }
        if (tools.hasStagedImages) {
            work { ticket ->
                if (tools.uploadStagedImages() && ticket == revision) { busy = false; send() }
            }
            return
        }
        if (selected == null) {
            if (models.none { it.id == preferredModelId }) return
            val files = tools.attachments; val citations = tools.quotes
            work { ticket ->
                val created = api.createConversation(preferredModelId, preferredReasoningMode)
                if (ticket != revision) return@work
                val search = webSearch
                conversations = listOf(created) + conversations; enter(created)
                tools.restoreDraft(files, citations); tools.forgetWelcomeDraft()
                editDraft(question); toggleWebSearch(search)
                drafts.edit().remove(key("text", "")).apply()
                busy = false
                send()
            }
            return
        }
        val conversation = selected ?: return
        val waiting = PendingSend(conversation.id, messages.maxOfOrNull { it.id.toLongOrNull() ?: 0 } ?: 0, content, tools.attachments, question)
        // Persist the recovery marker before network side effects or clearing the editor.
        if (!drafts.edit().putString(key("pending"), waiting.toJson()).commit()) { error = "无法保存草稿，请稍后重试"; return }
        pending = waiting; editDraft(""); error = null; streaming = true
        val reply = ReplyBuffer(); buffer = reply; live = reply.snapshot()
        val run = ++generation
        streamJob = viewModelScope.launch {
            val ticker = launch { while (isActive && run == generation) { delay(80); if (visible && run == generation) live = reply.snapshot() } }
            var failure: Exception? = null
            var submitted = false
            try {
                startGeneration(run)
                submitted = true
                withTimeout(15 * 60 * 1000L) { api.stream(conversation.id, content, webSearch,
                    waiting.attachments.filter { it.image }.map { it.id }, waiting.attachments.filterNot { it.image }.map { it.id }).collect { reply.accept(it) } }
            }
            catch (_: TimeoutCancellationException) { failure = ApiFailure(408, "生成等待超时，请刷新核对已保存内容") }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { failure = error }
            finally {
                ticker.cancel()
                if (run == generation) { live = reply.snapshot(finish = true); streaming = false }
                endGeneration(run)
            }
            if (run != generation) return@launch
            if (reply.savedId != null) {
                val final = reply.snapshot(finish = true)
                messages = messages + ChatMessage("local-user-${waiting.baseline}", "user", content, "", "completed", waiting.attachments.map { it.name }, waiting.attachments) +
                    ChatMessage(reply.savedId!!, "assistant", final.content, final.reasoning, reply.status, emptyList())
                tools.sent(); forgetPending(); live = null
            }
            if (!submitted || failure is ApiFailure && failure.status == 400) {
                forgetPending(); if (draft.isBlank()) editDraft(waiting.draftText)
            }
            if (!submitted) {
                live = null
                error = (failure as? ApiFailure)?.message ?: "无法启动后台生成服务，请返回前台重试；输入内容已保留"
                return@launch
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
    fun background() { visible = false; tools.speech.pause() }
    fun foreground() {
        visible = true
        if (account != null) reportCurrentDevice()
        if (streaming) live = buffer?.snapshot(finish = true)
        else if (account != null && !busy && selected != null) refresh()
    }
    fun back() {
        if (streaming) return
        generation++
        operation?.cancel(); revision++; selected = null; messages = emptyList(); live = null; pending = null; busy = false; error = null
        drafts.edit().remove(key("last", "")).apply()
        restoreWelcomeDraft()
        refresh()
    }
    fun rename(conversation: Conversation, title: String) {
        if (streaming || busy || title.isBlank()) return
        work { ticket ->
            val updated = api.renameConversation(conversation.id, title.trim().take(80))
            if (ticket == revision) {
                conversations = conversations.map { if (it.id == updated.id) updated else it }
                if (selected?.id == updated.id) selected = updated
            }
        }
    }
    fun pin(conversation: Conversation) {
        if (streaming || busy) return
        work { ticket -> api.pinConversation(conversation.id, !conversation.pinned); loadWorkspace(ticket) }
    }
    fun delete(conversation: Conversation) {
        if (streaming || busy) return
        work { ticket ->
            api.deleteConversation(conversation.id)
            if (ticket == revision) {
                conversations = conversations.filterNot { it.id == conversation.id }
                drafts.edit().remove(key("text", conversation.id)).remove(key("pending", conversation.id)).remove(key("web", conversation.id)).apply()
                if (selected?.id == conversation.id) {
                    selected = null; messages = emptyList(); pending = null; live = null
                    drafts.edit().remove(key("last", "")).apply(); restoreWelcomeDraft()
                }
            }
        }
    }
    internal suspend fun adminRequest(path: List<String>, method: String = "GET", body: org.json.JSONObject? = null,
                                      query: Map<String, String> = emptyMap()): org.json.JSONObject {
        if (account?.role != "admin") throw ApiFailure(403, "当前账号没有管理员权限")
        return try { api.adminRequest(path, method, body, query) }
        catch (failure: ApiFailure) {
            if (failure.status == 401 || failure.status == 403) returnedFromWeb()
            throw failure
        }
    }

    fun returnedFromWeb() {
        if (streaming) return
        work { ticket ->
            val user = api.currentAccount()
            if (ticket != revision) return@work
            if (user == null || user.id != account?.id) { clearAccount(); captcha = api.captcha(); return@work }
            account = user; loadWorkspace(ticket)
            if (selected != null) {
                selected = conversations.firstOrNull { it.id == selected?.id }
                if (selected != null) loadMessages(ticket) else { messages = emptyList(); pending = null; live = null; restoreWelcomeDraft() }
            }
        }
    }
    fun logout() {
        if (streaming) return
        work { ticket -> try { api.logout() } finally { if (ticket == revision) { clearAccount(); captcha = runCatching { api.captcha() }.getOrNull() } } }
    }
    private fun clearAccount() {
        deviceReport?.cancel(); deviceReport = null
        sms.verified()
        incomingShares.bindAccount("")
        generation++
        streamJob?.cancel(); cookies.clear(); account = null; selected = null; messages = emptyList(); conversations = emptyList(); models = emptyList()
        captcha = null; draft = ""; pending = null; live = null; streaming = false
        focusMessageId = ""; tools.bind("", "")
    }
    fun toggleFavorite(message: ChatMessage) {
        if (account == null || streaming || pending != null) return
        tools.toggleFavorite(message) { favoriteId -> messages = messages.map { if (it.id == message.id) it.copy(favoriteId = favoriteId) else it } }
    }
    fun openFavorite(conversationId: String, messageId: String): Boolean {
        val conversation = conversations.firstOrNull { it.id == conversationId } ?: return false
        open(conversation); focusMessageId = messageId
        return true
    }
    fun clearFocusMessage() { focusMessageId = "" }
    internal fun openSearchResult(result: ChatSearchResult, onOpen: () -> Unit) {
        if (account == null || streaming || busy || result.conversationId.isBlank()) return
        work { ticket ->
            // 搜索不限于最近 200 段聊天，先按账号读取真实会话配置，再加载消息。
            val conversation = api.conversationDetail(result.conversationId)
            if (ticket != revision) return@work
            enter(conversation)
            searchedConversation = true
            focusMessageId = result.messageId
            loadMessages(ticket)
            if (ticket == revision) {
                if (result.messageId.isNotBlank() && messages.none { it.id == result.messageId }) {
                    focusMessageId = ""; error = "原消息已不存在，已打开对应聊天"
                }
                onOpen()
            }
        }
    }
}
