package com.shakedivgi.smartsaver.data

// Build-time default API base URL.
// Patched by run_dev.py for different environments:
//   ngrok mode       → http://10.0.2.2:8000
//   LAN mode         → http://10.0.2.2:8000
//   Android emulator → http://10.0.2.2:8000  (emulator loopback to Mac host)
const val API_BASE_URL = "http://10.0.2.2:8000"
