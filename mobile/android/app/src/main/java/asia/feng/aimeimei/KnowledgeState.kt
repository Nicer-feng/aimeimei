package asia.feng.aimeimei

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.*

// 搜索结果与档案仅保留在当前账号内存中，账号变化会取消请求并清空。
internal class KnowledgeState(private val api: PlatformApi, private val scope: CoroutineScope, private val onUnauthorized: () -> Unit) {
    private var owner = ""
    private var revision = 0
    private var searchRevision = 0
    private var searchJob: Job? = null
    private var profileJob: Job? = null
    var query by mutableStateOf(""); private set
    var results by mutableStateOf<List<ChatSearchResult>>(emptyList()); private set
    var searching by mutableStateOf(false); private set
    var searchError by mutableStateOf(""); private set
    var profiles by mutableStateOf<List<AiProfile>>(emptyList()); private set
    var profilesLoading by mutableStateOf(false); private set
    var saving by mutableStateOf(false); private set
    var profileError by mutableStateOf(""); private set
    fun bind(accountId: String) {
        if (owner == accountId) return
        owner = accountId; revision++; searchRevision++; searchJob?.cancel(); profileJob?.cancel()
        results = emptyList(); query = ""; searching = false; searchError = ""
        profiles = emptyList(); profilesLoading = false; saving = false; profileError = ""
    }
    private fun failure(error: Exception): String {
        if (error is ApiFailure && error.status == 401) onUnauthorized()
        return when ((error as? ApiFailure)?.status) {
            401 -> "登录已失效，请重新登录"
            404 -> "记录已不存在，请刷新后重试"
            else -> "加载或保存失败，请检查网络后重试"
        }
    }
    fun search(text: String) {
        searchJob?.cancel(); val ticket = ++searchRevision; val session = revision
        query = text.take(80); results = emptyList(); searchError = ""
        if (owner.isBlank()) { searching = false; return }
        val requested = query
        searching = true
        searchJob = scope.launch {
            try {
                if (requested.isNotBlank()) delay(300)
                val rows = api.searchChats(requested)
                if (ticket == searchRevision && session == revision) results = rows
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { if (ticket == searchRevision && session == revision) searchError = failure(error) }
            finally { if (ticket == searchRevision && session == revision) searching = false }
        }
    }
    fun loadProfiles() {
        if (owner.isBlank() || saving) return
        profileJob?.cancel(); val ticket = revision
        profileJob = scope.launch {
            profilesLoading = true; profileError = ""
            try { val rows = api.profiles(); if (ticket == revision) profiles = rows }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { if (ticket == revision) profileError = failure(error) }
            finally { if (ticket == revision) profilesLoading = false }
        }
    }
    private fun change(action: suspend () -> Unit) {
        if (owner.isBlank() || saving) return
        profileJob?.cancel(); val ticket = revision
        profileJob = scope.launch {
            saving = true; profilesLoading = false; profileError = ""
            try { action() }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { if (ticket == revision) profileError = failure(error) }
            finally { if (ticket == revision) saving = false }
        }
    }
    fun save(id: String?, title: String, content: String, kind: String, enabled: Boolean, done: () -> Unit) {
        if (title.isBlank() || title.length > 80 || content.isBlank() || content.length > 12000 || kind !in profileKinds) return
        val ticket = revision; val order = profiles.firstOrNull { it.id == id }?.order ?: ((profiles.maxOfOrNull { it.order } ?: 0) + 10)
        change {
            val row = api.saveProfile(id, title, content, kind, enabled, order)
            if (ticket == revision) { profiles = (profiles.filterNot { it.id == row.id } + row).sortedBy { it.order }; done() }
        }
    }
    fun toggle(row: AiProfile) = save(row.id, row.title, row.content, row.kind, !row.enabled) {}
    fun delete(id: String, done: () -> Unit) {
        val ticket = revision
        change { api.deleteProfile(id); if (ticket == revision) { profiles = profiles.filterNot { it.id == id }; done() } }
    }
    fun move(row: AiProfile, direction: Int) {
        val index = profiles.indexOfFirst { it.id == row.id }; val target = index + direction
        if (index < 0 || target !in profiles.indices || direction !in listOf(-1, 1)) return
        val ids = profiles.map { it.id }.toMutableList().apply { val id = removeAt(index); add(target, id) }
        val ticket = revision
        change { val rows = api.reorderProfiles(ids); if (ticket == revision) profiles = rows }
    }
}
