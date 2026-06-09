import { useCallback, useEffect, useState } from "react";
import { ApiError } from "./api";

export type AsyncState<T> =
  | { status: "loading"; data?: undefined; error?: undefined; forbidden?: false }
  | { status: "empty"; data: T; error?: undefined; forbidden?: false }
  | { status: "success"; data: T; error?: undefined; forbidden?: false }
  | { status: "error"; data?: undefined; error: string; forbidden: boolean };

export function useAsyncData<T>(loader: () => Promise<T>, isEmpty: (data: T) => boolean, deps: React.DependencyList) {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });

  const refresh = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const data = await loader();
      setState(isEmpty(data) ? { status: "empty", data } : { status: "success", data });
    } catch (error) {
      setState({
        status: "error",
        error: error instanceof Error ? error.message : String(error),
        forbidden: error instanceof ApiError && error.forbidden
      });
    }
  }, deps);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { state, refresh };
}

export function isArrayEmpty<T>(data: T[]) {
  return data.length === 0;
}
