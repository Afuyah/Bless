// Check if the browser supports service workers
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/static/service-worker.js') // Adjust the path as needed
            .then((registration) => {
                console.log('Service Worker registered with scope:', registration.scope);

                // Listen for updates to the Service Worker
                registration.onupdatefound = () => {
                    const installingWorker = registration.installing;

                    installingWorker.onstatechange = () => {
                        if (installingWorker.state === 'installed') {
                            if (navigator.serviceWorker.controller) {
                                // New content is available; ask user to refresh
                                console.log('New content is available; please refresh.');
                                // Optionally, you can prompt the user to refresh the page
                                // if confirm('New version available. Refresh?')) {
                                //     window.location.reload();
                                // }
                            } else {
                                console.log('Content is cached for offline use.');
                            }
                        }
                    };
                };
            })
            .catch((error) => {
                console.error('Service Worker registration failed:', error);
            });
    });
}

// Optional: Allow the user to manually refresh and get new content
function updateServiceWorker() {
    if (navigator.serviceWorker) {
        navigator.serviceWorker.getRegistration().then((registration) => {
            if (registration && registration.waiting) {
                registration.waiting.postMessage({ action: 'SKIP_WAITING' });
            }
        });
    }
}

// Example function to trigger an update
document.getElementById('update-button').addEventListener('click', updateServiceWorker);
