package asia.feng.aimeimei

import android.app.Application
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.MediaPlayer
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File

internal class SpeechPlayer(private val app: Application, private val api: PlatformApi, private val scope: CoroutineScope,
                            private val onError: (String) -> Unit) {
    var messageId by mutableStateOf(""); private set
    var phase by mutableStateOf("idle"); private set
    var position by mutableStateOf(0); private set
    var duration by mutableStateOf(0); private set
    private var player: MediaPlayer? = null
    private var file: File? = null
    private var job: Job? = null
    private var ticker: Job? = null
    private var revision = 0
    private val audio = app.getSystemService(android.content.Context.AUDIO_SERVICE) as AudioManager
    private val attributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
    private val focus = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN).setAudioAttributes(attributes)
        .setOnAudioFocusChangeListener { change ->
            if (change == AudioManager.AUDIOFOCUS_LOSS || change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT) pause()
            if (change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK) player?.setVolume(.2f, .2f)
            if (change == AudioManager.AUDIOFOCUS_GAIN) player?.setVolume(1f, 1f)
        }.build()
    fun play(id: String, voice: String, speed: Float, directory: File) {
        if ((id.toLongOrNull() ?: 0) <= 0) return
        stop(); messageId = id; phase = "preparing"
        val ticket = ++revision
        job = scope.launch {
            var downloaded: File? = null
            try {
                api.request(listOf("api", "messages", id, "tts"), JSONObject().put("voice", voice).put("speed", speed))
                val audioFile = withContext(Dispatchers.IO) { File.createTempFile("speech-", ".mp3", directory) }
                downloaded = audioFile
                api.downloadPrivate(listOf("api", "messages", id, "tts", "audio"), audioFile,
                    mapOf("voice" to voice, "speed" to speed.toString()))
                if (ticket != revision) { audioFile.delete(); return@launch }
                file = audioFile
                val next = MediaPlayer()
                player = next; next.setAudioAttributes(attributes)
                next.setOnPreparedListener {
                    if (ticket == revision) {
                        duration = it.duration.coerceAtLeast(0)
                        if (audio.requestAudioFocus(focus) == AudioManager.AUDIOFOCUS_REQUEST_GRANTED) { it.start(); phase = "playing" }
                        else phase = "paused"
                    }
                }
                next.setOnCompletionListener { if (ticket == revision) { phase = "paused"; position = duration; audio.abandonAudioFocusRequest(focus) } }
                next.setOnErrorListener { _, _, _ -> if (ticket == revision) { stop(); onError("语音播放失败，请重新生成或重试") }; true }
                next.setDataSource(audioFile.path); next.prepareAsync()
                ticker = scope.launch {
                    while (isActive && ticket == revision) {
                        delay(250)
                        if (phase in listOf("playing", "paused")) position = runCatching { next.currentPosition }.getOrDefault(position)
                    }
                }
            } catch (cancelled: CancellationException) { downloaded?.delete(); throw cancelled }
            catch (_: Exception) { if (ticket == revision) { stop(); onError("语音生成或下载失败，请稍后重试") }; downloaded?.delete() }
        }
    }
    fun pause() {
        if (phase == "playing") { player?.pause(); phase = "paused"; audio.abandonAudioFocusRequest(focus) }
    }
    fun toggle() {
        val current = player ?: return
        if (phase == "playing") pause()
        else if (phase == "paused" && audio.requestAudioFocus(focus) == AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
            if (position >= duration) { current.seekTo(0); position = 0 }
            current.start(); phase = "playing"
        }
    }
    fun seek(value: Int) {
        if (phase in listOf("playing", "paused")) { position = value.coerceIn(0, duration); player?.seekTo(position) }
    }
    fun stop() {
        revision++; job?.cancel(); job = null; ticker?.cancel(); ticker = null
        player?.release(); player = null; audio.abandonAudioFocusRequest(focus)
        file?.delete(); file = null; messageId = ""; phase = "idle"; position = 0; duration = 0
    }
}
