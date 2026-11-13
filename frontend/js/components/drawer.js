// Right-hand slide-over panel. Content is supplied by the caller.
import { $ } from "../utils.js";

export function openDrawer(html) {
  const drawer = $("#drawer");
  $("#drawer-scrim").hidden = false;
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  drawer.innerHTML = html;
  return drawer;
}

export function setDrawer(html) {
  $("#drawer").innerHTML = html;
  return $("#drawer");
}

export function closeDrawer() {
  const drawer = $("#drawer");
  if (!drawer) return;
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  $("#drawer-scrim").hidden = true;
}

export function isDrawerOpen() {
  return $("#drawer").classList.contains("open");
}
