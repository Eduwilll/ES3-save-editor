const apiUrl = "http://127.0.0.1:8000";
const searchForm = document.querySelector("#search-form");
const passwordForm = document.querySelector("#password-form");
const status = document.querySelector("#status");
const games = document.querySelector("#games");
const resultCount = document.querySelector("#result-count");
const passwordHistory = document.querySelector("#password-history");
const historyStatus = document.querySelector("#history-status");
const togglePassword = document.querySelector("#toggle-password");

function selectGame(game) {
    document.querySelector("#game-id").value = String(game.id);
    document.querySelectorAll(".game-result").forEach((item) => {
        item.classList.toggle("is-selected", item.dataset.gameId === String(game.id));
    });
    loadPasswordHistory(game.id);
}

async function loadPasswordHistory(gameId) {
    historyStatus.textContent = "Loading...";
    passwordHistory.replaceChildren();

    try {
        const response = await fetch(`${apiUrl}/games/${gameId}/password`);
        if (response.status === 404) {
            historyStatus.textContent = "No saved passwords";
            passwordHistory.innerHTML = '<p class="history-empty">No passwords saved for this game.</p>';
            return;
        }
        if (!response.ok) throw new Error("Could not load history.");
        const entries = await response.json();
        historyStatus.textContent = `${entries.length} saved`;
        entries.slice().reverse().forEach((entry, index) => {
            const item = document.createElement("div");
            item.className = "history-item";
            item.innerHTML = `<span>Saved password ${entries.length - index}</span><button type="button" class="use-password">Use</button>`;
            item.querySelector(".use-password").addEventListener("click", () => {
                document.querySelector("#password").value = entry.password;
                document.querySelector("#password").type = "text";
                togglePassword.textContent = "Hide";
            });
            passwordHistory.append(item);
        });
    } catch (error) {
        historyStatus.textContent = "Unavailable";
        passwordHistory.innerHTML = '<p class="history-empty">Could not load saved history.</p>';
    }
}

searchForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const search = new FormData(searchForm).get("search");
    status.textContent = "Searching...";
    resultCount.textContent = "";
    games.innerHTML = '<div class="loading-state">Looking through the catalog...</div>';

    try {
        const response = await fetch(`${apiUrl}/games?search=${encodeURIComponent(String(search))}`);
        if (!response.ok) throw new Error("Search failed");
        const data = await response.json();
        games.replaceChildren(...data.games.map((game) => {
            const item = document.createElement("button");
            item.type = "button";
            item.className = "game-result";
            item.dataset.gameId = String(game.id);
            const title = game.steam_info?.name ?? "Unknown game";
            const image = game.steam_info?.tiny_image;
            const thumbnail = document.createElement("span");
            thumbnail.className = "game-thumb";
            if (image) {
                const imageElement = document.createElement("img");
                imageElement.src = image;
                imageElement.alt = "";
                thumbnail.append(imageElement);
            } else {
                thumbnail.textContent = "ES3";
            }
            const copy = document.createElement("span");
            copy.className = "game-result-copy";
            const titleElement = document.createElement("strong");
            titleElement.textContent = title;
            const idElement = document.createElement("small");
            idElement.textContent = `Steam ID ${game.id}`;
            copy.append(titleElement, idElement);
            const arrow = document.createElement("span");
            arrow.className = "game-arrow";
            arrow.setAttribute("aria-hidden", "true");
            arrow.textContent = "\u2192";
            item.append(thumbnail, copy, arrow);
            item.addEventListener("click", () => selectGame(game));

            return item;
        }));

        status.textContent = data.games.length ? "Select a game to continue." : "No games found.";
        resultCount.textContent = `${data.total} result${data.total === 1 ? "" : "s"}`;
    } catch (error) {
        status.textContent = error instanceof Error ? error.message : "Search failed";
        games.innerHTML = '<div class="empty-state error-state"><span class="empty-icon">!</span><p>Search failed. Check that the API is running and try again.</p></div>';
    }
});

passwordForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(passwordForm);
    const gameId = form.get("game-id");
    try {
        const response = await fetch(`${apiUrl}/games/${gameId}/password`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ password: form.get("password") }),
        });
        if (!response.ok) throw new Error("Could not save password.");
        status.textContent = "Password saved successfully.";
        await loadPasswordHistory(gameId);
    } catch (error) {
        status.textContent = error instanceof Error ? error.message : "Could not save password.";
    }
});

togglePassword.addEventListener("click", () => {
    const password = document.querySelector("#password");
    const isHidden = password.type === "password";
    password.type = isHidden ? "text" : "password";
    togglePassword.textContent = isHidden ? "Hide" : "Show";
    togglePassword.setAttribute("aria-label", isHidden ? "Hide password" : "Show password");
});
