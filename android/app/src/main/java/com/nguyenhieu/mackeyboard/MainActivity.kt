package com.nguyenhieu.mackeyboard

import android.annotation.SuppressLint
import android.app.AlertDialog
import android.app.DownloadManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
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
        private const val LOCAL_KEYBOARD_URL = "http://appassets.androidplatform.net/assets/index.html"
    }

    private lateinit var webView: WebView
    private var activeDownloadId: Long = -1L
    private var activeUpdateApkFile: File? = null
    private var pendingInstallApkFile: File? = null
    private var lastBackPressedAt: Long = 0L

    private val downloadCompleteReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action != DownloadManager.ACTION_DOWNLOAD_COMPLETE) return
            val completedId = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1L)
            if (completedId == -1L || completedId != activeDownloadId) return

            val dm = getSystemService(Context.DOWNLOAD_SERVICE) as? DownloadManager ?: return
            val query = DownloadManager.Query().setFilterById(completedId)
            dm.query(query)?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val statusIdx = cursor.getColumnIndex(DownloadManager.COLUMN_STATUS)
                    if (statusIdx >= 0 && cursor.getInt(statusIdx) == DownloadManager.STATUS_SUCCESSFUL) {
                        activeUpdateApkFile?.let { apkFile ->
                            if (apkFile.exists()) {
                                promptInstallApk(apkFile)
                            }
                        }
                    } else {
                        Toast.makeText(
                            this@MainActivity,
                            "Tải bản cập nhật thất bại, vui lòng thử lại sau.",
                            Toast.LENGTH_SHORT
                        ).show()
                    }
                }
            }
        }
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
                    return assetLoader.shouldInterceptRequest(request.url)
                }

                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)
                    if (getSavedServerHost().isBlank()) {
                        showServerConfigDialog(isFirstLaunch = true)
                    }
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

    private fun saveServerHost(rawHost: String) {
        val cleaned = rawHost.trim()
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_SERVER_HOST, cleaned)
            .apply()

        val escaped = JSONObject.quote(cleaned)
        webView.evaluateJavascript("window.__applyServerHost && window.__applyServerHost($escaped);", null)
    }

    private fun showServerConfigDialog(isFirstLaunch: Boolean = false) {
        val density = resources.displayMetrics.density
        val padH = (20 * density).toInt()
        val padV = (12 * density).toInt()

        val input = EditText(this).apply {
            setText(getSavedServerHost())
            hint = "VD: 100.88.1.5:5050 hoặc 192.168.1.20:5050"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine(true)
            setSelection(text.length)
        }

        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(padH, padV, padH, 0)
            addView(input)
        }

        val builder = AlertDialog.Builder(this)
            .setTitle("Kết nối MacBook (v${BuildConfig.VERSION_NAME})")
            .setMessage("Nhập IP Tailscale hoặc IP LAN của MacBook (hỗ trợ nhập cả 2 ngăn cách bằng dấu phẩy để tự chuyển mạch):")
            .setView(container)
            .setPositiveButton("Lưu và Kết nối") { _, _ ->
                saveServerHost(input.text?.toString().orEmpty())
                applyImmersiveStickyFullscreen()
            }
            .setNeutralButton("Cập nhật APK") { _, _ ->
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
        val releaseInfo = withContext(Dispatchers.IO) {
            fetchLatestGitHubRelease()
        }

        if (releaseInfo == null) {
            if (manualCheck) {
                Toast.makeText(
                    this,
                    "Không thể kiểm tra GitHub Releases lúc này.",
                    Toast.LENGTH_SHORT
                ).show()
            }
            return
        }

        val (tagName, apkDownloadUrl) = releaseInfo
        if (!isRemoteVersionNewer(tagName, BuildConfig.VERSION_NAME)) {
            if (manualCheck) {
                Toast.makeText(
                    this,
                    "Bạn đang ở bản mới nhất (v${BuildConfig.VERSION_NAME}).",
                    Toast.LENGTH_SHORT
                ).show()
            }
            return
        }

        Toast.makeText(
            this,
            "Phát hiện bản mới $tagName — đang tự động tải cập nhật...",
            Toast.LENGTH_SHORT
        ).show()

        startApkDownload(tagName, apkDownloadUrl)
    }

    private fun fetchLatestGitHubRelease(): Pair<String, String>? {
        val apiUrl = "https://api.github.com/repos/${BuildConfig.GITHUB_REPO}/releases/latest"
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(apiUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 7000
                readTimeout = 7000
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
            activeDownloadId = dm.enqueue(request)
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
    }
}
