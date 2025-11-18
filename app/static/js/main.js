// Bug Arena JavaScript

document.addEventListener('DOMContentLoaded', function() {
    // Auto-dismiss alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        if (!alert.classList.contains('alert-permanent')) {
            setTimeout(() => {
                const bsAlert = new bootstrap.Alert(alert);
                bsAlert.close();
            }, 5000);
        }
    });

    // Image preview for bug submission
    const imageInput = document.getElementById('image');
    if (imageInput) {
        imageInput.addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (file) {
                // If the page provides its own submission preview elements
                // (the multi-step form in `submit_bug.html`), update those
                // instead of creating a duplicate preview here.
                const pagePreviewDiv = document.getElementById('imagePreview');
                const pageFinalDiv = document.getElementById('finalImagePreview');

                if (pagePreviewDiv || pageFinalDiv) {
                    const reader = new FileReader();
                    reader.onload = function(e) {
                        const imgHtml = `<img src="${e.target.result}" alt="Preview" class="img-fluid">`;
                        if (pagePreviewDiv) pagePreviewDiv.innerHTML = imgHtml;
                        if (pageFinalDiv) pageFinalDiv.innerHTML = imgHtml;
                    };
                    reader.readAsDataURL(file);
                    return;
                }

                // Fallback: create a small inline preview for pages without
                // a dedicated preview area.
                const reader = new FileReader();
                reader.onload = function(e) {
                    // Create preview if it doesn't exist
                    let preview = document.getElementById('image-preview');
                    if (!preview) {
                        preview = document.createElement('img');
                        preview.id = 'image-preview';
                        preview.className = 'img-fluid mt-2';
                        preview.style.maxHeight = '300px';
                        imageInput.parentElement.appendChild(preview);
                    }
                    preview.src = e.target.result;
                };
                reader.readAsDataURL(file);
            }
        });
    }

    // Confirmation for battle creation
    const battleForm = document.querySelector('form[action*="battle"]');
    if (battleForm) {
        battleForm.addEventListener('submit', function(e) {
            if (!confirm('Are you ready to start this epic battle?')) {
                e.preventDefault();
            }
        });
    }

    // Add fade-in animation to cards
    const cards = document.querySelectorAll('.card');
    cards.forEach((card, index) => {
        setTimeout(() => {
            card.classList.add('fade-in');
        }, index * 100);
    });

    // Character counter for text areas
    const textareas = document.querySelectorAll('textarea[maxlength]');
    textareas.forEach(textarea => {
        const maxLength = textarea.getAttribute('maxlength');
        const counter = document.createElement('small');
        counter.className = 'form-text text-muted';
        counter.textContent = `0/${maxLength} characters`;
        textarea.parentElement.appendChild(counter);

        textarea.addEventListener('input', function() {
            const length = this.value.length;
            counter.textContent = `${length}/${maxLength} characters`;
        });
    });
});

// Function to upvote comments/lore (for future implementation)
function upvote(type, id) {
    fetch(`/${type}/${id}/upvote`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            const element = document.getElementById(`${type}-${id}-upvotes`);
            if (element) {
                element.textContent = data.upvotes;
            }
        }
    })
    .catch(error => console.error('Error:', error));
}

// Loading spinner for battle simulation
function showBattleLoading() {
    const spinner = document.createElement('div');
    spinner.className = 'spinner';
    spinner.id = 'battle-spinner';
    document.body.appendChild(spinner);
}

// Smooth scroll to top button (optional enhancement)
const scrollButton = document.createElement('button');
scrollButton.innerHTML = '↑';
scrollButton.className = 'btn btn-primary position-fixed bottom-0 end-0 m-3';
scrollButton.style.display = 'none';
scrollButton.onclick = () => window.scrollTo({ top: 0, behavior: 'smooth' });
document.body.appendChild(scrollButton);

window.addEventListener('scroll', () => {
    scrollButton.style.display = window.pageYOffset > 300 ? 'block' : 'none';
});