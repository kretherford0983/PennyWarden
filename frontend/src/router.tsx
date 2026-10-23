// Minimal History-API router (avoids a third-party routing dependency).
import { createContext, useContext, useEffect, useState, type ReactNode, type MouseEvent } from "react";

const RouterCtx = createContext<{ path: string; search: string; navigate: (to: string, opts?: { replace?: boolean }) => void }>({
  path: "/",
  search: "",
  navigate: () => {},
});

/** 2.1.0 (CodeQL js/xss-through-dom, alert #11): the one rule for every in-app address - a same-site path
 * ("/..."), never another site ("//host"), a scheme ("javascript:") or a backslash trick. null when it isn't one. */
export function sitePath(to: unknown): string | null {
  if (typeof to !== "string" || !to.startsWith("/") || to.startsWith("//") || to.includes("\\")) return null;
  return to;
}

export function Router({ children }: { children: ReactNode }) {
  const [loc, setLoc] = useState({ path: window.location.pathname, search: window.location.search });
  useEffect(() => {
    const on = () => setLoc({ path: window.location.pathname, search: window.location.search });
    window.addEventListener("popstate", on);
    return () => window.removeEventListener("popstate", on);
  }, []);
  const navigate = (to: string, opts?: { replace?: boolean }) => {
    // only same-origin relative paths are navigable
    if (sitePath(to) === null) return;
    if (opts?.replace) window.history.replaceState({}, "", to);
    else window.history.pushState({}, "", to);
    const u = new URL(to, window.location.origin);
    setLoc({ path: u.pathname, search: u.search });
    window.scrollTo(0, 0);
  };
  return <RouterCtx.Provider value={{ ...loc, navigate }}>{children}</RouterCtx.Provider>;
}

export function useRouter() {
  return useContext(RouterCtx);
}

export function Link({ to, children, className, ...rest }: { to: string; children: ReactNode; className?: string; [k: string]: any }) {
  const { navigate, path } = useRouter();
  const onClick = (e: MouseEvent) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    navigate(to);
  };
  const active = path === to || (to !== "/" && path.startsWith(to + "/"));
  // the address in the page follows the same rule as navigation (a middle-click or "open in new tab" uses it
  // directly): anything that isn't a same-site path becomes a harmless "#"; the constant "/" prefix keeps it a path
  const safe = sitePath(to);
  const href = safe === null ? "#" : "/" + safe.slice(1);
  return (
    <a href={href} onClick={onClick} className={`${className || ""}${active ? " active" : ""}`} aria-current={active ? "page" : undefined} {...rest}>
      {children}
    </a>
  );
}

/** Match "/fiscal-years/:id" style patterns. */
export function match(pattern: string, path: string): Record<string, string> | null {
  const a = pattern.split("/").filter(Boolean);
  const b = path.split("/").filter(Boolean);
  if (a.length !== b.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < a.length; i++) {
    if (a[i].startsWith(":")) params[a[i].slice(1)] = decodeURIComponent(b[i]);
    else if (a[i] !== b[i]) return null;
  }
  return params;
}
