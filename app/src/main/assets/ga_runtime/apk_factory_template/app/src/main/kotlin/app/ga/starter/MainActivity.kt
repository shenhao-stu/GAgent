package app.ga.starter

import android.app.Activity
import android.os.Bundle
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/**
 * GA「APK 工厂」starter 骨架 —— 一个可直接编译的最小 App。
 * 这是 GA 写真实 App 的起点: scaffold 后, 在这里(及新增文件)写真正的界面与逻辑,
 * 改 build.gradle 加依赖, 改 AndroidManifest 声明组件/权限。就是个普通 Android 工程。
 */
class MainActivity : Activity() {
    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 72, 48, 48)
            addView(TextView(this@MainActivity).apply { text = "GA Starter"; textSize = 26f })
            addView(TextView(this@MainActivity).apply {
                text = "由 GA APK 工厂生成的起步骨架。在此写你的 App。"
                textSize = 16f; setPadding(0, 28, 0, 0)
            })
        }
        setContentView(ScrollView(this).apply { addView(col) })
    }
}
