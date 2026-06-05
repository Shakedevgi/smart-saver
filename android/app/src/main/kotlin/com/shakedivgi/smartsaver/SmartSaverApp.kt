package com.shakedivgi.smartsaver

import android.app.Application
import com.shakedivgi.smartsaver.data.ApiService

class SmartSaverApp : Application() {

    val api: ApiService by lazy { ApiService() }

    companion object {
        lateinit var instance: SmartSaverApp
            private set
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
    }
}
