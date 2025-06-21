// Initialize a global object to store components that need reinitialization
const appState = {
  components: {
   
    lowStockTable: null
  },
  isLoading: false
};


// Toggle user dropdown
document.getElementById('user-menu-button').addEventListener('click', function() {
  const menu = document.getElementById('user-menu');
  menu.classList.toggle('hidden');
});

// Toggle notifications dropdown
document.getElementById('notifications-button').addEventListener('click', function() {
  const dropdown = document.getElementById('notifications-dropdown');
  dropdown.classList.toggle('hidden');
});

// Toggle sidebar collapse
document.getElementById('sidebar-collapse').addEventListener('click', function() {
  const sidebar = document.getElementById('sidebar');
  sidebar.classList.toggle('sidebar-collapsed');
  
  const icon = this.querySelector('i');
  if (sidebar.classList.contains('sidebar-collapsed')) {
    icon.classList.remove('fa-chevron-left');
    icon.classList.add('fa-chevron-right');
  } else {
    icon.classList.remove('fa-chevron-right');
    icon.classList.add('fa-chevron-left');
  }
});

// Dark mode toggle
document.getElementById('dark-mode-toggle').addEventListener('click', function() {
  const icon = this.querySelector('i');
  if (document.documentElement.classList.contains('dark')) {
    document.documentElement.classList.remove('dark');
    localStorage.theme = 'light';
    icon.classList.remove('fa-sun');
    icon.classList.add('fa-moon');
  } else {
    document.documentElement.classList.add('dark');
    localStorage.theme = 'dark';
    icon.classList.remove('fa-moon');
    icon.classList.add('fa-sun');
  }
});

// Set initial dark mode based on preference
if (localStorage.theme === 'dark' || (!('theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
  document.documentElement.classList.add('dark');
  document.getElementById('dark-mode-toggle').querySelector('i').classList.add('fa-sun');
} else {
  document.documentElement.classList.remove('dark');
  document.getElementById('dark-mode-toggle').querySelector('i').classList.add('fa-moon');
}

// Close dropdowns when clicking outside
document.addEventListener('click', function(event) {
  const userMenu = document.getElementById('user-menu');
  const userButton = document.getElementById('user-menu-button');
  const notificationsDropdown = document.getElementById('notifications-dropdown');
  const notificationsButton = document.getElementById('notifications-button');
  
  if (userMenu && !userButton.contains(event.target) && !userMenu.contains(event.target)) {
    userMenu.classList.add('hidden');
  }
  
  if (notificationsDropdown && !notificationsButton.contains(event.target) && !notificationsDropdown.contains(event.target)) {
    notificationsDropdown.classList.add('hidden');
  }
});


// Show toast notifications
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
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
  
  // Adjust for dark mode
  if (document.documentElement.classList.contains('dark')) {
    bgColor = bgColor.replace(/100/g, '900/30').replace(/700/g, '400');
    iconColor = iconColor.replace(/500/g, '400');
  }
  
  toast.className = `border-l-4 ${bgColor} p-4 rounded-md shadow-md flex items-start`;
  toast.innerHTML = `
    <i class="fas ${icon} text-lg mr-3 ${iconColor}"></i>
    <div class="flex-1">${message}</div>
    <button class="ml-2 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300">
      <i class="fas fa-times"></i>
    </button>
  `;
  
  // Add close functionality
  const closeButton = toast.querySelector('button');
  closeButton.addEventListener('click', () => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  });
  
  container.appendChild(toast);
  
  // Auto remove after 5 seconds
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 5000);
}

// HTMX Event Handlers
document.addEventListener('htmx:beforeRequest', function(evt) {
  const target = evt.detail.elt;
  if (target.hasAttribute('hx-get') || target.hasAttribute('hx-post')) {
    appState.isLoading = true;
    const loader = document.getElementById('global-loader') || createGlobalLoader();
    loader.classList.remove('hidden');
  }
});

document.addEventListener('htmx:afterRequest', function(evt) {
  appState.isLoading = false;
  const loader = document.getElementById('global-loader');
  if (loader) loader.classList.add('hidden');
});

document.addEventListener('htmx:afterSwap', function(evt) {
  // Reinitialize components after content swap
  initializeDataTable();
  initializeChart();
  
  
});

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


// Initial setup
document.addEventListener('DOMContentLoaded', function() {
  initializeDataTable();
  initializeChart();
  createGlobalLoader();
 
  // Show welcome toast
  setTimeout(() => {
    showToast('System initialized successfully', 'success');
  }, 1000);
});




  document.addEventListener('htmx:beforeRequest', function(evt) {
    // Show loader
    document.getElementById('chart-loader').classList.remove('hidden');
    // Hide chart canvas temporarily
    document.getElementById('sales-chart-container').classList.add('opacity-50');
  });

  document.addEventListener('htmx:afterSwap', function(evt) {
    // Hide loader
    document.getElementById('chart-loader').classList.add('hidden');
    // Restore chart visibility
    document.getElementById('sales-chart-container').classList.remove('opacity-50');
  });

  document.addEventListener('htmx:responseError', function(evt) {
    document.getElementById('chart-loader').classList.add('hidden');
    alert('Failed to load chart data. Please try again.');
  });


document.addEventListener('DOMContentLoaded', function() {
    // Only run this for full page loads (not HTMX requests)
    if (!window.history.state?.htmx) {
        const currentPath = window.location.pathname;
        
        // Don't do anything if we're already at the dashboard root
        if (currentPath !== '/admin' && currentPath !== '/admin/dashboard') {
            // Get the current URL via HTMX
            htmx.ajax('GET', currentPath, {
                target: '#main-content',
                swap: 'innerHTML',
                headers: {'HX-Request': 'true'}
            });
        }
    }
});

// Add HTMX state to history when navigating
htmx.on('htmx:afterSwap', function(evt) {
    if (evt.detail.requestConfig.elt.hasAttribute('hx-push-url')) {
        window.history.replaceState({htmx: true}, '', evt.detail.requestConfig.path);
    }
});
