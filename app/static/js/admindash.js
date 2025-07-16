// Initialize a global object to store components that need reinitialization
const appState = {
  components: {
    lowStockTable: null
  },
  isLoading: false
};

// DOM Event Listeners
document.addEventListener('DOMContentLoaded', function() {
  // Initialize components
  if (typeof initializeDataTable === 'function') initializeDataTable();
  if (typeof initializeChart === 'function') initializeChart();
  createGlobalLoader();

  // Show welcome toast
  setTimeout(() => {
    showToast('System initialized successfully', 'success');
  }, 1000);

  // Navigation handling for full page loads
  if (!window.history.state?.htmx) {
    const currentPath = window.location.pathname;
    if (currentPath !== '/admin' && currentPath !== '/admin/dashboard') {
      htmx.ajax('GET', currentPath, {
        target: '#main-content',
        swap: 'innerHTML',
        headers: {'HX-Request': 'true'}
      });
    }
  }
});

// Toggle user dropdown
document.getElementById('user-menu-button')?.addEventListener('click', function() {
  const menu = document.getElementById('user-menu');
  if (menu) menu.classList.toggle('hidden');
});

// Toggle notifications dropdown
document.getElementById('notifications-button')?.addEventListener('click', function() {
  const dropdown = document.getElementById('notifications-dropdown');
  if (dropdown) dropdown.classList.toggle('hidden');
});

// Toggle sidebar collapse
document.getElementById('sidebar-collapse')?.addEventListener('click', function() {
  const sidebar = document.getElementById('sidebar');
  if (sidebar) {
    sidebar.classList.toggle('sidebar-collapsed');
    const icon = this.querySelector('i');
    if (icon) {
      if (sidebar.classList.contains('sidebar-collapsed')) {
        icon.classList.replace('fa-chevron-left', 'fa-chevron-right');
      } else {
        icon.classList.replace('fa-chevron-right', 'fa-chevron-left');
      }
    }
  }
});

// Dark mode toggle - properly closed
document.getElementById('dark-mode-toggle')?.addEventListener('click', function() {
  const icon = this.querySelector('i');
  if (document.documentElement.classList.contains('dark')) {
    document.documentElement.classList.remove('dark');
    localStorage.theme = 'light';
    icon?.classList.replace('fa-sun', 'fa-moon');
  } else {
    document.documentElement.classList.add('dark');
    localStorage.theme = 'dark';
    icon?.classList.replace('fa-moon', 'fa-sun');
  }
});

// Close dropdowns when clicking outside
document.addEventListener('click', function(event) {
  const userMenu = document.getElementById('user-menu');
  const userButton = document.getElementById('user-menu-button');
  const notificationsDropdown = document.getElementById('notifications-dropdown');
  const notificationsButton = document.getElementById('notifications-button');
  
  if (userMenu && userButton && !userButton.contains(event.target) && !userMenu.contains(event.target)) {
    userMenu.classList.add('hidden');
  }
  
  if (notificationsDropdown && notificationsButton && !notificationsButton.contains(event.target) && !notificationsDropdown.contains(event.target)) {
    notificationsDropdown.classList.add('hidden');
  }
});



document.addEventListener('htmx:afterRequest', function(evt) {
  appState.isLoading = false;
  document.getElementById('global-loader')?.classList.add('hidden');
});

document.addEventListener('htmx:afterSwap', function(evt) {
  // Reinitialize components after content swap
  if (typeof initializeDataTable === 'function') initializeDataTable();
  if (typeof initializeChart === 'function') initializeChart();
  
  // Handle URL push state
  if (evt.detail.requestConfig.elt.hasAttribute('hx-push-url')) {
    window.history.replaceState({htmx: true}, '', evt.detail.requestConfig.path);
  }
});

document.addEventListener('htmx:responseError', function(evt) {
  document.getElementById('chart-loader')?.classList.add('hidden');
  showToast('Failed to load data. Please try again.', 'error');
});

// Helper Functions
function createGlobalLoader() {
  const loader = document.createElement('div');
  loader.id = 'global-loader';
  loader.className = 'fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center hidden';
  loader.innerHTML = `
    <div class="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary-500"></div>
  `;
  document.body.appendChild(loader);
  return loader;
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  
  const toast = document.createElement('div');
  let bgColor, icon, iconColor;
  
  switch(type) {
    case 'success':
      bgColor = 'bg-green-100 border-green-400 text-green-700';
      icon = 'fa-check-circle';
      iconColor = 'text-green-500';
      break;
    case 'error':
      bgColor = 'bg-red-100 border-red-400 text-red-700';
      icon = 'fa-exclamation-circle';
      iconColor = 'text-red-500';
      break;
    case 'warning':
      bgColor = 'bg-yellow-100 border-yellow-400 text-yellow-700';
      icon = 'fa-exclamation-triangle';
      iconColor = 'text-yellow-500';
      break;
    default:
      bgColor = 'bg-blue-100 border-blue-400 text-blue-700';
      icon = 'fa-info-circle';
      iconColor = 'text-blue-500';
  }
  
  if (document.documentElement.classList.contains('dark')) {
    bgColor = bgColor.replace(/100/g, '900/30').replace(/700/g, '400');
    iconColor = iconColor.replace(/500/g, '400');
  }
  
  toast.className = `border-l-4 ${bgColor} p-4 rounded-md shadow-md flex items-start mb-2`;
  toast.innerHTML = `
    <i class="fas ${icon} text-lg mr-3 ${iconColor}"></i>
    <div class="flex-1">${message}</div>
    <button class="ml-2 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300">
      <i class="fas fa-times"></i>
    </button>
  `;
  
  toast.querySelector('button')?.addEventListener('click', () => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  });
  
  container.appendChild(toast);
  
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 5000);
}