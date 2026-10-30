/* Responsive dashboard navigation and single-view workspace controller. */
(() => {
  "use strict";
  const main = document.getElementById("main-content");
  if (!main) return;
  const sidebar = document.getElementById("app-sidebar");
  const toggle = document.getElementById("sidebar-toggle");
  const backdrop = document.getElementById("sidebar-backdrop");
  const title = document.getElementById("page-title");
  const context = document.getElementById("page-context");
  const navLinks = [...document.querySelectorAll("[data-view-link]")];
  const dashboardIds = new Set(["home", "dashboard-shortcuts", "farmer-workspace"]);
  const directSections = [...main.children].filter((element) => element.tagName === "SECTION");
  const labels = new Map(navLinks.map((link) => [link.dataset.viewLink, link.querySelector("span")?.textContent.trim() || "Dashboard"]));
  const validViews = new Set(["home", ...directSections.map((section) => section.id).filter(Boolean)]);
  let currentView = "home";

  function closeMobileSidebar() {
    document.body.classList.remove("sidebar-open");
    toggle?.setAttribute("aria-expanded", "false");
  }

  function openMobileSidebar() {
    document.body.classList.add("sidebar-open");
    toggle?.setAttribute("aria-expanded", "true");
  }

  function isMobile() { return window.matchMedia("(max-width: 900px)").matches; }

  function activateView(viewId, options = {}) {
    const id = validViews.has(viewId) ? viewId : "home";
    currentView = id;
    const isDashboard = id === "home";

    directSections.forEach((section) => {
      const visible = isDashboard ? dashboardIds.has(section.id) : section.id === id;
      section.hidden = !visible;
      section.classList.toggle("active-view", visible);
    });

    navLinks.forEach((link) => {
      const active = link.dataset.viewLink === id;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });

    if (title) title.textContent = labels.get(id) || "Dashboard";
    if (context) context.textContent = isDashboard ? "YOUR FARM WORKSPACE" : "FARM MANAGEMENT WORKSPACE";
    document.title = `${labels.get(id) || "Dashboard"} | ShambaSense AI`;

    if (options.updateHistory !== false) {
      const nextHash = `#${id}`;
      if (window.location.hash !== nextHash) window.history.pushState({ view: id }, "", nextHash);
    }
    if (isMobile()) closeMobileSidebar();
    if (options.focus !== false) window.scrollTo({ top: 0, behavior: "smooth" });
  }

  window.showAppView = (viewId) => activateView(viewId);

  document.addEventListener("click", (event) => {
    const link = event.target.closest('a[href^="#"]');
    if (!link) return;
    const rawId = link.getAttribute("href").slice(1);
    if (!rawId || !validViews.has(rawId)) return;
    event.preventDefault();
    activateView(rawId);
  });

  toggle?.addEventListener("click", () => {
    if (isMobile()) {
      if (document.body.classList.contains("sidebar-open")) closeMobileSidebar();
      else openMobileSidebar();
      return;
    }
    document.body.classList.toggle("sidebar-collapsed");
    toggle.setAttribute("aria-expanded", String(!document.body.classList.contains("sidebar-collapsed")));
  });
  backdrop?.addEventListener("click", closeMobileSidebar);

  window.addEventListener("popstate", () => activateView(window.location.hash.slice(1) || "home", { updateHistory: false, focus: false }));
  window.addEventListener("resize", () => { if (!isMobile()) closeMobileSidebar(); });

  const initialView = window.location.hash.slice(1);
  activateView(validViews.has(initialView) ? initialView : "home", { updateHistory: false, focus: false });
})();
