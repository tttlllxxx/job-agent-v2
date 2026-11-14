import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "./api";

export function useWork() {
  const client = useQueryClient();
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function perform<T>(action: () => Promise<T>): Promise<T | undefined> {
    setBusy(true);
    setError(null);
    try {
      const result = await action();
      await client.invalidateQueries();
      return result;
    } catch (error) {
      if (error instanceof ApiError && error.status === 409)
        await client.invalidateQueries();
      setError(error);
      return undefined;
    } finally {
      setBusy(false);
    }
  }
  return { perform, error, busy, setError };
}
