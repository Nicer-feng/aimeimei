package asia.feng.aimeimei

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

internal class SideDiscussionState(private val api: PlatformApi, private val scope: CoroutineScope,
    private val onUnauthorized: () -> Unit) {
    private var owner = ""
    private var conversationId = ""
    private var revision = 0
    private var featureJob: Job? = null
    private var operation: Job? = null
    private var streamJob: Job? = null
    private var selectedRevision = 0
    private var featureEnabled by mutableStateOf(false)
    val available get() = owner.isNotBlank() && conversationId.isNotBlank() && featureEnabled
    var open by mutableStateOf(false); private set
    var active by mutableStateOf<SideDiscussion?>(null); private set
    var discussions by mutableStateOf<List<SideDiscussion>>(emptyList()); private set
    var messages by mutableStateOf<List<ChatMessage>>(emptyList()); private set
    var loading by mutableStateOf(false); private set
    var sending by mutableStateOf(false); private set
    var error by mutableStateOf(""); private set
    var draft by mutableStateOf(""); private set
    var live by mutableStateOf<LiveReply?>(null); private set
    var needsReview by mutableStateOf(false); private set
    var saving by mutableStateOf(false); private set
    var saveUncertain by mutableStateOf(false); private set
    private val savedConversations = mutableMapOf<String, String>()
    private val discussionDrafts = mutableMapOf<String, String>()
    private val reviews = mutableSetOf<String>()
    private val uncertainSaves = mutableSetOf<String>()
    val savedConversationId get() = active?.id?.let(savedConversations::get).orEmpty()
    private var buffer: ReplyBuffer? = null
    private var sentBaseline = 0L
    var pendingQuestion by mutableStateOf(""); private set

    fun bind(accountId: String, conversation: String) {
        if (owner == accountId && conversationId == conversation) return
        val accountChanged = owner != accountId
        revision++; selectedRevision++; featureJob?.cancel(); operation?.cancel(); streamJob?.cancel()
        owner = accountId; conversationId = conversation; open = false; active = null; discussions = emptyList(); messages = emptyList()
        loading = false; sending = false; error = ""; draft = ""; live = null; buffer = null; needsReview = false; saving = false; saveUncertain = false
        savedConversations.clear(); discussionDrafts.clear(); reviews.clear(); uncertainSaves.clear(); pendingQuestion = ""; sentBaseline = 0L
        if (accountChanged) featureEnabled = false
        if (accountId.isBlank()) featureEnabled = false
    }
    fun refreshAvailability() {
        if (owner.isBlank() || conversationId.isBlank()) return
        featureJob?.cancel()
        val ticket = revision
        featureJob = scope.launch {
            try { val enabled = enabled(); if (ticket == revision) featureEnabled = enabled }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (failure: Exception) { if (ticket == revision) { featureEnabled = false; fail(failure) } }
        }
    }
    private suspend fun enabled() = api.request(listOf("api", "features")).optJSONObject("features")?.optBoolean("side_discussion", true) != false
    private fun fail(failure: Exception) {
        error = when (failure) {
            is ApiFailure -> when (failure.status) {
                401 -> "登录已失效，请重新登录"
                403 -> { featureEnabled = false; "分支追问已由管理员关闭" }
                404 -> "分支或来源消息已不存在，请返回后刷新"
                400 -> "请求未被接受，请检查引用内容或模型配置"
                else -> failure.message.orEmpty()
            }
            is IllegalArgumentException -> failure.message.orEmpty()
            else -> "操作未完成，请检查网络后刷新；不会自动重发"
        }
        if (failure is ApiFailure && failure.status == 401) onUnauthorized()
    }
    private fun perform(clearError: Boolean = true, block: suspend (Int, Int) -> Unit) {
        if (owner.isBlank() || conversationId.isBlank() || sending || loading || saving) return
        val ticket = revision; val selected = selectedRevision
        operation = scope.launch {
            loading = true; if (clearError) error = ""
            try { block(ticket, selected) }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (failure: Exception) { if (ticket == revision && selected == selectedRevision) fail(failure) }
            finally { if (ticket == revision && selected == selectedRevision) loading = false }
        }
    }
    fun openHistory() {
        if (sending || loading || saving || owner.isBlank() || conversationId.isBlank()) return
        active?.let { discussionDrafts[it.id] = draft }
        open = true; active = null; messages = emptyList(); live = null; selectedRevision++
        perform { ticket, selected ->
            val permitted = enabled()
            if (ticket != revision || selected != selectedRevision) return@perform
            featureEnabled = permitted
            if (!permitted) { error = "分支追问已由管理员关闭"; return@perform }
            val rows = api.sideDiscussions(conversationId)
            if (ticket == revision && selected == selectedRevision) discussions = rows
        }
    }
    fun start(message: ChatMessage, text: String = message.content) {
        if (sending || loading || saving || owner.isBlank() || conversationId.isBlank()) return
        active?.let { discussionDrafts[it.id] = draft }
        open = true; selectedRevision++; active = null; messages = emptyList(); draft = ""; needsReview = false; saveUncertain = false
        perform { ticket, selected ->
            val permitted = enabled()
            if (ticket != revision || selected != selectedRevision) return@perform
            featureEnabled = permitted
            if (!permitted) { error = "分支追问已由管理员关闭"; return@perform }
            val row = api.createSideDiscussion(conversationId, message.id, text)
            if (ticket == revision && selected == selectedRevision) { active = row; discussions = listOf(row) + discussions.filterNot { it.id == row.id } }
        }
    }
    fun select(row: SideDiscussion) {
        if (sending || loading || saving || row.conversationId != conversationId) return
        active?.let { discussionDrafts[it.id] = draft }
        selectedRevision++; active = row; messages = emptyList(); draft = discussionDrafts[row.id].orEmpty(); live = null
        needsReview = row.id in reviews; saveUncertain = row.id in uncertainSaves; pendingQuestion = ""
        refresh()
    }
    fun refresh(keepError: Boolean = false) {
        val target = active ?: return
        perform(clearError = !keepError) { ticket, selected ->
            val detail = api.sideDiscussion(target.id)
            if (ticket == revision && selected == selectedRevision && detail.discussion.conversationId == conversationId) {
                active = detail.discussion; messages = detail.messages
                val answerSaved = detail.messages.any { it.role == "assistant" && (it.id.toLongOrNull() ?: 0) > sentBaseline }
                if (pendingQuestion.isBlank() || answerSaved) { live = null; pendingQuestion = "" }
                discussions = listOf(detail.discussion) + discussions.filterNot { it.id == target.id }
                if (detail.messages.lastOrNull()?.let { it.role == "user" || it.status != "completed" } == true) { needsReview = true; reviews.add(target.id) }
            }
        }
    }
    fun editDraft(text: String) { if (!sending && !saving) { draft = text.take(60000); active?.let { discussionDrafts[it.id] = draft } } }
    fun send(confirmed: Boolean = false) {
        val target = active ?: return
        val content = draft.trim()
        if (!available || sending || loading || saving || content.isBlank() || (needsReview && !confirmed)) return
        val ticket = revision; val selected = selectedRevision
        sentBaseline = messages.maxOfOrNull { it.id.toLongOrNull() ?: 0 } ?: 0L; pendingQuestion = content
        val reply = ReplyBuffer()
        sending = true; error = ""; needsReview = true; reviews.add(target.id); live = LiveReply(); buffer = reply
        streamJob = scope.launch {
            val ticker = launch {
                while (isActive && ticket == revision && selected == selectedRevision) {
                    delay(80)
                    if (ticket == revision && selected == selectedRevision) live = reply.snapshot(finish = true)
                }
            }
            try {
                api.sideDiscussionStream(target.id, content).collect { event ->
                    if (ticket != revision || selected != selectedRevision) return@collect
                    reply.accept(event)
                }
                if (ticket == revision && selected == selectedRevision) {
                    val received = buffer
                    if (received?.savedId != null) {
                        draft = ""; discussionDrafts.remove(target.id); needsReview = received.status != "completed"
                        if (!needsReview) reviews.remove(target.id)
                    }
                    else error = "尚未确认回答是否保存，请刷新分支记录后再决定是否发送"
                }
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (failure: Exception) { if (ticket == revision && selected == selectedRevision) fail(failure) }
            finally {
                ticker.cancel()
                if (ticket == revision && selected == selectedRevision) {
                    live = buffer?.snapshot(finish = true); sending = false; buffer = null
                    // 只读取服务器记录，不重发问题。读取失败时保留已收到的正文供查看。
                    refresh(keepError = true)
                }
            }
        }
    }
    fun stop() {
        if (!sending) return
        // 提升版本让旧协程的 finally 无法刷新或覆盖新分支状态。
        selectedRevision++; streamJob?.cancel(); streamJob = null; live = buffer?.snapshot(finish = true); buffer = null
        sending = false; needsReview = true; active?.let { reviews.add(it.id) }; error = "已停止接收；服务器可能仍在保存，请刷新记录核对后再发送"
    }
    fun saveConversation(confirmed: Boolean = false, done: (String) -> Unit) {
        val target = active ?: return
        savedConversations[target.id]?.let { done(it); return }
        if (sending || loading || saving || messages.none { it.role == "assistant" && it.content.isNotBlank() } || (saveUncertain && !confirmed)) return
        val ticket = revision; val selected = selectedRevision
        saving = true; error = ""; saveUncertain = true; uncertainSaves.add(target.id)
        operation = scope.launch {
            try {
                val id = api.saveSideConversation(target.id)
                if (ticket == revision && selected == selectedRevision) { savedConversations[target.id] = id; saveUncertain = false; uncertainSaves.remove(target.id); done(id) }
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (failure: Exception) { if (ticket == revision && selected == selectedRevision) { fail(failure); error += "。请先查看主聊天历史，避免重复保存。" } }
            finally { if (ticket == revision && selected == selectedRevision) saving = false }
        }
    }
    fun close() {
        if (saving) return
        if (sending) stop()
        selectedRevision++; operation?.cancel(); loading = false; open = false
    }
}
