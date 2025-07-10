
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

  toggleCartBtn?.addEventListener("click", function () {
    floatingCart.classList.toggle("show");
  });

  document.getElementById("clear-cart")?.addEventListener("click", function () {
    cartItems.innerHTML = "";
    toggleCart();
  });

  document.getElementById("product-list")?.addEventListener("click", function () {
    let item = document.createElement("div");
    item.textContent = "Sample Product"; // placeholder
    cartItems.appendChild(item);
    toggleCart();
  });

  toggleCart();
});


 document.addEventListener("DOMContentLoaded", function () {
  const docEl = document.documentElement;

  function isFullscreenActive() {
    return !!(document.fullscreenElement || document.webkitFullscreenElement || document.msFullscreenElement);
  }

  function enterFullscreen() {
    if (docEl.requestFullscreen) docEl.requestFullscreen();
    else if (docEl.webkitRequestFullscreen) docEl.webkitRequestFullscreen();
    else if (docEl.msRequestFullscreen) docEl.msRequestFullscreen();
  }

  const fsBtn = document.getElementById("fullscreen-toggle-btn");
  const fsIcon = document.getElementById("fullscreen-icon");
  const fsText = document.getElementById("fullscreen-text");

  function disableFSButton() {
    fsBtn?.classList.add("disabled");
    fsBtn?.setAttribute("aria-disabled", "true");
    fsBtn?.removeEventListener("click", onFSBtnClick);
  }

  function updateFSButton() {
    if (isFullscreenActive()) {
      fsIcon?.classList.replace("fa-expand", "fa-check-circle");
      fsText.textContent = "POS Active";
      disableFSButton();
    } else {
      fsIcon?.classList.replace("fa-check-circle", "fa-expand");
      fsText.textContent = "Fullscreen";
      fsBtn?.classList.remove("disabled");
      fsBtn?.setAttribute("aria-disabled", "false");
      fsBtn?.addEventListener("click", onFSBtnClick);
    }
  }

  function onFSBtnClick(e) {
    e.preventDefault();
    if (!isFullscreenActive()) enterFullscreen();
  }

  fsBtn?.addEventListener("click", onFSBtnClick);

  ["fullscreenchange", "webkitfullscreenchange", "msfullscreenchange"].forEach(evt =>
    document.addEventListener(evt, updateFSButton)
  );

  document.addEventListener("keydown", (e) => {
    if (isFullscreenActive() && (e.key === "Escape" || e.key === "F10")) {
      e.preventDefault();
      document.exitFullscreen?.();
      enterFullscreen(); // force re-entry
    }
  });

  // 👇 Scoped to this specific shop's POS screen
  if (window.location.pathname === POS_PATH) {
    enterFullscreen();
    updateFSButton();

    // Redundant backup check every 3s
    setInterval(() => {
      if (!isFullscreenActive()) enterFullscreen();
    }, 3000);
  }
});

