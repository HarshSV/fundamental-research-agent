"use client";

import { useEffect, useState } from "react";

/** Typewriter loop over `phrases`: types a phrase, pauses, deletes it, moves to the next. */
export function useTyped(phrases: string[]) {
  const [i, setI] = useState(0);
  const [n, setN] = useState(0);
  const [del, setDel] = useState(false);
  useEffect(() => {
    const full = phrases[i];
    const t = setTimeout(
      () => {
        if (!del && n < full.length) setN(n + 1);
        else if (!del) setDel(true);
        else if (n > 0) setN(n - 1);
        else {
          setDel(false);
          setI((i + 1) % phrases.length);
        }
      },
      !del && n === full.length ? 1500 : del ? 35 : 80,
    );
    return () => clearTimeout(t);
  }, [i, n, del, phrases]);
  return phrases[i].slice(0, n);
}
