package asia.feng.aimeimei

import android.app.Application
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import android.os.PowerManager
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.withTimeout

class MeimeiApplication : Application() {
    val chat by lazy { PlatformViewModel(this) }
    val updates by lazy { AppUpdater(this) }
}

class GenerationService : Service() {
    private var wakeLock: PowerManager.WakeLock? = null
    private var started = false
    private var task = -1
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == STOP) { (application as MeimeiApplication).chat.stop(); stopSelf(); return START_NOT_STICKY }
        task = intent?.getIntExtra("task", -1) ?: -1
        try {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel(CHANNEL, "回答生成进度", NotificationManager.IMPORTANCE_LOW))
            val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val stop = PendingIntent.getService(this, 1, Intent(this, GenerationService::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val notification = Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle("槑槑正在生成回答").setContentText("可以切换应用，完成后自动结束；点击返回查看进度")
                .setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true)
                .addAction(Notification.Action.Builder(null, "停止", stop).build()).build()
            startForeground(301, notification)
            val chat = (application as MeimeiApplication).chat
            if (!chat.streaming || chat.activeGeneration != task) { stopSelf(); return START_NOT_STICKY }
            runningTask = task
            if (!started) {
                started = true
                wakeLock = getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "$packageName:generation").apply { acquire(16 * 60 * 1000L) }
            }
            ready?.complete(Unit)
        } catch (_: Exception) {
            ready?.completeExceptionally(ApiFailure(503, "系统不允许启动后台生成服务，请返回应用后重试"))
            stopSelf()
        }
        return START_NOT_STICKY
    }
    override fun onTimeout(startId: Int, fgsType: Int) {
        (application as MeimeiApplication).chat.stop()
        stopSelf()
    }
    override fun onDestroy() {
        wakeLock?.let { if (it.isHeld) it.release() }; wakeLock = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
        // An unexpected service shutdown must not leave an unprotected stream running.
        val chat = (application as MeimeiApplication).chat
        if (chat.streaming && chat.activeGeneration == task) chat.stop()
        if (runningTask == task) runningTask = null
    }
    companion object {
        private const val CHANNEL = "answer_generation"
        private const val STOP = "asia.feng.aimeimei.STOP_GENERATION"
        private var ready: CompletableDeferred<Unit>? = null
        private var runningTask: Int? = null
        suspend fun begin(context: Context, task: Int) {
            val signal = CompletableDeferred<Unit>(); ready = signal
            try { context.startForegroundService(Intent(context, GenerationService::class.java).putExtra("task", task)); withTimeout(8000) { signal.await() } }
            finally { if (ready === signal) ready = null }
        }
        fun end(context: Context, task: Int) { if (runningTask == task) context.stopService(Intent(context, GenerationService::class.java)) }
    }
}
