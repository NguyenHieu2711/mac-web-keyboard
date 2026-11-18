package com.nguyenhieu.mackeyboard

import android.annotation.SuppressLint
import android.app.AlertDialog
import android.app.DownloadManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ActivityInfo
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.provider.Settings
import android.text.InputType
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.JavascriptInterface
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

        // Giữ màn hình luôn sáng khi dùng làm bàn phím rời cho MacBook
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

            webViewClient = object : WebViewClient() {
                override fun shouldInterceptRequest(
                    view: WebView,
                    request: WebResourceRequest
                ): WebResourceResponse? {
                    serveOtaWebAssetIfNewer(request.url)?.let { return it }
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
        if (relName !in listOf("index.html", "style.css", "app.js", "manifest.json")) return null

        val f = File(getOtaWebDir(), relName)
        if (!f.exists() || f.length() <= 0L) return null
        val mime = when {
            relName.endsWith(".html") -> "text/html"
            relName.endsWith(".css") -> "text/css"
            relName.endsWith(".js") -> "application/javascript"
            else -> "application/json"
        }
        return try {
            WebResourceResponse(mime, "UTF-8", f.inputStream())
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

    private fun fetchRawManifestJson(): JSONObject? {
        val rawUrl =
            "https://raw.githubusercontent.com/${BuildConfig.GITHUB_REPO}/main/releases/latest.json?t=${System.currentTimeMillis()}"
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
            for (name in files) {
                val u = "https://raw.githubusercontent.com/${BuildConfig.GITHUB_REPO}/main/static/$name?t=$ts"
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
    }
}
