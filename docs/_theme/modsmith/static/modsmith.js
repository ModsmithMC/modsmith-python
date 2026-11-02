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

  const languages = { python: "Python", bash: "Terminal", pycon: "Python" };
  document.querySelectorAll("div.highlight").forEach((block) => {
    const name = block.parentElement.className.match(/highlight-(\w+)/)?.[1];
    const bar = document.createElement("div");
    bar.className = "code-bar";
    const label = document.createElement("span");
    label.textContent = languages[name] ?? "Code";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "copy-button";
    button.textContent = "Copy";
    button.addEventListener("click", async () => {
      await navigator.clipboard.writeText(block.querySelector("pre").innerText);
      button.textContent = "Copied";
      setTimeout(() => (button.textContent = "Copy"), 1500);
    });
    bar.append(label, button);
    block.prepend(bar);
  });

  // Reference fields read as rows: name and type on the left, meaning on the right.
  document.querySelectorAll(".content dl.field-list > dt").forEach((label) => {
    // The signature already shows the return type.
    if (label.textContent.startsWith("Return type")) {
      label.nextElementSibling.remove();
      label.remove();
    }
  });
  document.querySelectorAll(".content dl.field-list > dd").forEach((field) => {
    const rows = field.querySelectorAll(":scope > ul > li > p, :scope > p");
    rows.forEach((row) => {
      const name = row.firstElementChild;
      const leading = row.firstChild === name;
      if (!leading || !name.matches("strong, a") || !row.textContent.includes("–")) return;
      const left = document.createElement("div");
      left.className = "field-name";
      const type = document.createElement("span");
      type.className = "field-type";
      const doc = document.createElement("div");
      doc.className = "field-doc";
      let target = type;
      [...row.childNodes].forEach((node) => {
        if (node === name) return left.append(node);
        const dash = node.nodeType === 3 ? node.textContent.indexOf("–") : -1;
        if (target === type && dash >= 0) {
          type.append(node.textContent.slice(0, dash));
          doc.append(node.textContent.slice(dash + 1).trimStart());
          target = doc;
        } else {
          target.append(node);
        }
      });
      type.textContent = type.textContent.replace(/^\s*\(|\)\s*$/g, "").trim() ? type.textContent : "";
      type.innerHTML = type.innerHTML.replace(/^\s*\(/, "").replace(/\)\s*$/, "");
      if (type.textContent) left.append(type);
      row.className = "field-row";
      row.replaceChildren(left, doc);
    });
  });

  // Reference entries in the table of contents show what kind of object they are.
  const kinds = { class: "class", exception: "exc", function: "func", method: "meth", attribute: "attr", property: "prop" };
  document.querySelectorAll(".site-toc a[href^='#']").forEach((link) => {
    const entry = document.getElementById(decodeURIComponent(link.hash.slice(1)));
    const list = entry?.closest("dl.py");
    const kind = list && Object.keys(kinds).find((name) => list.classList.contains(name));
    if (kind) link.dataset.kind = kinds[kind];
  });

  // The page's table of contents follows the reader.
  const links = new Map();
  document.querySelectorAll(".site-toc a[href^='#']").forEach((link) => {
    const target = document.getElementById(decodeURIComponent(link.hash.slice(1)));
    if (target) links.set(target, link);
  });
  if (links.size) {
    const visible = new Set();
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) =>
          entry.isIntersecting ? visible.add(entry.target) : visible.delete(entry.target),
        );
        const first = [...links.keys()].find((target) => visible.has(target));
        if (!first) return;
        links.forEach((link) => link.classList.remove("active"));
        links.get(first).classList.add("active");
      },
      { rootMargin: "-70px 0px -70% 0px" },
    );
    links.forEach((_, target) => observer.observe(target));
  }

  const repo = document.querySelector("[data-repo]");
  const repoName = document.querySelector("[data-repo-name]");
  const facts = document.querySelector("[data-repo-facts]");
  const icons = {
    stars:
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 2.7 5.8 6.3.8-4.6 4.3 1.2 6.2L12 17l-5.6 3.1 1.2-6.2L3 9.6l6.3-.8z"/></svg>',
    forks:
      '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="5" r="2.5"/><circle cx="18" cy="5" r="2.5"/><circle cx="12" cy="19" r="2.5"/><path d="M6 7.5V10a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7.5M12 12v4.5"/></svg>',
  };
  const compact = (count) =>
    new Intl.NumberFormat("en", { notation: "compact" }).format(count);
  const show = ({ name, stars, forks }) => {
    if (name) repoName.textContent = name;
    facts.innerHTML =
      `<span title="Stars">${icons.stars}${compact(stars)}</span>` +
      `<span title="Forks">${icons.forks}${compact(forks)}</span>`;
  };
  const key = "modsmith-repo";
  const load = async () => {
    try {
      const cached = JSON.parse(sessionStorage.getItem(key) ?? "null");
      if (cached) return show(cached);
      const response = await fetch(`https://api.github.com/repos/${repo.dataset.repo}`);
      if (!response.ok) return;
      const data = await response.json();
      const summary = {
        name: data.full_name,
        stars: data.stargazers_count,
        forks: data.forks_count,
      };
      sessionStorage.setItem(key, JSON.stringify(summary));
      show(summary);
    } catch (error) {}
  };
  if (repo && repoName && facts) load();
})();
