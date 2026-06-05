package com.shakedivgi.smartsaver.data

import com.google.gson.FieldNamingPolicy
import com.google.gson.GsonBuilder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

class ApiService(baseUrl: String = API_BASE_URL) {

    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private val gson = GsonBuilder()
        .setFieldNamingPolicy(FieldNamingPolicy.LOWER_CASE_WITH_UNDERSCORES)
        .create()

    private val jsonType = "application/json; charset=utf-8".toMediaType()
    private val base = baseUrl.trimEnd('/')

    // ── public API ──────────────────────────────────────────────────────────

    suspend fun health(): Result<HealthResponse> =
        get("/api/health", HealthResponse::class.java)

    suspend fun categories(): Result<CategoriesResponse> =
        get("/api/categories", CategoriesResponse::class.java)

    suspend fun search(request: SearchRequest): Result<SearchResponse> =
        post("/api/search", request, SearchResponse::class.java)

    suspend fun ingest(request: IngestRequest): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = gson.toJson(request).toRequestBody(jsonType)
            val req = Request.Builder().url("$base/api/ingest").post(body).build()
            val resp = client.newCall(req).execute()
            // 202 Accepted is the success code for async ingest
            if (!resp.isSuccessful && resp.code != 202) {
                error("HTTP ${resp.code}: ${resp.body?.string()?.take(200)}")
            }
        }
    }

    suspend fun createItem(request: ManualItemRequest): Result<Unit> = withContext(Dispatchers.IO) {
        runCatching {
            val body = gson.toJson(request).toRequestBody(jsonType)
            val req = Request.Builder().url("$base/api/items").post(body).build()
            val resp = client.newCall(req).execute()
            if (!resp.isSuccessful) error("HTTP ${resp.code}: ${resp.body?.string()?.take(200)}")
        }
    }

    suspend fun deleteItem(request: DeleteItemRequest): Result<DeleteItemResponse> =
        methodWithBody("/api/items", "DELETE", request, DeleteItemResponse::class.java)

    suspend fun updateItem(request: UpdateItemRequest): Result<UpdateItemResponse> =
        methodWithBody("/api/items", "PATCH", request, UpdateItemResponse::class.java)

    suspend fun renameCategory(request: RenameCategoryRequest): Result<CategoryBulkResponse> =
        methodWithBody("/api/categories", "PATCH", request, CategoryBulkResponse::class.java)

    suspend fun deleteCategory(request: DeleteCategoryRequest): Result<CategoryBulkResponse> =
        methodWithBody("/api/categories", "DELETE", request, CategoryBulkResponse::class.java)

    // ── private helpers ─────────────────────────────────────────────────────

    private suspend fun <T> get(path: String, responseType: Class<T>): Result<T> =
        withContext(Dispatchers.IO) {
            runCatching {
                val req = Request.Builder().url("$base$path").get().build()
                val resp = client.newCall(req).execute()
                if (!resp.isSuccessful) error("HTTP ${resp.code}")
                gson.fromJson(resp.body?.string() ?: error("Empty body"), responseType)
            }
        }

    private suspend fun <B, T> post(path: String, body: B, responseType: Class<T>): Result<T> =
        withContext(Dispatchers.IO) {
            runCatching {
                val reqBody = gson.toJson(body).toRequestBody(jsonType)
                val req = Request.Builder().url("$base$path").post(reqBody).build()
                val resp = client.newCall(req).execute()
                if (!resp.isSuccessful) error("HTTP ${resp.code}")
                gson.fromJson(resp.body?.string() ?: error("Empty body"), responseType)
            }
        }

    private suspend fun <B, T> methodWithBody(
        path: String, method: String, body: B, responseType: Class<T>
    ): Result<T> = withContext(Dispatchers.IO) {
        runCatching {
            val reqBody = gson.toJson(body).toRequestBody(jsonType)
            val req = Request.Builder().url("$base$path").method(method, reqBody).build()
            val resp = client.newCall(req).execute()
            if (!resp.isSuccessful) error("HTTP ${resp.code}")
            gson.fromJson(resp.body?.string() ?: error("Empty body"), responseType)
        }
    }
}
