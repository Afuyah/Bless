
document.addEventListener("DOMContentLoaded", function () {
    let cartItems = document.getElementById("cart-items");
    let floatingCart = document.querySelector(".floating-cart");
    let toggleCartBtn = document.getElementById("toggle-cart-btn");
    let productContainer = document.querySelector(".product-container");

    function toggleCart() {
        if (cartItems.children.length > 0) {
            floatingCart.classList.remove("d-none");
            productContainer.classList.remove("col-md-10");
            productContainer.classList.add("col-md-7");
        } else {
            floatingCart.classList.add("d-none");
            productContainer.classList.remove("col-md-7");
            productContainer.classList.add("col-md-10");
        }
    }

    // Toggle floating cart on small screens
    toggleCartBtn.addEventListener("click", function () {
        floatingCart.classList.toggle("show");
    });

    // Clear cart function
    document.getElementById("clear-cart").addEventListener("click", function () {
        cartItems.innerHTML = "";
        toggleCart();
    });

    // Simulate adding a product to the cart
    document.getElementById("product-list").addEventListener("click", function () {
        let item = document.createElement("div");
        item.textContent = " ";
        cartItems.appendChild(item);
        toggleCart();
    });

    toggleCart();
});

  document.addEventListener('DOMContentLoaded', function () {
    // Check if the page is the POS screen (you can use any condition to verify)
    if (window.location.pathname === '/pos') {
      const docEl = document.documentElement;

      function enterFullscreen() {
        if (docEl.requestFullscreen) {
          docEl.requestFullscreen();
        } else if (docEl.webkitRequestFullscreen) {
          docEl.webkitRequestFullscreen(); // Safari
        } else if (docEl.msRequestFullscreen) {
          docEl.msRequestFullscreen(); // IE/Edge
        }
      }

      enterFullscreen();
    }
  });

  document.addEventListener('DOMContentLoaded', function () {
    const docEl = document.documentElement;

    // Request fullscreen as soon as the page loads
    function enterFullscreen() {
      if (docEl.requestFullscreen) {
        docEl.requestFullscreen();
      } else if (docEl.webkitRequestFullscreen) {
        docEl.webkitRequestFullscreen(); // Safari
      } else if (docEl.msRequestFullscreen) {
        docEl.msRequestFullscreen(); // IE/Edge
      }
    }

    // Trigger fullscreen mode
    enterFullscreen();
  });


  document.addEventListener("DOMContentLoaded", () => {
    const fsBtn  = document.getElementById("fullscreen-toggle-btn");
    const fsIcon = document.getElementById("fullscreen-icon");
    const fsText = document.getElementById("fullscreen-text");
    const docEl  = document.documentElement;
  
    function isFullscreenActive() {
      return !!(document.fullscreenElement
             || document.webkitFullscreenElement
             || document.msFullscreenElement);
    }
  
    function enterFullscreen() {
      if (docEl.requestFullscreen)        docEl.requestFullscreen();
      else if (docEl.webkitRequestFullscreen) docEl.webkitRequestFullscreen();
      else if (docEl.msRequestFullscreen)     docEl.msRequestFullscreen();
    }
  
    function disableFSButton() {
      fsBtn.classList.add("disabled");
      fsBtn.setAttribute("aria-disabled", "true");
      fsBtn.removeEventListener("click", onFSBtnClick);
    }
  
    function updateFSButton() {
      if (isFullscreenActive()) {
        // Switch icon/text once fullscreen is active
        fsIcon.classList.replace("fa-expand", "fa-check-circle");
        fsText.textContent = "POS Active";
        disableFSButton();
      } else {
        // If user somehow exits, re‑enter
        fsIcon.classList.replace("fa-check-circle", "fa-expand");
        fsText.textContent = "Fullscreen";
        fsBtn.classList.remove("disabled");
        fsBtn.setAttribute("aria-disabled", "false");
        fsBtn.addEventListener("click", onFSBtnClick);
      }
    }
  
    function onFSBtnClick(e) {
      e.preventDefault();
      if (!isFullscreenActive()) enterFullscreen();
    }
  
    // Initial click listener
    fsBtn.addEventListener("click", onFSBtnClick);
  
    // Keep button state in sync
    ["fullscreenchange","webkitfullscreenchange","msfullscreenchange"]
      .forEach(evt => document.addEventListener(evt, updateFSButton));
  
    // Block Escape & F10 exits
    document.addEventListener("keydown", (e) => {
      if (isFullscreenActive() && (e.key==="Escape"||e.key==="F10")) {
        e.preventDefault();
        // bounce back
        document.exitFullscreen?.();
        enterFullscreen();
      }
    });
  
    // Backup enforcement every 3s
    setInterval(() => {
      if (window.location.pathname==='/pos' && !isFullscreenActive()) {
        enterFullscreen();
      }
    }, 3000);
  
    // Kick off on page load
    if (window.location.pathname==='/pos') {
      enterFullscreen();
      updateFSButton();
    }
  });
