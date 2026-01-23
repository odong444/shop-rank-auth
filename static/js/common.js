// ===== Modal Functions =====
function closeModal() {
    document.querySelectorAll('.modal').forEach(m => {
        if (m.close) m.close();
        else m.style.display = 'none';
    });
}

// Close modal on background click (for legacy modals)
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
    if (r === '300위 밖') return '<span class="text-base-content/50">300위 밖</span>';
    return r + '위';
}

function formatNumber(num) {
    if (num === undefined || num === null) return '-';
    return Number(num).toLocaleString();
}
