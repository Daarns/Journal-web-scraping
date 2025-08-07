document.addEventListener("DOMContentLoaded", function () {
  // Token handling
  const getToken = () => localStorage.getItem("token");

  // Elements
  const citationModal = document.getElementById("citationModal");
  const citationResult = document.querySelector(".citation-result");
  const citationText = document.querySelector(".citation-text");
  const citationLoading = document.querySelector(".citation-loading");
  const copyCitationBtn = document.querySelector(".copy-citation-btn");

  // Untuk menyimpan data paper saat ini
  let currentPaper = null;

  // Fungsi untuk mendapatkan cookie CSRF
  function getCsrfToken() {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; csrf_token=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return null;
  }

  // Fungsi untuk memastikan kita memiliki CSRF token valid
  async function ensureCsrfToken() {
    let csrfToken = getCsrfToken();

    // Jika tidak ada token, fetch baru dari API
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

  // Fungsi untuk menampilkan modal sitasi
  window.showCitationModal = function (paper) {
    if (!paper || !paper.id) {
      console.error("Invalid paper data:", paper);
      return;
    }

    // Log untuk debugging
    console.log("Citation modal opened with paper:", paper);

    currentPaper = paper;

    // Set paper title di modal
    const titleEl = citationModal?.querySelector(".paper-citation-title");
    if (titleEl) titleEl.textContent = paper.title;

    // Set paper ID sebagai data attribute
    citationModal?.setAttribute("data-paper-id", paper.id);

    // Reset UI
    if (citationResult) citationResult.classList.add("d-none");
    if (citationLoading) citationLoading.classList.add("d-none");

    // Show modal
    const modal = new bootstrap.Modal(citationModal);
    modal.show();
  };

  // Event listener untuk tombol style sitasi
  document.querySelectorAll(".citation-style-btn").forEach((btn) => {
    btn.addEventListener("click", async function () {
      // Hapus class active dari semua tombol
      document.querySelectorAll(".citation-style-btn").forEach((b) => {
        b.classList.remove("active");
      });

      // Tambahkan class active ke tombol yang dipilih
      this.classList.add("active");

      const style = this.getAttribute("data-style");
      if (!style) {
        console.error("No citation style specified");
        return;
      }

      console.log(`Generating citation in ${style} style`);
      await generateCitation(currentPaper, style);
    });
  });

  function attachCitationListeners() {
    document.querySelectorAll(".citation-btn").forEach((btn) => {
      // Periksa apakah tombol sudah memiliki event listener
      if (!btn.dataset.hasListener) {
        btn.addEventListener("click", function () {
          const paperElement = this.closest(".paper-item");
          if (!paperElement) return;

          const paperId = paperElement.dataset.paperId;
          const paperTitle =
            paperElement.querySelector(".paper-title")?.textContent || "";
          const paperAuthors =
            paperElement.querySelector(".paper-authors")?.textContent || "";
          const paperYear =
            paperElement.querySelector(".paper-year")?.textContent || "";
          const paperSource =
            paperElement.querySelector(".paper-source")?.textContent || "";

          window.showCitationModal({
            id: paperId,
            title: paperTitle,
            authors: paperAuthors,
            year: paperYear,
            source: paperSource,
          });
        });

        // Tandai tombol sudah memiliki event listener
        btn.dataset.hasListener = "true";
      }
    });
  }

  // Jalankan saat halaman dimuat
  attachCitationListeners();

  // Tambahkan MutationObserver untuk mendeteksi tombol sitasi baru
  const observer = new MutationObserver(function (mutations) {
    mutations.forEach(function (mutation) {
      if (mutation.addedNodes && mutation.addedNodes.length) {
        // Cek jika ada node baru yang berisi tombol sitasi
        setTimeout(attachCitationListeners, 100); // Delay kecil untuk memastikan DOM sudah stabil
      }
    });
  });

  // Mulai observasi
  observer.observe(document.body, {childList: true, subtree: true});

  // Fungsi untuk generate sitasi
  async function generateCitation(paper, style) {
    if (!paper || !style) {
      console.error("Missing required data for citation:", {paper, style});
      return;
    }

    // Log data paper untuk membantu debugging
    console.log("Paper data for citation:", paper);

    // Show loading
    if (citationResult) citationResult.classList.add("d-none");
    if (citationLoading) citationLoading.classList.remove("d-none");

    // Dapatkan CSRF token yang valid
    const csrfToken = await ensureCsrfToken();
    console.log(
      "Using CSRF token for citation:",
      csrfToken ? "present" : "missing"
    );

    const headers = {
      "Content-Type": "application/json",
    };

    // Add auth token if user is logged in
    const token = getToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    // Add CSRF token
    if (csrfToken) {
      headers["X-CSRF-Token"] = csrfToken;
    }

    // Pastikan semua nilai valid - penting untuk mengatasi error 422
    const requestData = {
      paper_id: paper.id || "",
      paper_title: paper.title || "",
      authors: paper.authors || "",
      year: paper.year || "", // Kirim string kosong jika tidak ada nilai
      source: paper.source || "",
      style: style,
    };

    // Log data request untuk membantu debugging
    console.log("Sending citation request with payload:", requestData);
    console.log("Request headers:", headers);

    try {
      const response = await fetch("/api/activity/generate-citation", {
        method: "POST",
        headers: headers,
        body: JSON.stringify(requestData),
        credentials: "include", // Penting untuk CSRF
      });

      // Handle error status
      if (!response.ok) {
        let errorMessage = `Error ${response.status}: ${response.statusText}`;

        try {
          const errorData = await response.json();
          console.error("Citation API error:", errorData);
          errorMessage = errorData.detail || errorMessage;
        } catch (parseError) {
          const errorText = await response.text();
          console.error("Citation API error (raw):", errorText);
          errorMessage = errorText || errorMessage;
        }

        throw new Error(errorMessage);
      }

      const data = await response.json();
      console.log("Citation generated successfully:", data);

      // Format citation text with italics for journal name based on citation style
      if (citationText) {
        let formattedCitation = data.citation_text;

        try {
          // Apply italics to journal name based on citation style
          // Existing code unchanged...
          if (style === "APA") {
            formattedCitation = formattedCitation.replace(
              /(\(\d{4}\)\.\s*)([^\.]+)(\.\s*$)/,
              "$1<em>$2</em>$3"
            );
          } else if (style === "MLA") {
            formattedCitation = formattedCitation.replace(
              /(".*?"\.\s*)([^,\.]+)(,\s*\d{4}\.)/,
              "$1<em>$2</em>$3"
            );
          } else if (style === "Chicago") {
            formattedCitation = formattedCitation.replace(
              /(".*?"\.\s*)([^\.]+)(\.$)/,
              "$1<em>$2</em>$3"
            );
          } else if (style === "Harvard") {
            const yearValue = paper.year || "";
            formattedCitation = formattedCitation.replace(
              new RegExp(`(${yearValue}\\.\\s*)([^\\.]+)(\\.)$`),
              "$1<em>$2</em>$3"
            );
          } else if (style === "Vancouver") {
            const parts = formattedCitation.split(".");
            if (parts.length >= 3) {
              const journalPart = parts[parts.length - 3].trim();
              formattedCitation = formattedCitation.replace(
                new RegExp(
                  `${journalPart.replace(/[-\/\\^$*+?.()|[\]{}]/g, "\\$&")}`,
                  "g"
                ),
                `<em>${journalPart}</em>`
              );
            }
          } else if (style === "IEEE") {
            formattedCitation = formattedCitation.replace(
              /(".*?",\s*)([^,]+)(,\s*\d{4}\.)/,
              "$1<em>$2</em>$3"
            );
          }
        } catch (formatError) {
          console.error("Error applying italics formatting:", formatError);
        }

        formattedCitation = formattedCitation.replace(
          /<em>/g,
          '<em style="font-style: italic;">'
        );

        citationText.innerHTML = formattedCitation;
      }

      if (citationResult) citationResult.classList.remove("d-none");

      // Record activity if we have window.recordActivity function
      if (window.recordActivity && paper.id) {
        window.recordActivity(paper.id, "citation", {
          title: paper.title,
          style: style,
        });
      }
    } catch (error) {
      console.error("Error generating citation:", error);
      if (citationText) {
        citationText.innerHTML = `
        <div class="alert alert-danger">
          Terjadi kesalahan saat menghasilkan sitasi: ${error.message}
        </div>
      `;
      }
      if (citationResult) citationResult.classList.remove("d-none");
    } finally {
      if (citationLoading) citationLoading.classList.add("d-none");
    }
  }

  // Event listener untuk copy citation button
  if (copyCitationBtn) {
    copyCitationBtn.addEventListener("click", function () {
      // Ambil teks dari elemen, hilangkan formatting HTML
      const htmlContent = citationText?.innerHTML || "";
      const tempDiv = document.createElement("div");
      tempDiv.innerHTML = htmlContent;

      // Ambil teks asli
      const plainText = tempDiv.textContent || "";

      // Tambahkan indikator italic dengan _ untuk jurnal
      // Ini membantu pengguna mengidentifikasi bagian yang seharusnya italic
      let textToShow = plainText;

      // Deteksi teks yang di-italic dan tambahkan penanda
      const italicPattern = /<em style="font-style: italic;">(.*?)<\/em>/g;
      const matches = [...htmlContent.matchAll(italicPattern)];
      if (matches.length > 0) {
        // Buat versi dengan indikator untuk ditampilkan sebagai feedback
        textToShow = plainText;
        matches.forEach((match) => {
          const italicText = match[1];
          // Tidak mengubah teks yang disalin, hanya untuk feedback visual
          textToShow = textToShow.replace(italicText, `_${italicText}_`);
        });
      }

      if (!plainText) {
        console.error("No citation text to copy");
        return;
      }

      // Salin teks asli (tanpa penanda)
      navigator.clipboard
        .writeText(plainText)
        .then(() => {
          // Success feedback dengan indikasi format
          this.innerHTML = '<i class="fas fa-check"></i> Tersalin';

          // Tampilkan tooltip dengan teks yang disalin untuk konfirmasi
          const tooltip = document.createElement("div");
          tooltip.className = "copy-tooltip";
          tooltip.innerHTML = `<div class="copy-tooltip-content">Tersalin: ${textToShow}</div>`;
          tooltip.style.cssText =
            "position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%); background: #333; color: white; padding: 5px 10px; border-radius: 4px; font-size: 12px; margin-bottom: 5px; white-space: nowrap; z-index: 1000;";
          this.style.position = "relative";
          this.appendChild(tooltip);

          setTimeout(() => {
            this.innerHTML = '<i class="fas fa-copy"></i> Salin';
            if (tooltip.parentNode === this) {
              this.removeChild(tooltip);
            }
          }, 2000);
        })
        .catch((err) => {
          // Error feedback
          console.error("Failed to copy:", err);
          this.innerHTML = '<i class="fas fa-times"></i> Gagal';
          setTimeout(() => {
            this.innerHTML = '<i class="fas fa-copy"></i> Salin';
          }, 2000);
        });
    });
  }
});
