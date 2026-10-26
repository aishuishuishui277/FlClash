package com.follow.clash.common

import android.os.SystemClock
import android.util.Log

object StartupTrace {
    private const val TAG = "FlClashStartup"

    val enabled: Boolean
        get() = runCatching { Log.isLoggable(TAG, Log.DEBUG) }.getOrDefault(false)

    fun event(name: String, code: Long = 0, value: Long = 0) {
        if (!enabled) return
        Log.d(TAG, "{\"event\":\"$name\",\"time_ms\":${System.currentTimeMillis()},\"elapsed_ms\":${SystemClock.elapsedRealtime()},\"code\":$code,\"value\":$value}")
    }

    fun core(data: String) {
        if (enabled) Log.d(TAG, data)
    }
}
