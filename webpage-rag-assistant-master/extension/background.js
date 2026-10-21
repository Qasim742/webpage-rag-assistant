chrome.runtime.onInstalled.addListener(() => {

    console.log(
        "Webpage RAG Assistant installed."
    );

});


chrome.runtime.onMessage.addListener(
    (message, sender, sendResponse) => {

        if (
            sender.id !== chrome.runtime.id ||
            message?.type !== "webpage-rag-api-request"
        ) {
            return;
        }

        const allowedPaths = new Set([
            "/process-page",
            "/chat"
        ]);

        if (
            typeof message.url !== "string" ||
            !allowedPaths.has(message.path) ||
            typeof message.body !== "object" ||
            message.body === null
        ) {
            sendResponse({
                error: "Invalid request sent to the backend."
            });
            return;
        }

        let apiUrl;

        try {
            apiUrl = new URL(message.url);
        } catch {
            sendResponse({
                error: "The configured backend URL is invalid."
            });
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
            sendResponse({
                error: "The backend URL must be an HTTP or HTTPS origin."
            });
            return;
        }

        const originPattern =
            `${apiUrl.protocol}//${apiUrl.hostname}/*`;

        chrome.permissions.contains(
            { origins: [originPattern] },
            (hasPermission) => {
                if (chrome.runtime.lastError) {
                    sendResponse({
                        error: `Could not check backend host permission: ${chrome.runtime.lastError.message}`
                    });
                    return;
                }

                if (!hasPermission) {
                    sendResponse({
                        error: `The extension does not have permission to access ${apiUrl.origin}. Save this backend origin in the extension Options first.`
                    });
                    return;
                }

                fetch(`${apiUrl.origin}${message.path}`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify(message.body)
                })
                    .then(async (response) => {
                        let data;

                        try {
                            data = await response.json();
                        } catch {
                            throw new Error(
                                `Backend returned an invalid response (HTTP ${response.status}).`
                            );
                        }

                        sendResponse({
                            status: response.status,
                            ok: response.ok,
                            data
                        });
                    })
                    .catch((error) => {
                        sendResponse({
                            error: `Could not connect to ${apiUrl.origin}: ${error.message}`
                        });
                    });
            }
        );

        return true;
    }
);