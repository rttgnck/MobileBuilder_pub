/**
 * Simple PWA Install Manager
 * Based on working KidsTales implementation
 */

let deferredPrompt = null;
let showPwaInstall = false;
let showAppleInstall = false;

// --- START LISTENING IMMEDIATELY ---
// This is the most important change. Listen for the event as soon as the script runs.
window.addEventListener('beforeinstallprompt', (e) => {
    console.log('[PWA] beforeinstallprompt event fired and caught!');
    
    // Prevent the default mini-infobar
    e.preventDefault();
    
    // Stash the event so it can be triggered later.
    deferredPrompt = e;
    
    // Set the flag that we can show the PWA install prompt
    showPwaInstall = true;
    
    // Now, you can decide WHEN to show your custom UI. 
    // You can still use a timeout here if you want a delay.
    setTimeout(() => {
        // Only show if it hasn't been dismissed recently and we are on the home page
        if (!wasRecentlyDismissed() && window.location.pathname === '/') {
            showInstallPrompt();
        }
    }, 3000); // Delay showing the banner for 3 seconds
});

// Initialize PWA install functionality
function initPWAInstall() {
    console.log('[PWA] Initializing PWA install...');
    
    // Debug PWA installability criteria
    debugPWAInstallability();
    
    // Check if already running as PWA
    if (isRunningAsPWA()) {
        console.log('[PWA] Already running as PWA');
        return;
    }

    // showPwaInstall = true;
    // showInstallPrompt();

    // console.log('[PWA] Listening for beforeinstallprompt event');
    // // Listen for beforeinstallprompt event
    // window.addEventListener('beforeinstallprompt', (e) => {
    //     console.log('[PWA] beforeinstallprompt event fired');
    //     e.preventDefault();
    //     deferredPrompt = e;
    //     showPwaInstall = true;
    //     showInstallPrompt();
    // });
    
    console.log('[PWA] Listening for appinstalled event');
    // Listen for appinstalled event
    window.addEventListener('appinstalled', (e) => {
        console.log('[PWA] App was installed');
        hideInstallPrompt();
        showPwaInstall = false;
        deferredPrompt = null;
    });
    
    console.log('[PWA] Checking for iOS Safari');
    // Check for iOS Safari
    if (isIOSSafari() && !isRunningAsPWA()) {
        console.log('[PWA] iOS Safari detected, showing Apple install');
        showAppleInstall = true;
        showInstallPrompt();
    }
    
    // console.log('[PWA] Checking for deferredPrompt');
    // // For debugging - force show install prompt on desktop Chrome after delay
    // if (!isRunningAsPWA() && !deferredPrompt) {
    //     setTimeout(() => {
    //         if (!deferredPrompt && !showPwaInstall && !showAppleInstall) {
    //             console.log('[PWA] No beforeinstallprompt event after 5s, checking if we should show manual prompt');
                
    //             // showPwaInstall = true;
    //             // showInstallPrompt();
    //             // If Chrome/Edge and not mobile, show install prompt anyway for testing
    //             if (isChrome() && !isMobile()) {
    //                 console.log('[PWA] Desktop Chrome detected, showing install prompt for testing');
    //                 showPwaInstall = true;
    //                 showInstallPrompt();
    //             }
    //         }
    //     }, 5000);
    // }
}

// Show install prompt based on platform
function showInstallPrompt() {
    if (document.getElementById('pwa-install-container')) {
        return; // Already showing
    }
    
    let promptHTML = '';
    
    if (showPwaInstall) {
        promptHTML = `
            <div id="pwa-install-container" class="install-app-container">
                <p class="install-app-instructions">
                    Install MobileBuilder to your device for a better experience!
                </p>
                <button class="install-app-btn" onclick="triggerInstall()">
                    Install App
                </button>
                <div class="install-dismiss-btn" onclick="dismissInstall()">
                    ×
                </div>
            </div>
        `;
    } else if (showAppleInstall) {
        promptHTML = `
            <div id="pwa-install-container" class="install-app-container">
                <p class="install-app-instructions">
                    Install MobileBuilder to your device for a better experience! Tap the "share" icon, and then tap on "Add to home screen".
                </p>
                <div class="install-dismiss-btn" onclick="dismissInstall()">
                    ×
                </div>
            </div>
        `;
    }
    
    if (promptHTML) {
        document.body.insertAdjacentHTML('beforeend', promptHTML);
        
        // Add styles if not present
        if (!document.getElementById('pwa-install-styles')) {
            addInstallStyles();
        }
        
        // Animate in
        setTimeout(() => {
            const container = document.getElementById('pwa-install-container');
            if (container) {
                container.classList.add('show');
            }
        }, 100);
    }
}

// Trigger the install prompt
async function triggerInstall() {
    if (!deferredPrompt) {
        console.log('[PWA] No deferred prompt available');
        return;
    }
    
    try {
        // Show the browser's install prompt
        deferredPrompt.prompt();
        
        // Wait for the user to respond to the prompt
        const { outcome } = await deferredPrompt.userChoice;
        console.log(`[PWA] User ${outcome} the install prompt`);
        
        if (outcome === 'accepted') {
            console.log('[PWA] User accepted the install prompt');
        }
        
        // The deferredPrompt can only be used once
        deferredPrompt = null;
        hideInstallPrompt();
        
    } catch (error) {
        console.error('[PWA] Install prompt failed:', error);
    }
}

// Dismiss the install prompt
function dismissInstall() {
    console.log('[PWA] Install prompt dismissed');
    hideInstallPrompt();
    
    // Remember dismissal for a while
    localStorage.setItem('pwa-install-dismissed', Date.now().toString());
}

// Hide install prompt
function hideInstallPrompt() {
    const container = document.getElementById('pwa-install-container');
    if (container) {
        container.classList.add('hide');
        setTimeout(() => {
            container.remove();
        }, 300);
    }
    showPwaInstall = false;
    showAppleInstall = false;
}

// Check if running as PWA
function isRunningAsPWA() {
    return window.matchMedia('(display-mode: standalone)').matches ||
           window.navigator.standalone === true;
}

// Check if iOS Safari
function isIOSSafari() {
    const userAgent = window.navigator.userAgent;
    const isIOS = /iPad|iPhone|iPod/.test(userAgent);
    const isSafari = /Safari/.test(userAgent) && !/Chrome|CriOS|FxiOS/.test(userAgent);
    return isIOS && isSafari;
}

// Check if Chrome/Chromium browser
function isChrome() {
    const userAgent = window.navigator.userAgent;
    return /Chrome|Chromium/.test(userAgent) && !/Edge/.test(userAgent);
}

// Check if mobile device
function isMobile() {
    return /Android|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini|Mobile|mobile|CriOS/i.test(navigator.userAgent) ||
           ('ontouchstart' in window) ||
           (navigator.maxTouchPoints > 0) ||
           (navigator.msMaxTouchPoints > 0) ||
           (window.innerWidth <= 768);
}

// Debug PWA installability criteria
function debugPWAInstallability() {
    console.log('=== PWA Installability Debug ===');
    console.log('Service Worker supported:', 'serviceWorker' in navigator);
    console.log('Running as PWA:', isRunningAsPWA());
    console.log('HTTPS or localhost:', location.protocol === 'https:' || location.hostname === 'localhost');
    console.log('Manifest link present:', !!document.querySelector('link[rel="manifest"]'));
    console.log('Is Chrome:', isChrome());
    console.log('Is Mobile:', isMobile());
    console.log('Is iOS Safari:', isIOSSafari());
    console.log('User Agent:', navigator.userAgent);
    
    // Check service worker registration
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.getRegistration().then(registration => {
            console.log('Service Worker registered:', !!registration);
            if (registration) {
                console.log('SW scope:', registration.scope);
                console.log('SW state:', registration.active?.state);
            }
        });
    }
    
    // Check manifest
    fetch('/static/manifest.json').then(response => {
        console.log('Manifest accessible:', response.ok);
        return response.json();
    }).then(manifest => {
        console.log('Manifest name:', manifest.name);
        console.log('Manifest start_url:', manifest.start_url);
        console.log('Manifest display:', manifest.display);
        console.log('Manifest icons count:', manifest.icons?.length);
    }).catch(e => {
        console.error('Manifest error:', e);
    });
    
    console.log('=== End PWA Debug ===');
}

// Add install prompt styles
function addInstallStyles() {
    const styles = document.createElement('style');
    styles.id = 'pwa-install-styles';
    styles.textContent = `
        .install-app-container {
            position: fixed;
            bottom: 30px;
            left: 50%;
            transform: translateX(-50%) translateY(100px);
            background: rgba(25, 25, 25, 0.85);
            backdrop-filter: blur(24px) saturate(150%);
            -webkit-backdrop-filter: blur(24px) saturate(150%);
            color: #f9fafb;
            padding: 24px 28px;
            z-index: 10000;
            transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            border: 1px solid rgba(156, 163, 175, 0.3);
            border-radius: 20px;
            box-shadow: 
                0 24px 48px rgba(0, 0, 0, 0.6),
                inset 0 0 0 1px rgba(99, 102, 241, 0.08);
            max-width: 320px;
            width: calc(100vw - 60px);
            opacity: 0;
            visibility: hidden;
            animation: float 3s ease-in-out infinite;
        }
        
        @keyframes float {
            0%, 100% { transform: translateX(-50%) translateY(0px); }
            50% { transform: translateX(-50%) translateY(-5px); }
        }
        
        .install-app-container.show {
            transform: translateX(-50%) translateY(0);
            opacity: 1;
            visibility: visible;
        }
        
        .install-app-container.hide {
            transform: translateX(-50%) translateY(100px);
            opacity: 0;
            visibility: hidden;
        }
        
        .install-app-instructions {
            margin: 0 0 20px 0;
            font-size: 0.95rem;
            line-height: 1.5;
            color: #d1d5db;
            text-align: center;
            padding-right: 0;
            font-weight: 400;
        }
        
        .install-app-btn {
            background: linear-gradient(135deg, #6366f1, #f59e0b);
            color: #1a1a2e;
            border: none;
            padding: 14px 28px;
            border-radius: 50px;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            display: block;
            margin: 0 auto;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: 
                0 8px 24px rgba(99, 102, 241, 0.3),
                0 4px 12px rgba(245, 158, 11, 0.2);
            position: relative;
            overflow: hidden;
            min-width: 140px;
        }
        
        .install-app-btn::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.2), transparent);
            transition: left 0.5s;
        }
        
        .install-app-btn:hover::before {
            left: 100%;
        }
        
        .install-app-btn:hover {
            transform: translateY(-3px) scale(1.02);
            box-shadow: 
                0 12px 32px rgba(99, 102, 241, 0.4),
                0 6px 16px rgba(245, 158, 11, 0.3);
        }
        
        .install-app-btn:active {
            transform: translateY(-1px) scale(1.01);
        }
        
        .install-dismiss-btn {
            position: absolute;
            top: 12px;
            right: 12px;
            background: rgba(156, 163, 175, 0.15);
            border: 1px solid rgba(156, 163, 175, 0.2);
            color: #9ca3af;
            font-size: 18px;
            cursor: pointer;
            width: 28px;
            height: 28px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            line-height: 1;
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
        }
        
        .install-dismiss-btn:hover {
            background: rgba(239, 68, 68, 0.15);
            border-color: rgba(239, 68, 68, 0.3);
            color: #ef4444;
            transform: scale(1.1);
        }
        
        .install-dismiss-btn:active {
            transform: scale(0.95);
        }
        
        @media (max-width: 768px) {
            .install-app-container {
                bottom: 20px;
                padding: 20px 24px;
                max-width: 300px;
                width: calc(100vw - 40px);
            }
            
            .install-app-instructions {
                font-size: 0.9rem;
                margin-bottom: 18px;
            }
            
            .install-app-btn {
                padding: 12px 24px;
                font-size: 0.9rem;
                min-width: 120px;
            }
            
            .install-dismiss-btn {
                width: 26px;
                height: 26px;
                font-size: 16px;
                top: 10px;
                right: 10px;
            }
        }
        
        @media (max-width: 480px) {
            .install-app-container {
                bottom: 15px;
                padding: 18px 20px;
                width: calc(100vw - 30px);
            }
            
            .install-app-instructions {
                font-size: 0.85rem;
                margin-bottom: 16px;
            }
            
            .install-app-btn {
                padding: 11px 20px;
                font-size: 0.85rem;
            }
        }
        
        /* Only show in browser mode */
        @media (display-mode: standalone) {
            .install-app-container {
                display: none !important;
            }
        }
        
        /* Ensure it appears above other elements */
        .install-app-container {
            z-index: 999999;
        }
    `;
    document.head.appendChild(styles);
}

// Check if install was recently dismissed
function wasRecentlyDismissed() {
    const dismissed = localStorage.getItem('pwa-install-dismissed');
    if (!dismissed) return false;
    
    const dismissTime = parseInt(dismissed);
    const now = Date.now();
    const daysSince = (now - dismissTime) / (1000 * 60 * 60 * 24);
    
    return daysSince < 7; // Don't show for 7 days after dismissal
}

// // Initialize when DOM is loaded
// document.addEventListener('DOMContentLoaded', () => {
//     // Wait a bit before showing install prompt
//     setTimeout(() => {
//         if (!wasRecentlyDismissed() && window.location.pathname === '/') {
//             initPWAInstall();
//         }
//     }, 3000); // Wait 3 seconds after page load
// });
document.addEventListener('DOMContentLoaded', initPWAInstall);

// // Make functions available globally
// window.triggerInstall = triggerInstall;
// window.dismissInstall = dismissInstall;

// Manual trigger for testing (call from console)
window.testPWAInstall = function() {
    console.log('[PWA] Manual test trigger');
    showPwaInstall = true;
    showInstallPrompt();
};

// // Debug function for console
// window.debugPWA = debugPWAInstallability;