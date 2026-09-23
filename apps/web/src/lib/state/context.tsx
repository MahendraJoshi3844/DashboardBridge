"use client";

import {
  createContext,
  useContext,
  useEffect,
  useReducer,
  useRef,
  type Dispatch,
  type ReactNode,
} from "react";

import { initialState, type MachineEvent, type MachineState } from "./machine";
import {
  FLOW_STORAGE_KEY,
  decodeFlow,
  encodeFlow,
  flowReducer,
} from "./persist";

/**
 * One machine for the whole flow.
 *
 * 03-ux-spec.md says *one machine, one current state*. A reducer held inside
 * the landing screen would be a second machine that the workspace then has to
 * re-derive from a URL, and re-derived state is state that can disagree with
 * itself. The provider lives in the root layout, so the direction chosen on the
 * landing screen is the same `SOURCE_SELECTED` the workspace uploads from.
 *
 * State and dispatch are separate contexts so a component that only dispatches
 * does not re-render when the state changes.
 */
const StateContext = createContext<MachineState | null>(null);
const DispatchContext = createContext<Dispatch<MachineEvent> | null>(null);

/**
 * `sessionStorage`, not `localStorage`: "where I was" is a property of this
 * tab, and a run resurrected in a new window next week would be offering to
 * resume a project the server may no longer hold. Closing the tab ends the
 * run, which is what closing a tab has always meant.
 *
 * Both calls are guarded. Storage throws rather than returning null when a
 * browser is set to block site data, and a private-mode failure to remember
 * the flow must not take the whole app down with it.
 */
function readStoredFlow(): MachineState {
  try {
    return decodeFlow(window.sessionStorage.getItem(FLOW_STORAGE_KEY));
  } catch {
    return initialState;
  }
}

function writeStoredFlow(state: MachineState): void {
  try {
    const encoded = encodeFlow(state);
    if (encoded === null) {
      window.sessionStorage.removeItem(FLOW_STORAGE_KEY);
    } else {
      window.sessionStorage.setItem(FLOW_STORAGE_KEY, encoded);
    }
  } catch {
    // Nothing to do and nothing worth saying: the flow still works, it just
    // will not survive a reload.
  }
}

export function MigrationProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(flowReducer, initialState);

  // Read once, during the first client render, into a ref. It has to happen
  // before any effect can run, because the effect below writes the current
  // state — and the current state at that moment is still `IDLE`, which would
  // clear the very key we are about to read. A ref is also what makes this
  // survive StrictMode's double-invoked effects: the second pass reads the
  // value already captured rather than a slot the first pass has emptied.
  //
  // Nothing rendered depends on it, so the server's markup and the first
  // client render still match; the restore itself is dispatched from an
  // effect, after hydration, for exactly that reason.
  const restored = useRef<MachineState | null>(null);
  if (restored.current === null && typeof window !== "undefined") {
    restored.current = readStoredFlow();
  }

  useEffect(() => {
    const flow = restored.current;
    if (flow !== null && flow.name !== "IDLE") {
      dispatch({ type: "RESUMED", state: flow });
    }
  }, []);

  useEffect(() => {
    writeStoredFlow(state);
  }, [state]);

  return (
    <StateContext.Provider value={state}>
      <DispatchContext.Provider value={dispatch}>
        {children}
      </DispatchContext.Provider>
    </StateContext.Provider>
  );
}

export function useMigration(): MachineState {
  const state = useContext(StateContext);
  if (state === null) {
    throw new Error("useMigration must be used inside <MigrationProvider>.");
  }
  return state;
}

export function useMigrationDispatch(): Dispatch<MachineEvent> {
  const dispatch = useContext(DispatchContext);
  if (dispatch === null) {
    throw new Error(
      "useMigrationDispatch must be used inside <MigrationProvider>.",
    );
  }
  return dispatch;
}
