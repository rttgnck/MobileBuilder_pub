/**
 * Mobile Scaling Controller
 * Provides interface scaling functionality for mobile devices
 */

class MobileScalingController {
    constructor() {
        this.scaleLevels = {
            xxs: { factor: 0.5, label: 'XXS' },
            xs: { factor: 0.6, label: 'XS' },
            sm: { factor: 0.7, label: 'SM' },
            md: { factor: 0.8, label: 'MD' },
            lg: { factor: 0.9, label: 'LG' },
            xl: { factor: 1.0, label: 'XL' }
        };
        
        this.usePageZoom = false; // Toggle between transform scaling and page zoom
        
        this.currentScale = 'sm'; // Default to small scale for mobile
        this.isControlsVisible = false;
        this.isMobile = this.detectMobile();
        this.isPWA = this.detectPWAMode();
        
        this.init();
    }
    
    /**
     * Initialize the scaling controller
     */
    init() {
        if (!this.isMobile || !this.isPWA) {
            return; // Don't initialize on desktop or non-PWA mode
        }
        
        this.createScalingControls();
        this.loadSavedScale();
        this.bindEvents();
        this.applyScale(this.currentScale);
        this.updateMethodButtonState();
        
        // Ensure scaling is applied after a short delay to handle dynamic content
        setTimeout(() => {
            this.applyScale(this.currentScale);
        }, 100);
        
        console.log('[Mobile Scaling] Initialized for PWA mobile device');
    }
    
    /**
     * Detect if the device is mobile
     */
    detectMobile() {
        return window.innerWidth <= 1024 || 
               /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
    }
    
    /**
     * Detect if running in PWA standalone mode
     */
    detectPWAMode() {
        return window.matchMedia('(display-mode: standalone)').matches || 
               window.navigator.standalone === true ||
               document.referrer.includes('android-app://');
    }
    
    /**
     * Create scaling control elements
     */
    createScalingControls() {
        // Create backdrop overlay
        const backdrop = document.createElement('div');
        backdrop.className = 'scaling-backdrop';
        backdrop.setAttribute('aria-label', 'Close scaling panel');
        
        // Create slide-out panel
        const panel = document.createElement('div');
        panel.className = 'scaling-panel';
        panel.setAttribute('aria-label', 'Interface scaling options');
        
        // No header needed for small panel
        
        // Create controls container
        const controlsContainer = document.createElement('div');
        controlsContainer.className = 'scaling-controls';
        
        // Create scale buttons
        Object.entries(this.scaleLevels).forEach(([key, config]) => {
            const button = document.createElement('button');
            button.className = 'scaling-button';
            button.textContent = config.label;
            button.setAttribute('data-scale', key);
            button.setAttribute('aria-label', `Set interface scale to ${config.label}`);
            
            if (key === this.currentScale) {
                button.classList.add('active');
            }
            
            controlsContainer.appendChild(button);
        });
        
        // Create method section
        const methodSection = document.createElement('div');
        methodSection.className = 'scaling-method-section';
        
        const methodTitle = document.createElement('div');
        methodTitle.className = 'scaling-method-title';
        methodTitle.textContent = 'Scaling Method';
        
        const methodButton = document.createElement('button');
        methodButton.className = 'scaling-button method-toggle';
        methodButton.textContent = 'Transform Scaling';
        methodButton.setAttribute('aria-label', 'Toggle between transform scaling and page zoom');
        
        methodSection.appendChild(methodTitle);
        methodSection.appendChild(methodButton);
        
        // Assemble panel
        panel.appendChild(controlsContainer);
        panel.appendChild(methodSection);
        
        // Create frosted glass handle
        const handle = document.createElement('div');
        handle.className = 'scaling-handle';
        handle.setAttribute('aria-label', 'Open interface scaling panel');
        
        const handleIcon = document.createElement('div');
        handleIcon.className = 'scaling-handle-icon';
        handleIcon.innerHTML = '+<br/>−';
        
        handle.appendChild(handleIcon);
        
        // Add to body
        document.body.appendChild(backdrop);
        document.body.appendChild(panel);
        document.body.appendChild(handle);
        
        // Store references
        this.backdrop = backdrop;
        this.panel = panel;
        this.handle = handle;
        this.controlsContainer = controlsContainer;
        this.scaleButtons = controlsContainer.querySelectorAll('.scaling-button[data-scale]');
        this.methodButton = methodButton;
    }
    
    /**
     * Bind event listeners
     */
    bindEvents() {
        // Handle click to open panel
        this.handle.addEventListener('click', () => {
            this.showControls();
        });
        
        // No close button needed - click outside to close
        
        // Backdrop click to close
        this.backdrop.addEventListener('click', () => {
            this.hideControls();
        });
        
        // Scale button clicks
        this.scaleButtons.forEach(button => {
            button.addEventListener('click', (e) => {
                const scale = e.target.getAttribute('data-scale');
                this.setScale(scale);
            });
        });
        
        // Method toggle button click
        if (this.methodButton) {
            this.methodButton.addEventListener('click', () => {
                this.toggleScalingMethod();
                this.updateMethodButtonState();
            });
        }
        
        // Handle escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isControlsVisible) {
                this.hideControls();
            }
        });
        
        // Handle orientation change
        window.addEventListener('orientationchange', () => {
            setTimeout(() => {
                this.handleOrientationChange();
            }, 100);
        });
        
        // Handle resize
        window.addEventListener('resize', this.debounce(() => {
            this.handleResize();
        }, 250));
    }
    
    /**
     * Toggle controls visibility
     */
    toggleControls() {
        if (this.isControlsVisible) {
            this.hideControls();
        } else {
            this.showControls();
        }
    }
    
    /**
     * Show scaling controls
     */
    showControls() {
        this.panel.classList.add('open');
        this.backdrop.classList.add('active');
        this.handle.classList.add('active');
        this.isControlsVisible = true;
        
        // Update button states
        this.updateButtonStates();
        this.updateMethodButtonState();
        
        // Prevent body scroll
        document.body.style.overflow = 'hidden';
        
        // Announce to screen readers
        this.announceToScreenReader('Scaling controls opened');
    }
    
    /**
     * Hide scaling controls
     */
    hideControls() {
        this.panel.classList.remove('open');
        this.backdrop.classList.remove('active');
        this.handle.classList.remove('active');
        this.isControlsVisible = false;
        
        // Restore body scroll
        document.body.style.overflow = '';
        
        // Announce to screen readers
        this.announceToScreenReader('Scaling controls closed');
    }
    
    /**
     * Set the interface scale
     */
    setScale(scaleKey) {
        if (!this.scaleLevels[scaleKey]) {
            console.warn('[Mobile Scaling] Invalid scale key:', scaleKey);
            return;
        }
        
        this.currentScale = scaleKey;
        this.applyScale(scaleKey);
        this.updateButtonStates();
        this.saveScale(scaleKey);
        this.hideControls();
        
        // Announce to screen readers
        const percentage = Math.round(this.scaleLevels[scaleKey].factor * 100);
        this.announceToScreenReader(`Interface scale set to ${percentage}%`);
        
        console.log('[Mobile Scaling] Scale set to:', scaleKey, `(${percentage}%)`);
    }
    
    /**
     * Apply scale to the interface
     */
    applyScale(scaleKey) {
        const config = this.scaleLevels[scaleKey];
        const body = document.body;
        
        if (this.usePageZoom) {
            // Use page zoom approach
            this.applyPageZoom(scaleKey, config);
        } else {
            // Use transform scaling approach
            this.applyTransformScale(scaleKey, config);
        }
    }
    
    /**
     * Apply transform-based scaling
     */
    applyTransformScale(scaleKey, config) {
        const body = document.body;
        
        // Remove existing scale classes
        body.classList.remove('mobile-scale-xxs', 'mobile-scale-xs', 'mobile-scale-sm', 'mobile-scale-md', 'mobile-scale-lg', 'mobile-scale-xl');
        body.classList.remove('mobile-zoom-xxs', 'mobile-zoom-xs', 'mobile-zoom-sm', 'mobile-zoom-md', 'mobile-zoom-lg', 'mobile-zoom-xl');
        
        // Add new scale class
        body.classList.add(`mobile-scale-${scaleKey}`);
        body.classList.add('mobile-scaled');
        
        // Update CSS custom property
        document.documentElement.style.setProperty('--scale-factor', config.factor);
        
        // Adjust viewport for scaling
        this.adjustViewport(config.factor);
        
        // Ensure connection screen is properly scaled
        this.scaleConnectionScreen(config.factor);
    }
    
    /**
     * Apply page zoom scaling
     */
    applyPageZoom(scaleKey, config) {
        const body = document.body;
        
        // Remove existing scale classes
        body.classList.remove('mobile-scale-xxs', 'mobile-scale-xs', 'mobile-scale-sm', 'mobile-scale-md', 'mobile-scale-lg', 'mobile-scale-xl');
        body.classList.remove('mobile-zoom-xxs', 'mobile-zoom-xs', 'mobile-zoom-sm', 'mobile-zoom-md', 'mobile-zoom-lg', 'mobile-zoom-xl');
        
        // Add new zoom class
        body.classList.add(`mobile-zoom-${scaleKey}`);
        
        // Remove mobile-scaled class for zoom approach
        body.classList.remove('mobile-scaled');
        
        // Ensure connection screen is properly scaled
        this.scaleConnectionScreen(config.factor);
    }
    
    /**
     * Update button active states
     */
    updateButtonStates() {
        this.scaleButtons.forEach(button => {
            const scale = button.getAttribute('data-scale');
            if (scale === this.currentScale) {
                button.classList.add('active');
            } else {
                button.classList.remove('active');
            }
        });
    }
    
    /**
     * Update method button state
     */
    updateMethodButtonState() {
        if (this.methodButton) {
            this.methodButton.textContent = this.usePageZoom ? 'Page Zoom' : 'Transform Scaling';
            this.methodButton.title = this.usePageZoom ? 'Currently using Page Zoom' : 'Currently using Transform Scaling';
        }
    }
    
    /**
     * Adjust viewport for scaling
     */
    adjustViewport(scaleFactor) {
        // Ensure the scaled content fits within the viewport
        const container = document.querySelector('.container');
        if (container) {
            const scaledWidth = window.innerWidth / scaleFactor;
            const scaledHeight = window.innerHeight / scaleFactor;
            
            container.style.minWidth = `${scaledWidth}px`;
            container.style.minHeight = `${scaledHeight}px`;
        }
    }
    
    /**
     * Scale connection screen properly
     */
    scaleConnectionScreen(scaleFactor) {
        const connectionScreen = document.querySelector('.connection-screen');
        if (connectionScreen) {
            // Ensure connection screen scales with the rest of the interface
            connectionScreen.style.transform = `scale(${scaleFactor})`;
            connectionScreen.style.transformOrigin = 'center center';
            
            // Adjust the connection panel to fit within the scaled screen
            const connectionPanel = document.querySelector('.connection-panel');
            if (connectionPanel) {
                const maxWidth = (window.innerWidth * 0.9) / scaleFactor;
                const maxHeight = (window.innerHeight * 0.9) / scaleFactor;
                
                connectionPanel.style.maxWidth = `${maxWidth}px`;
                connectionPanel.style.maxHeight = `${maxHeight}px`;
            }
        }
    }
    
    /**
     * Handle orientation change
     */
    handleOrientationChange() {
        // Reapply current scale after orientation change
        this.applyScale(this.currentScale);
        
        // Hide controls if visible (they might be in wrong position)
        if (this.isControlsVisible) {
            this.hideControls();
        }
        
        console.log('[Mobile Scaling] Orientation changed, scale reapplied');
    }
    
    /**
     * Handle window resize
     */
    handleResize() {
        // Check if we're still on mobile and in PWA mode
        const wasMobile = this.isMobile;
        const wasPWA = this.isPWA;
        this.isMobile = this.detectMobile();
        this.isPWA = this.detectPWAMode();
        
        if (wasMobile !== this.isMobile || wasPWA !== this.isPWA) {
            // Device type or PWA mode changed, reinitialize
            this.destroy();
            this.init();
        } else if (this.isMobile && this.isPWA) {
            // Still mobile PWA, reapply scale
            this.applyScale(this.currentScale);
        }
    }
    
    /**
     * Save scale preference to localStorage
     */
    saveScale(scaleKey) {
        try {
            localStorage.setItem('mobileBuilder_scale', scaleKey);
        } catch (e) {
            console.warn('[Mobile Scaling] Could not save scale preference:', e);
        }
    }
    
    /**
     * Load saved scale preference
     */
    loadSavedScale() {
        try {
            const saved = localStorage.getItem('mobileBuilder_scale');
            if (saved && this.scaleLevels[saved]) {
                this.currentScale = saved;
            }
        } catch (e) {
            console.warn('[Mobile Scaling] Could not load scale preference:', e);
        }
    }
    
    /**
     * Get current scale information
     */
    getCurrentScale() {
        return {
            key: this.currentScale,
            factor: this.scaleLevels[this.currentScale].factor,
            percentage: Math.round(this.scaleLevels[this.currentScale].factor * 100)
        };
    }
    
    /**
     * Announce to screen readers
     */
    announceToScreenReader(message) {
        const announcement = document.createElement('div');
        announcement.setAttribute('aria-live', 'polite');
        announcement.setAttribute('aria-atomic', 'true');
        announcement.style.position = 'absolute';
        announcement.style.left = '-10000px';
        announcement.style.width = '1px';
        announcement.style.height = '1px';
        announcement.style.overflow = 'hidden';
        announcement.textContent = message;
        
        document.body.appendChild(announcement);
        
        setTimeout(() => {
            document.body.removeChild(announcement);
        }, 1000);
    }
    
    /**
     * Debounce utility function
     */
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
    
    /**
     * Toggle between transform scaling and page zoom
     */
    toggleScalingMethod() {
        this.usePageZoom = !this.usePageZoom;
        this.applyScale(this.currentScale);
        
        console.log('[Mobile Scaling] Switched to:', this.usePageZoom ? 'Page Zoom' : 'Transform Scaling');
    }
    
    /**
     * Get current scaling method
     */
    getScalingMethod() {
        return this.usePageZoom ? 'zoom' : 'transform';
    }
    
    /**
     * Reapply scaling (useful when page content changes)
     */
    reapplyScaling() {
        if (this.isMobile && this.isPWA) {
            this.applyScale(this.currentScale);
            // Also ensure connection screen is scaled if it exists
            const connectionScreen = document.querySelector('.connection-screen');
            if (connectionScreen) {
                const config = this.scaleLevels[this.currentScale];
                this.scaleConnectionScreen(config.factor);
            }
        }
    }
    
    /**
     * Destroy the scaling controller
     */
    destroy() {
        if (this.backdrop) {
            this.backdrop.remove();
        }
        if (this.panel) {
            this.panel.remove();
        }
        if (this.handle) {
            this.handle.remove();
        }
        
        // Restore body scroll
        document.body.style.overflow = '';
        
        // Remove all scale classes
        document.body.classList.remove('mobile-scaled', 
            'mobile-scale-xxs', 'mobile-scale-xs', 'mobile-scale-sm', 'mobile-scale-md', 'mobile-scale-lg', 'mobile-scale-xl',
            'mobile-zoom-xxs', 'mobile-zoom-xs', 'mobile-zoom-sm', 'mobile-zoom-md', 'mobile-zoom-lg', 'mobile-zoom-xl');
        
        // Reset CSS custom property
        document.documentElement.style.removeProperty('--scale-factor');
    }
}

// Auto-initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Initialize mobile scaling controller
    window.mobileScalingController = new MobileScalingController();
    
    // Expose global methods for external use (only work in PWA mode)
    window.setInterfaceScale = (scale) => {
        if (window.mobileScalingController && window.mobileScalingController.isPWA) {
            window.mobileScalingController.setScale(scale);
        }
    };
    
    window.getCurrentScale = () => {
        if (window.mobileScalingController && window.mobileScalingController.isPWA) {
            return window.mobileScalingController.getCurrentScale();
        }
        return null;
    };
    
    window.toggleScalingControls = () => {
        if (window.mobileScalingController && window.mobileScalingController.isPWA) {
            window.mobileScalingController.toggleControls();
        }
    };
    
    window.toggleScalingMethod = () => {
        if (window.mobileScalingController && window.mobileScalingController.isPWA) {
            window.mobileScalingController.toggleScalingMethod();
        }
    };
    
    window.getScalingMethod = () => {
        if (window.mobileScalingController && window.mobileScalingController.isPWA) {
            return window.mobileScalingController.getScalingMethod();
        }
        return null;
    };
    
    window.reapplyScaling = () => {
        if (window.mobileScalingController && window.mobileScalingController.isPWA) {
            window.mobileScalingController.reapplyScaling();
        }
    };
});

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = MobileScalingController;
}
