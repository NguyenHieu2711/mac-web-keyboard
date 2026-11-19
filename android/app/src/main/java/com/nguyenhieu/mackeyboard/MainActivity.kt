package com.nguyenhieu.mackeyboard

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.app.DownloadManager
import android.content.BroadcastReceiver
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ActivityInfo
import android.content.pm.PackageManager
import android.graphics.Color
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.net.Uri
import android.util.Base64
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.provider.Settings
import android.speech.RecognizerIntent
import android.text.InputType
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.PermissionRequest
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.SeekBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.lifecycleScope
import androidx.webkit.WebViewAssetLoader
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

class MainActivity : AppCompatActivity() {

    companion object {
        private const val PREFS_NAME = "mac_web_keyboard_prefs"
        private const val KEY_SERVER_HOST = "server_host"
        private const val KEY_TRACKPAD_SPEED = "trackpad_speed"
        private const val KEY_OTA_WEB_VERSION = "ota_web_version"
        private const val DEFAULT_TRACKPAD_SPEED = 1.6f
        private const val LOCAL_KEYBOARD_URL = "http://appassets.androidplatform.net/assets/index.html"
    }

    private lateinit var webView: WebView
    private var activeDownloadId: Long = -1L
    private var activeUpdateApkFile: File? = null
    private var pendingInstallApkFile: File? = null
    private var mandatoryUpdateDialog: AlertDialog? = null
    private var downloadPollJob: Job? = null
    private var installTriggeredForId: Long = -1L
    private var lastBackPressedAt: Long = 0L
    private var pendingWebPermissionRequest: PermissionRequest? = null
    private var pendingVoiceLang: String? = null
    private var pendingPcmMicSpec: Triple<Int, Int, Int>? = null
    @Volatile private var pcmMicRunning: Boolean = false
    private var pcmMicThread: Thread? = null

    private val audioPermLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        val webReq = pendingWebPermissionRequest
        pendingWebPermissionRequest = null
        if (webReq != null) {
            if (granted) {
                webReq.grant(webReq.resources)
            } else {
                webReq.deny()
            }
        }
        val pcmSpec = pendingPcmMicSpec
        pendingPcmMicSpec = null
        if (pcmSpec != null) {
            if (granted) {
                startNativePcmMicStream(pcmSpec.first, pcmSpec.second, pcmSpec.third)
            } else {
                webView.evaluateJavascript("window.__onRemoteMicCaptureState && window.__onRemoteMicCaptureState(false);", null)
                Toast.makeText(this, "Cần cấp quyền Microphone để dùng Mic trên Remote PC.", Toast.LENGTH_SHORT).show()
            }
        }
        val lang = pendingVoiceLang
        pendingVoiceLang = null
        if (lang != null) {
            if (granted) {
                launchNativeSpeechRecognizer(lang)
            } else {
                webView.evaluateJavascript("window.__onRemoteVoiceState && window.__onRemoteVoiceState(false);", null)
                Toast.makeText(this, "Cần cấp quyền Microphone để đọc giọng nói.", Toast.LENGTH_SHORT).show()
            }
        }
    }

    @SuppressLint("MissingPermission")
    private fun startNativePcmMicStream(sampleRate: Int, channels: Int, framesPerPacket: Int) {
        stopNativePcmMicStream()
        val safeRate = if (sampleRate in 8000..48000) sampleRate else 44100
        val safeChannels = if (channels >= 2) 2 else 1
        val chanCfg = if (safeChannels == 2) AudioFormat.CHANNEL_IN_STEREO else AudioFormat.CHANNEL_IN_MONO
        val bytesPerFrame = safeChannels * 2
        val packetBytes = (framesPerPacket.coerceIn(240, 2400)) * bytesPerFrame
        val minBuf = AudioRecord.getMinBufferSize(safeRate, chanCfg, AudioFormat.ENCODING_PCM_16BIT)
            .coerceAtLeast(packetBytes * 4)

        pcmMicRunning = true
        pcmMicThread = Thread {
            var recorder: AudioRecord? = null
            try {
                recorder = AudioRecord(
                    MediaRecorder.AudioSource.VOICE_COMMUNICATION,
                    safeRate,
                    chanCfg,
                    AudioFormat.ENCODING_PCM_16BIT,
                    minBuf
                )
                if (recorder.state != AudioRecord.STATE_INITIALIZED) {
                    recorder.release()
                    recorder = AudioRecord(
                        MediaRecorder.AudioSource.MIC,
                        safeRate,
                        chanCfg,
                        AudioFormat.ENCODING_PCM_16BIT,
                        minBuf
                    )
                }
                if (recorder.state != AudioRecord.STATE_INITIALIZED) {
                    pcmMicRunning = false
                    runOnUiThread {
                        webView.evaluateJavascript("window.__onRemoteMicCaptureState && window.__onRemoteMicCaptureState(false);", null)
                    }
                    return@Thread
                }

                recorder.startRecording()
                runOnUiThread {
                    webView.evaluateJavascript("window.__onRemoteMicCaptureState && window.__onRemoteMicCaptureState(true);", null)
                }

                val buf = ByteArray(packetBytes)
                while (pcmMicRunning) {
                    var totalRead = 0
                    while (pcmMicRunning && totalRead < packetBytes) {
                        val r = recorder.read(buf, totalRead, packetBytes - totalRead)
                        if (r <= 0) break
                        totalRead += r
                    }
                    if (totalRead > 0 && pcmMicRunning) {
                        val b64 = Base64.encodeToString(buf, 0, totalRead, Base64.NO_WRAP)
                        webView.post {
                            if (pcmMicRunning) {
                                webView.evaluateJavascript("window.__onNativeMicPcm && window.__onNativeMicPcm('$b64');", null)
                            }
                        }
                    }
                }
            } catch (_: Exception) {
            } finally {
                try {
                    recorder?.stop()
                } catch (_: Exception) {
                }
                try {
                    recorder?.release()
                } catch (_: Exception) {
                }
                runOnUiThread {
                    webView.evaluateJavascript("window.__onRemoteMicCaptureState && window.__onRemoteMicCaptureState(false);", null)
                }
            }
        }.apply {
            name = "RemotePcMicThread"
            isDaemon = true
            start()
        }
    }

    private fun stopNativePcmMicStream() {
        pcmMicRunning = false
        pcmMicThread?.let { t ->
            try {
                t.join(250)
            } catch (_: Exception) {
            }
        }
        pcmMicThread = null
    }

    private val voiceResultLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        applyImmersiveStickyFullscreen()
        webView.evaluateJavascript("window.__onRemoteVoiceState && window.__onRemoteVoiceState(false);", null)
        if (result.resultCode == Activity.RESULT_OK) {
            val matches = result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
            val best = matches?.firstOrNull()?.trim().orEmpty()
            if (best.isNotEmpty()) {
                val escaped = JSONObject.quote(best)
                webView.evaluateJavascript(
                    "window.__onRemoteVoiceText && window.__onRemoteVoiceText($escaped);",
                    null
                )
            }
        }
    }

    private fun launchNativeSpeechRecognizer(lang: String) {
        try {
            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, lang.ifBlank { "vi-VN" })
                putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
            }
            webView.evaluateJavascript("window.__onRemoteVoiceState && window.__onRemoteVoiceState(true);", null)
            voiceResultLauncher.launch(intent)
        } catch (_: Exception) {
            webView.evaluateJavascript("window.__onRemoteVoiceState && window.__onRemoteVoiceState(false);", null)
            Toast.makeText(this, "Thiết bị chưa bật dịch vụ nhận diện giọng nói.", Toast.LENGTH_SHORT).show()
        }
    }

    private val downloadCompleteReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action != DownloadManager.ACTION_DOWNLOAD_COMPLETE) return
            val completedId = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1L)
            if (completedId == -1L || completedId != activeDownloadId) return

            val dm = getSystemService(Context.DOWNLOAD_SERVICE) as? DownloadManager ?: return
            handleDownloadStatusCheck(dm, completedId)
        }
    }

    private fun handleDownloadStatusCheck(dm: DownloadManager, downloadId: Long): Boolean {
        if (downloadId == -1L || installTriggeredForId == downloadId) return true
        val query = DownloadManager.Query().setFilterById(downloadId)
        dm.query(query)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val statusIdx = cursor.getColumnIndex(DownloadManager.COLUMN_STATUS)
                if (statusIdx >= 0) {
                    when (cursor.getInt(statusIdx)) {
                        DownloadManager.STATUS_SUCCESSFUL -> {
                            installTriggeredForId = downloadId
                            downloadPollJob?.cancel()
                            mandatoryUpdateDialog?.dismiss()
                            mandatoryUpdateDialog = null
                            activeUpdateApkFile?.let { apkFile ->
                                if (apkFile.exists()) {
                                    promptInstallApk(apkFile)
                                }
                            }
                            return true
                        }
                        DownloadManager.STATUS_FAILED -> {
                            installTriggeredForId = downloadId
                            downloadPollJob?.cancel()
                            mandatoryUpdateDialog?.dismiss()
                            mandatoryUpdateDialog = null
                            Toast.makeText(
                                this@MainActivity,
                                "Tải bản cập nhật thất bại, vui lòng bấm thử lại.",
                                Toast.LENGTH_SHORT
                            ).show()
                            return true
                        }
                    }
                }
            }
        }
        return false
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Giữ màn hình luôn sáng khi dùng làm bàn phím rời cho MacBook & dùng phím cứng chỉnh âm lượng Loa Remote PC
        volumeControlStream = AudioManager.STREAM_MUSIC
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            window.attributes = window.attributes.apply {
                layoutInDisplayCutoutMode =
                    WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            }
        }
        applyImmersiveStickyFullscreen()

        ContextCompat.registerReceiver(
            this,
            downloadCompleteReceiver,
            IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE),
            ContextCompat.RECEIVER_EXPORTED
        )

        val assetLoader = WebViewAssetLoader.Builder()
            .setDomain("appassets.androidplatform.net")
            .setHttpAllowed(true)
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()

        cleanupStaleOtaWebCache()

        webView = WebView(this).apply {
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
            setBackgroundColor(Color.parseColor("#090C12"))
            isVerticalScrollBarEnabled = false
            isHorizontalScrollBarEnabled = false
            overScrollMode = WebView.OVER_SCROLL_NEVER

            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                cacheMode = WebSettings.LOAD_NO_CACHE
                mediaPlaybackRequiresUserGesture = false
                mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
                setSupportZoom(false)
                builtInZoomControls = false
                displayZoomControls = false
                useWideViewPort = true
                loadWithOverviewMode = true
            }

            addJavascriptInterface(AndroidWebBridge(), "AndroidBridge")

            webChromeClient = object : WebChromeClient() {
                override fun onPermissionRequest(request: PermissionRequest?) {
                    if (request == null) return
                    runOnUiThread {
                        val wantsMic = request.resources.contains(PermissionRequest.RESOURCE_AUDIO_CAPTURE)
                        if (!wantsMic) {
                            request.deny()
                            return@runOnUiThread
                        }
                        if (ContextCompat.checkSelfPermission(
                                this@MainActivity,
                                Manifest.permission.RECORD_AUDIO
                            ) == PackageManager.PERMISSION_GRANTED
                        ) {
                            request.grant(request.resources)
                        } else {
                            pendingWebPermissionRequest = request
                            audioPermLauncher.launch(Manifest.permission.RECORD_AUDIO)
                        }
                    }
                }
            }

            webViewClient = object : WebViewClient() {
                override fun shouldInterceptRequest(
                    view: WebView,
                    request: WebResourceRequest
                ): WebResourceResponse? {
                    serveOtaWebAssetIfNewer(request.url)?.let { return it }
                    val u = request.url
                    if (u.host == "appassets.androidplatform.net" && u.path?.endsWith(".wasm") == true) {
                        val rel = u.path!!.removePrefix("/assets/").trimStart('/')
                        try {
                            return WebResourceResponse("application/wasm", null, assets.open(rel))
                        } catch (_: Exception) {
                        }
                    }
                    return assetLoader.shouldInterceptRequest(request.url)
                }

                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)
                    if (getSavedServerHost().isBlank()) {
                        showServerConfigDialog(isFirstLaunch = true)
                    }
                }
            }

            setDownloadListener { url, _, _, _, _ ->
                if (url.endsWith(".apk", ignoreCase = true) || url.contains("app-release.apk")) {
                    showDownloadingLockDialog("mới")
                    startApkDownload("latest", url)
                }
            }
        }

        setContentView(webView)
        webView.loadUrl(LOCAL_KEYBOARD_URL)

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                val now = System.currentTimeMillis()
                if (now - lastBackPressedAt < 1800L) {
                    finish()
                } else {
                    lastBackPressedAt = now
                    Toast.makeText(
                        this@MainActivity,
                        "Vuốt Back lần nữa để thoát bàn phím",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            }
        })

        // Tự động kiểm tra bản cập nhật mới nhất từ GitHub Releases ngay khi mở app
        lifecycleScope.launch {
            checkForUpdatesFromGitHub(manualCheck = false)
        }
    }

    override fun onResume() {
        super.onResume()
        applyImmersiveStickyFullscreen()

        // Nếu người dùng vừa bật quyền "Cài đặt ứng dụng không xác định" rồi quay lại app -> cài ngay
        val pending = pendingInstallApkFile
        if (pending != null && pending.exists() && packageManager.canRequestPackageInstalls()) {
            pendingInstallApkFile = null
            promptInstallApk(pending)
            return
        }

        // Luôn kiểm tra bản cập nhật bắt buộc mỗi khi mở/quay lại ứng dụng
        lifecycleScope.launch {
            checkForUpdatesFromGitHub(manualCheck = false)
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) {
            applyImmersiveStickyFullscreen()
        }
    }

    override fun onDestroy() {
        stopNativePcmMicStream()
        try {
            unregisterReceiver(downloadCompleteReceiver)
        } catch (_: Exception) {
        }
        webView.destroy()
        super.onDestroy()
    }

    private fun applyImmersiveStickyFullscreen() {
        WindowCompat.setDecorFitsSystemWindows(window, false)
        val controller = WindowInsetsControllerCompat(window, window.decorView)
        controller.hide(WindowInsetsCompat.Type.statusBars() or WindowInsetsCompat.Type.navigationBars())
        controller.systemBarsBehavior =
            WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
    }

    private fun getSavedServerHost(): String {
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getString(KEY_SERVER_HOST, "")?.trim().orEmpty()
    }

    private fun getSavedTrackpadSpeed(): Float {
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getFloat(KEY_TRACKPAD_SPEED, DEFAULT_TRACKPAD_SPEED).coerceIn(0.5f, 4.0f)
    }

    private fun saveTrackpadSpeed(speed: Float) {
        val clamped = (Math.round(speed.coerceIn(0.5f, 4.0f) * 10f) / 10f)
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putFloat(KEY_TRACKPAD_SPEED, clamped)
            .apply()
        webView.evaluateJavascript(
            "window.__setTrackpadSpeed && window.__setTrackpadSpeed($clamped);",
            null
        )
    }

    private fun getOtaWebDir(): File = File(filesDir, "ota_web")

    private fun getSavedOtaWebVersion(): String {
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getString(KEY_OTA_WEB_VERSION, "")?.trim().orEmpty()
    }

    private fun getEffectiveWebVersion(): String {
        val otaVer = getSavedOtaWebVersion()
        return if (otaVer.isNotEmpty() && isRemoteVersionNewer(otaVer, BuildConfig.VERSION_NAME)) {
            otaVer
        } else {
            BuildConfig.VERSION_NAME
        }
    }

    private fun cleanupStaleOtaWebCache() {
        val otaVer = getSavedOtaWebVersion()
        if (otaVer.isEmpty() || !isRemoteVersionNewer(otaVer, BuildConfig.VERSION_NAME)) {
            try {
                getOtaWebDir().deleteRecursively()
            } catch (_: Exception) {
            }
            getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .edit()
                .remove(KEY_OTA_WEB_VERSION)
                .apply()
        }
    }

    private fun serveOtaWebAssetIfNewer(uri: Uri): WebResourceResponse? {
        if (uri.host != "appassets.androidplatform.net") return null
        val otaVer = getSavedOtaWebVersion()
        if (otaVer.isEmpty() || !isRemoteVersionNewer(otaVer, BuildConfig.VERSION_NAME)) return null

        val relName = uri.path?.removePrefix("/assets/")?.trim('/') ?: return null
        val allowed = setOf(
            "index.html",
            "style.css",
            "app.js",
            "manifest.json",
            "ironrdp/rdp_client.js",
            "ironrdp/rdp_client_bg.wasm"
        )
        if (relName !in allowed) return null

        val f = File(getOtaWebDir(), relName)
        if (!f.exists() || f.length() <= 0L) return null
        val isWasm = relName.endsWith(".wasm")
        val mime = when {
            relName.endsWith(".html") -> "text/html"
            relName.endsWith(".css") -> "text/css"
            relName.endsWith(".js") -> "application/javascript"
            isWasm -> "application/wasm"
            else -> "application/json"
        }
        return try {
            WebResourceResponse(mime, if (isWasm) null else "UTF-8", f.inputStream())
        } catch (_: Exception) {
            null
        }
    }

    private fun fetchLiveAssetFromServer(relPath: String): WebResourceResponse? {
        val rawHosts = getSavedServerHost()
        if (rawHosts.isBlank()) return null
        val candidates = rawHosts.split(",")
            .map { it.trim().replace(Regex("^https?://|^wss?://"), "").substringBefore("/") }
            .filter { it.isNotEmpty() }
            .map { if (":" in it) it else "$it:5050" }

        val targetPath = if (relPath == "index.html") "" else relPath
        val mimeType = when {
            relPath.endsWith(".html") -> "text/html"
            relPath.endsWith(".css") -> "text/css"
            relPath.endsWith(".js") -> "application/javascript"
            relPath.endsWith(".json") -> "application/json"
            else -> "text/plain"
        }

        for (host in candidates) {
            var conn: HttpURLConnection? = null
            try {
                val url = URL("http://$host/$targetPath")
                conn = (url.openConnection() as HttpURLConnection).apply {
                    requestMethod = "GET"
                    connectTimeout = 700
                    readTimeout = 1000
                    setRequestProperty("Cache-Control", "no-cache")
                }
                if (conn.responseCode == HttpURLConnection.HTTP_OK) {
                    val bytes = conn.inputStream.use { it.readBytes() }
                    return WebResourceResponse(
                        mimeType,
                        "UTF-8",
                        bytes.inputStream()
                    )
                }
            } catch (_: Exception) {
                // Thử host tiếp theo hoặc fallback về asset nội bộ
            } finally {
                conn?.disconnect()
            }
        }
        return null
    }

    private fun saveServerHost(rawHost: String) {
        val cleaned = rawHost.trim()
        val prev = getSavedServerHost()
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_SERVER_HOST, cleaned)
            .apply()

        if (cleaned != prev) {
            val escaped = JSONObject.quote(cleaned)
            webView.evaluateJavascript("window.__applyServerHost && window.__applyServerHost($escaped);", null)
        }
    }

    private fun showServerConfigDialog(isFirstLaunch: Boolean = false) {
        val density = resources.displayMetrics.density
        val padH = (20 * density).toInt()
        val padV = (10 * density).toInt()
        val gapV = (14 * density).toInt()

        var currentSpeed = getSavedTrackpadSpeed()
        val speedTitle = TextView(this).apply {
            text = String.format("Tốc độ trượt Trackpad: %.1fx", currentSpeed)
            textSize = 14.5f
            setPadding(0, 0, 0, (4 * density).toInt())
        }

        val speedSeek = SeekBar(this).apply {
            max = 35 // 0.5x -> 4.0x (bước 0.1x)
            progress = Math.round((currentSpeed - 0.5f) * 10f).coerceIn(0, 35)
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(seekBar: SeekBar?, progress: Int, fromUser: Boolean) {
                    currentSpeed = (5 + progress) / 10f
                    speedTitle.text = String.format("Tốc độ trượt Trackpad: %.1fx", currentSpeed)
                    if (fromUser) {
                        saveTrackpadSpeed(currentSpeed)
                    }
                }

                override fun onStartTrackingTouch(seekBar: SeekBar?) {}
                override fun onStopTrackingTouch(seekBar: SeekBar?) {
                    saveTrackpadSpeed(currentSpeed)
                }
            })
        }

        val ipLabel = TextView(this).apply {
            text = "Địa chỉ IP MacBook / PC (ngăn cách dấu phẩy nếu dùng cả LAN & Tailscale):"
            textSize = 13f
            setPadding(0, gapV, 0, (4 * density).toInt())
        }

        val input = EditText(this).apply {
            setText(getSavedServerHost())
            hint = "VD: 192.168.1.20:5050, 100.88.1.5:5050"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine(true)
            setSelection(text.length)
        }

        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(padH, padV, padH, 0)
            addView(speedTitle)
            addView(speedSeek)
            addView(ipLabel)
            addView(input)
        }

        val builder = AlertDialog.Builder(this)
            .setTitle("Cài đặt (v${getEffectiveWebVersion()})")
            .setView(container)
            .setPositiveButton("Lưu") { _, _ ->
                saveTrackpadSpeed(currentSpeed)
                saveServerHost(input.text?.toString().orEmpty())
                applyImmersiveStickyFullscreen()
            }
            .setNeutralButton("Cập nhật") { _, _ ->
                applyImmersiveStickyFullscreen()
                lifecycleScope.launch {
                    checkForUpdatesFromGitHub(manualCheck = true)
                }
            }

        if (!isFirstLaunch) {
            builder.setNegativeButton("Đóng") { dialog, _ ->
                dialog.dismiss()
                applyImmersiveStickyFullscreen()
            }
        }

        val dialog = builder.create()
        dialog.setOnDismissListener {
            applyImmersiveStickyFullscreen()
        }
        dialog.show()
    }

    private fun triggerNativeVibration(durationMs: Long) {
        val clamped = durationMs.coerceIn(5L, 40L)
        try {
            val vibrator: Vibrator? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val vm = getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager
                vm?.defaultVibrator
            } else {
                @Suppress("DEPRECATION")
                getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
            }
            vibrator?.vibrate(
                VibrationEffect.createOneShot(clamped, VibrationEffect.DEFAULT_AMPLITUDE)
            )
        } catch (_: Exception) {
        }
    }

    // =========================================================================
    // IN-APP AUTO-UPDATE TỪ GITHUB RELEASES (DownloadManager + FileProvider)
    // =========================================================================
    private suspend fun checkForUpdatesFromGitHub(manualCheck: Boolean) {
        val manifestJson = withContext(Dispatchers.IO) {
            fetchRawManifestJson()
        }
        val remoteWebVer = manifestJson?.optString("web_version", "")?.trim().orEmpty()

        val releaseInfo = withContext(Dispatchers.IO) {
            if (manifestJson != null) {
                val t = manifestJson.optString("tag_name", "").trim()
                val u = manifestJson.optString("apk_url", "").trim()
                if (t.isNotEmpty() && u.isNotEmpty()) Pair(t, u) else fetchFromGitHubReleasesApi()
            } else {
                fetchLatestGitHubRelease()
            }
        }

        if (releaseInfo != null) {
            val (tagName, apkDownloadUrl) = releaseInfo
            if (isRemoteVersionNewer(tagName, BuildConfig.VERSION_NAME)) {
                showMandatoryUpdateDialog(tagName, apkDownloadUrl)
                return
            }
        }

        // Nếu vỏ APK đã mới nhất, kiểm tra tiếp gói giao diện OTA (cập nhật ngầm 0.5s không cần cài lại APK)
        if (remoteWebVer.isNotEmpty() && isRemoteVersionNewer(remoteWebVer, getEffectiveWebVersion())) {
            val updatedOk = withContext(Dispatchers.IO) {
                downloadOtaWebAssets(remoteWebVer)
            }
            if (updatedOk) {
                webView.reload()
                Toast.makeText(
                    this,
                    "Đã tự cập nhật giao diện mới (v$remoteWebVer)",
                    Toast.LENGTH_SHORT
                ).show()
                return
            }
        }

        if (manualCheck) {
            val msg = if (releaseInfo == null && manifestJson == null) {
                "Không thể kiểm tra cập nhật lúc này."
            } else {
                "Bạn đang ở bản mới nhất (v${getEffectiveWebVersion()})."
            }
            Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
        }
    }

    private fun buildLanUpdateHttpBases(): List<String> {
        val result = mutableListOf("http://192.168.52.230:5051")
        val rawHosts = getSavedServerHost()
        if (rawHosts.isNotBlank()) {
            rawHosts.split(",")
                .map { it.trim().replace(Regex("^https?://|^wss?://"), "").substringBefore("/") }
                .filter { it.isNotEmpty() }
                .forEach { h ->
                    val withPort = if (":" in h) h else "$h:5050"
                    result.add("http://$withPort")
                }
        }
        return result.distinct()
    }

    private fun resolveLatestGithubCommitSha(): String? {
        val apiUrl = "https://api.github.com/repos/${BuildConfig.GITHUB_REPO}/commits/main"
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(apiUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 4500
                readTimeout = 4500
                setRequestProperty("Accept", "application/vnd.github+json")
                setRequestProperty("Cache-Control", "no-cache")
                setRequestProperty("User-Agent", "MacWebKeyboard-Android/${BuildConfig.VERSION_NAME}")
            }
            if (conn.responseCode != HttpURLConnection.HTTP_OK) return null
            val body = conn.inputStream.bufferedReader().use { it.readText() }
            JSONObject(body).optString("sha", "").trim().ifEmpty { null }
        } catch (_: Exception) {
            null
        } finally {
            conn?.disconnect()
        }
    }

    private fun fetchRawManifestJson(): JSONObject? {
        // 1. Ưu tiên đọc trực tiếp từ máy chủ LAN (:5051 trên PC hoặc :5050 trên MacBook — 0ms trễ CDN!)
        for (base in buildLanUpdateHttpBases()) {
            var conn: HttpURLConnection? = null
            try {
                conn = (URL("$base/web-manifest?t=${System.currentTimeMillis()}").openConnection() as HttpURLConnection).apply {
                    requestMethod = "GET"
                    connectTimeout = 900
                    readTimeout = 1200
                    setRequestProperty("Cache-Control", "no-cache")
                }
                if (conn.responseCode == HttpURLConnection.HTTP_OK) {
                    val body = conn.inputStream.bufferedReader().use { it.readText() }
                    val j = JSONObject(body)
                    if (j.optString("web_version", "").isNotEmpty()) return j
                }
            } catch (_: Exception) {
            } finally {
                conn?.disconnect()
            }
        }

        // 2. Dự phòng qua GitHub: dùng SHA mới nhất để không bao giờ dính cache 5 phút của Fastly CDN
        val ref = resolveLatestGithubCommitSha() ?: "main"
        val rawUrl =
            "https://raw.githubusercontent.com/${BuildConfig.GITHUB_REPO}/$ref/releases/latest.json?t=${System.currentTimeMillis()}"
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(rawUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 5000
                readTimeout = 5000
                setRequestProperty("Cache-Control", "no-cache")
                setRequestProperty("User-Agent", "MacWebKeyboard-Android/${BuildConfig.VERSION_NAME}")
            }
            if (conn.responseCode != HttpURLConnection.HTTP_OK) return null
            val body = conn.inputStream.bufferedReader().use { it.readText() }
            JSONObject(body)
        } catch (_: Exception) {
            null
        } finally {
            conn?.disconnect()
        }
    }

    private fun downloadOtaWebAssets(targetWebVersion: String): Boolean {
        val files = listOf("index.html", "style.css", "app.js", "manifest.json")
        val tmpDir = File(filesDir, "ota_web_tmp")
        return try {
            tmpDir.deleteRecursively()
            tmpDir.mkdirs()
            val ts = System.currentTimeMillis()
            var fetchedFromLan = false

            for (base in buildLanUpdateHttpBases()) {
                var allOk = true
                for (name in files) {
                    val pathPart = if (base.endsWith(":5051")) "/static/$name" else "/$name".replace("/index.html", "/")
                    var conn: HttpURLConnection? = null
                    try {
                        conn = (URL("$base$pathPart?t=$ts").openConnection() as HttpURLConnection).apply {
                            requestMethod = "GET"
                            connectTimeout = 1200
                            readTimeout = 2500
                            setRequestProperty("Cache-Control", "no-cache")
                        }
                        if (conn.responseCode != HttpURLConnection.HTTP_OK) {
                            allOk = false
                            break
                        }
                        val bytes = conn.inputStream.use { it.readBytes() }
                        if (bytes.isEmpty()) {
                            allOk = false
                            break
                        }
                        File(tmpDir, name).writeBytes(bytes)
                    } catch (_: Exception) {
                        allOk = false
                        break
                    } finally {
                        conn?.disconnect()
                    }
                }
                if (allOk) {
                    fetchedFromLan = true
                    break
                }
            }

            if (!fetchedFromLan) {
                val ref = resolveLatestGithubCommitSha() ?: "main"
                for (name in files) {
                    val u = "https://raw.githubusercontent.com/${BuildConfig.GITHUB_REPO}/$ref/static/$name?t=$ts"
                    var conn: HttpURLConnection? = null
                    try {
                        conn = (URL(u).openConnection() as HttpURLConnection).apply {
                            requestMethod = "GET"
                            connectTimeout = 6000
                            readTimeout = 8000
                            setRequestProperty("Cache-Control", "no-cache")
                        }
                        if (conn.responseCode != HttpURLConnection.HTTP_OK) return false
                        val bytes = conn.inputStream.use { it.readBytes() }
                        if (bytes.isEmpty()) return false
                        File(tmpDir, name).writeBytes(bytes)
                    } finally {
                        conn?.disconnect()
                    }
                }
            }
            val finalDir = getOtaWebDir()
            finalDir.deleteRecursively()
            if (!tmpDir.renameTo(finalDir)) {
                finalDir.mkdirs()
                for (name in files) {
                    File(tmpDir, name).copyTo(File(finalDir, name), overwrite = true)
                }
                tmpDir.deleteRecursively()
            }
            getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .edit()
                .putString(KEY_OTA_WEB_VERSION, targetWebVersion)
                .apply()
            true
        } catch (_: Exception) {
            false
        }
    }

    private fun showMandatoryUpdateDialog(tagName: String, apkDownloadUrl: String) {
        if (isFinishing || isDestroyed) return
        mandatoryUpdateDialog?.let {
            if (it.isShowing) return
        }

        val existingApk = activeUpdateApkFile
        if (existingApk != null && existingApk.exists()) {
            val readyDialog = AlertDialog.Builder(this)
                .setTitle("Cập nhật bắt buộc ($tagName)")
                .setMessage("Bản cập nhật $tagName đã tải xong. Bạn bắt buộc phải cài đặt bản mới để tiếp tục sử dụng ứng dụng.")
                .setCancelable(false)
                .setPositiveButton("Cài đặt ngay") { _, _ ->
                    mandatoryUpdateDialog = null
                    promptInstallApk(existingApk)
                }
                .create()
            mandatoryUpdateDialog = readyDialog
            readyDialog.show()
            return
        }

        val dialog = AlertDialog.Builder(this)
            .setTitle("Có bản cập nhật mới ($tagName)")
            .setMessage("Phiên bản mới $tagName đã sẵn sàng (bản hiện tại: v${BuildConfig.VERSION_NAME}).\n\nBạn cần cập nhật ngay để tiếp tục vào ứng dụng.")
            .setCancelable(false)
            .setPositiveButton("Cập nhật ngay") { _, _ ->
                showDownloadingLockDialog(tagName)
                startApkDownload(tagName, apkDownloadUrl)
            }
            .create()

        mandatoryUpdateDialog = dialog
        dialog.show()
    }

    private fun showDownloadingLockDialog(tagName: String) {
        if (isFinishing || isDestroyed) return
        mandatoryUpdateDialog?.dismiss()
        val progressDialog = AlertDialog.Builder(this)
            .setTitle("Đang tải bản cập nhật $tagName...")
            .setMessage("Vui lòng chờ giây lát, gói cài đặt sẽ tự động bật lên ngay khi tải xong.")
            .setCancelable(false)
            .create()
        mandatoryUpdateDialog = progressDialog
        progressDialog.show()
    }

    private fun fetchLatestGitHubRelease(): Pair<String, String>? {
        return fetchFromGitHubReleasesApi() ?: fetchFromRawRepoManifest()
    }

    private fun fetchFromGitHubReleasesApi(): Pair<String, String>? {
        val apiUrl = "https://api.github.com/repos/${BuildConfig.GITHUB_REPO}/releases/latest"
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(apiUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 6000
                readTimeout = 6000
                setRequestProperty("Accept", "application/vnd.github+json")
                setRequestProperty("User-Agent", "MacWebKeyboard-Android/${BuildConfig.VERSION_NAME}")
            }
            if (conn.responseCode != HttpURLConnection.HTTP_OK) {
                return null
            }
            val body = conn.inputStream.bufferedReader().use { it.readText() }
            val json = JSONObject(body)
            val tagName = json.optString("tag_name", "").trim()
            if (tagName.isEmpty()) return null

            val assets = json.optJSONArray("assets") ?: return null
            var chosenUrl = ""
            for (i in 0 until assets.length()) {
                val asset = assets.optJSONObject(i) ?: continue
                val name = asset.optString("name", "")
                val url = asset.optString("browser_download_url", "")
                if (name.endsWith(".apk", ignoreCase = true) && url.isNotEmpty()) {
                    chosenUrl = url
                    if (name.equals("app-release.apk", ignoreCase = true)) {
                        break
                    }
                }
            }
            if (chosenUrl.isEmpty()) null else Pair(tagName, chosenUrl)
        } catch (_: Exception) {
            null
        } finally {
            conn?.disconnect()
        }
    }

    private fun fetchFromRawRepoManifest(): Pair<String, String>? {
        val rawUrl =
            "https://raw.githubusercontent.com/${BuildConfig.GITHUB_REPO}/main/releases/latest.json?t=${System.currentTimeMillis()}"
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(rawUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 6000
                readTimeout = 6000
                setRequestProperty("Cache-Control", "no-cache")
                setRequestProperty("User-Agent", "MacWebKeyboard-Android/${BuildConfig.VERSION_NAME}")
            }
            if (conn.responseCode != HttpURLConnection.HTTP_OK) {
                return null
            }
            val body = conn.inputStream.bufferedReader().use { it.readText() }
            val json = JSONObject(body)
            val tagName = json.optString("tag_name", "").trim()
            val apkUrl = json.optString("apk_url", "").trim()
            if (tagName.isEmpty() || apkUrl.isEmpty()) null else Pair(tagName, apkUrl)
        } catch (_: Exception) {
            null
        } finally {
            conn?.disconnect()
        }
    }

    private fun isRemoteVersionNewer(remoteTag: String, currentVersion: String): Boolean {
        val cleanRemote = remoteTag.trim().removePrefix("v").removePrefix("V").substringBefore("-")
        val cleanCurrent = currentVersion.trim().removePrefix("v").removePrefix("V").substringBefore("-")
        if (cleanRemote.isEmpty() || cleanRemote == cleanCurrent) return false

        val remoteParts = cleanRemote.split(".").map { it.toIntOrNull() ?: 0 }
        val currentParts = cleanCurrent.split(".").map { it.toIntOrNull() ?: 0 }
        val maxLen = maxOf(remoteParts.size, currentParts.size)

        for (i in 0 until maxLen) {
            val r = remoteParts.getOrElse(i) { 0 }
            val c = currentParts.getOrElse(i) { 0 }
            if (r > c) return true
            if (r < c) return false
        }
        return false
    }

    private fun startApkDownload(tagName: String, apkUrl: String) {
        try {
            val safeTag = tagName.replace(Regex("[^a-zA-Z0-9._-]"), "_")
            val fileName = "app-release-$safeTag.apk"
            val downloadsDir = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: return

            // Xóa các bản APK cũ trong thư mục cập nhật của app để tiết kiệm bộ nhớ
            downloadsDir.listFiles()?.forEach { f ->
                if (f.name.endsWith(".apk", ignoreCase = true)) {
                    f.delete()
                }
            }

            val targetFile = File(downloadsDir, fileName)
            activeUpdateApkFile = targetFile

            val request = DownloadManager.Request(Uri.parse(apkUrl))
                .setTitle("Cập nhật Mac Keyboard ($tagName)")
                .setDescription("Đang tải gói cài đặt từ GitHub Releases...")
                .setMimeType("application/vnd.android.package-archive")
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE)
                .setAllowedOverMetered(true)
                .setAllowedOverRoaming(true)
                .setDestinationInExternalFilesDir(
                    this,
                    Environment.DIRECTORY_DOWNLOADS,
                    fileName
                )

            val dm = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
            installTriggeredForId = -1L
            activeDownloadId = dm.enqueue(request)

            // Polling dự phòng mỗi 600ms để bật trình cài đặt ngay lập tức trên Samsung One UI
            downloadPollJob?.cancel()
            downloadPollJob = lifecycleScope.launch {
                while (isActive && activeDownloadId != -1L) {
                    delay(600L)
                    if (handleDownloadStatusCheck(dm, activeDownloadId)) {
                        break
                    }
                }
            }
        } catch (e: Exception) {
            Toast.makeText(
                this,
                "Không thể khởi tạo tải APK: ${e.message}",
                Toast.LENGTH_SHORT
            ).show()
        }
    }

    private fun promptInstallApk(apkFile: File) {
        if (!packageManager.canRequestPackageInstalls()) {
            pendingInstallApkFile = apkFile
            Toast.makeText(
                this,
                "Hãy bật quyền 'Cài đặt ứng dụng không xác định' cho Mac Keyboard để cập nhật.",
                Toast.LENGTH_LONG
            ).show()
            val permIntent = Intent(
                Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:$packageName")
            )
            startActivity(permIntent)
            return
        }

        try {
            val apkUri = FileProvider.getUriForFile(
                this,
                "$packageName.fileprovider",
                apkFile
            )
            val installIntent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(apkUri, "application/vnd.android.package-archive")
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            startActivity(installIntent)
        } catch (e: Exception) {
            Toast.makeText(
                this,
                "Lỗi mở bộ cài đặt APK: ${e.message}",
                Toast.LENGTH_LONG
            ).show()
        }
    }

    inner class AndroidWebBridge {
        @JavascriptInterface
        fun getServerHost(): String = getSavedServerHost()

        @JavascriptInterface
        fun openServerDialog() {
            runOnUiThread {
                showServerConfigDialog(isFirstLaunch = false)
            }
        }

        @JavascriptInterface
        fun vibrate(ms: Long) {
            triggerNativeVibration(ms)
        }

        @JavascriptInterface
        fun getAppVersion(): String = getEffectiveWebVersion()

        @JavascriptInterface
        fun getTrackpadSpeed(): Float = getSavedTrackpadSpeed()

        @JavascriptInterface
        fun setTrackpadSpeed(speed: Float) {
            runOnUiThread {
                saveTrackpadSpeed(speed)
            }
        }

        @JavascriptInterface
        fun startNativeUpdate() {
            runOnUiThread {
                lifecycleScope.launch {
                    checkForUpdatesFromGitHub(manualCheck = true)
                }
            }
        }

        @JavascriptInterface
        fun setOrientation(mode: String) {
            runOnUiThread {
                requestedOrientation = if (mode.equals("portrait", ignoreCase = true)) {
                    ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
                } else {
                    ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
                }
                applyImmersiveStickyFullscreen()
            }
        }

        @JavascriptInterface
        fun startVoiceInput(lang: String) {
            runOnUiThread {
                if (ContextCompat.checkSelfPermission(
                        this@MainActivity,
                        Manifest.permission.RECORD_AUDIO
                    ) == PackageManager.PERMISSION_GRANTED
                ) {
                    launchNativeSpeechRecognizer(lang)
                } else {
                    pendingVoiceLang = lang.ifBlank { "vi-VN" }
                    audioPermLauncher.launch(Manifest.permission.RECORD_AUDIO)
                }
            }
        }

        @JavascriptInterface
        fun startPcmMicCapture(sampleRate: Int, channels: Int, framesPerPacket: Int) {
            runOnUiThread {
                if (ContextCompat.checkSelfPermission(
                        this@MainActivity,
                        Manifest.permission.RECORD_AUDIO
                    ) == PackageManager.PERMISSION_GRANTED
                ) {
                    startNativePcmMicStream(sampleRate, channels, framesPerPacket)
                } else {
                    pendingPcmMicSpec = Triple(sampleRate, channels, framesPerPacket)
                    audioPermLauncher.launch(Manifest.permission.RECORD_AUDIO)
                }
            }
        }

        @JavascriptInterface
        fun stopPcmMicCapture() {
            stopNativePcmMicStream()
        }

        @JavascriptInterface
        fun hasNativePcmMic(): Boolean = true

        @JavascriptInterface
        fun ensureMicPermission() {
            runOnUiThread {
                if (ContextCompat.checkSelfPermission(
                        this@MainActivity,
                        Manifest.permission.RECORD_AUDIO
                    ) != PackageManager.PERMISSION_GRANTED
                ) {
                    audioPermLauncher.launch(Manifest.permission.RECORD_AUDIO)
                }
            }
        }

        @JavascriptInterface
        fun getClipboardText(): String {
            return try {
                val cm = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                cm?.primaryClip?.getItemAt(0)?.coerceToText(this@MainActivity)?.toString().orEmpty()
            } catch (_: Exception) {
                ""
            }
        }

        @JavascriptInterface
        fun setClipboardText(text: String) {
            try {
                val cm = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager ?: return
                cm.setPrimaryClip(ClipData.newPlainText("RemotePC", text))
            } catch (_: Exception) {
            }
        }
    }
}
