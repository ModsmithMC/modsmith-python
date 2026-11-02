(() => {
  const root = document.documentElement;

  document.querySelector("[data-theme-toggle]")?.addEventListener("click", () => {
    const dark =
      root.dataset.theme === "dark" ||
      (!root.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
    root.dataset.theme = dark ? "light" : "dark";
    try {
      localStorage.setItem("modsmith-theme", root.dataset.theme);
    } catch (error) {}
  });

  const menu = document.querySelector("[data-menu]");
  const sidebar = document.querySelector("[data-sidebar]");
  menu?.addEventListener("click", () => {
    const open = sidebar?.classList.toggle("open") ?? false;
    menu.setAttribute("aria-expanded", String(open));
  });

  const search = document.querySelector("[data-search]");
  document.addEventListener("keydown", (event) => {
    const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName ?? "");
    if (event.key === "/" && !typing) {
      event.preventDefault();
      search?.focus();
    }
  });

  document.querySelectorAll("div.highlight").forEach((block) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "copy-button";
    button.textContent = "Copy";
    button.addEventListener("click", async () => {
      await navigator.clipboard.writeText(block.querySelector("pre").innerText);
      button.textContent = "Copied";
      setTimeout(() => (button.textContent = "Copy"), 1500);
    });
    block.append(button);
  });
})();
