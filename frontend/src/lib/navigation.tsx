"use client";

/**
 * In-app navigation history.  Owner: the-steelix-flame.
 *
 * Exists so the Back control can appear only when going back actually lands
 * somewhere useful. `window.history.length` is no good for this: it counts
 * everything the tab ever visited, so on the first screen after login it would
 * happily offer to go "back" to the login page, which immediately redirects
 * forward again — a button that visibly does nothing.
 *
 * So we track navigations that happened *inside an authenticated shell*. The
 * provider mounts in `(app)/layout` and `portal/layout`, never at the root, so
 * the hop from /login is never counted. Land directly on a shared link and
 * there is no Back button, which is correct: there is nowhere in-app behind you.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { usePathname, useRouter } from "next/navigation";

type NavigationState = {
  canGoBack: boolean;
  goBack: () => void;
};

const NavigationContext = createContext<NavigationState>({
  canGoBack: false,
  goBack: () => {},
});

export function NavigationProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [canGoBack, setCanGoBack] = useState(false);
  const previousPath = useRef<string | null>(null);

  useEffect(() => {
    // The first path we see is where the user entered; there is nothing behind
    // it. Every change after that means there is.
    if (previousPath.current !== null && previousPath.current !== pathname) {
      setCanGoBack(true);
    }
    previousPath.current = pathname;
  }, [pathname]);

  // `router.back()` rather than a computed parent path: the user asked to
  // return to where they came from, and arriving at a quotation from the
  // negotiation inbox should go back to the inbox, not to the quotations list.
  const goBack = useCallback(() => router.back(), [router]);

  return (
    <NavigationContext.Provider value={{ canGoBack, goBack }}>
      {children}
    </NavigationContext.Provider>
  );
}

export function useNavigation(): NavigationState {
  return useContext(NavigationContext);
}
