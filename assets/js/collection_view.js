// Fungsi untuk mendapatkan cookie
function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
  return null;
}

// Fungsi untuk mendapatkan CSRF token
async function ensureCsrfToken() {
  let csrfToken = getCookie('csrf_token');
  
  // Jika token tidak ada, ambil dari API
  if (!csrfToken) {
    try {
      const response = await fetch('/api/get-csrf-token');
      if (response.ok) {
        const data = await response.json();
        csrfToken = data.csrf_token;
      }
    } catch (error) {
      console.error('Error fetching CSRF token:', error);
    }
  }
  
  return csrfToken;
}

document.addEventListener("DOMContentLoaded", function () {
  // Token handling
  const getToken = () => localStorage.getItem("token");
  const isLoggedIn = () => !!getToken();

  // DOM Elements
  const collectionsGrid = document.querySelector(".collections-grid");
  const loadingState = document.querySelector(".collections-loading-state");
  const emptyState = document.querySelector(".collections-empty-state");
  const createCollectionBtns = document.querySelectorAll(
    ".create-collection-btn"
  );
  const collectionFormModal = document.getElementById("collectionFormModal");
  const collectionDetailModal = document.getElementById(
    "collectionDetailModal"
  );
  const deleteConfirmModal = document.getElementById("deleteConfirmModal");

  // Form Elements
  const collectionForm = document.getElementById("collectionForm");
  const collectionIdInput = document.getElementById("collectionId");
  const collectionNameInput = document.getElementById("collectionName");
  const collectionDescInput = document.getElementById("collectionDescription");
  const saveCollectionBtn = document.getElementById("saveCollectionBtn");

  // Detail Modal Elements
  const collectionDetailTitle = document.getElementById(
    "collectionDetailModalLabel"
  );
  const collectionDescription = document.querySelector(
    ".collection-description"
  );
  const collectionPaperCount = document.querySelector(
    ".collection-paper-count"
  );
  const collectionCreatedDate = document.querySelector(
    ".collection-created-date"
  );
  const papersLoading = document.querySelector(".papers-loading");
  const papersEmpty = document.querySelector(".papers-empty");
  const collectionPapersList = document.querySelector(
    ".collection-papers-list"
  );
  const editCollectionBtn = document.querySelector(".edit-collection-btn");
  const deleteCollectionBtn = document.querySelector(".delete-collection-btn");
  const confirmDeleteBtn = document.getElementById("confirmDeleteBtn");

  // Current collection data
  let collections = [];
  let currentCollection = null;

  // Check login status
  if (!isLoggedIn()) {
    window.location.href = "/login?returnUrl=/collections";
    return;
  }

  // Initialize - load collections
  fetchCollections();

  // Event Listeners
  createCollectionBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      resetCollectionForm();
      const formModalTitle = document.getElementById(
        "collectionFormModalLabel"
      );
      if (formModalTitle) formModalTitle.textContent = "Buat Koleksi Baru";
      const modal = new bootstrap.Modal(collectionFormModal);
      modal.show();
    });
  });

  if (saveCollectionBtn) {
    saveCollectionBtn.addEventListener("click", handleSaveCollection);
  }

  if (editCollectionBtn) {
    editCollectionBtn.addEventListener("click", () => {
      if (!currentCollection) return;

      collectionIdInput.value = currentCollection.id;
      collectionNameInput.value = currentCollection.name;
      collectionDescInput.value = currentCollection.description || "";

      const formModalTitle = document.getElementById(
        "collectionFormModalLabel"
      );
      if (formModalTitle) formModalTitle.textContent = "Edit Koleksi";

      const modal = new bootstrap.Modal(collectionFormModal);
      modal.show();
    });
  }

  if (deleteCollectionBtn) {
    deleteCollectionBtn.addEventListener("click", () => {
      if (!currentCollection) return;
      const modal = new bootstrap.Modal(deleteConfirmModal);
      modal.show();
    });
  }

  if (confirmDeleteBtn) {
    confirmDeleteBtn.addEventListener("click", async () => {
      if (!currentCollection) return;

      confirmDeleteBtn.disabled = true;
      confirmDeleteBtn.innerHTML =
        '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Menghapus...';

      try {
        await deleteCollection(currentCollection.id);

        // Close modals
        bootstrap.Modal.getInstance(deleteConfirmModal).hide();
        bootstrap.Modal.getInstance(collectionDetailModal).hide();

        // Refresh collections
        fetchCollections();

        showToast("Koleksi berhasil dihapus");
      } catch (error) {
        console.error("Error deleting collection:", error);
        showToast("Gagal menghapus koleksi", "error");
      } finally {
        confirmDeleteBtn.disabled = false;
        confirmDeleteBtn.innerHTML = "Hapus";
      }
    });
  }

  // Functions
  async function fetchCollections() {
    showLoadingState();

    try {
      const headers = {
        Authorization: `Bearer ${getToken()}`,
      };
      
      // Tambahkan CSRF token jika tersedia
      const csrfToken = await ensureCsrfToken();
      if (csrfToken) {
        headers["X-CSRF-Token"] = csrfToken;
      }
      
      const response = await fetch("/api/activity/collections", {
        headers: headers,
      });

      if (!response.ok) {
        throw new Error("Failed to fetch collections");
      }

      collections = await response.json();
      renderCollections();
    } catch (error) {
      console.error("Error fetching collections:", error);
      showToast("Gagal memuat koleksi", "error");
      showEmptyState();
    }
  }

  function renderCollections() {
    if (!collectionsGrid) return;

    if (collections.length === 0) {
      showEmptyState();
      return;
    }

    // Clear previous content
    collectionsGrid.innerHTML = "";

    // Create collection cards
    collections.forEach((collection) => {
      const colDiv = document.createElement("div");
      colDiv.className = "col-md-4 col-lg-3 mb-4";

      const cardDiv = document.createElement("div");
      cardDiv.className = "collection-card";
      cardDiv.setAttribute("data-collection-id", collection.id);

      // Format date
      const createdDate = new Date(collection.created_at);
      const formattedDate = createdDate.toLocaleDateString("id-ID", {
        day: "numeric",
        month: "short",
        year: "numeric",
      });

      // Truncate description
      const description = collection.description || "Tidak ada deskripsi";

      cardDiv.innerHTML = `
        <div class="collection-card-body">
            <h5 class="collection-card-title">${collection.name}</h5>
            <p class="collection-card-text">${description}</p>
        </div>
        <div class="collection-card-footer">
            <div class="collection-info-right">
                <span class="collection-date">
                    <i class="fas fa-calendar-alt"></i> ${formattedDate}
                </span>
                <span class="collection-paper-count">
                    <i class="fas fa-file-alt"></i> ${collection.paper_count} paper
                </span>
            </div>
        </div>
    `;

      // Add click event to open detail modal
      cardDiv.addEventListener("click", () => {
        openCollectionDetail(collection.id);
      });

      colDiv.appendChild(cardDiv);
      collectionsGrid.appendChild(colDiv);
    });

    // Show collections grid
    showCollectionsGrid();
  }

  async function openCollectionDetail(collectionId) {
    // Show modal with loading state
    papersLoading.classList.remove("d-none");
    papersEmpty.classList.add("d-none");
    collectionPapersList.classList.add("d-none");

    // Show modal
    const modal = new bootstrap.Modal(collectionDetailModal);
    modal.show();

    try {
      const headers = {
        Authorization: `Bearer ${getToken()}`,
      };
      
      // Tambahkan CSRF token jika tersedia
      const csrfToken = await ensureCsrfToken();
      if (csrfToken) {
        headers["X-CSRF-Token"] = csrfToken;
      }
      
      const response = await fetch(
        `/api/activity/collections/${collectionId}`,
        {
          headers: headers,
        }
      );

      if (!response.ok) {
        throw new Error("Failed to fetch collection details");
      }

      currentCollection = await response.json();
      renderCollectionDetail();
    } catch (error) {
      console.error("Error fetching collection details:", error);
      papersLoading.classList.add("d-none");
      papersEmpty.classList.remove("d-none");
      showToast("Gagal memuat detail koleksi", "error");
    }
  }

  function renderCollectionDetail() {
    if (!currentCollection) return;

    // Update modal title and info
    collectionDetailTitle.textContent = currentCollection.name;
    collectionDescription.textContent = currentCollection.description || "Tidak ada deskripsi";
    collectionPaperCount.textContent = `${currentCollection.paper_count} paper`;

    // Format date
    const createdDate = new Date(currentCollection.created_at);
    const formattedDate = createdDate.toLocaleDateString("id-ID", {
        day: "numeric",
        month: "long",
        year: "numeric"
    });
    collectionCreatedDate.textContent = `Dibuat pada ${formattedDate}`;

    // Hide loading
    papersLoading.classList.add("d-none");

    // Check if collection has papers
    if (!currentCollection.papers || currentCollection.papers.length === 0) {
      papersEmpty.classList.remove("d-none");
      collectionPapersList.classList.add("d-none");
      return;
    }

    // Render papers
    collectionPapersList.innerHTML = "";
    currentCollection.papers.forEach((paper) => {
      const paperDiv = document.createElement("div");
      paperDiv.className = "collection-paper-item";
      paperDiv.setAttribute("data-paper-id", paper.paper_id);

      // Create notes section if notes exist
      const notesSection = paper.notes
        ? `
                <div class="paper-notes-container">
                    <div class="paper-notes-text">
                        <i class="fas fa-sticky-note me-1"></i> ${paper.notes}
                    </div>
                </div>
            `
        : "";

      paperDiv.innerHTML = `
                <div class="d-flex justify-content-between">
                    <div class="paper-info">
                        <h6 class="paper-title-small">${paper.title}</h6>
                        <p class="paper-authors-small">${paper.authors}</p>
                        <div class="paper-meta-small d-flex gap-2">
                            ${
                              paper.year
                                ? `<span class="paper-year-small">${paper.year}</span>`
                                : ""
                            }
                            ${
                              paper.source
                                ? `<span class="paper-source-small">${paper.source}</span>`
                                : ""
                            }
                        </div>
                        ${notesSection}
                    </div>
                    <div>
                        <button class="btn btn-sm btn-outline-danger remove-paper-btn" data-paper-id="${
                          paper.id
                        }">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                </div>
                <div class="paper-actions-small mt-2">
                    <a href="/search?q=${encodeURIComponent(
                      paper.title
                    )}" class="btn btn-sm btn-outline-primary" target="_blank">
                        <i class="fas fa-search"></i> Cari
                    </a>
                    <button class="btn btn-sm btn-outline-info edit-note-btn" data-paper-id="${
                      paper.id
                    }">
                        <i class="fas fa-edit"></i> Edit Catatan
                    </button>
                </div>
            `;

      // Add event listeners for paper actions
      const removeBtn = paperDiv.querySelector(".remove-paper-btn");
      if (removeBtn) {
        removeBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          confirmRemovePaper(paper.id);
        });
      }

      const editNoteBtn = paperDiv.querySelector(".edit-note-btn");
      if (editNoteBtn) {
        editNoteBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          openEditNoteModal(paper);
        });
      }

      collectionPapersList.appendChild(paperDiv);
    });

    // Show papers list
    collectionPapersList.classList.remove("d-none");
  }

  async function handleSaveCollection() {
    // Validate form
    const name = collectionNameInput.value.trim();
    if (!name) {
      showToast("Nama koleksi tidak boleh kosong", "warning");
      return;
    }

    // Disable button during save
    saveCollectionBtn.disabled = true;
    saveCollectionBtn.innerHTML =
      '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Menyimpan...';

    const collectionId = collectionIdInput.value;
    const description = collectionDescInput.value.trim();

    try {
      const headers = {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${getToken()}`,
      };
      
      // Tambahkan CSRF token jika tersedia
      const csrfToken = await ensureCsrfToken();
      if (csrfToken) {
        headers["X-CSRF-Token"] = csrfToken;
      }
      
      let response;

      // Create or update collection based on whether ID exists
      if (collectionId) {
        // Update existing collection
        response = await fetch(`/api/activity/collections/${collectionId}`, {
          method: "PUT",
          headers: headers,
          body: JSON.stringify({
            name,
            description,
          }),
        });
      } else {
        // Create new collection
        response = await fetch("/api/activity/collections", {
          method: "POST",
          headers: headers,
          body: JSON.stringify({
            name,
            description,
          }),
        });
      }

      if (!response.ok) {
        throw new Error("Failed to save collection");
      }

      // Close modal
      const modal = bootstrap.Modal.getInstance(collectionFormModal);
      modal.hide();

      // Refresh collections
      fetchCollections();

      // Show success message
      showToast(
        collectionId ? "Koleksi berhasil diperbarui" : "Koleksi berhasil dibuat"
      );
    } catch (error) {
      console.error("Error saving collection:", error);
      showToast("Gagal menyimpan koleksi", "error");
    } finally {
      // Re-enable button
      saveCollectionBtn.disabled = false;
      saveCollectionBtn.textContent = "Simpan";
    }
  }

  async function deleteCollection(collectionId) {
    const headers = {
      "Authorization": `Bearer ${getToken()}`,
    };
    
    // Tambahkan CSRF token jika tersedia
    const csrfToken = await ensureCsrfToken();
    if (csrfToken) {
      headers["X-CSRF-Token"] = csrfToken;
    }
    
    const response = await fetch(`/api/activity/collections/${collectionId}`, {
      method: "DELETE",
      headers: headers,
    });

    if (!response.ok) {
      throw new Error("Failed to delete collection");
    }

    return true;
  }

  function confirmRemovePaper(paperId) {
    if (confirm("Apakah Anda yakin ingin menghapus paper ini dari koleksi?")) {
      removePaperFromCollection(paperId);
    }
  }

  async function removePaperFromCollection(paperId) {
    try {
      const headers = {
        "Authorization": `Bearer ${getToken()}`,
      };
      
      // Tambahkan CSRF token jika tersedia
      const csrfToken = await ensureCsrfToken();
      if (csrfToken) {
        headers["X-CSRF-Token"] = csrfToken;
      }
      
      const response = await fetch(
        `/api/activity/collections/${currentCollection.id}/papers/${paperId}`,
        {
          method: "DELETE",
          headers: headers,
        }
      );

      if (!response.ok) {
        throw new Error("Failed to remove paper");
      }

      // Refresh collection detail
      openCollectionDetail(currentCollection.id);
      showToast("Paper berhasil dihapus dari koleksi");
    } catch (error) {
      console.error("Error removing paper:", error);
      showToast("Gagal menghapus paper", "error");
    }
  }

  function openEditNoteModal(paper) {
    // Create modal dynamically
    const modalHtml = `
            <div class="modal fade" id="editNoteModal" tabindex="-1" aria-hidden="true">
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">Edit Catatan</h5>
                            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <div class="paper-info mb-3">
                                <h6 class="paper-title-small">${
                                  paper.title
                                }</h6>
                            </div>
                            <div class="form-group">
                                <label for="paperNoteEdit" class="form-label">Catatan</label>
                                <textarea class="form-control bg-dark text-white" id="paperNoteEdit" rows="4">${
                                  paper.notes || ""
                                }</textarea>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-outline-light" data-bs-dismiss="modal">Batal</button>
                            <button type="button" class="btn btn-primary save-note-btn">Simpan</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

    // Add modal to document
    const modalContainer = document.createElement("div");
    modalContainer.innerHTML = modalHtml;
    document.body.appendChild(modalContainer);

    // Get modal instance
    const editNoteModal = document.getElementById("editNoteModal");
    const modal = new bootstrap.Modal(editNoteModal);

    // Add save event
    const saveNoteBtn = editNoteModal.querySelector(".save-note-btn");
    saveNoteBtn.addEventListener("click", async () => {
      const noteText = editNoteModal
        .querySelector("#paperNoteEdit")
        .value.trim();

      saveNoteBtn.disabled = true;
      saveNoteBtn.innerHTML =
        '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Menyimpan...';

      try {
        const headers = {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${getToken()}`,
        };
        
        // Tambahkan CSRF token jika tersedia
        const csrfToken = await ensureCsrfToken();
        if (csrfToken) {
          headers["X-CSRF-Token"] = csrfToken;
        }
        
        const response = await fetch(
          `/api/activity/collections/${currentCollection.id}/papers/${paper.id}`,
          {
            method: "PUT",
            headers: headers,
            body: JSON.stringify({
              notes: noteText,
            }),
          }
        );

        if (!response.ok) {
          throw new Error("Failed to update note");
        }

        // Close modal
        modal.hide();

        // Remove modal from DOM after hidden
        editNoteModal.addEventListener("hidden.bs.modal", function () {
          editNoteModal.remove();
        });

        // Refresh collection detail
        openCollectionDetail(currentCollection.id);
        showToast("Catatan berhasil diperbarui");
      } catch (error) {
        console.error("Error updating note:", error);
        showToast("Gagal memperbarui catatan", "error");
      } finally {
        saveNoteBtn.disabled = false;
        saveNoteBtn.textContent = "Simpan";
      }
    });

    // Show modal
    modal.show();

    // Remove modal from DOM after hidden
    editNoteModal.addEventListener("hidden.bs.modal", function () {
      editNoteModal.remove();
    });
  }

  function resetCollectionForm() {
    if (collectionForm) collectionForm.reset();
    if (collectionIdInput) collectionIdInput.value = "";
  }

  function showLoadingState() {
    if (loadingState) loadingState.classList.remove("d-none");
    if (emptyState) emptyState.classList.add("d-none");
    if (collectionsGrid) collectionsGrid.classList.add("d-none");
  }

  function showEmptyState() {
    if (loadingState) loadingState.classList.add("d-none");
    if (emptyState) emptyState.classList.remove("d-none");
    if (collectionsGrid) collectionsGrid.classList.add("d-none");
  }

  function showCollectionsGrid() {
    if (loadingState) loadingState.classList.add("d-none");
    if (emptyState) emptyState.classList.add("d-none");
    if (collectionsGrid) collectionsGrid.classList.remove("d-none");
  }

  // Toast notification
  function showToast(message, type = "success") {
    // Create toast container if not exists
    let toastContainer = document.querySelector(".toast-container");
    if (!toastContainer) {
      toastContainer = document.createElement("div");
      toastContainer.className =
        "toast-container position-fixed bottom-0 end-0 p-3";
      document.body.appendChild(toastContainer);
    }

    // Create toast element
    const toastId = `toast-${Date.now()}`;
    const toast = document.createElement("div");
    toast.className = `toast align-items-center text-white ${
      type === "success"
        ? "bg-success"
        : type === "warning"
        ? "bg-warning text-dark"
        : "bg-danger"
    }`;
    toast.setAttribute("role", "alert");
    toast.setAttribute("aria-live", "assertive");
    toast.setAttribute("aria-atomic", "true");
    toast.setAttribute("id", toastId);

    toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">
                    ${message}
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
        `;

    // Add to container
    toastContainer.appendChild(toast);

    // Initialize and show toast
    const toastInstance = new bootstrap.Toast(toast, {
      delay: 3000,
    });
    toastInstance.show();

    // Remove from DOM after hidden
    toast.addEventListener("hidden.bs.toast", function () {
      toast.remove();
    });
  }
});