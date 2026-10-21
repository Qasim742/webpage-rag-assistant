chrome.runtime.onMessage.addListener(
    (message, _sender, sendResponse) => {
        if (message?.type !== "webpage-rag-extract-content") {
            return;
        }

        sendResponse({
            url: window.location.href,
            title: document.title,
            content: document.body?.innerText?.trim().slice(0, 500_000) || ""
        });
    }
);