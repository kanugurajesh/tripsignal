"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { ACTORS, type Actor } from "./api";

const Ctx = createContext<{ actor: Actor; setActor: (a: Actor) => void }>({
  actor: ACTORS[0],
  setActor: () => {},
});

export function ActorProvider({ children }: { children: React.ReactNode }) {
  const [actor, setActorState] = useState<Actor>(ACTORS[0]);
  useEffect(() => {
    try {
      const id = localStorage.getItem("tripsignal.actor");
      const found = ACTORS.find((a) => a.id === id);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- restoring a per-viewer preference after hydration
      if (found) setActorState(found);
    } catch {}
  }, []);
  const setActor = (a: Actor) => {
    setActorState(a);
    try {
      localStorage.setItem("tripsignal.actor", a.id);
    } catch {}
  };
  return <Ctx.Provider value={{ actor, setActor }}>{children}</Ctx.Provider>;
}

export const useActor = () => useContext(Ctx);
