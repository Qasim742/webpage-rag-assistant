const DEFAULT_API_URL = "http://127.0.0.1:8001";

const apiUrlInput = document.getElementById("api-url");
const saveButton = document.getElementById("save-btn");
const status = document.getElementById("status");

chrome.storage.local.get(
    { apiUrl: DEFAULT_API_URL },
    (settings) => {
        apiUrlInput.value = settings.apiUrl;
    }
);

saveButton.addEventListener("click", () => {
    let apiUrl;

    try {
        apiUrl = new URL(apiUrlInput.value.trim());
    } catch {
        status.textContent = "Enter a valid backend URL.";
        return;
    }

    if (
        !["http:", "https:"].includes(apiUrl.protocol) ||
        apiUrl.username ||
        apiUrl.password ||
        (apiUrl.pathname !== "/" && apiUrl.pathname !== "") ||
        apiUrl.search ||
        apiUrl.hash
    ) {
        status.textContent =
            "Use an HTTP or HTTPS backend origin without a path.";
        return;
    }

    const originPattern =
        `${apiUrl.protocol}//${apiUrl.hostname}/*`;

    chrome.permissions.request(
        { origins: [originPattern] },
        (granted) => {
            if (!granted) {
                status.textContent =
                    "Permission for this backend origin was not granted.";
                return;
            }

            chrome.storage.local.set(
                { apiUrl: apiUrl.origin },
                () => {
                    status.textContent = chrome.runtime.lastError
                        ? "Could not save the backend URL."
                        : "Backend URL saved.";
                }
            );
        }
    );
});
