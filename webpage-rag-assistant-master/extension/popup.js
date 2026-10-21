const processPageButton =
    document.getElementById("process-page-btn");

const askButton =
    document.getElementById("ask-btn");

const questionInput =
    document.getElementById("question-input");

const answerDiv =
    document.getElementById("answer");

const statusText =
    document.getElementById("status");


const API_BASE_URL =
    "http://127.0.0.1:8001";

async function getApiBaseUrl() {
    const settings =
        await chrome.storage.local.get({
            apiUrl: API_BASE_URL
        });

    let url;

    try {
        url = new URL(settings.apiUrl);
    } catch {
        throw new Error("The configured backend URL is invalid.");
    }

    if (
        !["http:", "https:"].includes(url.protocol) ||
        url.username ||
        url.password ||
        (url.pathname !== "/" && url.pathname !== "") ||
        url.search ||
        url.hash
    ) {
        throw new Error(
            "The backend URL must be an HTTP or HTTPS origin without a path."
        );
    }

    return url.origin;
}

async function ensureBackendPermission(apiBaseUrl) {
    if (!chrome.permissions?.contains) {
        return;
    }

    let allowed;

    try {
        const backendUrl = new URL(apiBaseUrl);
        allowed = await chrome.permissions.contains({
            origins: [
                `${backendUrl.protocol}//${backendUrl.hostname}/*`
            ]
        });
    } catch (error) {
        throw new Error(
            `Chrome could not check permission for ${apiBaseUrl}. Reload the extension at chrome://extensions. ${error.message}`
        );
    }

    if (!allowed) {
        throw new Error(
            `Chrome has not granted this extension access to ${apiBaseUrl}. Open the extension's Options, save this backend URL to grant access, then reload the extension at chrome://extensions.`
        );
    }
}

async function requestBackend(apiBaseUrl, path, body) {
    await ensureBackendPermission(apiBaseUrl);

    try {
        const result = await chrome.runtime.sendMessage({
            type: "webpage-rag-api-request",
            url: apiBaseUrl,
            path,
            body
        });

        if (result?.error) {
            throw new Error(result.error);
        }

        if (!result || typeof result.ok !== "boolean") {
            throw new Error(
                "The extension background service did not return a valid response. Reload the extension at chrome://extensions."
            );
        }

        if (!result.ok) {
            throw new Error(
                result.data?.detail ||
                `Backend request failed (HTTP ${result.status}).`
            );
        }

        return result.data;
    } catch (error) {
        if (error instanceof Error) {
            throw error;
        }

        throw new Error(
            `The extension could not contact its background service. Reload it at chrome://extensions. ${String(error)}`
        );
    }
}

async function getCurrentTab() {
    const queries = [
        { active: true, lastFocusedWindow: true },
        { active: true, currentWindow: true },
    ];

    for (const query of queries) {
        let tabs;

        try {
            tabs = await chrome.tabs.query(query);
        } catch (error) {
            throw new Error(
                `Chrome could not inspect the active tab. Reload the extension at chrome://extensions and ensure its tabs permission is enabled. ${error.message}`
            );
        }

        const tab = tabs?.find(
            (candidate) =>
                candidate.id !== undefined &&
                typeof candidate.url === "string" &&
                candidate.url.length > 0
        );

        if (tab) {
            return tab;
        }
    }

    throw new Error(
        "Chrome did not expose the active tab URL. Reload the extension at chrome://extensions, verify the tabs permission, then open a normal HTTP or HTTPS webpage and try again. Chrome-internal pages cannot be read."
    );
}

async function getRenderedPage(tabId) {
    if (!chrome.scripting?.executeScript) {
        throw new Error(
            "Page-reading permission is unavailable. Reload the extension at chrome://extensions and make sure its scripting permission is enabled."
        );
    }

    try {
        const results = await chrome.scripting.executeScript({
            target: { tabId },
            func: () => ({
                url: window.location.href,
                title: document.title,
                content: document.body?.innerText?.trim().slice(0, 500_000) || ""
            })
        });

        return results?.[0]?.result;
    } catch (error) {
        throw new Error(
            `Chrome could not read this page. Open a regular HTTP or HTTPS webpage, click the extension to grant access, and try again. Browser-internal and restricted pages cannot be read. ${error.message}`
        );
    }
}


async function processCurrentPage() {

    try {

        statusText.textContent =
            "Processing webpage...";

        answerDiv.textContent =
            "Please wait...";

        const tab =
            await getCurrentTab();
        const url = tab.url;

        if (!url) {
            throw new Error(
                "Could not get current webpage URL."
            );
        }

        let pageUrl;
        try {
            pageUrl = new URL(url);
        } catch {
            throw new Error("Chrome did not provide a valid webpage URL.");
        }

        if (
            !["http:", "https:"].includes(pageUrl.protocol) ||
            !pageUrl.hostname ||
            pageUrl.username ||
            pageUrl.password
        ) {
            throw new Error(
                "Only HTTP and HTTPS webpages can be processed."
            );
        }

        const apiBaseUrl =
            await getApiBaseUrl();

        const page = await getRenderedPage(tab.id);
        if (page?.url !== url) {
            throw new Error(
                "The active tab changed while the page was being read. Try processing it again."
            );
        }

        const content = page?.content?.trim();

        const data = await requestBackend(
            apiBaseUrl,
            "/process-page",
            {
                url: pageUrl.href,
                title: page.title || "",
                content: content || null
            }
        );

        statusText.textContent =
            "Page processed successfully.";

        answerDiv.textContent =
            `Processed ${data.chunks} chunks. You can now ask questions.`;

    } catch (error) {

        console.error(error);

        statusText.textContent =
            "Processing failed.";

        answerDiv.textContent =
            error.message;
    }
}


async function askQuestion() {

    try {

        const question =
            questionInput.value.trim();

        if (!question) {

            answerDiv.textContent =
                "Please enter a question.";

            return;
        }

        statusText.textContent =
            "Generating answer...";

        answerDiv.textContent =
            "Thinking...";

        const tab = await getCurrentTab();
        let pageUrl;
        try {
            pageUrl = new URL(tab.url);
        } catch {
            throw new Error("Chrome did not provide a valid webpage URL.");
        }

        if (
            !["http:", "https:"].includes(pageUrl.protocol) ||
            !pageUrl.hostname ||
            pageUrl.username ||
            pageUrl.password
        ) {
            throw new Error(
                "Only HTTP and HTTPS webpages can be used for questions."
            );
        }

        const apiBaseUrl =
            await getApiBaseUrl();

        const data = await requestBackend(
            apiBaseUrl,
            "/chat",
            { question, url: pageUrl.href }
        );

        statusText.textContent =
            "Answer generated.";

        answerDiv.textContent =
            data.answer;

    } catch (error) {

        console.error(error);

        statusText.textContent =
            "Question failed.";

        answerDiv.textContent =
            error.message;
    }
}


processPageButton.addEventListener(
    "click",
    processCurrentPage
);


askButton.addEventListener(
    "click",
    askQuestion
);