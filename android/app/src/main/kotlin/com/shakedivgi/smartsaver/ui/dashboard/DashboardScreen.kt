package com.shakedivgi.smartsaver.ui.dashboard

import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.shakedivgi.smartsaver.data.SearchHit
import com.shakedivgi.smartsaver.ui.theme.BrandColors

// ──────────────────────────────────────────────── Root screen

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(vm: DashboardViewModel) {
    val state by vm.state.collectAsState()
    val focusManager = LocalFocusManager.current

    // Edit item sheet
    state.editingHit?.let { hit ->
        EditItemSheet(
            hit = hit,
            knownCategories = state.categories,
            onSave = { title, summary, category ->
                vm.updateHit(hit, title.takeIf { it.isNotBlank() }, summary.takeIf { it.isNotBlank() }, category)
            },
            onDismiss = { vm.setEditingHit(null) }
        )
    }

    // Add item sheet
    if (state.showAddSheet) {
        AddItemSheet(
            knownCategories = state.categories,
            onSave = { url, title, summary, category ->
                vm.addManualItem(url, title, summary, category)
                vm.setShowAddSheet(false)
            },
            onDismiss = { vm.setShowAddSheet(false) }
        )
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(listOf(BrandColors.midnightDeep, BrandColors.midnightMid))
            )
    ) {
        PullToRefreshBox(
            isRefreshing = state.isRefreshing,
            onRefresh = { vm.refresh(isUserPull = true) },
            modifier = Modifier.fillMaxSize()
        ) {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(bottom = 100.dp)
            ) {
                // Brand header
                item {
                    BrandHeader(
                        itemsIndexed = state.itemsIndexed,
                        categoryCount = state.categories.size,
                        onAdd = { vm.setShowAddSheet(true) },
                        onRefresh = { vm.refresh() }
                    )
                }

                // Search bar
                item {
                    SearchBar(
                        query = state.query,
                        onQueryChange = { vm.setQuery(it) },
                        onSearch = {
                            focusManager.clearFocus()
                            vm.search()
                        },
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)
                    )
                }

                // Category chips
                item {
                    CategoryChipRow(
                        categories = state.categories,
                        selected = state.selectedCategory,
                        allCount = state.itemsIndexed,
                        onSelect = { vm.selectCategory(it) },
                        onRename = { old, new -> vm.renameCategory(old, new) },
                        onDelete = { vm.deleteCategory(it) },
                        onMoveToGeneral = { vm.moveCategoryToGeneral(it) }
                    )
                }

                // Source filter pills
                item {
                    SourceFilterBar(
                        selected = state.selectedSource,
                        onSelect = { vm.selectSource(it) }
                    )
                }

                // Error banner
                state.error?.let { err ->
                    item {
                        ErrorBanner(message = err, onDismiss = { vm.clearError() })
                    }
                }

                // Results header
                if (!state.isLoading && state.filteredHits.isNotEmpty()) {
                    item {
                        ResultsHeader(
                            label = state.selectedCategory ?: if (state.query.isEmpty()) "All items" else "Results",
                            count = state.filteredHits.size
                        )
                    }
                }

                // Loading spinner
                if (state.isLoading) {
                    item {
                        Box(Modifier.fillMaxWidth().padding(top = 48.dp), contentAlignment = Alignment.Center) {
                            CircularProgressIndicator(color = BrandColors.electricBlue)
                        }
                    }
                }

                // Empty state
                if (!state.isLoading && state.filteredHits.isEmpty() && state.error == null) {
                    item { EmptyState(hasQuery = state.query.isNotEmpty()) }
                }

                // Item cards with swipe-to-delete
                items(state.filteredHits, key = { it.url }) { hit ->
                    SwipeToDeleteContainer(
                        onDelete = { vm.deleteHit(hit) }
                    ) {
                        ItemCard(
                            hit = hit,
                            onClick = { vm.setEditingHit(hit) }
                        )
                    }
                }
            }
        }
    }
}

// ──────────────────────────────────────────────── Brand header

@Composable
private fun BrandHeader(
    itemsIndexed: Int,
    categoryCount: Int,
    onAdd: () -> Unit,
    onRefresh: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .statusBarsPadding()
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        // Bookmark logo tile
        Box(
            modifier = Modifier
                .size(48.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(Brush.verticalGradient(listOf(BrandColors.gradientTop, BrandColors.gradientBottom))),
            contentAlignment = Alignment.Center
        ) {
            Icon(Icons.Default.Bookmark, contentDescription = null, tint = Color.White, modifier = Modifier.size(24.dp))
        }

        Column(modifier = Modifier.weight(1f)) {
            Text("Smart Saver", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, color = Color.White)
            Text(
                "$itemsIndexed items · $categoryCount categories",
                style = MaterialTheme.typography.bodySmall,
                color = Color.White.copy(alpha = 0.45f)
            )
        }

        IconButton(onClick = onAdd) {
            Icon(Icons.Default.Add, contentDescription = "Add item", tint = BrandColors.electricBlue)
        }
        IconButton(onClick = onRefresh) {
            Icon(Icons.Default.Refresh, contentDescription = "Refresh", tint = Color.White.copy(alpha = 0.6f))
        }
    }
}

// ──────────────────────────────────────────────── Search bar

@Composable
private fun SearchBar(
    query: String,
    onQueryChange: (String) -> Unit,
    onSearch: () -> Unit,
    modifier: Modifier = Modifier
) {
    OutlinedTextField(
        value = query,
        onValueChange = onQueryChange,
        modifier = modifier.fillMaxWidth(),
        placeholder = { Text("Search saved items semantically…", color = Color.White.copy(alpha = 0.35f)) },
        leadingIcon = { Icon(Icons.Default.Search, contentDescription = null, tint = BrandColors.electricBlue) },
        trailingIcon = {
            if (query.isNotEmpty()) {
                IconButton(onClick = { onQueryChange(""); onSearch() }) {
                    Icon(Icons.Default.Clear, contentDescription = "Clear", tint = Color.White.copy(alpha = 0.5f))
                }
            }
        },
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
        keyboardActions = KeyboardActions(onSearch = { onSearch() }),
        singleLine = true,
        shape = RoundedCornerShape(12.dp),
        colors = OutlinedTextFieldDefaults.colors(
            focusedTextColor = Color.White,
            unfocusedTextColor = Color.White,
            focusedBorderColor = BrandColors.electricBlue,
            unfocusedBorderColor = BrandColors.cardBorder,
            focusedContainerColor = BrandColors.cardBackground,
            unfocusedContainerColor = BrandColors.cardBackground,
            cursorColor = BrandColors.electricBlue
        )
    )
}

// ──────────────────────────────────────────────── Category chips

@Composable
private fun CategoryChipRow(
    categories: List<String>,
    selected: String?,
    allCount: Int,
    onSelect: (String?) -> Unit,
    onRename: (String, String) -> Unit,
    onDelete: (String) -> Unit,
    onMoveToGeneral: (String) -> Unit
) {
    var renamingCategory by remember { mutableStateOf<String?>(null) }
    var deletingCategory by remember { mutableStateOf<String?>(null) }

    LazyRow(
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        item {
            CategoryChip(
                label = "All",
                count = allCount,
                isSelected = selected == null,
                onClick = { onSelect(null) }
            )
        }
        items(categories, key = { it }) { cat ->
            CategoryChip(
                label = cat,
                isSelected = selected == cat,
                onClick = { onSelect(cat) },
                onRename = { renamingCategory = cat },
                onDelete = { deletingCategory = cat }
            )
        }
    }

    // Rename dialog
    renamingCategory?.let { cat ->
        RenameDialog(
            currentName = cat,
            onConfirm = { newName -> onRename(cat, newName); renamingCategory = null },
            onDismiss = { renamingCategory = null }
        )
    }

    // Delete confirmation dialog
    deletingCategory?.let { cat ->
        DeleteCategoryDialog(
            categoryName = cat,
            onMoveToGeneral = { onMoveToGeneral(cat); deletingCategory = null },
            onDeleteAll = { onDelete(cat); deletingCategory = null },
            onDismiss = { deletingCategory = null }
        )
    }
}

@Composable
private fun CategoryChip(
    label: String,
    count: Int? = null,
    isSelected: Boolean,
    onClick: () -> Unit,
    onRename: (() -> Unit)? = null,
    onDelete: (() -> Unit)? = null
) {
    val bg = if (isSelected) BrandColors.electricBlue else BrandColors.cardBackground
    val border = if (isSelected) BrandColors.electricBlue else BrandColors.cardBorder

    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(20.dp))
            .background(bg)
            .border(1.dp, border, RoundedCornerShape(20.dp))
            .clickable { onClick() }
            .padding(start = 12.dp, end = if (onRename != null) 4.dp else 12.dp, top = 6.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal,
            color = if (isSelected) Color.White else Color.White.copy(alpha = 0.7f)
        )
        if (count != null) {
            Badge(containerColor = Color.White.copy(alpha = 0.2f)) {
                Text("$count", style = MaterialTheme.typography.labelSmall, color = Color.White)
            }
        }
        if (onRename != null && onDelete != null) {
            IconButton(onClick = onRename, modifier = Modifier.size(20.dp)) {
                Icon(Icons.Default.Edit, contentDescription = "Rename", tint = Color.White.copy(alpha = 0.6f), modifier = Modifier.size(12.dp))
            }
            IconButton(onClick = onDelete, modifier = Modifier.size(20.dp)) {
                Icon(Icons.Default.Delete, contentDescription = "Delete", tint = Color.White.copy(alpha = 0.6f), modifier = Modifier.size(12.dp))
            }
        }
    }
}

// ──────────────────────────────────────────────── Source filter

@Composable
private fun SourceFilterBar(
    selected: ContentSource,
    onSelect: (ContentSource) -> Unit
) {
    LazyRow(
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        items(ContentSource.values()) { source ->
            val isSelected = source == selected
            val bg = if (isSelected) BrandColors.electricBlue else Color.White.copy(alpha = 0.07f)
            val border = if (isSelected) BrandColors.electricBlue else Color.White.copy(alpha = 0.15f)

            Row(
                modifier = Modifier
                    .clip(CircleShape)
                    .background(bg)
                    .border(1.dp, border, CircleShape)
                    .clickable { onSelect(source) }
                    .padding(horizontal = 14.dp, vertical = 7.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(5.dp)
            ) {
                val icon = when (source) {
                    ContentSource.All       -> Icons.Default.GridView
                    ContentSource.Instagram -> Icons.Default.CameraAlt
                    ContentSource.TikTok    -> Icons.Default.MusicVideo
                    ContentSource.YouTube   -> Icons.Default.PlayCircle
                    ContentSource.Article   -> Icons.Default.Description
                }
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = if (isSelected) Color.White else BrandColors.electricBlue.copy(alpha = 0.7f),
                    modifier = Modifier.size(14.dp)
                )
                Text(
                    text = source.label,
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = if (isSelected) Color.White else Color.White.copy(alpha = 0.6f)
                )
            }
        }
    }
}

// ──────────────────────────────────────────────── Item card

@Composable
fun ItemCard(hit: SearchHit, onClick: () -> Unit) {
    val status = hit.metadata.status
    val isProcessing = status == "processing"
    val isFailed = status == "failed"
    val isUncertain = hit.metadata.isUncertain == true

    val borderColor = when {
        isProcessing -> BrandColors.warning.copy(alpha = 0.7f)
        isFailed     -> BrandColors.danger.copy(alpha = 0.7f)
        isUncertain  -> Color(0xFFFF9800).copy(alpha = 0.7f)
        else         -> BrandColors.cardBorder
    }

    // Pulsing animation for processing items
    val pulse = rememberInfiniteTransition(label = "pulse")
    val pulseAlpha by pulse.animateFloat(
        initialValue = 0.6f, targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(900, easing = EaseInOut), RepeatMode.Reverse),
        label = "pulseAlpha"
    )

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 5.dp)
            .border(1.dp, borderColor, RoundedCornerShape(14.dp))
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(containerColor = BrandColors.cardBackground)
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top
            ) {
                // Title
                Text(
                    text = hit.metadata.title ?: hit.url,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = Color.White,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f).padding(end = 8.dp)
                )

                // Status badge
                when {
                    isProcessing -> StatusBadge("Processing", BrandColors.warning, animate = true, pulseAlpha)
                    isFailed     -> StatusBadge("Failed", BrandColors.danger)
                    isUncertain  -> StatusBadge("Needs Review", Color(0xFFFF9800))
                }
            }

            // Category + source badges
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                hit.category?.let { cat ->
                    MiniChip(text = cat, color = BrandColors.electricBlue.copy(alpha = 0.25f), textColor = BrandColors.electricBlue)
                }
                val sourceType = hit.metadata.sourceType
                if (!sourceType.isNullOrEmpty() && sourceType != "article") {
                    MiniChip(text = sourceType.replaceFirstChar { it.uppercase() }, color = Color.White.copy(alpha = 0.07f), textColor = Color.White.copy(alpha = 0.5f))
                }
            }

            // Summary
            val summaryText = hit.summary ?: hit.metadata.summary
            if (!summaryText.isNullOrBlank()) {
                Text(
                    text = summaryText,
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.White.copy(alpha = 0.6f),
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
            }

            // Technologies
            val techs = hit.metadata.technologiesList
            if (techs.isNotEmpty()) {
                LazyRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    items(techs) { tech ->
                        MiniChip(text = tech, color = BrandColors.midnightMid, textColor = Color.White.copy(alpha = 0.5f))
                    }
                }
            }

            // URL in caption
            Text(
                text = hit.url,
                style = MaterialTheme.typography.labelSmall,
                color = BrandColors.electricBlue.copy(alpha = 0.5f),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
    }
}

@Composable
private fun StatusBadge(text: String, color: Color, animate: Boolean = false, alpha: Float = 1f) {
    val effectiveAlpha = if (animate) alpha else 1f
    Surface(
        shape = RoundedCornerShape(20.dp),
        color = color.copy(alpha = 0.2f * effectiveAlpha)
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.SemiBold,
            color = color.copy(alpha = effectiveAlpha),
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp)
        )
    }
}

@Composable
private fun MiniChip(text: String, color: Color, textColor: Color) {
    Surface(shape = RoundedCornerShape(6.dp), color = color) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            color = textColor,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
        )
    }
}

// ──────────────────────────────────────────────── Swipe-to-delete wrapper

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SwipeToDeleteContainer(
    onDelete: () -> Unit,
    content: @Composable () -> Unit
) {
    val state = rememberSwipeToDismissBoxState(
        initialValue = SwipeToDismissBoxValue.Settled,
        positionalThreshold = { it * 0.4f }
    )

    LaunchedEffect(state.currentValue) {
        if (state.currentValue == SwipeToDismissBoxValue.EndToStart) {
            onDelete()
        }
    }

    SwipeToDismissBox(
        state = state,
        backgroundContent = {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 16.dp, vertical = 5.dp)
                    .clip(RoundedCornerShape(14.dp))
                    .background(BrandColors.danger.copy(alpha = 0.85f)),
                contentAlignment = Alignment.CenterEnd
            ) {
                Row(
                    modifier = Modifier.padding(end = 20.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Icon(Icons.Default.Delete, contentDescription = "Delete", tint = Color.White)
                    Text("Delete", color = Color.White, fontWeight = FontWeight.SemiBold)
                }
            }
        },
        enableDismissFromStartToEnd = false
    ) {
        content()
    }
}

// ──────────────────────────────────────────────── Misc UI

@Composable
private fun ResultsHeader(label: String, count: Int) {
    Row(
        modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Text(label, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = Color.White)
        Text("($count)", style = MaterialTheme.typography.bodySmall, color = Color.White.copy(alpha = 0.4f))
    }
}

@Composable
private fun EmptyState(hasQuery: Boolean) {
    Column(
        modifier = Modifier.fillMaxWidth().padding(top = 80.dp, bottom = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Icon(Icons.Default.Inbox, contentDescription = null, tint = Color.White.copy(alpha = 0.25f), modifier = Modifier.size(56.dp))
        Text("Nothing to show yet", style = MaterialTheme.typography.titleSmall, color = Color.White)
        Text(
            text = if (hasQuery) "No matches found." else "Share a link from any app to seed your library.",
            style = MaterialTheme.typography.bodySmall,
            color = Color.White.copy(alpha = 0.45f)
        )
    }
}

@Composable
private fun ErrorBanner(message: String, onDismiss: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(BrandColors.danger.copy(alpha = 0.85f))
            .padding(12.dp),
        verticalAlignment = Alignment.Top,
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Icon(Icons.Default.Warning, contentDescription = null, tint = Color.White, modifier = Modifier.size(18.dp))
        Text(
            text = message,
            style = MaterialTheme.typography.bodySmall,
            color = Color.White,
            modifier = Modifier.weight(1f)
        )
        IconButton(onClick = onDismiss, modifier = Modifier.size(24.dp)) {
            Icon(Icons.Default.Close, contentDescription = "Dismiss", tint = Color.White, modifier = Modifier.size(16.dp))
        }
    }
}

// ──────────────────────────────────────────────── Edit item sheet

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun EditItemSheet(
    hit: SearchHit,
    knownCategories: List<String>,
    onSave: (String, String, String?) -> Unit,
    onDismiss: () -> Unit
) {
    var title by remember { mutableStateOf(hit.metadata.title ?: "") }
    var summary by remember { mutableStateOf(hit.summary ?: hit.metadata.summary ?: "") }
    var category by remember { mutableStateOf(hit.category ?: "") }
    var customCategory by remember { mutableStateOf("") }
    var useCustom by remember { mutableStateOf(false) }
    val uriHandler = LocalUriHandler.current

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        containerColor = BrandColors.cardBackground,
        contentColor = Color.White
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .navigationBarsPadding()
                .padding(bottom = 20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text("Edit Item", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = Color.White)
                TextButton(onClick = {
                    val finalCat = if (useCustom) customCategory.trim().takeIf { it.isNotEmpty() } else category.takeIf { it.isNotEmpty() }
                    onSave(title, summary, finalCat)
                }) { Text("Save", color = BrandColors.electricBlue, fontWeight = FontWeight.Bold) }
            }

            SheetTextField("Title", title, { title = it }, singleLine = true)
            SheetTextField("Summary", summary, { summary = it }, singleLine = false, maxLines = 4)

            // Category picker
            if (!useCustom) {
                var expanded by remember { mutableStateOf(false) }
                ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = it }) {
                    OutlinedTextField(
                        value = category,
                        onValueChange = {},
                        readOnly = true,
                        label = { Text("Category", color = Color.White.copy(alpha = 0.5f)) },
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
                        modifier = Modifier.fillMaxWidth().menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable),
                        colors = sheetTextFieldColors()
                    )
                    ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }, containerColor = BrandColors.midnightMid) {
                        knownCategories.forEach { cat ->
                            DropdownMenuItem(text = { Text(cat, color = Color.White) }, onClick = { category = cat; expanded = false })
                        }
                        DropdownMenuItem(text = { Text("New category…", color = BrandColors.electricBlue) }, onClick = { useCustom = true; expanded = false })
                    }
                }
            } else {
                SheetTextField("New Category", customCategory, { customCategory = it }, singleLine = true)
                TextButton(onClick = { useCustom = false }) { Text("← Pick existing", color = BrandColors.electricBlue) }
            }

            // Open in browser
            TextButton(onClick = { uriHandler.openUri(hit.url) }) {
                Icon(Icons.Default.OpenInBrowser, contentDescription = null, tint = BrandColors.electricBlue, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text("Open in browser", color = BrandColors.electricBlue)
            }
        }
    }
}

// ──────────────────────────────────────────────── Add item sheet

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AddItemSheet(
    knownCategories: List<String>,
    onSave: (String, String, String, String) -> Unit,
    onDismiss: () -> Unit
) {
    var url by remember { mutableStateOf("") }
    var title by remember { mutableStateOf("") }
    var summary by remember { mutableStateOf("") }
    var category by remember { mutableStateOf("") }
    var customCategory by remember { mutableStateOf("") }
    var useCustom by remember { mutableStateOf(false) }

    val finalCategory = if (useCustom) customCategory.trim() else category
    val canSave = url.isNotBlank() && title.isNotBlank() && finalCategory.isNotBlank()

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        containerColor = BrandColors.cardBackground,
        contentColor = Color.White
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .navigationBarsPadding()
                .padding(bottom = 20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text("Add Item", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = Color.White)
                TextButton(
                    onClick = { onSave(url.trim(), title.trim(), summary.trim(), finalCategory) },
                    enabled = canSave
                ) { Text("Save", color = if (canSave) BrandColors.electricBlue else Color.White.copy(alpha = 0.3f), fontWeight = FontWeight.Bold) }
            }

            SheetTextField("Link", url, {
                url = if (it.isNotEmpty() && !it.startsWith("http")) "https://$it" else it
            }, singleLine = true, placeholder = "https://example.com/article")

            SheetTextField("Title", title, { title = it }, singleLine = true, placeholder = "What is this?")
            SheetTextField("Summary", summary, { summary = it }, singleLine = false, maxLines = 3, placeholder = "Why this matters…")

            // Category picker
            if (!useCustom) {
                var expanded by remember { mutableStateOf(false) }
                ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = it }) {
                    OutlinedTextField(
                        value = category,
                        onValueChange = {},
                        readOnly = true,
                        label = { Text("Category", color = Color.White.copy(alpha = 0.5f)) },
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
                        modifier = Modifier.fillMaxWidth().menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable),
                        colors = sheetTextFieldColors()
                    )
                    ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }, containerColor = BrandColors.midnightMid) {
                        knownCategories.forEach { cat ->
                            DropdownMenuItem(text = { Text(cat, color = Color.White) }, onClick = { category = cat; expanded = false })
                        }
                        DropdownMenuItem(text = { Text("New category…", color = BrandColors.electricBlue) }, onClick = { useCustom = true; expanded = false })
                    }
                }
            } else {
                SheetTextField("New Category", customCategory, { customCategory = it }, singleLine = true, placeholder = "e.g. Real Estate")
                TextButton(onClick = { useCustom = false }) { Text("← Pick existing", color = BrandColors.electricBlue) }
            }
        }
    }
}

// ──────────────────────────────────────────────── Dialogs

@Composable
private fun RenameDialog(currentName: String, onConfirm: (String) -> Unit, onDismiss: () -> Unit) {
    var newName by remember { mutableStateOf(currentName) }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = BrandColors.cardBackground,
        title = { Text("Rename Category", color = Color.White) },
        text = {
            OutlinedTextField(
                value = newName,
                onValueChange = { newName = it },
                singleLine = true,
                colors = sheetTextFieldColors()
            )
        },
        confirmButton = {
            TextButton(onClick = { if (newName.isNotBlank()) onConfirm(newName.trim()) }) {
                Text("Rename", color = BrandColors.electricBlue)
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = Color.White.copy(alpha = 0.6f)) } }
    )
}

@Composable
private fun DeleteCategoryDialog(
    categoryName: String,
    onMoveToGeneral: () -> Unit,
    onDeleteAll: () -> Unit,
    onDismiss: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = BrandColors.cardBackground,
        title = { Text("Delete \"$categoryName\"?", color = Color.White) },
        text = { Text("Items can be moved to a General bucket, or deleted along with the category.", color = Color.White.copy(alpha = 0.7f)) },
        confirmButton = {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                TextButton(onClick = onMoveToGeneral) { Text("Move items to General", color = BrandColors.electricBlue) }
                TextButton(onClick = onDeleteAll) { Text("Delete all content", color = BrandColors.danger) }
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = Color.White.copy(alpha = 0.6f)) } }
    )
}

// ──────────────────────────────────────────────── Shared helpers

@Composable
private fun SheetTextField(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    singleLine: Boolean,
    maxLines: Int = 1,
    placeholder: String = ""
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label, color = Color.White.copy(alpha = 0.5f)) },
        placeholder = if (placeholder.isNotEmpty()) ({ Text(placeholder, color = Color.White.copy(alpha = 0.25f)) }) else null,
        singleLine = singleLine,
        maxLines = if (singleLine) 1 else maxLines,
        modifier = Modifier.fillMaxWidth(),
        colors = sheetTextFieldColors()
    )
}

@Composable
private fun sheetTextFieldColors() = OutlinedTextFieldDefaults.colors(
    focusedTextColor = Color.White,
    unfocusedTextColor = Color.White,
    focusedBorderColor = BrandColors.electricBlue,
    unfocusedBorderColor = BrandColors.cardBorder,
    focusedContainerColor = BrandColors.midnightMid,
    unfocusedContainerColor = BrandColors.midnightMid,
    cursorColor = BrandColors.electricBlue,
    focusedLabelColor = BrandColors.electricBlue,
    unfocusedLabelColor = Color.White.copy(alpha = 0.4f)
)
