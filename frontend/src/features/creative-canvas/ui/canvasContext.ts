import { createContext, useContext } from "react";

/** The project the open Canvas belongs to; node views build file URLs from it. */
export const CanvasProjectContext = createContext<string>("");

export function useCanvasProject(): string {
  return useContext(CanvasProjectContext);
}
