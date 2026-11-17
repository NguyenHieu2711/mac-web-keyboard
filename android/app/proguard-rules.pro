# Giữ nguyên JavascriptInterface cho Android WebView gọi được trên bản Release R8
-keepclassmembers class com.nguyenhieu.mackeyboard.MainActivity$AndroidWebBridge {
    @android.webkit.JavascriptInterface <methods>;
}
-keepattributes JavascriptInterface
