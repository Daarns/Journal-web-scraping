document.addEventListener("DOMContentLoaded", function() {
    // Token handling
    const getToken = () => localStorage.getItem("token");
    const isLoggedIn = () => !!getToken();
    
    // Variabel untuk tracking berapa kali paper dilihat dalam sesi
    const viewedPapers = {};
    
    // Fungsi untuk mendapatkan cookie
    function getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return parts.pop().split(';').shift();
        return null;
    }

    // Fungsi untuk mendapatkan CSRF token yang valid
    async function ensureCsrfToken() {
        let csrfToken = getCookie("csrf_token");

        // Jika tidak ada token, ambil dari API
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
    
    // 1. TRACKING ACTIVITY - Fungsi utama untuk mencatat aktivitas
    async function recordActivity(paperId, activityType, metadata = {}) {
        if (!isLoggedIn() || !paperId) return;
        
        const headers = {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${getToken()}`
        };
        
        // Tambahkan CSRF token ke headers
        const csrfToken = await ensureCsrfToken();
        if (csrfToken) {
            headers["X-CSRF-Token"] = csrfToken;
        }
        
        // Untuk activity view, tambahkan informasi view count dalam session
        if (activityType === 'view') {
            viewedPapers[paperId] = (viewedPapers[paperId] || 0) + 1;
            metadata.view_count = viewedPapers[paperId];
            
            // Tandai sebagai repeated view jika dilihat lebih dari sekali
            if (viewedPapers[paperId] > 1) {
                metadata.repeated_view = true;
            }
        }
        
        // Kirim data aktivitas ke server
        try {
            const response = await fetch('/api/activity/activity', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({
                    paper_id: paperId,
                    activity_type: activityType,
                    activity_data: metadata
                }),
                credentials: 'include' // Penting untuk CSRF
            });
            
            if (!response.ok) {
                throw new Error(`Failed to record activity: ${response.status}`);
            }
            
            console.log(`Activity ${activityType} recorded successfully`);
        } catch (err) {
            console.error('Error recording activity:', err);
        }
    }
    
    // 2. TRACKING VIEW - Auto track saat user melihat paper
    document.addEventListener("click", function(e) {
        // Track klik pada link "Lihat Paper" (eksternal link)
        const viewPaperLink = e.target.closest(".btn-outline-primary");
        if (viewPaperLink && viewPaperLink.textContent.includes("Lihat Paper")) {
            const paperDiv = viewPaperLink.closest(".paper-item");
            if (paperDiv) {
                const paperId = paperDiv.getAttribute("data-paper-id");
                const title = paperDiv.querySelector(".paper-title")?.textContent || "";
                const authors = paperDiv.querySelector(".paper-authors")?.textContent || "";
                recordActivity(paperId, "view", { 
                    title, 
                    authors,
                    external_link: true,
                    url: viewPaperLink.getAttribute("href") 
                });
            }
        }
    });
    
    // 3. TRACKING SUMMARY - Track klik pada tombol "Ringkasan"
    document.addEventListener("click", function(e) {
        const summarizeBtn = e.target.closest(".summarize-btn");
        if (summarizeBtn) {
            const paperId = summarizeBtn.getAttribute("data-paper-id");
            const paperTitle = summarizeBtn.getAttribute("data-paper-title");
            const paperDiv = summarizeBtn.closest(".paper-item");
            const authors = paperDiv?.querySelector(".paper-authors")?.textContent || "";
            
            recordActivity(paperId, "summarize", { 
                title: paperTitle,
                authors
            });
        }
    });
    
    // 4. TRACKING QUESTION - Track saat user bertanya tentang paper
    document.addEventListener("click", function(e) {
        // Track saat tombol tanya diklik
        if (e.target.closest(".ask-btn")) {
            const askBtn = e.target.closest(".ask-btn");
            const paperDiv = askBtn.closest(".paper-item");
            const paperId = paperDiv?.getAttribute("data-paper-id");
            const paperTitle = askBtn.getAttribute("data-paper-title");
            const authors = paperDiv?.querySelector(".paper-authors")?.textContent || "";
            
            recordActivity(paperId, "question", { 
                title: paperTitle,
                authors,
                action: "opened_question_modal"
            });
        }
        
        // Track saat pertanyaan dikirim
        if (e.target.classList.contains("send-question-btn")) {
            const questionInput = document.getElementById("modalQuestionInput");
            const chatContainer = document.getElementById("chatContainer");
            const paperContext = chatContainer?.querySelector(".paper-context-title");
            
            if (questionInput && questionInput.value.trim() && window.currentPaperContext) {
                recordActivity(window.currentPaperContext.id, "question", {
                    title: window.currentPaperContext.title,
                    authors: window.currentPaperContext.authors,
                    question: questionInput.value.trim(),
                    action: "sent_question"
                });
            }
        }
    });
    
    // 5. TRACKING CITATION - Track ketika user meminta sitasi
    document.addEventListener("click", function(e) {
        if (e.target.classList.contains("citation-style-btn")) {
            const modal = document.getElementById("citationModal");
            const paperId = modal?.getAttribute("data-paper-id");
            const paperTitle = modal?.querySelector(".paper-citation-title")?.textContent || "";
            const style = e.target.getAttribute("data-style");
            
            recordActivity(paperId, "citation", { 
                title: paperTitle,
                style: style
            });
        }
    });
    
    // 6. COLLECTION MANAGEMENT - Cek koleksi dan tampilkan UI yang sesuai
    async function checkCollectionsAndUpdateUI() {
        if (!isLoggedIn()) return;
        
        const addToCollectionModal = document.getElementById("addToCollectionModal");
        if (!addToCollectionModal) return;
        
        const collectionSelect = document.getElementById("collectionSelect");
        const noCollectionsMsg = document.querySelector(".no-collections");
        const createCollectionBtn = document.getElementById("createCollectionBtn");
        const addToExistingSection = document.querySelector(".add-to-existing-section");
        const createNewSection = document.querySelector(".create-new-section");
        
        // Show loading
        if (collectionSelect) {
            collectionSelect.innerHTML = '<option value="" selected disabled>Loading collections...</option>';
        }
        
        try {
            const headers = {
                'Authorization': `Bearer ${getToken()}`
            };
            
            // Tambahkan CSRF token ke headers
            const csrfToken = await ensureCsrfToken();
            if (csrfToken) {
                headers["X-CSRF-Token"] = csrfToken;
            }
            
            // Fetch user collections
            const response = await fetch('/api/activity/collections', {
                headers: headers,
                credentials: 'include' // Penting untuk CSRF
            });
            
            if (!response.ok) {
                throw new Error('Failed to fetch collections');
            }
            
            const collections = await response.json();
            
            if (collections.length === 0) {
                // Tampilkan UI untuk "Belum ada koleksi"
                if (noCollectionsMsg) noCollectionsMsg.classList.remove("d-none");
                if (createNewSection) createNewSection.classList.remove("d-none");
                if (addToExistingSection) addToExistingSection.classList.add("d-none");
            } else {
                // Tampilkan dropdown koleksi yang tersedia
                if (noCollectionsMsg) noCollectionsMsg.classList.add("d-none");
                if (addToExistingSection) addToExistingSection.classList.remove("d-none");
                
                if (collectionSelect) {
                    collectionSelect.innerHTML = '<option value="" selected disabled>Pilih koleksi</option>';
                    
                    collections.forEach(collection => {
                        const option = document.createElement('option');
                        option.value = collection.id;
                        option.textContent = `${collection.name} (${collection.paper_count} paper)`;
                        collectionSelect.appendChild(option);
                    });
                    
                    // Tambahkan opsi untuk buat koleksi baru
                    const newOption = document.createElement('option');
                    newOption.value = "new";
                    newOption.textContent = "➕ Buat koleksi baru";
                    newOption.className = "text-primary";
                    collectionSelect.appendChild(newOption);
                }
            }
        } catch (err) {
            console.error('Error fetching collections:', err);
            if (collectionSelect) {
                collectionSelect.innerHTML = '<option value="" selected disabled>Error loading collections</option>';
            }
        }
    }
    
    // 7. Toggle UI saat memilih untuk membuat koleksi baru dari dropdown
    document.addEventListener('change', function(e) {
        if (e.target.id === 'collectionSelect') {
            const createNewSection = document.querySelector('.create-new-section');
            const addToExistingSection = document.querySelector('.add-to-existing-section');
            
            if (e.target.value === 'new') {
                // Tampilkan form pembuatan koleksi baru
                if (createNewSection) createNewSection.classList.remove('d-none');
                if (addToExistingSection) addToExistingSection.classList.add('d-none');
            } else {
                // Tampilkan dropdown koleksi yang ada
                if (createNewSection) createNewSection.classList.add('d-none');
                if (addToExistingSection) addToExistingSection.classList.remove('d-none');
            }
        }
    });
    
    // 8. Jalankan cek koleksi saat modal dibuka
    const addToCollectionModal = document.getElementById("addToCollectionModal");
    if (addToCollectionModal) {
        addToCollectionModal.addEventListener("show.bs.modal", checkCollectionsAndUpdateUI);
    }

    // Fungsi untuk mengambil riwayat aktivitas
    async function fetchActivityHistory() {
        try {
            const headers = {
                'Authorization': `Bearer ${getToken()}`
            };
            
            // Tambahkan CSRF token ke headers
            const csrfToken = await ensureCsrfToken();
            if (csrfToken) {
                headers["X-CSRF-Token"] = csrfToken;
            }
            
            const response = await fetch('/api/activity/activity-history', {
                headers: headers,
                credentials: 'include' // Penting untuk CSRF
            });
            
            if (!response.ok) {
                throw new Error('Failed to fetch activity history');
            }
            
            return await response.json();
        } catch (error) {
            console.error('Error fetching activity history:', error);
            throw error;
        }
    }

    // Tambahkan event listener untuk modal activity history jika ada
    const activityHistoryModal = document.getElementById('activityHistoryModal');
    if (activityHistoryModal) {
        activityHistoryModal.addEventListener('shown.bs.modal', async function() {
            const activityHistoryContent = document.getElementById('activityHistoryContent');
            
            if (activityHistoryContent) {
                activityHistoryContent.innerHTML = `
                    <div class="d-flex justify-content-center my-4">
                        <div class="spinner-border text-primary" role="status">
                            <span class="visually-hidden">Loading...</span>
                        </div>
                        <div class="ms-3">Memuat riwayat aktivitas...</div>
                    </div>
                `;
                
                try {
                    const activities = await fetchActivityHistory();
                    displayActivityHistory(activities, activityHistoryContent);
                } catch (error) {
                    activityHistoryContent.innerHTML = `
                        <div class="alert alert-danger">
                            <i class="fas fa-exclamation-circle"></i> 
                            Gagal memuat riwayat aktivitas. Silakan coba lagi.
                        </div>
                    `;
                }
            }
        });
    }

    // Fungsi untuk menampilkan riwayat aktivitas
    function displayActivityHistory(activities, container) {
        if (!activities || activities.length === 0) {
            container.innerHTML = `
                <div class="alert alert-info">
                    <i class="fas fa-info-circle"></i> Belum ada riwayat aktivitas.
                </div>
            `;
            return;
        }
        
        let html = `<div class="activity-list">`;
        
        activities.forEach(activity => {
            const date = new Date(activity.timestamp);
            const formattedDate = `${date.toLocaleDateString('id-ID', {day: 'numeric', month: 'short', year: 'numeric'})} ${date.toLocaleTimeString('id-ID', {hour: '2-digit', minute: '2-digit'})}`;
            
            let icon = 'fa-history';
            let title = 'Aktivitas';
            
            if (activity.activity_type === 'view') {
                icon = 'fa-eye';
                title = 'Melihat Paper';
            } else if (activity.activity_type === 'summarize') {
                icon = 'fa-file-alt';
                title = 'Membuat Ringkasan';
            } else if (activity.activity_type === 'question') {
                icon = 'fa-question-circle';
                title = 'Bertanya';
            } else if (activity.activity_type === 'citation') {
                icon = 'fa-quote-right';
                title = 'Membuat Sitasi';
            } else if (activity.activity_type === 'save') {
                icon = 'fa-bookmark';
                title = 'Menyimpan Paper';
            }
            
            const data = activity.activity_data || {};
            const paperTitle = data.title || 'Untitled Paper';
            
            html += `
                <div class="activity-item" data-activity-id="${activity.id}">
                    <div class="activity-icon">
                        <i class="fas ${icon}"></i>
                    </div>
                    <div class="activity-content">
                        <h5 class="activity-title">${title}</h5>
                        <p class="activity-paper">${paperTitle}</p>
                        <div class="activity-meta">
                            <span class="activity-time">${formattedDate}</span>
                        </div>
                    </div>
                </div>
            `;
        });
        
        html += `</div>`;
        container.innerHTML = html;
    }

    // 9. Ekspos fungsi-fungsi untuk digunakan di file JS lain
    window.recordActivity = recordActivity;
    window.checkCollectionsAndUpdateUI = checkCollectionsAndUpdateUI;
    window.fetchActivityHistory = fetchActivityHistory;
});