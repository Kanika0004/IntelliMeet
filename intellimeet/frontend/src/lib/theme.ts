import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";

function current(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

export function setTheme(t: Theme | "system") {
  const dark = t === "dark" || (t === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
  try {
    if (t === "system") localStorage.removeItem("im-theme");
    else localStorage.setItem("im-theme", t);
  } catch {
    /* storage unavailable */
  }
  window.dispatchEvent(new Event("im-theme"));
}

export function storedTheme(): Theme | "system" {
  try {
    const t = localStorage.getItem("im-theme");
    return t === "dark" || t === "light" ? t : "system";
  } catch {
    return "system";
  }
}

export function useTheme() {
  const [theme, setState] = useState<Theme>(current);
  useEffect(() => {
    const on = () => setState(current());
    window.addEventListener("im-theme", on);
    return () => window.removeEventListener("im-theme", on);
  }, []);
  const toggle = useCallback(() => setTheme(current() === "dark" ? "light" : "dark"), []);
  return { theme, toggle };
}
