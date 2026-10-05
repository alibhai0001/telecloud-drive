// State Management
let currentFolderId = null;
let currentViewMode = localStorage.getItem('viewMode') || 'grid';
let folders = [];
let files = [];
let allFoldersList = [];
let activeTasksPolling = null;
let renameTarget = { type: null, id: null };
let moveTarget = { type: null, id: null };
let currentEditingFile = { id: null, name: null };
let phoneCodeHash = null;

// File Type Helper
function getFileTypeInfo(mimeType, fileName) {
    const ext = (fileName.split('.').pop() || '').toLowerCase();
    
    if (mimeType?.startsWith('video/') || ['mp4', 'mkv', 'avi', 'mov', 'webm', 'flv', 'wmv'].includes(ext)) {
        return { type: 'video', icon: 'film', color: 'text-rose-400', bg: 'bg-rose-500/10', isCode: false };
    }
    if (mimeType?.startsWith('audio/') || ['mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac'].includes(ext)) {
        return { type: 'audio', icon: 'music', color: 'text-amber-400', bg: 'bg-amber-500/10', isCode: false };
    }
    if (mimeType?.startsWith('image/') || ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'ico'].includes(ext)) {
        return { type: 'image', icon: 'image', color: 'text-emerald-400', bg: 'bg-emerald-500/10', isCode: false };
    }
    if (mimeType === 'application/pdf' || ext === 'pdf') {
        return { type: 'pdf', icon: 'file-text', color: 'text-red-400', bg: 'bg-red-500/10', isCode: false };
    }
    if (['zip', 'rar', '7z', 'tar', 'gz'].includes(ext)) {
        return { type: 'archive', icon: 'archive', color: 'text-purple-400', bg: 'bg-purple-500/10', isCode: false };
    }
    if (['html', 'htm'].includes(ext)) {
        return { type: 'html', icon: 'globe', color: 'text-orange-400', bg: 'bg-orange-500/10', isCode: true };
    }
    if (['css', 'scss', 'less'].includes(ext)) {
        return { type: 'css', icon: 'palette', color: 'text-blue-400', bg: 'bg-blue-500/10', isCode: true };
    }
    if (['js', 'ts', 'jsx', 'tsx', 'py', 'json', 'c', 'cpp', 'java', 'rs', 'go', 'php', 'sql', 'sh', 'bat', 'txt', 'md', 'env', 'yaml', 'yml'].includes(ext)) {
        return { type: 'code', icon: 'file-code', color: 'text-cyan-400', bg: 'bg-cyan-500/10', isCode: true };
    }
    return { type: 'generic', icon: 'file', color: 'text-slate-400', bg: 'bg-slate-500/10', isCode: false };
}

// Toast Notifications
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    const colors = {
        success: 'bg-emerald-600 text-white border-emerald-500',
        error: 'bg-rose-600 text-white border-rose-500',
        info: 'bg-slate-800 text-white border-slate-700'
    };
    
    toast.className = `flex items-center gap-2 px-4 py-3 rounded-xl text-sm font-medium border shadow-2xl toast-enter ${colors[type] || colors.info}`;
    toast.innerHTML = `
        <i data-lucide="${type === 'success' ? 'check-circle' : type === 'error' ? 'alert-circle' : 'info'}" class="w-4 h-4"></i>
        <span>${message}</span>
    `;
    
    container.appendChild(toast);
    lucide.createIcons();
    
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Modal Helpers
function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (!modal) return;
    modal.classList.remove('hidden');
    setTimeout(() => modal.classList.add('modal-active'), 10);
    lucide.createIcons();
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (!modal) return;
    modal.classList.remove('modal-active');
    setTimeout(() => modal.classList.add('hidden'), 200);
}

// Initial Load & Telegram Mini App SDK Hook
document.addEventListener('DOMContentLoaded', () => {
    // Check if running inside Telegram WebApp
    if (window.Telegram?.WebApp) {
        try {
            window.Telegram.WebApp.ready();
            window.Telegram.WebApp.expand();
        } catch (e) {
            console.log("Telegram WebApp initialization notice:", e);
        }
    }

    setViewMode(currentViewMode, false);
    checkAuthStatus();
    loadCurrentDirectory();
    loadDeployments();
    setupDragAndDrop();
    setupSearch();
    startTasksPolling();
});

// View Mode Toggle
function setViewMode(mode, reload = true) {
    currentViewMode = mode;
    localStorage.setItem('viewMode', mode);
    
    const gridBtn = document.getElementById('viewGridBtn');
    const listBtn = document.getElementById('viewListBtn');
    
    if (mode === 'grid') {
        gridBtn.className = 'p-1.5 rounded-lg text-white bg-slate-800 transition-all';
        listBtn.className = 'p-1.5 rounded-lg text-dark-muted hover:text-white transition-all';
    } else {
        listBtn.className = 'p-1.5 rounded-lg text-white bg-slate-800 transition-all';
        gridBtn.className = 'p-1.5 rounded-lg text-dark-muted hover:text-white transition-all';
    }
    
    if (reload) renderCurrentDirectory();
}

// Directory & File Management
async function loadCurrentDirectory() {
    try {
        const folderParam = currentFolderId ? `?parent_id=${currentFolderId}` : '';
        const fileParam = currentFolderId ? `?folder_id=${currentFolderId}` : '';
        
        const [foldersRes, filesRes, breadcrumbsRes, statsRes] = await Promise.all([
            fetch(`/api/folders${folderParam}`).then(r => r.json()),
            fetch(`/api/files${fileParam}`).then(r => r.json()),
            fetch(`/api/folders/${currentFolderId || 0}/breadcrumbs`).then(r => r.json()),
            fetch('/api/stats').then(r => r.json())
        ]);
        
        folders = foldersRes;
        files = filesRes;
        
        renderBreadcrumbs(breadcrumbsRes);
        updateFolderToolbar();
        renderCurrentDirectory();
        updateStorageStats(statsRes);
    } catch (e) {
        console.error("Error loading directory:", e);
        showToast("Failed to load files", "error");
    }
}

async function updateFolderToolbar() {
    const siteBtn = document.getElementById('currentFolderSiteBtn');
    const siteBtnText = document.getElementById('currentFolderSiteText');
    const deployBtn = document.getElementById('btnDeployFolder');
    const zipBtn = document.getElementById('btnZipFolder');
    const initSiteBtn = document.getElementById('btnInitSite');

    if (currentFolderId) {
        if (zipBtn) zipBtn.classList.remove('hidden');
        if (initSiteBtn) initSiteBtn.classList.remove('hidden');
        if (deployBtn) deployBtn.classList.remove('hidden');

        try {
            const depRes = await fetch(`/api/deployments/folder/${currentFolderId}`).then(r => r.json());
            if (depRes.deployed && depRes.deployment) {
                if (siteBtn) {
                    siteBtn.href = `/d/${depRes.deployment.slug}/`;
                    if (siteBtnText) siteBtnText.textContent = `/d/${depRes.deployment.slug}`;
                    siteBtn.classList.remove('hidden');
                }
                if (deployBtn) deployBtn.classList.add('hidden');
            } else {
                const hasIndex = files.some(f => f.name.toLowerCase() === 'index.html');
                if (hasIndex && siteBtn) {
                    siteBtn.href = `/site/${currentFolderId}/`;
                    if (siteBtnText) siteBtnText.textContent = 'Live Website';
                    siteBtn.classList.remove('hidden');
                } else if (siteBtn) {
                    siteBtn.classList.add('hidden');
                }
            }
        } catch (e) {
            console.error("Error checking folder deployment:", e);
        }
    } else {
        if (siteBtn) siteBtn.classList.add('hidden');
        if (deployBtn) deployBtn.classList.add('hidden');
        if (zipBtn) zipBtn.classList.add('hidden');
        if (initSiteBtn) initSiteBtn.classList.add('hidden');
    }
}

function renderBreadcrumbs(crumbs) {
    const container = document.getElementById('breadcrumbsContainer');
    container.innerHTML = '';
    
    crumbs.forEach((c, idx) => {
        const isLast = idx === crumbs.length - 1;
        const btn = document.createElement('button');
        btn.className = `flex items-center gap-1.5 transition-colors ${isLast ? 'text-white font-semibold' : 'text-dark-muted hover:text-white'}`;
        btn.onclick = () => navigateToFolder(c.id);
        
        if (idx === 0) {
            btn.innerHTML = `<i data-lucide="home" class="w-3.5 h-3.5"></i><span>${c.name}</span>`;
        } else {
            btn.innerHTML = `<span>${c.name}</span>`;
        }
        
        container.appendChild(btn);
        
        if (!isLast) {
            const sep = document.createElement('span');
            sep.className = 'text-slate-600';
            sep.innerHTML = '<i data-lucide="chevron-right" class="w-3.5 h-3.5"></i>';
            container.appendChild(sep);
        }
    });
    lucide.createIcons();
}

function updateStorageStats(stats) {
    document.getElementById('statFilesCount').textContent = `${stats.file_count || 0} files`;
    document.getElementById('statTotalSize').textContent = `${stats.human_size || '0 B'} used`;
}

function renderCurrentDirectory() {
    const foldersSection = document.getElementById('foldersSection');
    const foldersGrid = document.getElementById('foldersGrid');
    const filesSection = document.getElementById('filesSection');
    const filesGrid = document.getElementById('filesGrid');
    const filesList = document.getElementById('filesList');
    const emptyState = document.getElementById('emptyState');
    const itemCount = document.getElementById('folderItemCount');
    
    const totalItems = folders.length + files.length;
    itemCount.textContent = `${totalItems} item${totalItems === 1 ? '' : 's'}`;
    
    if (totalItems === 0) {
        foldersSection.classList.add('hidden');
        filesSection.classList.add('hidden');
        emptyState.classList.remove('hidden');
        return;
    }
    
    emptyState.classList.add('hidden');
    
    // Render Folders
    if (folders.length > 0) {
        foldersSection.classList.remove('hidden');
        foldersGrid.innerHTML = folders.map(f => `
            <div onclick="navigateToFolder(${f.id})" 
                 class="folder-card group bg-slate-900/80 hover:bg-slate-800/90 border ${f.has_website ? 'border-cyan-500/40 bg-cyan-950/10' : 'border-dark-border'} rounded-xl p-3 flex items-center justify-between cursor-pointer relative">
                <div class="flex items-center gap-2.5 overflow-hidden">
                    <i data-lucide="${f.has_website ? 'globe' : 'folder'}" class="w-5 h-5 ${f.has_website ? 'text-cyan-400 fill-cyan-400/20' : 'text-brand-500 fill-brand-500/20'} flex-shrink-0 group-hover:scale-110 transition-transform"></i>
                    <span class="text-sm font-medium text-slate-200 truncate group-hover:text-white" title="${escapeHtml(f.name)}">${escapeHtml(f.name)}</span>
                </div>
                <div class="flex items-center opacity-0 group-hover:opacity-100 transition-opacity gap-0.5" onclick="event.stopPropagation()">
                    ${f.has_website ? `
                        <a href="/site/${f.id}/" target="_blank" class="p-1 hover:text-cyan-400 text-dark-muted rounded" title="Open Hosted Website">
                            <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
                        </a>
                    ` : ''}
                    <button onclick="openMoveModal('folder', ${f.id}, '${escapeHtml(f.name)}')" class="p-1 hover:text-brand-400 text-dark-muted rounded" title="Move Folder">
                        <i data-lucide="folder-input" class="w-3.5 h-3.5"></i>
                    </button>
                    <button onclick="openRenameModal('folder', ${f.id}, '${escapeHtml(f.name)}')" class="p-1 hover:text-amber-400 text-dark-muted rounded" title="Rename">
                        <i data-lucide="edit-2" class="w-3.5 h-3.5"></i>
                    </button>
                    <button onclick="handleDeleteFolder(${f.id})" class="p-1 hover:text-rose-400 text-dark-muted rounded" title="Delete">
                        <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                    </button>
                </div>
            </div>
        `).join('');
    } else {
        foldersSection.classList.add('hidden');
    }
    
    // Render Files
    if (files.length > 0) {
        filesSection.classList.remove('hidden');
        
        if (currentViewMode === 'grid') {
            filesGrid.classList.remove('hidden');
            filesList.classList.add('hidden');
            
            filesGrid.innerHTML = files.map(f => {
                const info = getFileTypeInfo(f.mime_type, f.name);
                return `
                    <div class="file-card group bg-dark-card/90 border border-dark-border rounded-2xl p-4 flex flex-col justify-between hover:border-slate-500 cursor-pointer relative"
                         onclick="handleFileClick(${f.id}, '${escapeHtml(f.name)}', ${info.isCode})">
                        <!-- Icon Header -->
                        <div class="flex items-center justify-between mb-3">
                            <div class="w-10 h-10 rounded-xl ${info.bg} ${info.color} flex items-center justify-center group-hover:scale-105 transition-transform">
                                <i data-lucide="${info.icon}" class="w-5 h-5"></i>
                            </div>
                            <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity" onclick="event.stopPropagation()">
                                ${info.isCode ? `
                                    <button onclick="openCodeEditor(${f.id}, '${escapeHtml(f.name)}')" class="p-1.5 text-dark-muted hover:text-cyan-400 rounded-lg hover:bg-slate-700/80" title="Edit Code">
                                        <i data-lucide="edit" class="w-3.5 h-3.5"></i>
                                    </button>
                                ` : ''}
                                <button onclick="openShareModal(${f.id}, '${escapeHtml(f.name)}')" class="p-1.5 text-dark-muted hover:text-cyan-400 rounded-lg hover:bg-slate-700/80" title="Share Public Link">
                                    <i data-lucide="share-2" class="w-3.5 h-3.5"></i>
                                </button>
                                <button onclick="openMoveModal('file', ${f.id}, '${escapeHtml(f.name)}')" class="p-1.5 text-dark-muted hover:text-brand-400 rounded-lg hover:bg-slate-700/80" title="Move File">
                                    <i data-lucide="folder-input" class="w-3.5 h-3.5"></i>
                                </button>
                                <a href="/api/download/${f.id}" download class="p-1.5 text-dark-muted hover:text-white rounded-lg hover:bg-slate-700/80" title="Download">
                                    <i data-lucide="download" class="w-3.5 h-3.5"></i>
                                </a>
                                <button onclick="openRenameModal('file', ${f.id}, '${escapeHtml(f.name)}')" class="p-1.5 text-dark-muted hover:text-amber-400 rounded-lg hover:bg-slate-700/80" title="Rename">
                                    <i data-lucide="edit-2" class="w-3.5 h-3.5"></i>
                                </button>
                                <button onclick="handleDeleteFile(${f.id})" class="p-1.5 text-dark-muted hover:text-rose-400 rounded-lg hover:bg-slate-700/80" title="Delete">
                                    <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                                </button>
                            </div>
                        </div>
                        
                        <!-- File Name & Meta -->
                        <div>
                            <p class="text-xs font-semibold text-slate-200 truncate group-hover:text-brand-500 transition-colors" title="${escapeHtml(f.name)}">
                                ${escapeHtml(f.name)}
                            </p>
                            <div class="flex items-center justify-between text-[10px] text-dark-muted mt-1.5">
                                <span>${f.human_size}</span>
                                <span class="text-emerald-400 font-mono">Telegram Cloud</span>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        } else {
            // List View
            filesGrid.classList.add('hidden');
            filesList.classList.remove('hidden');
            
            filesList.innerHTML = files.map(f => {
                const info = getFileTypeInfo(f.mime_type, f.name);
                return `
                    <div class="flex items-center justify-between p-3 px-4 hover:bg-slate-800/60 transition-colors group cursor-pointer"
                         onclick="handleFileClick(${f.id}, '${escapeHtml(f.name)}', ${info.isCode})">
                        <div class="flex items-center gap-3 overflow-hidden flex-1">
                            <div class="w-8 h-8 rounded-lg ${info.bg} ${info.color} flex items-center justify-center flex-shrink-0">
                                <i data-lucide="${info.icon}" class="w-4 h-4"></i>
                            </div>
                            <span class="text-sm font-medium text-slate-200 truncate group-hover:text-brand-500">${escapeHtml(f.name)}</span>
                        </div>
                        <div class="flex items-center gap-4 text-xs text-dark-muted flex-shrink-0" onclick="event.stopPropagation()">
                            <span class="w-20 text-right">${f.human_size}</span>
                            <div class="flex items-center gap-1">
                                ${info.isCode ? `
                                    <button onclick="openCodeEditor(${f.id}, '${escapeHtml(f.name)}')" class="p-1.5 hover:text-cyan-400 rounded-lg hover:bg-slate-700" title="Edit Code">
                                        <i data-lucide="edit" class="w-4 h-4"></i>
                                    </button>
                                ` : ''}
                                <button onclick="openShareModal(${f.id}, '${escapeHtml(f.name)}')" class="p-1.5 hover:text-cyan-400 rounded-lg hover:bg-slate-700" title="Share Public Link">
                                    <i data-lucide="share-2" class="w-4 h-4"></i>
                                </button>
                                <button onclick="openMoveModal('file', ${f.id}, '${escapeHtml(f.name)}')" class="p-1.5 hover:text-brand-400 rounded-lg hover:bg-slate-700" title="Move File">
                                    <i data-lucide="folder-input" class="w-4 h-4"></i>
                                </button>
                                <a href="/api/download/${f.id}" download class="p-1.5 hover:text-white rounded-lg hover:bg-slate-700" title="Download">
                                    <i data-lucide="download" class="w-4 h-4"></i>
                                </a>
                                <button onclick="openRenameModal('file', ${f.id}, '${escapeHtml(f.name)}')" class="p-1.5 hover:text-amber-400 rounded-lg hover:bg-slate-700" title="Rename">
                                    <i data-lucide="edit-2" class="w-4 h-4"></i>
                                </button>
                                <button onclick="handleDeleteFile(${f.id})" class="p-1.5 hover:text-rose-400 rounded-lg hover:bg-slate-700" title="Delete">
                                    <i data-lucide="trash-2" class="w-4 h-4"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }
    } else {
        filesSection.classList.add('hidden');
    }
    
    lucide.createIcons();
}

function handleFileClick(fileId, fileName, isCode) {
    if (isCode) {
        openCodeEditor(fileId, fileName);
    } else {
        openFilePreview(fileId);
    }
}

function navigateToFolder(folderId) {
    currentFolderId = folderId;
    loadCurrentDirectory();
}

// ----------------- Remote Downloader (GDrive + Direct URL) -----------------
async function openRemoteModal() {
    const select = document.getElementById('remoteFolderSelect');
    select.innerHTML = '<option value="">📁 Root (My Cloud)</option>';
    
    try {
        const res = await fetch('/api/folders').then(r => r.json());
        res.forEach(f => {
            const opt = document.createElement('option');
            opt.value = f.id;
            opt.textContent = `📁 ${f.name}`;
            if (f.id === currentFolderId) opt.selected = true;
            select.appendChild(opt);
        });
    } catch (e) {
        console.error("Error fetching folders list:", e);
    }
    
    document.getElementById('remoteUrlInput').value = '';
    openModal('remoteModal');
}

async function handleRemoteSubmit(event) {
    event.preventDefault();
    const url = document.getElementById('remoteUrlInput').value.trim();
    const folderId = document.getElementById('remoteFolderSelect').value;
    const cookieOverride = document.getElementById('remoteModalCookieInput')?.value.trim();
    
    if (!url) return;
    
    try {
        const res = await fetch('/api/remote/url', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: url,
                folder_id: folderId ? parseInt(folderId) : null,
                cookie: cookieOverride || null
            })
        });
        
        const data = await res.json();
        if (res.ok && data.success) {
            closeModal('remoteModal');
            showToast("Remote download transfer started!", "success");
            openTasksDrawer();
        } else {
            showToast(data.detail || data.error || "Failed to start transfer", "error");
        }
    } catch (e) {
        console.error("Remote submit error:", e);
        showToast("Error connecting to server", "error");
    }
}

// ----------------- New File / Code Modal -----------------
function openNewFileModal() {
    document.getElementById('newFileNameInput').value = '';
    document.getElementById('newFileTemplateSelect').value = 'blank';
    document.getElementById('newFileContentInput').value = '';
    openModal('newFileModal');
}

function applyFileTemplate(template) {
    const nameInput = document.getElementById('newFileNameInput');
    const contentInput = document.getElementById('newFileContentInput');
    
    if (template === 'html5') {
        nameInput.value = 'index.html';
        contentInput.value = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>My Website</title>
    <style>
        body { font-family: sans-serif; background: #0f172a; color: white; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .box { background: #1e293b; padding: 2rem; border-radius: 1rem; text-align: center; border: 1px solid #334155; }
    </style>
</head>
<body>
    <div class="box">
        <h1>🚀 Hosted on Telegram Cloud!</h1>
        <p>Edit this file anytime to update your live website.</p>
    </div>
</body>
</html>`;
    } else if (template === 'css') {
        nameInput.value = 'style.css';
        contentInput.value = `/* Stylesheet */
body {
    background-color: #0f172a;
    color: #f8fafc;
    font-family: system-ui, -apple-system, sans-serif;
}`;
    } else if (template === 'js') {
        nameInput.value = 'script.js';
        contentInput.value = `// JavaScript Application
console.log("Website loaded successfully from Telegram Cloud!");`;
    } else if (template === 'python') {
        nameInput.value = 'script.py';
        contentInput.value = `# Python Cloud Script
print("Hello from TeleCloud!")`;
    } else if (template === 'json') {
        nameInput.value = 'data.json';
        contentInput.value = `{\n  "name": "TeleCloud",\n  "status": "active",\n  "version": "2.0"\n}`;
    } else if (template === 'notes') {
        nameInput.value = 'notes.md';
        contentInput.value = `# 📝 My Cloud Notes\n\n- Point 1\n- Point 2\n- Point 3`;
    } else {
        contentInput.value = '';
    }
}

async function handleCreateFileSubmit(event) {
    event.preventDefault();
    const name = document.getElementById('newFileNameInput').value.trim();
    const content = document.getElementById('newFileContentInput').value;
    
    if (!name) return;
    
    try {
        const res = await fetch('/api/files/text', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                content: content,
                folder_id: currentFolderId
            })
        });
        
        const data = await res.json();
        if (res.ok && data.success) {
            closeModal('newFileModal');
            showToast(`Created file "${name}" in Telegram Cloud!`, "success");
            loadCurrentDirectory();
        } else {
            showToast(data.detail || "Failed to create file", "error");
        }
    } catch (e) {
        showToast("Error creating file: " + e.message, "error");
    }
}

// ----------------- Code Editor -----------------
async function openCodeEditor(fileId, fileName) {
    currentEditingFile = { id: fileId, name: fileName };
    document.getElementById('editorFileName').textContent = fileName;
    document.getElementById('editorStatusText').textContent = "Fetching content from Telegram Cloud...";
    document.getElementById('codeEditorTextarea').value = "Loading...";
    
    openModal('codeEditorModal');
    
    try {
        const res = await fetch(`/api/files/${fileId}/content`);
        const data = await res.json();
        if (res.ok) {
            document.getElementById('codeEditorTextarea').value = data.content || '';
            document.getElementById('editorStatusText').textContent = "Ready to edit";
        } else {
            showToast(data.detail || "Could not load file content", "error");
            document.getElementById('codeEditorTextarea').value = "Error loading content";
        }
    } catch (e) {
        showToast("Error loading file", "error");
    }
}

async function saveEditorContent() {
    if (!currentEditingFile.id) return;
    const btn = document.getElementById('btnSaveEditor');
    const content = document.getElementById('codeEditorTextarea').value;
    
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i> Saving...';
    lucide.createIcons();
    
    try {
        const res = await fetch(`/api/files/${currentEditingFile.id}/content`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: content })
        });
        
        const data = await res.json();
        if (res.ok && data.success) {
            showToast("Saved to Telegram Cloud!", "success");
            document.getElementById('editorStatusText').textContent = "Saved at " + new Date().toLocaleTimeString();
            loadCurrentDirectory();
        } else {
            showToast(data.detail || "Failed to save file", "error");
        }
    } catch (e) {
        showToast("Error saving: " + e.message, "error");
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="save" class="w-3.5 h-3.5"></i> Save Changes';
        lucide.createIcons();
    }
}

function handleEditorPreview() {
    const ext = (currentEditingFile.name?.split('.').pop() || '').toLowerCase();
    if (ext === 'html' || ext === 'htm') {
        if (currentFolderId) {
            window.open(`/site/${currentFolderId}/`, '_blank');
        } else {
            window.open(`/api/stream/${currentEditingFile.id}`, '_blank');
        }
    } else {
        window.open(`/api/stream/${currentEditingFile.id}`, '_blank');
    }
}

// ----------------- Move Item (File or Folder) -----------------
async function openMoveModal(type, id, name) {
    moveTarget = { type, id };
    document.getElementById('moveItemName').textContent = `${type.toUpperCase()}: ${name}`;
    const select = document.getElementById('moveDestinationSelect');
    select.innerHTML = '<option value="">📁 Root (My Cloud)</option>';
    
    try {
        const res = await fetch('/api/folders').then(r => r.json());
        res.forEach(f => {
            // Avoid selecting self as destination
            if (type === 'folder' && f.id === id) return;
            const opt = document.createElement('option');
            opt.value = f.id;
            opt.textContent = `📁 ${f.name}`;
            select.appendChild(opt);
        });
    } catch (e) {
        console.error("Error fetching folders:", e);
    }
    
    openModal('moveModal');
}

async function handleMoveSubmit(event) {
    event.preventDefault();
    const destVal = document.getElementById('moveDestinationSelect').value;
    const destFolderId = destVal ? parseInt(destVal) : null;
    
    const url = moveTarget.type === 'folder'
        ? `/api/folders/${moveTarget.id}/move`
        : `/api/files/${moveTarget.id}/move`;
        
    const body = moveTarget.type === 'folder'
        ? { parent_id: destFolderId }
        : { folder_id: destFolderId };
        
    try {
        const res = await fetch(url, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        
        const data = await res.json();
        if (res.ok && data.success) {
            closeModal('moveModal');
            showToast("Item moved successfully!", "success");
            loadCurrentDirectory();
        } else {
            showToast(data.detail || "Failed to move item", "error");
        }
    } catch (e) {
        showToast("Error moving item", "error");
    }
}

// ----------------- Zip Folder & Website Starter -----------------
function handleDownloadFolderZip() {
    if (!currentFolderId) return;
    showToast("Generating ZIP archive from Telegram Cloud...", "info");
    window.location.href = `/api/folders/${currentFolderId}/download-zip`;
}

async function handleInitWebsite() {
    if (!currentFolderId) return;
    if (!confirm("Add starter Website files (index.html, style.css, script.js) to this folder?")) return;
    
    try {
        showToast("Generating website starter template...", "info");
        const res = await fetch(`/api/folders/${currentFolderId}/init-website`, { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast("Website template created! Opening site...", "success");
            loadCurrentDirectory();
            setTimeout(() => {
                window.open(data.site_url, '_blank');
            }, 800);
        } else {
            showToast(data.detail || "Failed to initialize website", "error");
        }
    } catch (e) {
        showToast("Error creating website template", "error");
    }
}

// ----------------- Local File Upload -----------------
async function handleLocalFileUpload(event) {
    const files = event.target.files;
    if (!files || files.length === 0) return;
    
    for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);
        if (currentFolderId) {
            formData.append('folder_id', currentFolderId);
        }
        
        try {
            const res = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (res.ok && data.success) {
                showToast(`Uploading ${file.name}...`, "info");
                openTasksDrawer();
            } else {
                showToast(data.detail || `Upload failed for ${file.name}`, "error");
            }
        } catch (e) {
            console.error("Upload error:", e);
            showToast(`Failed to upload ${file.name}`, "error");
        }
    }
    
    event.target.value = '';
}

function setupDragAndDrop() {
    const dropZone = document.getElementById('dropZone');
    const dragOverlay = document.getElementById('dragOverlay');
    
    ['dragenter', 'dragover'].forEach(eventName => {
        window.addEventListener(eventName, (e) => {
            e.preventDefault();
            dragOverlay.classList.remove('opacity-0');
        }, false);
    });
    
    ['dragleave', 'drop'].forEach(eventName => {
        window.addEventListener(eventName, (e) => {
            e.preventDefault();
            dragOverlay.classList.add('opacity-0');
        }, false);
    });
    
    window.addEventListener('drop', (e) => {
        e.preventDefault();
        dragOverlay.classList.add('opacity-0');
        if (e.dataTransfer && e.dataTransfer.files.length > 0) {
            handleLocalFileUpload({ target: { files: e.dataTransfer.files } });
        }
    });
}

// ----------------- Task Polling -----------------
function startTasksPolling() {
    if (activeTasksPolling) clearInterval(activeTasksPolling);
    
    activeTasksPolling = setInterval(async () => {
        try {
            const res = await fetch('/api/tasks');
            if (!res.ok) return;
            const tasks = await res.json();
            renderTasks(tasks);
        } catch (e) {
            // silent polling error
        }
    }, 1500);
}

function renderTasks(tasks) {
    const list = document.getElementById('tasksList');
    const badge = document.getElementById('sidebarTaskBadge');
    
    const activeTasks = tasks.filter(t => ['pending', 'downloading', 'uploading'].includes(t.status));
    
    if (activeTasks.length > 0) {
        badge.textContent = activeTasks.length;
        badge.classList.remove('hidden');
    } else {
        badge.classList.add('hidden');
    }
    
    if (tasks.length === 0) {
        list.innerHTML = '<p class="text-xs text-dark-muted text-center py-4">No active or recent transfers</p>';
        return;
    }
    
    list.innerHTML = tasks.map(t => {
        const isCompleted = t.status === 'completed';
        const isFailed = t.status === 'failed';
        
        const statusColor = isCompleted ? 'text-emerald-400' : isFailed ? 'text-rose-400' : 'text-brand-500';
        const barColor = isCompleted ? 'bg-emerald-500' : isFailed ? 'bg-rose-500' : 'bg-brand-500';
        
        return `
            <div class="bg-slate-900/90 border border-dark-border rounded-xl p-3 text-xs space-y-2">
                <div class="flex items-center justify-between">
                    <span class="font-semibold text-white truncate max-w-[200px]" title="${escapeHtml(t.title)}">${escapeHtml(t.title)}</span>
                    <span class="${statusColor} font-bold uppercase text-[10px]">${t.status}</span>
                </div>
                <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                    <div class="${barColor} h-1.5 rounded-full transition-all duration-300" style="width: ${t.progress}%"></div>
                </div>
                <div class="flex items-center justify-between text-[11px] text-dark-muted">
                    <span class="${isFailed ? 'text-rose-400 font-medium' : ''}">${escapeHtml(t.step || '')}</span>
                    <span class="font-mono font-bold text-slate-300">${t.progress}%</span>
                </div>
                ${isFailed && t.error ? `
                    <div class="mt-1 p-2 bg-rose-500/10 border border-rose-500/20 rounded-lg text-[10px] text-rose-300 break-words">
                        ${escapeHtml(t.error)}
                    </div>
                ` : ''}
                ${isFailed ? `
                    <div class="pt-1 flex items-center justify-end">
                        <button onclick="handleRetryTask('${t.id}')" class="px-2.5 py-1 bg-amber-500/20 hover:bg-amber-500/30 text-amber-400 border border-amber-500/30 rounded-lg text-[10px] font-semibold flex items-center gap-1 transition-all">
                            <i data-lucide="rotate-ccw" class="w-3 h-3"></i> Resume / Retry
                        </button>
                    </div>
                ` : ''}
            </div>
        `;
    }).join('');
    
    // Auto reload directory if a task recently completed
    if (tasks.some(t => t.status === 'completed' && (Date.now() / 1000 - t.updated_at < 2))) {
        loadCurrentDirectory();
    }
}

function toggleTasksDrawer() {
    const drawer = document.getElementById('tasksDrawer');
    drawer.classList.toggle('hidden');
    lucide.createIcons();
}

function openTasksDrawer() {
    const drawer = document.getElementById('tasksDrawer');
    drawer.classList.remove('hidden');
    lucide.createIcons();
}

async function clearCompletedTasks() {
    await fetch('/api/tasks/clear', { method: 'DELETE' });
    loadCurrentDirectory();
}

// ----------------- Media Preview & Streaming -----------------
async function openFilePreview(fileId) {
    try {
        const file = await fetch(`/api/files/${fileId}`).then(r => r.json());
        if (!file) return;
        
        const info = getFileTypeInfo(file.mime_type, file.name);
        document.getElementById('previewTitle').textContent = file.name;
        document.getElementById('previewDownloadBtn').href = `/api/download/${file.id}`;
        
        const previewBody = document.getElementById('previewBody');
        const streamUrl = `/api/stream/${file.id}`;
        
        if (info.type === 'video') {
            previewBody.innerHTML = `
                <video controls autoplay class="max-h-[70vh] max-w-full rounded-xl shadow-2xl bg-black">
                    <source src="${streamUrl}" type="${file.mime_type || 'video/mp4'}">
                    Your browser does not support HTML5 video streaming.
                </video>
            `;
        } else if (info.type === 'audio') {
            previewBody.innerHTML = `
                <div class="w-full max-w-md bg-slate-900 border border-dark-border p-6 rounded-2xl flex flex-col items-center gap-4 text-center">
                    <div class="w-16 h-16 rounded-2xl bg-amber-500/20 text-amber-400 flex items-center justify-center">
                        <i data-lucide="music" class="w-8 h-8"></i>
                    </div>
                    <p class="font-semibold text-white truncate max-w-xs">${escapeHtml(file.name)}</p>
                    <audio controls autoplay class="w-full">
                        <source src="${streamUrl}" type="${file.mime_type || 'audio/mp3'}">
                    </audio>
                </div>
            `;
        } else if (info.type === 'image') {
            previewBody.innerHTML = `
                <img src="${streamUrl}" alt="${escapeHtml(file.name)}" class="max-h-[75vh] max-w-full rounded-xl shadow-2xl object-contain">
            `;
        } else if (info.type === 'pdf') {
            previewBody.innerHTML = `
                <iframe src="${streamUrl}" class="w-full h-[75vh] rounded-xl border border-dark-border bg-white"></iframe>
            `;
        } else {
            previewBody.innerHTML = `
                <div class="text-center py-10 space-y-4">
                    <div class="w-16 h-16 rounded-2xl bg-slate-800 text-slate-400 mx-auto flex items-center justify-center">
                        <i data-lucide="${info.icon}" class="w-8 h-8"></i>
                    </div>
                    <p class="text-slate-300 text-sm">Preview not directly supported for this format.</p>
                    <a href="/api/download/${file.id}" download class="inline-flex items-center gap-2 px-5 py-2.5 bg-brand-500 hover:bg-brand-600 text-white rounded-xl text-sm font-semibold shadow-lg">
                        <i data-lucide="download" class="w-4 h-4"></i> Download File (${file.human_size})
                    </a>
                </div>
            `;
        }
        
        openModal('previewModal');
    } catch (e) {
        console.error("Preview error:", e);
        showToast("Could not open preview", "error");
    }
}

// ----------------- Telegram Auth & Setup -----------------
function setAuthTab(tab) {
    const userBtn = document.getElementById('tabUserLoginBtn');
    const botBtn = document.getElementById('tabBotLoginBtn');
    const userSection = document.getElementById('userLoginSection');
    const botSection = document.getElementById('botLoginSection');
    
    if (tab === 'user') {
        userBtn.className = 'px-4 py-2 border-b-2 border-brand-500 text-white font-semibold text-xs';
        botBtn.className = 'px-4 py-2 border-b-2 border-transparent text-dark-muted hover:text-white text-xs';
        userSection.classList.remove('hidden');
        botSection.classList.add('hidden');
    } else {
        botBtn.className = 'px-4 py-2 border-b-2 border-brand-500 text-white font-semibold text-xs';
        userBtn.className = 'px-4 py-2 border-b-2 border-transparent text-dark-muted hover:text-white text-xs';
        botSection.classList.remove('hidden');
        userSection.classList.add('hidden');
    }
}

async function checkAuthStatus() {
    try {
        const res = await fetch('/api/auth/status');
        const data = await res.json();
        
        const userNameDisplay = document.getElementById('userNameDisplay');
        const userStatusDisplay = document.getElementById('userStatusDisplay');
        const userAvatar = document.getElementById('userAvatar');
        const modalStatusText = document.getElementById('modalAuthStatusText');
        const modalDetailText = document.getElementById('modalAuthDetailText');
        const statusDot = document.getElementById('statusDot');
        const logoutBtn = document.getElementById('modalLogoutBtn');
        const authFormContainer = document.getElementById('authFormContainer');
        
        if (data.authorized && data.user) {
            const name = data.user.first_name || (data.user.username ? `@${data.user.username}` : 'Telegram Active');
            userNameDisplay.textContent = name;
            userStatusDisplay.textContent = data.user.is_bot ? '● Bot Active' : '● Connected';
            userStatusDisplay.className = 'text-[10px] text-emerald-400 truncate';
            userAvatar.textContent = name.charAt(0).toUpperCase();
            userAvatar.className = 'w-8 h-8 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 flex items-center justify-center font-bold text-xs flex-shrink-0';
            
            modalStatusText.textContent = `Connected: ${name}`;
            modalDetailText.textContent = data.user.phone ? `Phone: ${data.user.phone}` : (data.user.username ? `@${data.user.username} (Bot)` : 'Unlimited Cloud Storage Active');
            statusDot.className = 'w-3 h-3 rounded-full bg-emerald-400';
            logoutBtn.classList.remove('hidden');
            authFormContainer.classList.add('hidden');
        } else {
            userNameDisplay.textContent = 'Not Connected';
            userStatusDisplay.textContent = 'Setup Required';
            userStatusDisplay.className = 'text-[10px] text-amber-400 truncate';
            userAvatar.textContent = '!';
            userAvatar.className = 'w-8 h-8 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30 flex items-center justify-center font-bold text-xs flex-shrink-0';
            
            modalStatusText.textContent = 'Telegram Not Connected';
            modalDetailText.textContent = 'Enter API ID & HASH or Bot Token to connect storage.';
            statusDot.className = 'w-3 h-3 rounded-full bg-amber-400 animate-pulse';
            logoutBtn.classList.add('hidden');
            authFormContainer.classList.remove('hidden');
        }
    } catch (e) {
        console.error("Auth check error:", e);
    }
}

function openTelegramModal() {
    checkAuthStatus();
    loadSettings();
    openModal('telegramModal');
}

async function loadSettings() {
    try {
        const res = await fetch('/api/settings').then(r => r.json());
        if (res.gdrive_cookie) {
            document.getElementById('cfgGDriveCookie').value = res.gdrive_cookie;
        }
    } catch (e) {
        console.error("Error loading settings:", e);
    }
}

async function handleSaveGDriveCookie() {
    const cookie = document.getElementById('cfgGDriveCookie').value.trim();
    try {
        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ gdrive_cookie: cookie })
        });
        if (res.ok) {
            showToast("Google Drive cookie saved successfully!", "success");
        } else {
            showToast("Failed to save cookie", "error");
        }
    } catch (e) {
        showToast("Error saving cookie", "error");
    }
}

async function handleSendLoginCode() {
    const apiId = document.getElementById('cfgApiId').value.trim();
    const apiHash = document.getElementById('cfgApiHash').value.trim();
    const phone = document.getElementById('cfgPhone').value.trim();
    
    if (!apiId || !apiHash || !phone) {
        showToast("Please fill in API ID, API HASH, and Phone Number", "error");
        return;
    }
    
    const btn = document.getElementById('btnSendCode');
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Sending code...';
    lucide.createIcons();
    
    try {
        const res = await fetch('/api/auth/send-code', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_id: apiId, api_hash: apiHash, phone: phone })
        });
        const data = await res.json();
        
        if (data.success) {
            phoneCodeHash = data.phone_code_hash;
            showToast("Verification code sent to your Telegram app!", "success");
            document.getElementById('stepPhoneSection').classList.add('hidden');
            document.getElementById('stepCodeSection').classList.remove('hidden');
        } else {
            showToast(data.error || "Failed to send code", "error");
        }
    } catch (e) {
        showToast("Connection error: " + e.message, "error");
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="send" class="w-4 h-4"></i> Send Verification Code';
        lucide.createIcons();
    }
}

async function handleVerifyLoginCode() {
    const phone = document.getElementById('cfgPhone').value.trim();
    const code = document.getElementById('cfgCode').value.trim();
    const password = document.getElementById('cfgPassword').value;
    
    if (!code) {
        showToast("Please enter verification code", "error");
        return;
    }
    
    const btn = document.getElementById('btnVerifyCode');
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Verifying...';
    lucide.createIcons();
    
    try {
        const res = await fetch('/api/auth/verify-code', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                phone: phone,
                code: code,
                phone_code_hash: phoneCodeHash,
                password: password || null
            })
        });
        const data = await res.json();
        
        if (data.success) {
            showToast("Telegram connected successfully!", "success");
            checkAuthStatus();
            closeModal('telegramModal');
            loadCurrentDirectory();
        } else if (data.requires_password) {
            document.getElementById('passwordFieldGroup').classList.remove('hidden');
            showToast(data.error || "2FA Password is required", "info");
        } else {
            showToast(data.error || "Verification failed", "error");
        }
    } catch (e) {
        showToast("Verification error: " + e.message, "error");
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="check-circle" class="w-4 h-4"></i> Complete Login';
        lucide.createIcons();
    }
}

async function handleBotLogin() {
    const apiId = document.getElementById('cfgApiId').value.trim();
    const apiHash = document.getElementById('cfgApiHash').value.trim();
    const botToken = document.getElementById('cfgBotToken').value.trim();
    
    if (!apiId || !apiHash || !botToken) {
        showToast("Please fill in API ID, API HASH, and Bot Token", "error");
        return;
    }
    
    const btn = document.getElementById('btnBotLogin');
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Connecting Bot...';
    lucide.createIcons();
    
    try {
        const res = await fetch('/api/auth/bot-login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                api_id: apiId,
                api_hash: apiHash,
                bot_token: botToken
            })
        });
        const data = await res.json();
        
        if (data.success) {
            showToast("Bot connected successfully!", "success");
            checkAuthStatus();
            closeModal('telegramModal');
            loadCurrentDirectory();
        } else {
            showToast(data.error || "Failed to connect bot", "error");
        }
    } catch (e) {
        showToast("Bot login error: " + e.message, "error");
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="bot" class="w-4 h-4"></i> Connect Bot';
        lucide.createIcons();
    }
}

async function handleLogout() {
    if (!confirm("Are you sure you want to disconnect Telegram?")) return;
    try {
        await fetch('/api/auth/logout', { method: 'POST' });
        showToast("Disconnected from Telegram", "info");
        checkAuthStatus();
        loadCurrentDirectory();
    } catch (e) {
        showToast("Error disconnecting", "error");
    }
}

// ----------------- Create / Rename / Delete -----------------
function openCreateFolderModal() {
    document.getElementById('folderNameInput').value = '';
    openModal('createFolderModal');
}

async function handleCreateFolderSubmit(event) {
    event.preventDefault();
    const name = document.getElementById('folderNameInput').value.trim();
    if (!name) return;
    
    try {
        const res = await fetch('/api/folders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name, parent_id: currentFolderId })
        });
        if (res.ok) {
            closeModal('createFolderModal');
            showToast(`Created folder "${name}"`, "success");
            loadCurrentDirectory();
        } else {
            showToast("Failed to create folder", "error");
        }
    } catch (e) {
        showToast("Error creating folder", "error");
    }
}

function openRenameModal(type, id, currentName) {
    renameTarget = { type, id };
    document.getElementById('renameInput').value = currentName;
    openModal('renameModal');
}

async function handleRenameSubmit(event) {
    event.preventDefault();
    const newName = document.getElementById('renameInput').value.trim();
    if (!newName) return;
    
    const url = renameTarget.type === 'folder' 
        ? `/api/folders/${renameTarget.id}`
        : `/api/files/${renameTarget.id}/rename`;
        
    try {
        const res = await fetch(url, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: newName })
        });
        if (res.ok) {
            closeModal('renameModal');
            showToast("Renamed successfully", "success");
            loadCurrentDirectory();
        } else {
            showToast("Failed to rename item", "error");
        }
    } catch (e) {
        showToast("Error renaming item", "error");
    }
}

async function handleDeleteFolder(folderId) {
    if (!confirm("Are you sure you want to delete this folder and all its contents?")) return;
    try {
        const res = await fetch(`/api/folders/${folderId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast("Folder deleted", "success");
            loadCurrentDirectory();
        } else {
            showToast("Failed to delete folder", "error");
        }
    } catch (e) {
        showToast("Error deleting folder", "error");
    }
}

async function handleDeleteFile(fileId) {
    if (!confirm("Are you sure you want to delete this file from Cloud Storage?")) return;
    try {
        const res = await fetch(`/api/files/${fileId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast("File deleted", "success");
            loadCurrentDirectory();
        } else {
            showToast("Failed to delete file", "error");
        }
    } catch (e) {
        showToast("Error deleting file", "error");
    }
}

// ----------------- Search -----------------
function setupSearch() {
    const input = document.getElementById('searchInput');
    let timeout = null;
    
    input.addEventListener('input', () => {
        clearTimeout(timeout);
        const q = input.value.trim();
        if (!q) {
            loadCurrentDirectory();
            return;
        }
        
        timeout = setTimeout(async () => {
            try {
                const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`).then(r => r.json());
                folders = res.folders || [];
                files = res.files || [];
                renderCurrentDirectory();
            } catch (e) {
                console.error("Search error:", e);
            }
        }, 300);
    });
}

// ----------------- Public Share & Retry -----------------
async function openShareModal(fileId, fileName) {
    document.getElementById('shareFileName').textContent = fileName;
    const input = document.getElementById('shareUrlInput');
    const previewLink = document.getElementById('sharePreviewLink');
    const btnCopy = document.getElementById('btnCopyShare');
    
    btnCopy.innerHTML = '<i data-lucide="copy" class="w-3.5 h-3.5"></i> Copy';
    input.value = "Generating share link...";
    openModal('shareModal');
    
    try {
        const res = await fetch(`/api/files/${fileId}/share`, { method: 'POST' });
        const data = await res.json();
        if (data.success && data.share_url) {
            const fullUrl = `${window.location.origin}${data.share_url}`;
            input.value = fullUrl;
            previewLink.href = data.share_url;
        } else {
            input.value = "Failed to generate link";
            showToast("Failed to create share link", "error");
        }
    } catch (e) {
        input.value = "Error generating link";
        showToast("Error creating share link", "error");
    }
    lucide.createIcons();
}

function copyShareLink() {
    const input = document.getElementById('shareUrlInput');
    input.select();
    navigator.clipboard.writeText(input.value);
    
    const btn = document.getElementById('btnCopyShare');
    btn.innerHTML = '<i data-lucide="check" class="w-3.5 h-3.5"></i> Copied!';
    lucide.createIcons();
    showToast("Public link copied to clipboard!", "success");
    setTimeout(() => {
        btn.innerHTML = '<i data-lucide="copy" class="w-3.5 h-3.5"></i> Copy';
        lucide.createIcons();
    }, 2000);
}

async function handleRetryTask(taskId) {
    try {
        showToast("Resuming transfer...", "info");
        const res = await fetch(`/api/tasks/${taskId}/retry`, { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast("Transfer resumed!", "success");
            openTasksDrawer();
        } else {
            showToast(data.detail || "Failed to resume transfer", "error");
        }
    } catch (e) {
        showToast("Connection error while resuming", "error");
    }
}

// Helper: HTML escape
function escapeHtml(text) {
    return text ? text.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#039;').replace(/</g, '&lt;').replace(/>/g, '&gt;') : '';
}

// ==================== DEPLOYMENTS & WEB HOSTING HUB ====================
let allDeployments = [];

function showDriveView() {
    document.getElementById('driveViewContainer').classList.remove('hidden');
    document.getElementById('deploymentsViewContainer').classList.add('hidden');
    
    document.getElementById('navDriveBtn').className = 'sidebar-link active w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all text-slate-200 hover:bg-slate-800/80';
    document.getElementById('navDeployBtn').className = 'w-full flex items-center justify-between px-4 py-3 rounded-xl text-sm font-medium transition-all text-slate-300 hover:bg-slate-800/80 hover:text-white group';
    
    loadCurrentDirectory();
}

function showDeploymentsView() {
    document.getElementById('driveViewContainer').classList.add('hidden');
    document.getElementById('deploymentsViewContainer').classList.remove('hidden');
    
    document.getElementById('navDeployBtn').className = 'sidebar-link active w-full flex items-center justify-between px-4 py-3 rounded-xl text-sm font-medium transition-all text-slate-200 bg-slate-800/90';
    document.getElementById('navDriveBtn').className = 'w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all text-slate-300 hover:bg-slate-800/80 hover:text-white';
    
    loadDeployments();
}

async function loadDeployments() {
    try {
        const res = await fetch('/api/deployments');
        const deps = await res.json();
        allDeployments = deps;
        
        const badge = document.getElementById('sidebarDeployBadge');
        if (badge) {
            if (deps.length > 0) {
                badge.textContent = deps.length;
                badge.classList.remove('hidden');
            } else {
                badge.classList.add('hidden');
            }
        }
        
        renderDeployments(deps);
    } catch (e) {
        console.error("Error loading deployments:", e);
    }
}

function renderDeployments(deps) {
    const grid = document.getElementById('deploymentsGrid');
    const emptyState = document.getElementById('deploymentsEmptyState');
    
    if (!grid || !emptyState) return;

    if (!deps || deps.length === 0) {
        grid.innerHTML = '';
        emptyState.classList.remove('hidden');
        return;
    }
    
    emptyState.classList.add('hidden');
    
    grid.innerHTML = deps.map(d => {
        let typeIcon = 'rocket';
        let typeBadge = 'Website';
        let typeColor = 'text-purple-400 bg-purple-500/10 border-purple-500/20';
        
        if (d.type === 'tg_mini_app') {
            typeIcon = 'smartphone';
            typeBadge = 'Telegram Mini App';
            typeColor = 'text-cyan-400 bg-cyan-500/10 border-cyan-500/20';
        } else if (d.type === 'bio_link') {
            typeIcon = 'link-2';
            typeBadge = 'Link-in-Bio';
            typeColor = 'text-pink-400 bg-pink-500/10 border-pink-500/20';
        } else if (d.type === 'retro_game') {
            typeIcon = 'gamepad-2';
            typeBadge = 'HTML5 Game';
            typeColor = 'text-amber-400 bg-amber-500/10 border-amber-500/20';
        } else if (d.type === 'portfolio') {
            typeIcon = 'sparkles';
            typeBadge = 'Portfolio';
            typeColor = 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20';
        }
        
        const visits = d.visits_count || 0;
        const liveUrl = `/d/${d.slug}`;
        
        return `
            <div class="bg-slate-900/80 border border-dark-border hover:border-purple-500/40 rounded-2xl p-5 shadow-xl transition-all hover:scale-[1.01] flex flex-col justify-between space-y-4 group">
                <div class="space-y-3">
                    <div class="flex items-start justify-between gap-3">
                        <div class="flex items-center gap-3 overflow-hidden">
                            <div class="w-10 h-10 rounded-xl ${typeColor} flex items-center justify-center flex-shrink-0">
                                <i data-lucide="${typeIcon}" class="w-5 h-5"></i>
                            </div>
                            <div class="overflow-hidden">
                                <h3 class="font-bold text-sm text-white truncate group-hover:text-purple-300 transition-colors">${escapeHtml(d.name)}</h3>
                                <span class="text-[10px] font-medium px-2 py-0.5 rounded-full border ${typeColor}">${typeBadge}</span>
                            </div>
                        </div>
                        <span class="flex items-center gap-1 text-[11px] text-emerald-400 font-semibold bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-full">
                            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> Live
                        </span>
                    </div>

                    <!-- Telegram Direct Link (if bot username exists) -->
                    ${d.tg_app_url ? `
                    <div class="bg-blue-950/50 border border-blue-500/30 rounded-xl p-2.5 flex items-center justify-between text-xs font-mono text-blue-300">
                        <div class="flex items-center gap-2 overflow-hidden mr-2">
                            <i data-lucide="send" class="w-3.5 h-3.5 text-blue-400 flex-shrink-0"></i>
                            <span class="truncate select-all text-[11px]">${escapeHtml(d.tg_app_url)}</span>
                        </div>
                        <div class="flex items-center gap-1 flex-shrink-0">
                            <button onclick="copyToClipboard('${d.tg_app_url}', 'Telegram Link')" class="p-1 hover:text-white text-blue-400 rounded transition-colors" title="Copy Telegram Link">
                                <i data-lucide="copy" class="w-3.5 h-3.5"></i>
                            </button>
                            <a href="${d.tg_app_url}" target="_blank" class="p-1 hover:text-white text-blue-400 rounded transition-colors" title="Open in Telegram">
                                <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
                            </a>
                        </div>
                    </div>` : ''}

                    <!-- Web URL Display Box -->
                    <div class="bg-slate-950/80 border border-dark-border rounded-xl p-2.5 flex items-center justify-between text-xs font-mono text-cyan-400">
                        <span class="truncate select-all mr-2 text-[11px]">/d/${d.slug}/</span>
                        <div class="flex items-center gap-1 flex-shrink-0">
                            <button onclick="copyDeploymentUrl('${d.slug}')" class="p-1 hover:text-white text-dark-muted rounded transition-colors" title="Copy Link">
                                <i data-lucide="copy" class="w-3.5 h-3.5"></i>
                            </button>
                            <a href="${liveUrl}" target="_blank" class="p-1 hover:text-white text-cyan-400 rounded transition-colors" title="Open Live Site">
                                <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
                            </a>
                        </div>
                    </div>

                    <!-- Meta Tags -->
                    <div class="flex items-center justify-between text-[11px] text-dark-muted pt-1">
                        <span onclick="editDeploymentFiles(${d.folder_id})" class="hover:text-white text-slate-400 cursor-pointer flex items-center gap-1 truncate" title="View in Drive">
                            <i data-lucide="folder" class="w-3 h-3 text-brand-500"></i> ${escapeHtml(d.folder_name || 'Folder #' + d.folder_id)}
                        </span>
                        <span class="flex items-center gap-1 text-slate-400">
                            <i data-lucide="eye" class="w-3 h-3 text-amber-400"></i> ${visits} visit${visits === 1 ? '' : 's'}
                        </span>
                    </div>
                </div>

                <!-- Card Action Buttons -->
                <div class="pt-3 border-t border-dark-border/60 flex items-center justify-between gap-2">
                    <div class="flex items-center gap-1.5 flex-wrap">
                        ${d.tg_app_url ? `
                        <a href="${d.tg_app_url}" target="_blank" class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-blue-500/20 text-blue-300 hover:bg-blue-500/30 border border-blue-500/30 transition-all flex items-center gap-1.5">
                            <i data-lucide="send" class="w-3 h-3"></i> Telegram Link
                        </a>` : ''}
                        <a href="${liveUrl}" target="_blank" class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-purple-500/20 text-purple-300 hover:bg-purple-500/30 border border-purple-500/30 transition-all flex items-center gap-1.5">
                            <i data-lucide="play" class="w-3 h-3"></i> Open Web
                        </a>
                        <button onclick="editDeploymentFiles(${d.folder_id})" class="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-dark-border transition-all flex items-center gap-1.5">
                            <i data-lucide="file-code" class="w-3 h-3 text-cyan-400"></i> Edit Files
                        </button>
                    </div>
                    <button onclick="handleDeleteDeployment('${d.id}')" class="p-1.5 text-dark-muted hover:text-rose-400 rounded-lg hover:bg-rose-500/10 transition-all" title="Unpublish / Delete Deployment">
                        <i data-lucide="trash-2" class="w-4 h-4"></i>
                    </button>
                </div>
            </div>
        `;
    }).join('');
    
    lucide.createIcons();
}

function copyDeploymentUrl(slug) {
    const fullUrl = `${window.location.origin}/d/${slug}/`;
    navigator.clipboard.writeText(fullUrl);
    showToast(`Copied: /d/${slug}/`, 'success');
}

function editDeploymentFiles(folderId) {
    showDriveView();
    navigateToFolder(folderId);
}

// Deploy Modal Management
async function openDeployModal(defaultTab = 'starter') {
    try {
        const foldersRes = await fetch('/api/folders').then(r => r.json());
        const select = document.getElementById('deployFolderSelect');
        if (select) {
            select.innerHTML = '<option value="">-- Choose a folder --</option>' + 
                foldersRes.map(f => `<option value="${f.id}" data-name="${escapeHtml(f.name)}">📁 ${escapeHtml(f.name)}</option>`).join('');
            
            if (currentFolderId) {
                select.value = currentFolderId;
                const opt = select.querySelector(`option[value="${currentFolderId}"]`);
                if (opt) {
                    const fName = opt.getAttribute('data-name');
                    document.getElementById('deployFolderName').value = fName;
                    autoGenerateSlug(fName, 'deployFolderSlug');
                }
            }
        }
    } catch (e) {
        console.error("Error loading folders for deploy modal:", e);
    }
    
    setDeployTab(defaultTab);
    openModal('deployModal');
}

function setDeployTab(tab) {
    const starterBtn = document.getElementById('tabDeployStarterBtn');
    const folderBtn = document.getElementById('tabDeployFolderBtn');
    const zipBtn = document.getElementById('tabDeployZipBtn');
    
    const starterForm = document.getElementById('deployStarterForm');
    const folderForm = document.getElementById('deployFolderForm');
    const zipForm = document.getElementById('deployZipForm');
    
    const activeBtnClass = 'px-4 py-2 border-b-2 border-purple-500 text-white font-semibold text-xs transition-all';
    const inactiveBtnClass = 'px-4 py-2 border-b-2 border-transparent text-dark-muted hover:text-white text-xs transition-all';
    
    if (starterBtn) starterBtn.className = tab === 'starter' ? activeBtnClass : inactiveBtnClass;
    if (folderBtn) folderBtn.className = tab === 'folder' ? activeBtnClass : inactiveBtnClass;
    if (zipBtn) zipBtn.className = tab === 'zip' ? activeBtnClass : inactiveBtnClass;
    
    if (starterForm && folderForm && zipForm) {
        if (tab === 'starter') {
            starterForm.classList.remove('hidden');
            folderForm.classList.add('hidden');
            zipForm.classList.add('hidden');
        } else if (tab === 'folder') {
            folderForm.classList.remove('hidden');
            starterForm.classList.add('hidden');
            zipForm.classList.add('hidden');
        } else if (tab === 'zip') {
            zipForm.classList.remove('hidden');
            starterForm.classList.add('hidden');
            folderForm.classList.add('hidden');
        }
    }
}

function updateTemplateSelection(radio) {
    document.querySelectorAll('.template-card').forEach(card => {
        card.classList.remove('border-purple-500', 'bg-purple-500/15');
        card.classList.add('border-dark-border', 'bg-slate-900/60');
    });
    
    const parentCard = radio.closest('.template-card');
    if (parentCard) {
        parentCard.classList.add('border-purple-500', 'bg-purple-500/15');
        parentCard.classList.remove('border-dark-border', 'bg-slate-900/60');
    }

    const nameInput = document.getElementById('deployStarterName');
    const slugInput = document.getElementById('deployStarterSlug');
    const preview = document.getElementById('starterLiveUrlPreview');
    if (nameInput && slugInput) {
        if (radio.value === 'fastotp') {
            nameInput.value = 'FastOTP Live Panel';
            slugInput.value = 'otp';
            if (preview) preview.textContent = '/d/otp/';
        } else if (radio.value === 'portfolio' && (!nameInput.value || nameInput.value.includes('FastOTP') || nameInput.value.includes('Mini App'))) {
            nameInput.value = 'My Portfolio Site';
            slugInput.value = 'my-portfolio';
            if (preview) preview.textContent = '/d/my-portfolio/';
        } else if (radio.value === 'tg_mini_app' && (!nameInput.value || nameInput.value.includes('FastOTP') || nameInput.value.includes('Portfolio'))) {
            nameInput.value = 'Telegram Mini App';
            slugInput.value = 'mini-app';
            if (preview) preview.textContent = '/d/mini-app/';
        }
    }
}

function autoGenerateSlug(text, targetId) {
    const slug = text.toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/(^-|-$)+/g, '');
    const target = document.getElementById(targetId);
    if (target) {
        target.value = slug;
    }
    const preview = document.getElementById('starterLiveUrlPreview');
    if (preview && targetId === 'deployStarterSlug') {
        preview.textContent = `/d/${slug || 'my-portfolio'}/`;
    }
}

function handleFolderSelectChange(select) {
    const opt = select.options[select.selectedIndex];
    if (opt && opt.value) {
        const name = opt.getAttribute('data-name') || opt.text.replace('📁 ', '');
        document.getElementById('deployFolderName').value = name;
        autoGenerateSlug(name, 'deployFolderSlug');
    }
}

function handleZipFileSelected(event) {
    const file = event.target.files[0];
    if (file) {
        document.getElementById('zipFileLabel').textContent = file.name;
        const stem = file.name.replace(/\.zip$/i, '');
        const nameInput = document.getElementById('deployZipName');
        if (!nameInput.value) {
            nameInput.value = stem;
            autoGenerateSlug(stem, 'deployZipSlug');
        }
    }
}

function handleDeployCurrentFolder() {
    if (!currentFolderId) return;
    openDeployModal('folder');
}

// Deploy Submit Handlers
async function handleDeployStarterSubmit(event) {
    event.preventDefault();
    const btn = document.getElementById('btnSubmitDeployStarter');
    const origText = btn.innerHTML;
    
    const name = document.getElementById('deployStarterName').value.trim();
    const slug = document.getElementById('deployStarterSlug').value.trim();
    const templateType = document.querySelector('input[name="starterTemplateType"]:checked')?.value || 'portfolio';
    
    try {
        btn.disabled = true;
        btn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Deploying...';
        lucide.createIcons();
        
        const res = await fetch('/api/deployments/create-starter', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name,
                slug,
                template_type: templateType,
                parent_id: currentFolderId
            })
        });
        
        const data = await res.json();
        if (res.ok && data.success) {
            closeModal('deployModal');
            showToast(`🎉 Website '${name}' deployed at /d/${data.deployment.slug}/`, 'success');
            showDeploymentsView();
            window.open(data.live_url, '_blank');
        } else {
            showToast(data.detail || "Failed to deploy starter template", "error");
        }
    } catch (e) {
        showToast("Error creating deployment: " + e.message, "error");
    } finally {
        btn.disabled = false;
        btn.innerHTML = origText;
        lucide.createIcons();
    }
}

async function handleDeployFolderSubmit(event) {
    event.preventDefault();
    const btn = document.getElementById('btnSubmitDeployFolder');
    const origText = btn.innerHTML;
    
    const folderId = parseInt(document.getElementById('deployFolderSelect').value);
    const name = document.getElementById('deployFolderName').value.trim();
    const slug = document.getElementById('deployFolderSlug').value.trim();
    
    if (!folderId) {
        showToast("Please select a folder to deploy", "error");
        return;
    }
    
    try {
        btn.disabled = true;
        btn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Deploying...';
        lucide.createIcons();
        
        const res = await fetch('/api/deployments', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name,
                slug,
                folder_id: folderId,
                type: 'static_website'
            })
        });
        
        const data = await res.json();
        if (res.ok && data.success) {
            closeModal('deployModal');
            showToast(`🚀 Deployed successfully at /d/${data.deployment.slug}/`, 'success');
            showDeploymentsView();
            window.open(data.live_url, '_blank');
        } else {
            showToast(data.detail || "Failed to deploy folder", "error");
        }
    } catch (e) {
        showToast("Error deploying folder: " + e.message, "error");
    } finally {
        btn.disabled = false;
        btn.innerHTML = origText;
        lucide.createIcons();
    }
}

async function handleDeployZipSubmit(event) {
    event.preventDefault();
    const btn = document.getElementById('btnSubmitDeployZip');
    const origText = btn.innerHTML;
    
    const fileInput = document.getElementById('deployZipInput');
    const name = document.getElementById('deployZipName').value.trim();
    const slug = document.getElementById('deployZipSlug').value.trim();
    
    if (!fileInput.files || !fileInput.files[0]) {
        showToast("Please choose a .zip file", "error");
        return;
    }
    
    const formData = new FormData();
    formData.append('zip_file', fileInput.files[0]);
    if (name) formData.append('name', name);
    if (slug) formData.append('slug', slug);
    if (currentFolderId) formData.append('parent_id', currentFolderId);
    
    try {
        btn.disabled = true;
        btn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Uploading & Deploying...';
        lucide.createIcons();
        
        const res = await fetch('/api/deployments/from-zip', {
            method: 'POST',
            body: formData
        });
        
        const data = await res.json();
        if (res.ok && data.success) {
            closeModal('deployModal');
            showToast(`🚀 ZIP website deployed live at /d/${data.deployment.slug}/`, 'success');
            showDeploymentsView();
            window.open(data.live_url, '_blank');
        } else {
            showToast(data.detail || "Failed to deploy from zip", "error");
        }
    } catch (e) {
        showToast("Error deploying ZIP: " + e.message, "error");
    } finally {
        btn.disabled = false;
        btn.innerHTML = origText;
        lucide.createIcons();
    }
}

async function handleDeleteDeployment(depId) {
    if (!confirm("Are you sure you want to unpublish / remove this deployment? (Files will remain safe in your cloud)")) {
        return;
    }
    
    try {
        const res = await fetch(`/api/deployments/${depId}`, { method: 'DELETE' });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast("Deployment removed", "info");
            loadDeployments();
        } else {
            showToast("Failed to delete deployment", "error");
        }
    } catch (e) {
        showToast("Error deleting deployment", "error");
    }
}
