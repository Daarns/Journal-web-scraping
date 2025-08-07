document.addEventListener("DOMContentLoaded", function () {
  // ======= ELEMEN UI =======
  // Elements untuk pencarian
  const searchQuery = document.querySelector(".search-query");
  const searchButton = document.getElementById("search-button");
  const suggestedKeywords = document.querySelector(".suggested-keywords");
  const emptyState = document.querySelector(".empty-state");
  const loadingState = document.querySelector(".loading-state");
  const resultsArea = document.querySelector(".results-area");
  const papersList = document.querySelector(".papers-list");
  const suggestedQueriesList = document.querySelector(
    ".suggested-queries-list"
  );
  const questionInput = document.querySelector(".question-input");
  const tagsArea = document.querySelector(".tags-area");
  const searchForm = document.getElementById("search-form");
  // Token untuk request terautentikasi
  const getToken = () => localStorage.getItem("token");
  const modalQuestionInput = document.getElementById("modalQuestionInput");
  const sendQuestionBtn = document.querySelector(".send-question-btn");
  const chatContainer = document.getElementById("chatContainer");
  const isUserLoggedIn = () => !!localStorage.getItem("token");

  // Variabel untuk pagination (TAMBAHKAN INI)
  let currentPaperContext = null; // Untuk menyimpan konteks paper saat ini
  let currentPage = 1;
  let itemsPerPage = 4;
  let allPapers = [];
  let originalPapers = []; // Untuk menyimpan daftar lengkap sebelum filter
  let minYear = new Date().getFullYear() - 10;
  let maxYear = new Date().getFullYear();
  let availableYears = new Set();
  let uploadedPdfPapers = {};

  async function ensureCsrfToken() {
    let csrfToken = getCookie("csrf_token");

    // Jika tidak ada token, ambil dari API
    if (!csrfToken) {
      try {
        const response = await fetch("/api/get-csrf-token");
        if (response.ok) {
          const data = await response.json();
          csrfToken = data.csrf_token;
        }
      } catch (error) {
        console.error("Error fetching CSRF token:", error);
      }
    }

    return csrfToken;
  }

  // Fungsi helper untuk mendapatkan cookie
  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return null;
  }

  // ======= FITUR LOGIN/LOGOUT (KODE YANG SUDAH ADA) =======
  // Pengecekan token sesi dan mengelola UI login/logout
  function checkLoginStatus() {
    // Cek apakah token ada di localStorage
    const token = localStorage.getItem("token");

    // Jika tidak ada token (pengguna belum login)
    if (!token) {
      // Dapatkan path halaman saat ini
      const currentPath = window.location.pathname;

      // Buat kunci unik berdasarkan path halaman saat ini
      const pageModalKey = `modal_shown_${currentPath}`;

      // Cek apakah modal sudah pernah ditampilkan di halaman ini pada sesi browser ini
      const modalShownOnThisPage = sessionStorage.getItem(pageModalKey);

      // Jika belum pernah ditampilkan di halaman ini pada sesi ini dan ini adalah halaman search
      if (!modalShownOnThisPage && currentPath === "/search") {
        // Tunggu sebentar supaya halaman selesai di-render
        setTimeout(() => {
          // Tampilkan modal info guest
          const guestInfoModal = new bootstrap.Modal(
            document.getElementById("guestInfoModal")
          );
          guestInfoModal.show();

          // Catat bahwa modal sudah ditampilkan di halaman ini
          sessionStorage.setItem(pageModalKey, "true");
        }, 300);
      }
      return false;
    }

    return true;
  }

  // Penanganan token dari URL (untuk login callback)
  function handleTokenFromUrl() {
    // Periksa token di URL dan simpan jika ada
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get("token");

    if (token) {
      // Simpan token ke localStorage
      localStorage.setItem("token", token);

      // Hapus token dari URL untuk keamanan
      const cleanUrl = window.location.pathname;
      window.history.replaceState({}, document.title, cleanUrl);

      // Refresh halaman untuk menerapkan status login
      window.location.reload();
    }
  }

  // Penanganan token dari fragment URL (#) - alternatif yang lebih aman
  function handleTokenFromFragment() {
    if (window.location.hash) {
      console.log("Fragment detected in URL:", window.location.hash);

      // Support untuk format #token=xyz
      if (window.location.hash.startsWith("#token=")) {
        const token = window.location.hash.substring(7);
        console.log("Token found in hash (format #token=)");

        if (token) {
          try {
            // Decode token untuk debug
            const base64Url = token.split(".")[1];
            const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
            const jsonPayload = decodeURIComponent(
              atob(base64)
                .split("")
                .map(function (c) {
                  return "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2);
                })
                .join("")
            );

            const payload = JSON.parse(jsonPayload);
            console.log("Token payload:", payload);

            // Log info avatar jika ada
            if (payload.avatar) {
              console.log("Avatar URL found in token:", payload.avatar);
            }
          } catch (e) {
            console.error("Error decoding token:", e);
          }

          // Simpan token ke localStorage
          localStorage.setItem("token", token);
          console.log("Token saved to localStorage");

          // Hapus hash dari URL untuk keamanan
          window.history.replaceState(
            {},
            document.title,
            window.location.pathname
          );

          // Refresh halaman setelah token disimpan
          window.location.reload();
          return;
        }
      }

      // Support untuk format URLSearchParams setelah #
      const hashParams = new URLSearchParams(window.location.hash.substring(1));
      const token = hashParams.get("token");

      if (token) {
        console.log("Token found in hash (URLSearchParams format)");
        // Simpan token ke localStorage
        localStorage.setItem("token", token);

        // Hapus hash dari URL untuk keamanan
        window.history.replaceState(
          {},
          document.title,
          window.location.pathname
        );

        // Refresh halaman untuk menerapkan status login
        window.location.reload();
      }
    }
  }

  // ======= FITUR PENCARIAN AI (KODE BARU) =======
  // Auto-suggestion dengan debounce
  let suggestionsTimeout;
  if (searchQuery) {
    searchQuery.addEventListener("input", function () {
      clearTimeout(suggestionsTimeout);

      if (this.value.length > 10) {
        suggestionsTimeout = setTimeout(() => {
          fetchSuggestions(this.value);
        }, 500);
      } else {
        if (suggestedKeywords) {
          suggestedKeywords.innerHTML = "";
        }
      }
    });
  }

  // Fetch keyword suggestions dari Gemini
  async function fetchSuggestions(query) {
      try {
          const headers = {
              "Content-Type": "application/json",
          };
          const token = getToken();
          if (token) {
              headers["Authorization"] = `Bearer ${token}`;
          }
  
          // ✅ DETECT search context untuk suggestions
          const searchContext = detectSearchContext(query);
          
          // ✅ SKIP suggestions untuk author-only search
          if (searchContext.type === 'author_only') {
              if (suggestedKeywords) {
                  suggestedKeywords.innerHTML = "";
              }
              return;
          }
  
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 3000);
  
          const response = await fetch("/api/ai/suggest-keywords", {
              method: "POST",
              headers,
              body: JSON.stringify({
                  query: query,
                  search_context: searchContext // ✅ Pass context
              }),
              signal: controller.signal,
          });
  
          clearTimeout(timeoutId);
  
          if (response.ok) {
              const data = await response.json();
              displaySuggestions(data.keywords);
          }
      } catch (error) {
          if (error.name === "AbortError") {
              console.log("Suggestion request timed out (3s)");
          } else {
              console.error("Error fetching suggestions:", error);
          }
          if (suggestedKeywords) {
              suggestedKeywords.innerHTML = "";
          }
      }
  }
  
  // ✅ ADD function untuk detect search context
  function detectSearchContext(query) {
      const queryLower = query.toLowerCase().trim();
      
      // Author-only patterns
      const authorOnlyPatterns = [
          /^[A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]*)?$/,  // "Bayu Sutawijaya"
          /^(?:dr\.?\s*|prof\.?\s*)?[A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]*)?\s*$/,
      ];
      
      // Author with topic patterns
      const authorTopicPatterns = [
          /(?:jurnal|paper|research|karya)\s+(?:milik\s+|dari\s+|oleh\s+)?([A-Z][a-z]+\s+[A-Z][a-z]+).*(?:tentang|mengenai|about)\s+(.+)/i,
          /(?:saya\s+)?(?:mencari|cari)\s+jurnal\s+(?:milik\s+)?([A-Z][a-z]+\s+[A-Z][a-z]+).*(?:tentang|mengenai|about)\s+(.+)/i,
      ];
      
      // Check author-only
      for (const pattern of authorOnlyPatterns) {
          if (pattern.test(query)) {
              return {
                  type: 'author_only',
                  author: query.trim()
              };
          }
      }
      
      // Check author with topic
      for (const pattern of authorTopicPatterns) {
          const match = query.match(pattern);
          if (match) {
              return {
                  type: 'author_with_topic',
                  author: match[1],
                  topic: match[2]
              };
          }
      }
      
      // Default to general topic
      return {
          type: 'general_topic',
          query: query
      };
  }

  // Display keyword suggestions
  function displaySuggestions(keywords) {
    if (!keywords || keywords.length === 0 || !suggestedKeywords) return;

    suggestedKeywords.innerHTML =
      "Sugesti: " +
      keywords
        .map((keyword) => `<span class="suggested-keyword">${keyword}</span>`)
        .join(" ");

    // Click to add to search query
    document.querySelectorAll(".suggested-keyword").forEach((keyword) => {
      keyword.addEventListener("click", function () {
        if (searchQuery) {
          const currentQuery = searchQuery.value;
          searchQuery.value = currentQuery + " " + this.textContent;
        }
      });
    });
  }

  // Handle search submission
  if (searchButton) {
    searchButton.addEventListener("click", performSearch);
  }

  if (searchQuery) {
    searchQuery.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && e.ctrlKey) {
        e.preventDefault();
        performSearch();
      }
    });
  }

  // Pencarian utama
  async function performSearch() {
    if (!searchQuery) return;

    const query = searchQuery.value.trim();
    if (!query) return;

    // Reset default year range to last 10 years
    const currentYear = new Date().getFullYear();
    minYear = currentYear - 10;
    maxYear = currentYear;

    // Ekstrak tahun dari query jika ada
    // Format: "jurnal tentang AI tahun 2020" atau "jurnal AI antara tahun 2018 sampai 2022"
    const yearRangeRegex =
      /(?:tahun|dari tahun|between|antara)\s+(\d{4})\s+(?:sampai|hingga|to|until|dan|and|-)\s+(\d{4})/i;
    const singleYearRegex = /(?:tahun|dari tahun|from|in)\s+(\d{4})/i;

    let yearMatch = query.match(yearRangeRegex);
    if (yearMatch) {
      minYear = parseInt(yearMatch[1]);
      maxYear = parseInt(yearMatch[2]);
    } else {
      yearMatch = query.match(singleYearRegex);
      if (yearMatch) {
        minYear = maxYear = parseInt(yearMatch[1]);
      }
    }

    // Update UI ke loading state
    if (emptyState) emptyState.classList.add("d-none");
    if (resultsArea) resultsArea.classList.add("d-none");
    if (loadingState) loadingState.classList.remove("d-none");

    // Update status button
    if (searchButton) {
      searchButton.disabled = true;
      const searchText = searchButton.querySelector(".search-text");
      const spinner = searchButton.querySelector(".spinner-border");

      if (searchText) searchText.classList.add("d-none");
      if (spinner) spinner.classList.remove("d-none");
    }

    try {
      const headers = {"Content-Type": "application/json"};
      const token = getToken();
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      // Tambahkan CSRF token jika tersedia
      const csrfToken = await ensureCsrfToken();
      if (csrfToken) {
        headers["X-CSRF-Token"] = csrfToken;
      }

      const response = await fetch("/api/search", {
        method: "POST",
        headers,
        body: JSON.stringify({query}),
      });

      if (response.ok) {
        const data = await response.json();
        displayResults(data);
      } else {
        const error = await response.json();
        showError(error.detail || "Terjadi kesalahan saat mencari");
      }
    } catch (error) {
      console.error("Search error:", error);
      showError("Terjadi kesalahan jaringan");
    } finally {
      // Reset status button
      if (searchButton) {
        searchButton.disabled = false;
        const searchText = searchButton.querySelector(".search-text");
        const spinner = searchButton.querySelector(".spinner-border");

        if (searchText) searchText.classList.remove("d-none");
        if (spinner) spinner.classList.add("d-none");
      }

      if (loadingState) loadingState.classList.add("d-none");
    }
  }

  function displayResults(data) {
    // Tampilkan area hasil
    if (emptyState) emptyState.classList.add("d-none");
    if (loadingState) loadingState.classList.add("d-none");
    if (resultsArea) resultsArea.classList.remove("d-none");

    const filterControls = document.querySelector(".filter-controls");
    if (filterControls) {
      filterControls.classList.remove("d-none");
    }

    // Simpan data asli
    originalPapers = data.papers || [];
    allPapers = [...originalPapers]; // Copy untuk penggunaan awal

    // Collect available years from papers
    availableYears.clear();
    originalPapers.forEach((paper) => {
      if (paper.year && !isNaN(parseInt(paper.year))) {
        const year = parseInt(paper.year);
        availableYears.add(year);

        // Update min and max year
        if (year < minYear) minYear = year;
        if (year > maxYear) maxYear = year;
      }
    });

    // Update filter dropdown with available years
    updateYearFilterOptions();

    // Tambahkan tombol reset filter
    addResetFilterButton();

    // Kode suggestedQueries tetap sama seperti aslinya
    const suggestedQueries = document.querySelector(".suggested-queries");
    if (
      suggestedQueriesList &&
      data.suggested_queries &&
      data.suggested_queries.length > 0
    ) {
      // Tampilkan container suggested queries
      if (suggestedQueries) suggestedQueries.classList.remove("d-none");

      suggestedQueriesList.innerHTML = data.suggested_queries
        .map((query) => `<span class="suggested-query-tag">${query}</span>`)
        .join("");

      // Add click event to use suggested queries
      document.querySelectorAll(".suggested-query-tag").forEach((tag) => {
        tag.addEventListener("click", function () {
          if (searchQuery) {
            searchQuery.value = this.textContent;
            performSearch();
          }
        });
      });
    } else {
      // Sembunyikan container jika tidak ada suggested queries
      if (suggestedQueries) suggestedQueries.classList.add("d-none");
    }

    // Setup pagination dan tampilkan halaman pertama
    setupPagination();
    showPage(1);
  }

  function updateYearFilterOptions() {
    const yearFilterDropdown = document.querySelector(
      ".year-filter .dropdown-menu"
    );
    if (!yearFilterDropdown) return;

    // Bersihkan dropdown kecuali opsi "Semua tahun"
    const allYearsOption =
      yearFilterDropdown.querySelector('a[data-year="all"]');
    yearFilterDropdown.innerHTML = "";

    // Tambahkan kembali opsi "Semua tahun"
    if (allYearsOption) {
      yearFilterDropdown.appendChild(allYearsOption.cloneNode(true));
    } else {
      const allYearsItem = document.createElement("li");
      allYearsItem.innerHTML =
        '<a class="dropdown-item" href="#" data-year="all">Semua tahun</a>';
      yearFilterDropdown.appendChild(allYearsItem);
    }

    // Tambahkan opsi rentang tahun (mis. 2020-2024)
    if (maxYear - minYear >= 5) {
      // Buat group tahun dengan rentang 5 tahun
      for (let start = maxYear; start >= minYear; start -= 5) {
        const end = Math.max(start - 4, minYear);
        const yearRange = `${end}-${start}`;

        const yearItem = document.createElement("li");
        yearItem.innerHTML = `<a class="dropdown-item" href="#" data-year="${yearRange}">${end} → ${start}</a>`;
        yearFilterDropdown.appendChild(yearItem);
      }
    }

    // Tambahkan separator
    const separator = document.createElement("li");
    separator.innerHTML = '<hr class="dropdown-divider">';
    yearFilterDropdown.appendChild(separator);

    // Tambahkan tahun-tahun individual yang tersedia, diurutkan dari terbaru
    const sortedYears = Array.from(availableYears).sort((a, b) => b - a);
    sortedYears.forEach((year) => {
      const yearItem = document.createElement("li");
      yearItem.innerHTML = `<a class="dropdown-item" href="#" data-year="${year}">${year}</a>`;
      yearFilterDropdown.appendChild(yearItem);
    });

    // Tambahkan event listener untuk opsi baru
    setupFilterHandlers();
  }

  // Function to reset search state
  function resetSearchState() {
    // Sembunyikan hasil pencarian
    if (resultsArea) resultsArea.classList.add("d-none");
    if (emptyState) emptyState.classList.remove("d-none");

    // Sembunyikan filter di navbar
    const filterControls = document.querySelector(".filter-controls");
    if (filterControls) {
      filterControls.classList.add("d-none");
    }

    const suggestedQueries = document.querySelector(".suggested-queries");
    if (suggestedQueries) {
      suggestedQueries.classList.add("d-none");
    }

    // Reset variabel lainnya
    allPapers = [];
    currentPage = 1;
  }

  resetSearchState();

  function setupFilterHandlers() {
    // Event delegate untuk year filter dropdown
    document.addEventListener("click", function (event) {
      const yearItem = event.target.closest(".year-filter .dropdown-item");
      if (!yearItem) return;

      event.preventDefault();
      const yearRange = yearItem.getAttribute("data-year");
      const filterValueEl = document.querySelector(
        ".year-filter .filter-value"
      );

      if (yearRange === "all") {
        if (filterValueEl) filterValueEl.textContent = "";
        document
          .querySelector(".year-filter .btn")
          .setAttribute("data-current-filter", "all");
      } else if (yearRange.includes("-")) {
        // Range tahun
        const [start, end] = yearRange.split("-");
        if (filterValueEl) filterValueEl.textContent = ` ${start} → ${end}`;
        document
          .querySelector(".year-filter .btn")
          .setAttribute("data-current-filter", yearRange);
      } else {
        // Tahun individual
        if (filterValueEl) filterValueEl.textContent = ` ${yearRange}`;
        document
          .querySelector(".year-filter .btn")
          .setAttribute("data-current-filter", yearRange);
      }

      // Filter papers by year
      filterPapers();
    });

    // Source filter (kode yang sudah ada)
    document
      .querySelectorAll(".source-filter .dropdown-item")
      .forEach((item) => {
        item.addEventListener("click", function (e) {
          e.preventDefault();
          const source = this.getAttribute("data-source");
          const filterBtn = document.querySelector(".source-filter .btn");

          if (source === "all") {
            if (filterBtn) filterBtn.textContent = "Source";
          } else {
            if (filterBtn) filterBtn.textContent = "Source: " + source;
          }

          // Filter papers by source
          filterPapers();
        });
      });
  }

  // Filter papers based on selected criteria
  function filterPapers() {
    if (!originalPapers || originalPapers.length === 0) return;

    // Get filter values
    const yearBtn = document.querySelector(".year-filter .btn");
    const yearFilter = yearBtn
      ? yearBtn.getAttribute("data-current-filter") || "all"
      : "all";

    // Source filter
    const sourceBtn = document.querySelector(".source-filter .btn");
    let sourceFilter = "all";

    // Ambil source filter dari text content button atau data attribute
    if (sourceBtn) {
      const btnText = sourceBtn.textContent.trim();
      if (btnText !== "Source") {
        sourceFilter = btnText.replace("Source: ", "").toLowerCase();
      } else {
        sourceFilter = sourceBtn.getAttribute("data-current-filter") || "all";
      }
    }

    // Apply filters - MULAI DARI DATA ASLI!
    let filteredPapers = [...originalPapers]; // Selalu filter dari data asli

    // Filter by source
    if (sourceFilter && sourceFilter !== "all") {
      filteredPapers = filteredPapers.filter((paper) => {
        const paperSource = paper.source ? paper.source.toLowerCase() : "";

        // Handle specific sources
        if (sourceFilter === "scholar") {
          return (
            paperSource.includes("scholar") ||
            paperSource.includes("google scholar")
          );
        } else if (sourceFilter === "arxiv") {
          return paperSource.includes("arxiv");
        } else if (sourceFilter === "semantic") {
          return (
            paperSource.toLowerCase().includes("semantic") ||
            (paper.id && paper.id.toString().startsWith("ss_")) ||
            paperSource.toLowerCase().includes("semantic scholar")
          );
        }

        // Default case
        return paperSource.includes(sourceFilter.toLowerCase());
      });
    }

    // Filter by year
    if (yearFilter && yearFilter !== "all") {
      if (yearFilter.includes("-")) {
        // Range tahun (2020-2024)
        const [yearStart, yearEnd] = yearFilter
          .split("-")
          .map((y) => parseInt(y.trim()));
        if (!isNaN(yearStart) && !isNaN(yearEnd)) {
          filteredPapers = filteredPapers.filter((paper) => {
            const year = parseInt(paper.year);
            return !isNaN(year) && year >= yearStart && year <= yearEnd;
          });
        }
      } else {
        // Tahun individual (2023)
        const selectedYear = parseInt(yearFilter);
        if (!isNaN(selectedYear)) {
          filteredPapers = filteredPapers.filter((paper) => {
            return parseInt(paper.year) === selectedYear;
          });
        }
      }
    }

    // Update allPapers dengan hasil filtering
    allPapers = filteredPapers;
    setupPagination();
    showPage(1);
  }
  // Tambahkan fungsi untuk mereset filter
  function resetAllFilters() {
    // Reset year filter
    const yearBtn = document.querySelector(".year-filter .btn");
    if (yearBtn) {
      yearBtn.setAttribute("data-current-filter", "all");
      const filterValueEl = yearBtn.querySelector(".filter-value");
      if (filterValueEl) filterValueEl.textContent = "";
    }

    // Reset source filter
    const sourceBtn = document.querySelector(".source-filter .btn");
    if (sourceBtn) {
      sourceBtn.textContent = "Source";
      sourceBtn.setAttribute("data-current-filter", "all");
    }

    // Reset papers list ke data asli
    allPapers = [...originalPapers];

    console.log("Filters reset. Showing all papers:", allPapers.length);

    // Update UI
    setupPagination();
    showPage(1);
  }

  // Tambahkan tombol reset di bagian filter
  function addResetFilterButton() {
    const filterControls = document.querySelector(".filter-controls .d-flex");
    if (!filterControls) return;

    // Hapus tombol reset yang mungkin sudah ada
    const existingBtn = document.querySelector(".reset-filter-btn");
    if (existingBtn) existingBtn.remove();

    // Buat tombol reset baru
    const resetBtn = document.createElement("button");
    resetBtn.className = "btn btn-sm btn-outline-light reset-filter-btn ms-2";
    resetBtn.innerHTML = '<i class="fas fa-undo"></i> Reset';
    resetBtn.addEventListener("click", resetAllFilters);

    filterControls.appendChild(resetBtn);
  }

  // Setup pagination controls
  function setupPagination() {
    const paginationContainer = document.querySelector(".pagination-container");
    const pagination = document.querySelector(".pagination");

    if (!paginationContainer || !pagination) {
      console.error("Pagination elements not found in DOM");
      return;
    }

    // Hitung total halaman
    const totalPages = Math.ceil(allPapers.length / itemsPerPage);

    // Sembunyikan pagination jika hanya ada 1 halaman atau tidak ada hasil
    if (allPapers.length <= itemsPerPage) {
      paginationContainer.classList.add("d-none");
      return;
    }

    // Tampilkan pagination container
    paginationContainer.classList.remove("d-none");

    // Generate pagination HTML
    let paginationHTML = `
      <li class="page-item ${currentPage === 1 ? "disabled" : ""}">
        <a class="page-link" href="#" id="prev-page" aria-label="Previous">
          <span aria-hidden="true">&laquo;</span>
        </a>
      </li>
    `;

    // Generate page numbers
    for (let i = 1; i <= Math.min(totalPages, 5); i++) {
      paginationHTML += `
        <li class="page-item ${i === currentPage ? "active" : ""}">
          <a class="page-link" href="#" data-page="${i}">${i}</a>
        </li>
      `;
    }

    paginationHTML += `
      <li class="page-item ${currentPage === totalPages ? "disabled" : ""}">
        <a class="page-link" href="#" id="next-page" aria-label="Next">
          <span aria-hidden="true">&raquo;</span>
        </a>
      </li>
    `;

    pagination.innerHTML = paginationHTML;

    // Tambahkan event listeners
    const prevBtn = document.getElementById("prev-page");
    if (prevBtn) {
      prevBtn.addEventListener("click", function (e) {
        e.preventDefault();
        if (currentPage > 1) {
          showPage(currentPage - 1);
        }
      });
    }

    const nextBtn = document.getElementById("next-page");
    if (nextBtn) {
      nextBtn.addEventListener("click", function (e) {
        e.preventDefault();
        if (currentPage < totalPages) {
          showPage(currentPage + 1);
        }
      });
    }

    document.querySelectorAll(".page-link[data-page]").forEach((link) => {
      link.addEventListener("click", function (e) {
        e.preventDefault();
        const page = parseInt(this.getAttribute("data-page"));
        showPage(page);
      });
    });
  }

  // Display specific page of results (FUNGSI BARU)
  function showPage(page) {
    currentPage = page;

    // Calculate slice range
    const startIndex = (page - 1) * itemsPerPage;
    const endIndex = Math.min(startIndex + itemsPerPage, allPapers.length);
    const papersForPage = allPapers.slice(startIndex, endIndex);

    // Clear existing papers
    if (papersList) {
      papersList.innerHTML = "";

      // Add papers for current page
      if (papersForPage.length > 0) {
        papersForPage.forEach((paper) => {
          const paperElement = createPaperElement(paper);
          papersList.appendChild(paperElement);
        });
      } else {
        papersList.innerHTML = `
          <div class="alert alert-info">
            Tidak ditemukan jurnal yang sesuai dengan kriteria pencarian.
          </div>
        `;
      }
    }

    // Update pagination UI
    updatePaginationUI(page);
  }

  // Update active state in pagination controls (FUNGSI BARU)
  function updatePaginationUI(page) {
    // Update active page
    document.querySelectorAll(".pagination .page-item").forEach((item) => {
      item.classList.remove("active");
    });

    const activePage = document.querySelector(
      `.page-link[data-page="${page}"]`
    );
    if (activePage) {
      activePage.parentElement.classList.add("active");
    }

    // Update prev/next buttons
    const totalPages = Math.ceil(allPapers.length / itemsPerPage);

    const prevBtn = document.getElementById("prev-page");
    if (prevBtn) {
      prevBtn.parentElement.classList.toggle("disabled", page === 1);
    }

    const nextBtn = document.getElementById("next-page");
    if (nextBtn) {
      nextBtn.parentElement.classList.toggle("disabled", page === totalPages);
    }
  }

  // Fungsi untuk memformat ringkasan dengan sections dan styling
  function formatSummary(summary) {
    // Cek apakah ringkasan berisi struktur section
    if (summary.includes("##") || summary.includes("**")) {
      // Konversi markdown sederhana
      let formattedSummary = summary
        .replace(/##\s+(.*?)(?=##|$)/g, '<h5 class="summary-section">$1</h5>')
        .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
        .replace(/\n\n/g, "</p><p>")
        .replace(/\n/g, "<br>");

      return `<div class="summary-content">${formattedSummary}</div>`;
    } else {
      // Jika tidak ada format khusus, tampilkan sebagai paragraf biasa
      return `<div class="summary-content"><p>${summary}</p></div>`;
    }
  }

  // Function to create an element for a paper result
  function createPaperElement(paper) {
    const paperDiv = document.createElement("div");
    paperDiv.className = "paper-item";
    paperDiv.setAttribute(
      "data-paper-id",
      paper.id || Math.random().toString(36).substring(2)
    );

    // Tentukan logo path berdasarkan source
    let logoPath = "default-icon.png"; // Default logo
    let sourceClass = "default";
    const source = paper.source.toLowerCase();
    const paperId = paper.id;

    // Set logo dan class berdasarkan sumber
    if (source.includes("ieee")) {
      logoPath = "ieee-icon.png";
      sourceClass = "ieee";
    } else if (source.includes("arxiv")) {
      logoPath = "arxiv.jpg";
      sourceClass = "arxiv";
    } else if (source.includes("pubmed")) {
      logoPath = "pubmed-icon.png";
      sourceClass = "pubmed";
    } else if (source.includes("springer")) {
      logoPath = "springer-icon.png";
      sourceClass = "springer";
    } else if (source.includes("acm")) {
      logoPath = "acm-icon.png";
      sourceClass = "acm";
    } else if (source.includes("google scholar")) {
      logoPath = "google-scholar.jpg";
      sourceClass = "google-scholar";
    } else if (
      paperId.startsWith("ss_") ||
      source.includes("semantic scholar")
    ) {
      logoPath = "semantic_scholar_logo.png";
      sourceClass = "semantic-scholar";
    }

    // HTML template untuk paper dengan logo
    paperDiv.innerHTML = `
        <div class="paper-header">
            <div class="paper-title-container">
                <h3 class="paper-title">${paper.title}</h3>
                <p class="paper-authors">${paper.authors}</p>
                <div class="paper-metadata">
                    <span class="paper-year">${paper.year || "N/A"}</span>
                    ${
                      paper.doi
                        ? '<span class="paper-doi">DOI: ' +
                          paper.doi +
                          "</span>"
                        : ""
                    }
                </div>
            </div>
            <div class="source-logo-container">
                <img src="/assets/img/paper-icon/${logoPath}" alt="${source} logo" class="source-logo" onerror="this.src='/assets/img/paper-icon/default-icon.png'">
            </div>
        </div>
        <p class="paper-summary">${paper.summary}</p>
        <div class="paper-actions">
            <a href="${
              paper.link
            }" target="_blank" class="btn btn-sm btn-outline-primary">
                <i class="fas fa-external-link-alt"></i> Lihat Paper
            </a>
            <button class="btn btn-sm btn-outline-secondary summarize-btn" data-paper-id="${
              paper.id || Math.random().toString(36).substring(2)
            }" data-paper-title="${paper.title}">
                <i class="fas fa-file-alt"></i> Ringkasan
            </button>
            <button class="btn btn-sm btn-outline-info ask-btn" data-paper-title="${
              paper.title
            }">
                <i class="fas fa-question-circle"></i> Tanya
            </button>
            ${
              isUserLoggedIn()
                ? `
            <button class="btn btn-sm btn-outline-success citation-btn user-only-feature" data-paper-id="${
              paper.id || Math.random().toString(36).substring(2)
            }">
                <i class="fas fa-quote-right"></i> Sitasi
            </button>
            `
                : ""
            }
        </div>
    `;

    // Setup event handler untuk tombol summarize dengan modal
    const summarizeBtn = paperDiv.querySelector(".summarize-btn");
    summarizeBtn.addEventListener("click", function () {
      const paperId = this.getAttribute("data-paper-id");
      const paperTitle = this.getAttribute("data-paper-title");

      // Panggil handleSummarize dengan paper saat ini
      handleSummarize(paper, paperId, paperTitle);
    });

    // Setup ask button dengan modal chat
    const askBtn = paperDiv.querySelector(".ask-btn");
    askBtn.addEventListener("click", async function () {
      const paperTitle = this.getAttribute("data-paper-title");
      const paperId = paper.id || Math.random().toString(36).substring(2);

      // Set up modal title dengan judul paper
      document.getElementById("chatModalTitle").textContent = `Tanya tentang: ${
        paperTitle.length > 60
          ? paperTitle.substring(0, 60) + "..."
          : paperTitle
      }`;

      // PERBAIKAN: Cek existing session sebelum inisialisasi modal
      if (isUserLoggedIn()) {
        const existingSessionId = await checkExistingChatSession(paperId);
        if (existingSessionId) {
          // Gunakan session yang ada
          openChatSession(existingSessionId);
          return; // Hentikan eksekusi kode selanjutnya
        }
      }

      // Inisialisasi modal chat dengan pengecekan PDF
      initChatModal(paper, paperId, paperTitle);

      // Show modal
      const chatModal = new bootstrap.Modal(
        document.getElementById("chatModal")
      );
      chatModal.show();

      // Focus pada input pertanyaan
      setTimeout(() => {
        document.getElementById("modalQuestionInput").focus();
      }, 500);
    });

    const citationBtn = paperDiv.querySelector(".citation-btn");
    if (citationBtn) {
      citationBtn.addEventListener("click", function () {
        const paperId = this.getAttribute("data-paper-id");

        // Buat objek paper untuk diteruskan ke showCitationModal
        const paperData = {
          id: paperId,
          title: paper.title || "Untitled Paper",
          authors: paper.authors || "",
          year: paper.year || "",
          source: paper.source || "",
        };

        // Panggil fungsi showCitationModal dari citation.js
        if (window.showCitationModal) {
          window.showCitationModal(paperData);
        } else {
          console.error("showCitationModal function not available");
        }
      });
    }

    return paperDiv;
  }

  // Fungsi handleSummarize yang dipisah
  async function handleSummarize(paper, paperId, paperTitle) {
    try {
      // Tampilkan loading state
      document.getElementById("summaryModalContent").innerHTML = `
        <div class="d-flex justify-content-center my-4">
          <div class="spinner-border text-primary" role="status">
            <span class="visually-hidden">Loading...</span>
          </div>
          <div class="ms-3">Menghasilkan ringkasan...</div>
        </div>
      `;

      // Setup modal title
      document.getElementById("summaryModalTitle").textContent = paperTitle;

      // Show modal menggunakan Bootstrap
      const summaryModal = new bootstrap.Modal(
        document.getElementById("summaryModal")
      );
      summaryModal.show();

      // Dapatkan CSRF token yang valid
      const csrfToken = await ensureCsrfToken();

      // Kirim request dengan pdf_url jika tersedia
      const headers = {"Content-Type": "application/json"};
      const token = getToken();
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      // Tambahkan CSRF token ke headers
      if (csrfToken) {
        headers["X-CSRF-Token"] = csrfToken;
      }

      // Validasi URL PDF sebelum mengirimkan
      let pdf_url = paper.pdf_url;
      if (
        paper.pdf_url &&
        paper.source === "Google Scholar" &&
        !paper.pdf_url.includes(paperId.replace("gs_", "")) &&
        !paper.pdf_url.includes("semanticscholar.org") // Biarkan URL dari semanticscholar
      ) {
        console.warn(
          "URL PDF tidak valid untuk paper ini, tidak akan digunakan"
        );
        pdf_url = null;
      }

      // Buat request body
      const requestBody = {
        paper_id: paperId,
        title: paperTitle,
        abstract: paper.summary,
        pdf_url: pdf_url,
        source: paper.source || null,
      };

      // Log data request untuk debugging
      console.log("Sending summary request with payload:", requestBody);

      const response = await fetch(`/api/ai/summarize`, {
        method: "POST",
        headers,
        body: JSON.stringify(requestBody),
        credentials: "include", // Penting untuk CSRF
      });

      if (response.ok) {
        const data = await response.json();

        // Format ringkasan
        const summaryHTML = formatSummary(data.summary);

        // Update currentPaperContext dengan PDF URL yang diterima
        if (!currentPaperContext || currentPaperContext.id !== paperId) {
          currentPaperContext = {
            id: paperId,
            title: paperTitle,
            pdf_url: data.pdf_url || null,
          };
        } else {
          // Update PDF URL jika sudah ada konteks
          currentPaperContext.pdf_url =
            data.pdf_url || currentPaperContext.pdf_url;
        }

        // Tambahkan indikator sumber ringkasan dan opsi upload jika ekstraksi gagal
        let sourceIndicator = "";

        if (data.used_pdf) {
          sourceIndicator = `
            <div class="pdf-source-indicator mb-3 text-success">
                <i class="fas fa-file-pdf"></i> 
                <span>Ringkasan lengkap dibuat berdasarkan konten penuh PDF paper</span>
                ${
                  data.pdf_url
                    ? `<span class="d-none">PDF URL: ${data.pdf_url}</span>`
                    : ""
                }
            </div>`;
        } else if (data.pdf_url) {
          // Jika ada URL PDF tapi ekstraksi gagal
          sourceIndicator = `
        <div class="pdf-source-indicator mb-3 text-warning">
            <i class="fas fa-exclamation-triangle"></i>
            <span>Ringkasan dibuat hanya dari abstrak. PDF tersedia tetapi tidak dapat diakses sistem.</span>
            ${
              data.pdf_url
                ? `<span class="d-none">PDF URL: ${data.pdf_url}</span>`
                : ""
            }
        </div>`;
        } else {
          // Jika tidak ada URL PDF sama sekali
          sourceIndicator = `
            <div class="pdf-source-indicator mb-3 text-info">
                <i class="fas fa-info-circle"></i> 
                <span>Ringkasan saat ini dibuat dari abstrak. Upload PDF untuk mendapatkan analisis lengkap.</span>
            </div>`;
        }

        // Update modal content
        document.getElementById("summaryModalContent").innerHTML =
          sourceIndicator + summaryHTML;

        // Cek apakah PDF sudah pernah diupload untuk paper ini
        const pdfAlreadyUploaded = data.used_pdf || uploadedPdfPapers[paperId];
        updateSummaryModalFooter(paperId, paperTitle, pdfAlreadyUploaded);
      } else {
        // Handle error status
        let errorMessage = `Error ${response.status}: ${response.statusText}`;

        try {
          const errorData = await response.json();
          console.error("Summary API error:", errorData);
          errorMessage = errorData.detail || errorMessage;
        } catch (parseError) {
          const errorText = await response.text();
          console.error("Summary API error (raw):", errorText);
          errorMessage = errorText || errorMessage;
        }

        document.getElementById("summaryModalContent").innerHTML = `
          <div class="alert alert-danger">
            Gagal menghasilkan ringkasan: ${errorMessage}
          </div>
        `;
      }
    } catch (error) {
      console.error("Error generating summary:", error);
      document.getElementById("summaryModalContent").innerHTML = `
        <div class="alert alert-danger">
          Terjadi kesalahan: ${error.message || "Unknown error"}
        </div>
      `;
    }
  }

  // Function to add message to chat
  function addMessageToChat(message, isUser = false) {
    const messageDiv = document.createElement("div");
    messageDiv.className = `message-bubble ${
      isUser ? "user-message" : "ai-message"
    }`;

    // Gunakan formatting markdown untuk pesan AI saja
    if (!isUser) {
      messageDiv.innerHTML = formatChatMessage(message);
    } else {
      messageDiv.textContent = message;
    }

    chatContainer.appendChild(messageDiv);
    scrollToBottom();
  }

  // Function to show typing indicator
  function showTypingIndicator() {
    const indicatorDiv = document.createElement("div");
    indicatorDiv.className = "typing-indicator";
    indicatorDiv.innerHTML = `
      <span></span>
      <span></span>
      <span></span>
    `;
    indicatorDiv.id = "typingIndicator";
    chatContainer.appendChild(indicatorDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;
  }

  // Function to remove typing indicator
  function removeTypingIndicator() {
    const indicator = document.getElementById("typingIndicator");
    if (indicator) {
      indicator.remove();
    }
  }

  // Function untuk smooth scrolling ke bawah chat
  function scrollToBottom() {
    setTimeout(() => {
      chatContainer.scrollTop = chatContainer.scrollHeight;
    }, 100);
  }

  async function sendQuestion() {
    const question = modalQuestionInput.value.trim();
    if (!question || !currentPaperContext) return;

    // Add user message to chat
    addMessageToChat(question, true);
    modalQuestionInput.value = "";

    // Show typing indicator
    if (currentPaperContext.pdf_url) {
      showTypingIndicator(
        "Sedang mengakses PDF paper untuk memberikan jawaban lengkap..."
      );
    } else {
      showTypingIndicator();
    }

    try {
      const headers = {"Content-Type": "application/json"};
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;

      // Tambahkan CSRF token ke headers
      const csrfToken = await ensureCsrfToken();
      if (csrfToken) {
        headers["X-CSRF-Token"] = csrfToken;
      }

      // ✅ PERSISTENT SESSION REQUEST
      const requestBody = {
        question,
        paper_id: currentPaperContext.id,
        paper_title: currentPaperContext.title,
        context: JSON.stringify([currentPaperContext]),
        pdf_url: currentPaperContext.pdf_url,
        use_full_text: true,
        guest_mode: !isUserLoggedIn(),
        session_id: currentPaperContext.chat_session_id || null, // ✅ PERSISTENT SESSION
        force_persistent: true, // ✅ FORCE ke session yang sama
      };

      const response = await fetch("/api/ai/question", {
        method: "POST",
        headers,
        body: JSON.stringify(requestBody),
        credentials: "include",
      });

      removeTypingIndicator();

      if (response.ok) {
        const data = await response.json();

        // Tambahkan jawaban ke chat
        if (data.used_pdf) {
          addMessageToChat(`${data.answer}`);
        } else {
          addMessageToChat(data.answer);
        }

        // ✅ PERSISTENT SESSION MANAGEMENT
        if (data.session_id && currentPaperContext) {
          currentPaperContext.chat_session_id = data.session_id;

          // ✅ SAVE PERSISTENT session ke localStorage
          const savedSessions = JSON.parse(
            localStorage.getItem("chatSessions") || "{}"
          );

          savedSessions[currentPaperContext.id] = {
            sessionId: data.session_id,
            title: currentPaperContext.title,
            paperId: currentPaperContext.id,
            persistentSession: true, // ✅ MARK sebagai persistent
            lastUsed: new Date().toISOString(),
          };

          localStorage.setItem("chatSessions", JSON.stringify(savedSessions));

          // ✅ UPDATE SIDEBAR - hanya update existing atau create baru jika belum ada
          if (data.is_new_session && isUserLoggedIn()) {
            if (window.addChatSessionToSidebar) {
              window.addChatSessionToSidebar(
                data.session_id,
                question,
                currentPaperContext.title,
                new Date(),
                true // ✅ Mark sebagai persistent
              );
            }
          } else if (isUserLoggedIn()) {
            // ✅ UPDATE existing session di sidebar jika perlu
            updateChatSessionInSidebar(data.session_id, question);
          }

          console.log("✅ PERSISTENT session updated:", data.session_id);
        }

        // Tambahkan pesan reminder untuk user tamu
        if (
          !isUserLoggedIn() &&
          chatContainer.querySelectorAll(".message-bubble").length > 4
        ) {
          setTimeout(() => {
            const guestReminder = document.createElement("div");
            guestReminder.className = "guest-reminder";
            guestReminder.innerHTML = `
                          <div class="alert alert-info">
                              <i class="fas fa-info-circle"></i> 
                              <strong>Login untuk menyimpan percakapan ini</strong>
                              <div>Sebagai pengguna tamu, percakapan ini tidak akan disimpan setelah sesi berakhir.</div>
                              <a href="/login?returnUrl=${encodeURIComponent(
                                window.location.pathname
                              )}" class="btn btn-sm btn-light mt-2">Login Sekarang</a>
                          </div>
                      `;
            chatContainer.appendChild(guestReminder);
            scrollToBottom();
          }, 1000);
        }
      } else {
        addMessageToChat(
          "Maaf, terjadi kesalahan dalam memproses pertanyaan Anda."
        );
      }
    } catch (error) {
      removeTypingIndicator();
      addMessageToChat("Terjadi kesalahan jaringan. Silakan coba lagi.");
      console.error("Error asking question:", error);
    }
  }

  // Event listener for send button
  if (sendQuestionBtn) {
    sendQuestionBtn.addEventListener("click", sendQuestion);
  }

  // Event listener for Enter key in input
  if (modalQuestionInput) {
    modalQuestionInput.addEventListener("keypress", function (e) {
      if (e.key === "Enter") {
        sendQuestion();
      }
    });
  }

  // Event listener for modal hide
  document
    .getElementById("chatModal")
    .addEventListener("hidden.bs.modal", function () {
      // Clear current paper context when modal is closed
      // currentPaperContext = null;
    });

  // Simple keyword extraction method
  function extractKeyTerms(text) {
    // Common academic terms
    const academicTerms = [
      "AI",
      "machine learning",
      "deep learning",
      "neural network",
      "algorithm",
      "model",
      "dataset",
      "analysis",
      "framework",
      "method",
      "approach",
      "technique",
      "system",
      "implementation",
      "evaluation",
      "performance",
      "accuracy",
      "precision",
      "recall",
    ];

    return academicTerms.filter((term) =>
      text.toLowerCase().includes(term.toLowerCase())
    );
  }

  // Show error message
  function showError(message) {
    if (emptyState) emptyState.classList.add("d-none");
    if (loadingState) loadingState.classList.add("d-none");
    if (resultsArea) resultsArea.classList.remove("d-none");

    if (papersList) {
      papersList.innerHTML = `
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-circle"></i> ${message}
                </div>
            `;
    }
  }

  async function handlePdfUpload(paperId, paperTitle, fromChat = false) {
    // Buat form input file tersembunyi
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = "application/pdf";
    fileInput.style.display = "none";
    document.body.appendChild(fileInput);

    // Trigger file browser
    fileInput.click();

    // Handle file selection
    fileInput.addEventListener("change", async function () {
      if (!fileInput.files || !fileInput.files[0]) {
        document.body.removeChild(fileInput);
        return;
      }

      const file = fileInput.files[0];
      if (file.type !== "application/pdf") {
        alert("File harus dalam format PDF");
        document.body.removeChild(fileInput);
        return;
      }

      // Tampilkan loading state di modal yang sesuai
      if (fromChat) {
        document.getElementById("chatPdfNotice").innerHTML = `
          <div class="d-flex align-items-center pdf-source-indicator">
            <div class="spinner-border spinner-border-sm text-primary" role="status">
              <span class="visually-hidden">Loading...</span>
            </div>
            <div class="ms-3">Mengupload dan memproses PDF...</div>
          </div>
        `;
      } else {
        document.getElementById("summaryModalContent").innerHTML = `
          <div class="d-flex justify-content-center my-4">
            <div class="spinner-border text-primary" role="status">
              <span class="visually-hidden">Loading...</span>
            </div>
            <div class="ms-3">Mengupload dan memproses PDF...</div>
          </div>
        `;
      }

      // Persiapkan form data
      const formData = new FormData();
      formData.append("paper_id", paperId);
      formData.append("title", paperTitle);
      formData.append("pdf_file", file);

      // Get token if available
      const headers = {};
      const token = getToken();
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      const csrfToken = await ensureCsrfToken();
      if (csrfToken) {
        headers["X-CSRF-Token"] = csrfToken;
      }

      try {
        // Upload file
        const response = await fetch("/api/ai/upload-pdf", {
          method: "POST",
          headers,
          body: formData,
          credentials: "include", // Penting untuk menyertakan cookies
        });

        if (response.ok) {
          const data = await response.json();

          // Perbarui context untuk fitur chat
          if (currentPaperContext && currentPaperContext.id === paperId) {
            currentPaperContext.has_local_pdf = true;
            // Tambahkan PDF URL lokal untuk referensi
            currentPaperContext.pdf_url = `local://${paperId}.pdf`;
          }

          // Set flag bahwa PDF sudah diupload untuk paper ini
          uploadedPdfPapers[paperId] = true;

          if (fromChat) {
            // Update chat notice jika upload dari chat
            const chatPdfNotice = document.getElementById("chatPdfNotice");
            chatPdfNotice.innerHTML = `
              <div class="pdf-source-indicator text-success">
                <i class="fas fa-file-pdf"></i> 
                <span>PDF berhasil diproses. AI akan menggunakan informasi dari PDF lengkap (${(
                  data.text_length / 1000
                ).toFixed(1)}K karakter).</span>
                ${
                  isUserLoggedIn()
                    ? `
                  <button class="btn btn-sm btn-outline-danger ms-2 reset-pdf-btn" 
                          data-paper-id="${paperId}" data-paper-title="${paperTitle}">
                    <i class="fas fa-undo-alt"></i> Reset PDF
                  </button>`
                    : ""
                }
              </div>
            `;

            // Tambahkan event listener untuk tombol reset PDF
            const resetBtn = chatPdfNotice.querySelector(".reset-pdf-btn");
            if (resetBtn) {
              resetBtn.addEventListener("click", () =>
                confirmResetPdf(paperId, paperTitle)
              );
            }

            // Hapus tombol upload setelah berhasil
            document.querySelector(".chat-actions").innerHTML = "";

            // Tambahkan pesan konfirmasi ke chat
            const successMessage = `
              <div class="ai-message">
                <div class="ai-avatar">AI</div>
                <div class="message-content">
                  <p>PDF berhasil diupload dan diproses. Sekarang saya dapat menjawab pertanyaan Anda dengan lebih komprehensif berdasarkan teks lengkap paper.</p>
                  <p class="small text-muted">Silakan ajukan pertanyaan Anda tentang paper ini.</p>
                </div>
              </div>
            `;
            chatContainer.innerHTML += successMessage;
            scrollToBottom();
          } else {
            // Format ringkasan jika untuk modal summary
            const summaryHTML = formatSummary(data.summary);

            let statusIndicator = "";
            if (data.guest_mode) {
              statusIndicator = `
                <div class="pdf-source-indicator mb-3 text-info">
                  <i class="fas fa-info-circle"></i> 
                  <span>Anda menggunakan fitur ini sebagai tamu. Hasil ekstraksi PDF akan tersedia selama 24 jam.</span>
                </div>`;
            }

            // Update modal dengan hasil
            document.getElementById("summaryModalContent").innerHTML = `
              <div class="pdf-source-indicator mb-3 text-success">
                <i class="fas fa-file-pdf"></i> 
                <span>Ringkasan dibuat dari PDF yang Anda unggah (${(
                  data.text_length / 1000
                ).toFixed(1)}K karakter)</span>
                <span class="d-none">PDF URL: local://${paperId}.pdf</span>
              </div>
              ${statusIndicator}
              ${summaryHTML}
            `;

            // Update footer modal - tampilkan tombol reset dan hapus tombol upload
            updateSummaryModalFooter(paperId, paperTitle, true);
          }
        } else {
          const errorData = await response.json();
          const errorMessage = `
            <div class="alert alert-danger">
              Gagal memproses PDF: ${errorData.detail || "Unknown error"}
            </div>
          `;

          if (fromChat) {
            document.getElementById("chatPdfNotice").innerHTML = errorMessage;
          } else {
            document.getElementById("summaryModalContent").innerHTML =
              errorMessage;
          }
        }
      } catch (error) {
        console.error("Error uploading PDF:", error);
        const errorMessage = `
          <div class="alert alert-danger">
            Terjadi kesalahan saat mengupload PDF. Silakan coba lagi.
          </div>
        `;

        if (fromChat) {
          document.getElementById("chatPdfNotice").innerHTML = errorMessage;
        } else {
          document.getElementById("summaryModalContent").innerHTML =
            errorMessage;
        }
      } finally {
        document.body.removeChild(fileInput);
      }
    });
  }

  // Handle questions about papers
  if (questionInput) {
    questionInput.addEventListener("keypress", function (e) {
      if (e.key === "Enter") {
        const question = this.value.trim();
        if (question) {
          askQuestion(question);
          this.value = "";
        }
      }
    });
  }

  async function askQuestion(question) {
    try {
      const headers = {"Content-Type": "application/json"};
      const token = getToken();
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      // Get currently displayed papers as context
      const papers = Array.from(document.querySelectorAll(".paper-item")).map(
        (item) => ({
          title: item.querySelector(".paper-title").textContent,
          summary: item.querySelector(".paper-summary").textContent,
        })
      );

      const response = await fetch("/api/ai/question", {
        method: "POST",
        headers,
        body: JSON.stringify({
          question,
          context: papers.length ? JSON.stringify(papers) : "",
        }),
      });

      if (response.ok) {
        const data = await response.json();
        displayAnswer(question, data.answer);
      } else {
        const error = await response.json();
        showError(error.detail || "Gagal mendapatkan jawaban");
      }
    } catch (error) {
      console.error("Error asking question:", error);
    }
  }

  // Display answer to question
  function displayAnswer(question, answer) {
    if (!papersList) return;

    const answerDiv = document.createElement("div");
    answerDiv.className = "answer-container bg-light p-3 rounded mb-4";
    answerDiv.innerHTML = `
            <div class="question-bubble"><strong>Q:</strong> ${question}</div>
            <div class="answer-bubble mt-2"><strong>A:</strong> ${answer}</div>
        `;

    // Insert at the top of papers list
    if (papersList.firstChild) {
      papersList.insertBefore(answerDiv, papersList.firstChild);
    } else {
      papersList.appendChild(answerDiv);
    }
  }

  // Event listener untuk tombol copy ringkasan
  document.addEventListener("click", function (e) {
    if (e.target.closest(".copy-summary-btn")) {
      const summaryText = document.getElementById(
        "summaryModalContent"
      ).innerText;
      navigator.clipboard
        .writeText(summaryText)
        .then(() => {
          // Feedback visual bahwa copy berhasil
          const copyBtn = e.target.closest(".copy-summary-btn");
          copyBtn.innerHTML = '<i class="fas fa-check"></i> Tersalin';
          setTimeout(() => {
            copyBtn.innerHTML = '<i class="fas fa-copy"></i> Salin Ringkasan';
          }, 2000);
        })
        .catch((err) => {
          console.error("Gagal menyalin teks: ", err);
          const copyBtn = e.target.closest(".copy-summary-btn");
          copyBtn.innerHTML = '<i class="fas fa-times"></i> Gagal Menyalin';
          setTimeout(() => {
            copyBtn.innerHTML = '<i class="fas fa-copy"></i> Salin Ringkasan';
          }, 2000);
        });
    }
  });

  document.addEventListener("loginStatusUpdated", function (e) {
    // Update tampilan semua element user-only-feature
    const userOnlyFeatures = document.querySelectorAll(".user-only-feature");
    userOnlyFeatures.forEach((el) => {
      if (e.detail.isLoggedIn) {
        el.classList.remove("d-none");
      } else {
        el.classList.add("d-none");
      }
    });
  });

  // ======= KODE YANG SUDAH ADA (LANJUTAN) =======
  // Panggil fungsi penanganan token
  handleTokenFromUrl();
  handleTokenFromFragment();

  // Panggil fungsi pengecekan login
  checkLoginStatus();

  // Pastikan warna teks di textarea dan input adalah putih
  if (searchQuery) {
    searchQuery.addEventListener("input", function () {
      this.style.color = "white";
    });
    searchQuery.style.color = "white";
  }

  if (questionInput) {
    questionInput.addEventListener("input", function () {
      this.style.color = "white";
    });
    questionInput.style.color = "white";
  }

  // Tambahkan listener untuk tombol lanjutkan sebagai tamu
  const continueAsGuestBtn = document.querySelector(".modal-footer .btn-link");
  if (continueAsGuestBtn) {
    continueAsGuestBtn.addEventListener("click", function () {
      // Tidak perlu melakukan apa-apa, modal akan ditutup otomatis oleh Bootstrap
    });
  }

  // Tambahkan listener untuk tag klik (mempertahankan fitur yang sudah ada)
  const tags = document.querySelectorAll(".tag");
  tags.forEach((tag) => {
    tag.addEventListener("click", function () {
      const tagText = this.textContent.trim();
      if (searchQuery) {
        // Tambahkan tag ke query
        let currentQuery = searchQuery.value.trim();
        searchQuery.value = currentQuery + (currentQuery ? ", " : "") + tagText;
        searchQuery.focus();
      }
    });
  });

  // Ganti handler lama dengan fungsi baru
  if (searchForm) {
    searchForm.addEventListener("submit", function (e) {
      e.preventDefault();
      performSearch();
    });
  }

  function initChatModal(paper, paperId, paperTitle) {
    console.log("🚀 Initializing chat modal for:", paperId, paperTitle);

    // Reset chat history
    chatContainer.innerHTML = "";

    // ✅ IMPROVED: PERSISTENT SESSION RETRIEVAL - SATU PAPER SATU SESSION SELAMANYA
    let existingSessionId = null;
    const savedSessions = JSON.parse(
      localStorage.getItem("chatSessions") || "{}"
    );

    console.log("💾 Checking saved sessions:", savedSessions);

    // ✅ PRIORITY 1: Cek dari localStorage dulu (persistent)
    if (savedSessions[paperId]) {
      if (
        typeof savedSessions[paperId] === "object" &&
        savedSessions[paperId].sessionId
      ) {
        existingSessionId = savedSessions[paperId].sessionId;
        console.log(
          "✅ Found PERSISTENT session ID from localStorage:",
          existingSessionId
        );
      } else if (
        typeof savedSessions[paperId] === "number" ||
        typeof savedSessions[paperId] === "string"
      ) {
        existingSessionId = savedSessions[paperId];
        console.log("✅ Found session ID (legacy format):", existingSessionId);
      }
    }

    // ✅ SET GLOBAL CONTEXT - PERSISTENT SESSION ID
    window.currentPaperContext = {
      id: paperId,
      title: paperTitle,
      authors: paper.authors || "",
      abstract: paper.abstract || paper.summary || "",
      pdf_url: paper.pdf_url || null,
      has_local_pdf: false,
      chat_session_id: existingSessionId, // ✅ PERSISTENT SESSION
    };

    console.log("📝 Set currentPaperContext:", window.currentPaperContext);

    if (existingSessionId && isUserLoggedIn()) {
      console.log(
        "🔄 Loading existing chat history for PERSISTENT session:",
        existingSessionId
      );
      loadChatHistory(existingSessionId);
    } else {
      console.log("🆕 Starting new chat session");
      // Tampilkan pesan selamat datang
      const welcomeMessage = `
              <div class="welcome-message">
                  <p>Saya siap menjawab pertanyaan Anda tentang paper "<strong>${paperTitle}</strong>".</p>
                  <p class="small text-subtle">Anda dapat bertanya tentang metodologi, temuan, atau aspek lainnya dari paper ini.</p>
              </div>`;

      chatContainer.innerHTML = welcomeMessage;
    }

    // Reset input
    modalQuestionInput.value = "";

    // ✅ CHECK PDF dengan delay untuk memastikan context sudah set
    setTimeout(() => {
      console.log("🔍 Starting PDF availability check...");
      checkPdfAvailabilityForChat(paper, paperId, paperTitle);
    }, 200);
  }

  async function checkExistingChatSession(paperId) {
    if (!isUserLoggedIn()) return null;

    // ✅ PRIORITY 1: Cek localStorage dulu untuk PERSISTENT session
    const savedSessions = JSON.parse(
      localStorage.getItem("chatSessions") || "{}"
    );

    if (savedSessions[paperId]) {
      let sessionId = null;

      if (
        typeof savedSessions[paperId] === "object" &&
        savedSessions[paperId].sessionId
      ) {
        sessionId = savedSessions[paperId].sessionId;
      } else if (
        typeof savedSessions[paperId] === "number" ||
        typeof savedSessions[paperId] === "string"
      ) {
        sessionId = savedSessions[paperId];
      }

      if (sessionId) {
        console.log(
          "✅ Found PERSISTENT session from localStorage:",
          sessionId
        );

        // ✅ VERIFY session masih valid di server
        try {
          const headers = {"Content-Type": "application/json"};
          const token = getToken();
          if (token) headers["Authorization"] = `Bearer ${token}`;

          const verifyResponse = await fetch(
            `/api/ai/chat-sessions/${sessionId}`,
            {
              method: "GET",
              headers,
              credentials: "include",
            }
          );

          if (verifyResponse.ok) {
            console.log("✅ PERSISTENT session verified on server");
            return sessionId;
          } else {
            console.log("⚠️ PERSISTENT session expired, will create new one");
            // Hapus session yang expired dari localStorage
            delete savedSessions[paperId];
            localStorage.setItem("chatSessions", JSON.stringify(savedSessions));
          }
        } catch (error) {
          console.error("Error verifying persistent session:", error);
        }
      }
    }

    // ✅ PRIORITY 2: Cek server untuk existing session jika localStorage kosong
    try {
      const headers = {"Content-Type": "application/json"};
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const response = await fetch(`/api/ai/paper-chat-session/${paperId}`, {
        method: "GET",
        headers,
        credentials: "include",
      });

      if (response.ok) {
        const data = await response.json();

        if (data.session_id) {
          // ✅ SAVE ke localStorage sebagai PERSISTENT session
          savedSessions[paperId] = {
            sessionId: data.session_id,
            title: data.paper_title || "Unknown Paper",
            paperId: paperId,
            persistentSession: true,
          };
          localStorage.setItem("chatSessions", JSON.stringify(savedSessions));

          console.log(
            "✅ Found and saved PERSISTENT session from server:",
            data.session_id
          );
          return data.session_id;
        }
      }
    } catch (error) {
      console.error("Error checking existing chat session:", error);
    }

    console.log(
      "🆕 No existing session found, will create new PERSISTENT session"
    );
    return null;
  }

  // Fungsi baru untuk memuat riwayat chat dari session_id
  async function loadChatHistory(sessionId) {
    try {
      const headers = {"Content-Type": "application/json"};
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const response = await fetch(`/api/ai/chat-sessions/${sessionId}`, {
        method: "GET",
        headers,
        credentials: "include",
      });

      if (response.ok) {
        const data = await response.json();

        // Tampilkan pesan selamat datang awal
        const welcomeMessage = document.createElement("div");
        welcomeMessage.className = "welcome-message";
        welcomeMessage.innerHTML = `
          <p>Melanjutkan percakapan tentang paper "<strong>${data.paper_title}</strong>".</p>
        `;
        chatContainer.appendChild(welcomeMessage);

        // Tambahkan semua pesan dari riwayat
        data.messages.forEach((msg) => {
          addMessageToChat(msg.message, msg.is_user);
        });

        // Scroll ke bagian bawah chat
        scrollToBottom();
      } else {
        console.error("Error loading chat history");
        // Jika gagal memuat, tampilkan pesan selamat datang biasa
        const welcomeMessage = `
          <div class="welcome-message">
            <p>Saya siap menjawab pertanyaan Anda tentang paper "<strong>${currentPaperContext.title}</strong>".</p>
            <p class="small text-subtle">Anda dapat bertanya tentang metodologi, temuan, atau aspek lainnya dari paper ini.</p>
          </div>`;

        chatContainer.innerHTML = welcomeMessage;
      }
    } catch (error) {
      console.error("Error loading chat history:", error);
    }
  }

  // Fungsi untuk memeriksa ketersediaan PDF dan menampilkan notifikasi
  async function checkPdfAvailabilityForChat(paper, paperId, paperTitle) {
    const chatPdfNotice = document.getElementById("chatPdfNotice");
    const chatActionsContainer = document.querySelector(".chat-actions");

    // Reset container
    if (chatPdfNotice) {
      chatPdfNotice.classList.add("d-none");
      chatPdfNotice.innerHTML = "";
    }

    if (chatActionsContainer) {
      chatActionsContainer.innerHTML = "";
    }

    try {
      // Periksa ekstraksi yang ada
      const csrfToken = await ensureCsrfToken();
      const headers = {"Content-Type": "application/json"};
      const token = getToken();
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      if (csrfToken) {
        headers["X-CSRF-Token"] = csrfToken;
      }

      const response = await fetch("/api/ai/check-extraction", {
        method: "POST",
        headers,
        body: JSON.stringify({paper_id: paperId}),
        credentials: "include",
      });

      if (response.ok) {
        const data = await response.json();

        // Update context dengan status PDF
        if (currentPaperContext && currentPaperContext.id === paperId) {
          currentPaperContext.has_local_pdf = data.has_extraction;
          currentPaperContext.pdf_url =
            data.pdf_url || currentPaperContext.pdf_url;
        }

        // Jika tidak ada ekstraksi PDF, tampilkan notifikasi dan tombol upload
        if (chatPdfNotice && chatActionsContainer) {
          if (!data.has_extraction) {
            chatPdfNotice.classList.remove("d-none");
            chatPdfNotice.innerHTML = `
              <div class="pdf-source-indicator text-info">
                <i class="fas fa-info-circle"></i> 
                <span>Tanpa PDF lengkap, jawaban akan dibatasi pada informasi dari abstrak saja.</span>
              </div>
            `;

            // Tambahkan tombol upload PDF
            const uploadBtn = document.createElement("button");
            uploadBtn.className =
              "btn btn-sm btn-outline-primary pdf-upload-btn";
            uploadBtn.innerHTML = '<i class="fas fa-upload"></i> Upload PDF';
            uploadBtn.onclick = () =>
              handlePdfUpload(paperId, paperTitle, true);
            chatActionsContainer.appendChild(uploadBtn);
          } else {
            // Jika ada ekstraksi, tampilkan informasi dan tombol reset
            chatPdfNotice.classList.remove("d-none");
            chatPdfNotice.innerHTML = `
              <div class="pdf-source-indicator text-success">
                <i class="fas fa-file-pdf"></i> 
                <span>AI akan menggunakan informasi dari PDF lengkap untuk menjawab pertanyaan Anda.</span>
                ${
                  isUserLoggedIn()
                    ? `
                  <button class="btn btn-sm btn-outline-danger ms-2 reset-pdf-btn" 
                          data-paper-id="${paperId}" data-paper-title="${paperTitle}">
                    <i class="fas fa-undo-alt"></i> Reset PDF
                  </button>`
                    : ""
                }
              </div>
            `;

            // Tambahkan event listener untuk tombol reset PDF
            const resetBtn = chatPdfNotice.querySelector(".reset-pdf-btn");
            if (resetBtn) {
              resetBtn.addEventListener("click", () =>
                confirmResetPdf(paperId, paperTitle)
              );
            }
          }
        }
      }
    } catch (error) {
      console.error("Error checking PDF extraction:", error);
    }
  }
  // Fungsi untuk konfirmasi reset PDF
  async function confirmResetPdf(paperId, paperTitle) {
    // Buat modal konfirmasi menggunakan template yang sudah ada
    const modalHtml = `
      <div class="modal fade" id="resetPdfConfirmModal" tabindex="-1" aria-hidden="true">
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">Konfirmasi Reset PDF</h5>
              <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body">
              <p>Apakah Anda yakin ingin menghapus PDF yang diupload untuk paper ini?</p>
              <div class="paper-preview mt-3 p-3 rounded" style="background-color: rgba(0,0,0,0.2);">
                <div class="fw-bold">${paperTitle}</div>
              </div>
              <div class="alert alert-warning mt-3">
                <i class="fas fa-exclamation-triangle"></i> 
                <span>Setelah dihapus, AI akan menggunakan abstrak untuk menjawab pertanyaan.</span>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-outline-light" data-bs-dismiss="modal">Batal</button>
              <button type="button" class="btn btn-danger" id="confirmResetPdfBtn">
                Reset PDF
              </button>
            </div>
          </div>
        </div>
      </div>
    `;

    // Tambahkan modal ke DOM
    document.body.insertAdjacentHTML("beforeend", modalHtml);

    // Ambil referensi modal
    const modalElement = document.getElementById("resetPdfConfirmModal");
    const modal = new bootstrap.Modal(modalElement);

    // Tambahkan event listener untuk tombol konfirmasi
    document
      .getElementById("confirmResetPdfBtn")
      .addEventListener("click", async function () {
        try {
          // Tampilkan loading state
          this.disabled = true;
          this.innerHTML =
            '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Menghapus...';

          // Panggil API untuk reset PDF
          const csrfToken = await ensureCsrfToken();
          const headers = {
            "Content-Type": "application/json",
            Authorization: `Bearer ${getToken()}`,
          };
          if (csrfToken) headers["X-CSRF-Token"] = csrfToken;

          const response = await fetch("/api/ai/reset-extraction", {
            method: "POST",
            headers,
            body: JSON.stringify({paper_id: paperId}),
            credentials: "include",
          });

          if (response.ok) {
            // Tutup modal
            modal.hide();

            // Update UI
            if (currentPaperContext && currentPaperContext.id === paperId) {
              currentPaperContext.has_local_pdf = false;
            }

            // Re-check PDF availability untuk update UI
            checkPdfAvailabilityForChat({id: paperId}, paperId, paperTitle);

            // Tampilkan toast sukses
            if (window.showToast) {
              window.showToast(
                "PDF berhasil direset. AI akan menggunakan abstrak paper."
              );
            } else {
              // Fallback jika showToast tidak tersedia
              const toastDiv = document.createElement("div");
              toastDiv.className =
                "position-fixed top-0 end-0 p-3 toast-container";
              toastDiv.style.zIndex = 9999;
              toastDiv.innerHTML = `
              <div class="toast bg-success text-white" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="toast-body">
                  <i class="fas fa-check-circle me-2"></i> PDF berhasil direset. AI akan menggunakan abstrak paper.
                </div>
              </div>
            `;
              document.body.appendChild(toastDiv);

              const toast = new bootstrap.Toast(
                toastDiv.querySelector(".toast"),
                {delay: 3000}
              );
              toast.show();

              setTimeout(() => {
                document.body.removeChild(toastDiv);
              }, 3500);
            }
          } else {
            const error = await response.json();
            throw new Error(error.detail || "Gagal mereset PDF");
          }
        } catch (error) {
          console.error("Error resetting PDF extraction:", error);
          if (window.showToast) {
            window.showToast("Terjadi kesalahan saat mereset PDF", "error");
          } else {
            alert("Terjadi kesalahan saat mereset PDF: " + error.message);
          }
        } finally {
          // Hapus modal dari DOM setelah ditutup
          modalElement.addEventListener("hidden.bs.modal", function () {
            modalElement.remove();
          });

          // Tutup modal jika error
          if (modal._isShown) {
            modal.hide();
          }
        }
      });

    // Tampilkan modal
    modal.show();
  }

  // Fungsi baru untuk memperbarui footer modal summary
  function updateSummaryModalFooter(paperId, paperTitle, pdfUploaded = false) {
    const modalFooter = document.querySelector(
      "#summaryModal .modal-footer .d-flex"
    );
    if (modalFooter) {
      // Reset footer
      modalFooter.innerHTML = "";

      // Buat container untuk tombol-tombol kiri
      const leftButtonsContainer = document.createElement("div");
      leftButtonsContainer.className = "d-flex gap-2";

      // 1. Tombol Salin Ringkasan
      const copyBtn = document.createElement("button");
      copyBtn.className = "btn btn-outline-info copy-summary-btn";
      copyBtn.innerHTML = '<i class="fas fa-copy"></i> Salin Ringkasan';
      copyBtn.addEventListener("click", function () {
        const summaryText = document.getElementById(
          "summaryModalContent"
        ).innerText;
        navigator.clipboard
          .writeText(summaryText)
          .then(() => {
            this.innerHTML = '<i class="fas fa-check"></i> Tersalin';
            setTimeout(() => {
              this.innerHTML = '<i class="fas fa-copy"></i> Salin Ringkasan';
            }, 2000);
          })
          .catch((err) => {
            console.error("Gagal menyalin teks: ", err);
            this.innerHTML = '<i class="fas fa-times"></i> Gagal Menyalin';
            setTimeout(() => {
              this.innerHTML = '<i class="fas fa-copy"></i> Salin Ringkasan';
            }, 2000);
          });
      });
      leftButtonsContainer.appendChild(copyBtn);

      // 2. Tambahkan tombol Upload PDF hanya jika PDF belum diupload
      if (!pdfUploaded && !uploadedPdfPapers[paperId]) {
        const uploadBtn = document.createElement("button");
        uploadBtn.className =
          "btn btn-outline-primary pdf-action-btn pdf-upload-btn";
        uploadBtn.innerHTML = '<i class="fas fa-upload"></i> Upload PDF';
        uploadBtn.setAttribute("data-paper-id", paperId);
        uploadBtn.setAttribute("data-paper-title", paperTitle);
        uploadBtn.addEventListener("click", () =>
          handlePdfUpload(paperId, paperTitle)
        );
        leftButtonsContainer.appendChild(uploadBtn);
      } else if (isUserLoggedIn() && pdfUploaded) {
        // Tambahkan tombol Reset PDF jika pengguna login dan PDF sudah diupload
        const resetBtn = document.createElement("button");
        resetBtn.className = "btn btn-outline-danger reset-pdf-btn";
        resetBtn.innerHTML = '<i class="fas fa-undo-alt"></i> Reset PDF';
        resetBtn.setAttribute("data-paper-id", paperId);
        resetBtn.setAttribute("data-paper-title", paperTitle);
        resetBtn.addEventListener("click", () =>
          confirmResetPdf(paperId, paperTitle)
        );
        leftButtonsContainer.appendChild(resetBtn);
      }

      // 3. Tambahkan tombol Lihat PDF jika PDF tersedia
      // Dapatkan URL PDF dari konteks paper yang sedang aktif
      let pdfUrl = null;

      // Cek apakah ada currentPaperContext dengan PDF
      if (
        currentPaperContext &&
        currentPaperContext.id === paperId &&
        currentPaperContext.pdf_url
      ) {
        pdfUrl = currentPaperContext.pdf_url;
      }

      // Cek dari indikator pada konten summary modal
      const pdfIndicator = document.querySelector(".pdf-source-indicator");
      let hasPdfUrl = false;

      if (pdfIndicator) {
        // Ekstrak URL dari text jika ada
        const pdfUrlMatch = pdfIndicator.innerHTML.match(
          /(https?:\/\/[^\s"']+\.pdf)/i
        );
        if (pdfUrlMatch) {
          pdfUrl = pdfUrlMatch[1];
          hasPdfUrl = true;
        }

        // Juga cek hidden span jika ada
        const hiddenUrlSpan = pdfIndicator.querySelector("span.d-none");
        if (hiddenUrlSpan && hiddenUrlSpan.textContent.includes("PDF URL:")) {
          pdfUrl = hiddenUrlSpan.textContent.replace("PDF URL:", "").trim();
          hasPdfUrl = true;
        }
      }

      // Jika PDF tersedia (baik dari upload atau ekstraksi otomatis)
      if (pdfUrl && !pdfUrl.startsWith("local://")) {
        const viewBtn = document.createElement("button");
        viewBtn.className = "btn btn-outline-success view-pdf-btn";
        viewBtn.innerHTML =
          '<i class="fas fa-external-link-alt"></i> Lihat PDF';
        viewBtn.addEventListener("click", function () {
          window.open(pdfUrl, "_blank");
        });
        leftButtonsContainer.appendChild(viewBtn);
      }

      // Tombol tutup di pojok kanan
      const closeBtn = document.createElement("button");
      closeBtn.type = "button";
      closeBtn.className = "btn btn-secondary ms-auto";
      closeBtn.setAttribute("data-bs-dismiss", "modal");
      closeBtn.textContent = "Tutup";

      // Tambahkan kedua container ke modal footer
      modalFooter.appendChild(leftButtonsContainer);
      modalFooter.appendChild(closeBtn);
    }
  }

  function updateChatSessionInSidebar(sessionId, latestQuestion) {
    const historyItem = document.querySelector(
      `.history-item[data-session-id="${sessionId}"]`
    );

    if (historyItem) {
      // Update pertanyaan terakhir dan timestamp
      const questionElement = historyItem.querySelector(
        ".history-item-question"
      );
      const dateElement = historyItem.querySelector(".history-item-date");

      if (questionElement) {
        const shortQuestion =
          latestQuestion.length > 40
            ? latestQuestion.substring(0, 40) + "..."
            : latestQuestion;
        questionElement.textContent = shortQuestion;
      }

      if (dateElement) {
        const now = new Date();
        const formattedDate = `${now.toLocaleDateString("id-ID", {
          day: "numeric",
          month: "short",
        })}`;
        dateElement.textContent = formattedDate;
      }

      // Move to top of list
      const historyList = document.querySelector(".chat-history-list");
      if (historyList && historyItem.parentNode === historyList) {
        historyList.removeChild(historyItem);
        historyList.insertBefore(historyItem, historyList.firstChild);
      }

      console.log("✅ Updated existing session in sidebar:", sessionId);
    }
  }
});
