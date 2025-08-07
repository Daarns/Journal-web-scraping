document.addEventListener("DOMContentLoaded", function() {
    // Token handling
    const getToken = () => localStorage.getItem("token");
    const isLoggedIn = () => !!getToken();
    
    // Elements
    const addToCollectionModal = document.getElementById("addToCollectionModal");
    const collectionSelect = document.getElementById("collectionSelect");
    const newCollectionName = document.getElementById("newCollectionName");
    const newCollectionDesc = document.getElementById("newCollectionDesc");
    const paperNotes = document.getElementById("paperNotes");
    const saveToCollectionBtn = document.querySelector(".save-to-collection-btn");
    
    // Untuk menyimpan data paper saat ini
    let currentPaper = null;
    
    // Fungsi untuk menampilkan modal koleksi
    window.showCollectionModal = function(paper) {
        if (!paper || !paper.id || !isLoggedIn()) return;
        
        currentPaper = paper;
        
        // Set paper title di modal
        const titleEl = addToCollectionModal?.querySelector(".paper-collection-title");
        if (titleEl) titleEl.textContent = paper.title;
        
        // Reset form fields
        if (newCollectionName) newCollectionName.value = '';
        if (newCollectionDesc) newCollectionDesc.value = '';
        if (paperNotes) paperNotes.value = '';
        
        // Show modal
        const modal = new bootstrap.Modal(addToCollectionModal);
        modal.show();
    };
    
    // Save to collection handler
    if (saveToCollectionBtn) {
        saveToCollectionBtn.addEventListener("click", async function() {
            if (!currentPaper || !currentPaper.id) return;
            
            // Disable button
            this.disabled = true;
            this.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Menyimpan...';
            
            // Check if we're creating new collection or using existing
            const isNewCollection = collectionSelect.value === 'new' || document.querySelector('.create-new-section').classList.contains('d-none') === false;
            
            try {
                if (isNewCollection) {
                    // Validate new collection name
                    if (!newCollectionName || !newCollectionName.value.trim()) {
                        alert("Nama koleksi tidak boleh kosong");
                        return;
                    }
                    
                    // Create new collection first
                    const collection = await createCollection(
                        newCollectionName.value.trim(),
                        newCollectionDesc?.value.trim() || ""
                    );
                    
                    if (!collection || !collection.id) {
                        throw new Error("Gagal membuat koleksi baru");
                    }
                    
                    // Add paper to new collection
                    await addPaperToCollection(collection.id, currentPaper, paperNotes?.value.trim());
                    
                } else {
                    // Add to existing collection
                    await addPaperToCollection(collectionSelect.value, currentPaper, paperNotes?.value.trim());
                }
                
                // Show success message
                alert("Paper berhasil disimpan ke koleksi!");
                
                // Close modal
                const modal = bootstrap.Modal.getInstance(addToCollectionModal);
                modal.hide();
                
            } catch (error) {
                console.error("Error saving to collection:", error);
                alert("Terjadi kesalahan saat menyimpan paper ke koleksi.");
            } finally {
                // Re-enable button
                this.disabled = false;
                this.innerHTML = "Simpan";
            }
        });
    }
    
    // Create a new collection
    async function createCollection(name, description) {
        const headers = {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${getToken()}`
        };
        
        const response = await fetch('/api/activity/collections', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({
                name: name,
                description: description || ""
            })
        });
        
        if (!response.ok) {
            throw new Error("Failed to create collection");
        }
        
        return await response.json();
    }
    
    // Add paper to collection
    async function addPaperToCollection(collectionId, paper, notes) {
        const headers = {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${getToken()}`
        };
        
        const response = await fetch(`/api/activity/collections/${collectionId}/papers`, {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({
                paper_id: paper.id,
                title: paper.title,
                authors: paper.authors || "",
                year: paper.year || "",
                source: paper.source || "",
                notes: notes || ""
            })
        });
        
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.detail || "Failed to add paper to collection");
        }
        
        return await response.json();
    }
    
    // Add "Add to Collection" button to each paper
    function addCollectionButtonToPapers() {
        if (!isLoggedIn()) return;
        
        const paperItems = document.querySelectorAll('.paper-item');
        paperItems.forEach(paper => {
            // Check if button already exists
            if (paper.querySelector('.collection-btn')) return;
            
            const actionsDiv = paper.querySelector('.paper-actions');
            if (!actionsDiv) return;
            
            const paperId = paper.getAttribute('data-paper-id');
            const paperTitle = paper.querySelector('.paper-title')?.textContent || "";
            const authors = paper.querySelector('.paper-authors')?.textContent || "";
            
            // Create collection button
            const collectionBtn = document.createElement('button');
            collectionBtn.className = 'btn btn-sm btn-outline-warning collection-btn ms-1';
            collectionBtn.innerHTML = '<i class="fas fa-bookmark"></i> Simpan';
            collectionBtn.addEventListener('click', function() {
                showCollectionModal({
                    id: paperId,
                    title: paperTitle,
                    authors: authors,
                    year: authors.match(/\((\d{4})\)/) ? authors.match(/\((\d{4})\)/)[1] : "",
                    source: paper.querySelector('.source-logo')?.alt || ""
                });
            });
            
            // Add button to actions
            actionsDiv.appendChild(collectionBtn);
        });
    }
    
    // Run addCollectionButtonToPapers when papers are loaded
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.addedNodes && mutation.addedNodes.length > 0) {
                // Check our specific target node
                for (let i = 0; i < mutation.addedNodes.length; i++) {
                    const node = mutation.addedNodes[i];
                    if (node.classList && node.classList.contains('paper-item')) {
                        addCollectionButtonToPapers();
                    }
                }
            }
        });
    });
    
    // Start observing the papers list
    const papersList = document.querySelector('.papers-list');
    if (papersList) {
        observer.observe(papersList, { childList: true, subtree: true });
    }
    
    // Initial run to add buttons to any papers already loaded
    addCollectionButtonToPapers();
});