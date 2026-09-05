"use client";

/**
 * The one data-fetching hook.  Owner: sinjeki.
 *
 * No Redux, no React Query. Every screen is `const { data, error, reload } =
 * useApi<T>("/path")`, and every mutation calls `reload()`. The backend
 * returns fully recomputed objects, so there is nothing to cache-invalidate.
 */

import { useCallback, useEffect, useState } from "react";

import { ApiError, get } from "@/lib/api";

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!path) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      setData(await get<T>(path));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, String(err)));
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    void load();
  }, [load]);

  return { data, error, loading, reload: load, setData };
}
