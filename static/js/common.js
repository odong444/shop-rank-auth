// ===== Sidebar Toggle =====
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    sidebar.classList.toggle('open');
    overlay.classList.toggle('open');
}

// ===== Modal Functions =====
function closeModal() {
    document.querySelectorAll('.modal').forEach(m => m.style.display = 'none');
}

// Close modal on background click
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', function(e) {
            if (e.target === this) closeModal();
        });
    });
});

// ===== Format Functions =====
function formatRank(r) {
    if (!r || r === '-' || r === 'loading') return '-';
    if (r === '300위 밖') return '<span style="color:#888">300위 밖</span>';
    return r + '위';
}

function formatNumber(num) {
    if (num === undefined || num === null) return '-';
    return Number(num).toLocaleString();
}
