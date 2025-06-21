// charts.js - Complete Chart Initialization Solution for HTMX

// ====================
// Configuration
// ====================
const CHART_CONFIG = {
  colors: {
    blue: 'rgba(59, 130, 246, 1)',
    blueLight: 'rgba(59, 130, 246, 0.1)',
    green: 'rgba(16, 185, 129, 1)',
    greenLight: 'rgba(16, 185, 129, 0.1)',
    purple: 'rgba(79, 70, 229, 1)',
    purpleLight: 'rgba(79, 70, 229, 0.1)',
    indigo: 'rgba(99, 102, 241, 1)',
    indigoLight: 'rgba(99, 102, 241, 0.7)',
    orange: 'rgba(234, 88, 12, 1)',
    orangeLight: 'rgba(234, 88, 12, 0.1)'
  },
  darkMode: {
    grid: 'rgba(255, 255, 255, 0.1)',
    text: 'rgba(255, 255, 255, 0.7)'
  },
  lightMode: {
    grid: 'rgba(0, 0, 0, 0.05)',
    text: 'rgba(0, 0, 0, 0.6)'
  }
};

// ====================
// Core Functions
// ====================
class ChartManager {
  constructor() {
    this.instances = {};
    this.initialize();
  }

  initialize() {
    this.setupEventListeners();
    this.loadChartJS().then(() => {
      if (document.readyState === 'complete') {
        this.initAllCharts();
      }
    });
  }

  async loadChartJS() {
    if (typeof Chart === 'undefined') {
      await import('https://cdn.jsdelivr.net/npm/chart.js');
    }
  }

  setupEventListeners() {
    // Initial load
    document.addEventListener('DOMContentLoaded', () => {
      this.initAllCharts();
    });

    // HTMX content swap
    document.body.addEventListener('htmx:afterSwap', (event) => {
      if (event.detail.target.id === 'main-content') {
        setTimeout(() => this.initAllCharts(), 50);
      }
    });

    // Theme changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      this.refreshAllCharts();
    });
  }

  // ====================
  // Chart Initializers
  // ====================
  initSalesChart() {
    return this._initChart('salesChart', {
      type: 'line',
      data: (ctx) => ({
        labels: JSON.parse(ctx.dataset.labels || '[]'),
        datasets: [{
          label: 'Sales (Ksh)',
          data: JSON.parse(ctx.dataset.values || '[]'),
          backgroundColor: CHART_CONFIG.colors.purpleLight,
          borderColor: CHART_CONFIG.colors.purple,
          borderWidth: 2,
          tension: 0.3,
          fill: true
        }]
      }),
      options: {
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: ctx => 'Ksh ' + ctx.raw.toLocaleString()
            }
          }
        },
        scales: {
          y: {
            ticks: {
              callback: value => 'Ksh ' + value.toLocaleString()
            }
          }
        }
      }
    });
  }

  initDailySalesChart() {
    return this._initChart('dailySalesChart', {
      type: 'bar',
      data: (ctx) => ({
        labels: JSON.parse(ctx.dataset.days || '[]'),
        datasets: [
          {
            label: 'Sales (Ksh)',
            data: JSON.parse(ctx.dataset.sales || '[]'),
            backgroundColor: CHART_CONFIG.colors.blueLight,
            borderColor: CHART_CONFIG.colors.blue,
            borderWidth: 1
          },
          {
            label: 'Transactions',
            data: JSON.parse(ctx.dataset.transactions || '[]'),
            type: 'line',
            borderColor: CHART_CONFIG.colors.green,
            backgroundColor: 'transparent',
            borderWidth: 2,
            pointRadius: 4
          }
        ]
      }),
      options: {
        scales: {
          y: {
            ticks: {
              callback: value => 'Ksh ' + value.toLocaleString()
            }
          }
        }
      }
    });
  }

  initHourlySalesChart() {
    return this._initChart('hourlySalesChart', {
      type: 'line',
      data: (ctx) => ({
        labels: JSON.parse(ctx.dataset.hours || '[]'),
        datasets: [{
          label: 'Sales by Hour',
          data: JSON.parse(ctx.dataset.sales || '[]'),
          backgroundColor: CHART_CONFIG.colors.purpleLight,
          borderColor: CHART_CONFIG.colors.purple,
          borderWidth: 2,
          tension: 0.4,
          fill: true
        }]
      }),
      options: {
        scales: {
          y: {
            ticks: {
              callback: value => 'Ksh ' + value.toLocaleString()
            }
          }
        }
      }
    });
  }

  // ====================
  // Utility Methods
  // ====================
  _initChart(chartId, { type, data, options = {} }) {
    const ctx = document.getElementById(chartId);
    if (!ctx) return null;

    try {
      // Destroy existing instance
      if (this.instances[chartId]) {
        this.instances[chartId].destroy();
      }

      // Create new chart
      this.instances[chartId] = new Chart(ctx, {
        type,
        data: typeof data === 'function' ? data(ctx) : data,
        options: this._getChartOptions(options)
      });

      return this.instances[chartId];
    } catch (error) {
      console.error(`${chartId} error:`, error);
      this._showChartError(ctx, `Failed to load ${chartId.replace('Chart', '').toLowerCase()} data`);
      return null;
    }
  }

  _getChartOptions(customOptions = {}) {
    const isDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const gridColor = isDarkMode ? CHART_CONFIG.darkMode.grid : CHART_CONFIG.lightMode.grid;
    const textColor = isDarkMode ? CHART_CONFIG.darkMode.text : CHART_CONFIG.lightMode.text;

    return {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'top',
          labels: { color: textColor }
        },
        tooltip: {
          mode: 'index',
          intersect: false,
          callbacks: {
            label: context => {
              let label = context.dataset.label || '';
              if (label.includes('Ksh') || label.includes('Revenue')) {
                return `${label}: Ksh ${context.raw.toLocaleString()}`;
              }
              return `${label}: ${context.raw}`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: gridColor },
          ticks: { color: textColor }
        },
        y: {
          beginAtZero: true,
          grid: { color: gridColor },
          ticks: { color: textColor }
        },
        ...customOptions.scales
      },
      ...customOptions
    };
  }

  _showChartError(ctx, message) {
    const errorElement = ctx.parentElement.querySelector('.chart-error');
    if (errorElement) {
      errorElement.textContent = message;
      errorElement.style.display = 'block';
    }
  }

  // ====================
  // Public Interface
  // ====================
  initAllCharts() {
    if (typeof Chart === 'undefined') {
      console.error('Chart.js is not loaded!');
      document.querySelectorAll('.chart-error').forEach(el => {
        el.textContent = 'Chart library not loaded';
        el.style.display = 'block';
      });
      return;
    }

    return {
      sales: this.initSalesChart(),
      dailySales: this.initDailySalesChart(),
      hourlySales: this.initHourlySalesChart()
    };
  }

  refreshAllCharts() {
    this.initAllCharts();
  }

  destroyAllCharts() {
    Object.values(this.instances).forEach(chart => chart.destroy());
    this.instances = {};
  }
}

// ====================
// Initialization
// ====================
// Create singleton instance
window.chartManager = new ChartManager();