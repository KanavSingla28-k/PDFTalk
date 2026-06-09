'use client';

/**
 * useCountdown — counts down from a given number of seconds to 0.
 * Used to show the Retry-After cooldown on rate-limited requests.
 */

import { useState, useEffect, useRef } from 'react';

export function useCountdown(initialSeconds: number | undefined): {
  remaining: number;
  isActive: boolean;
  start: (seconds: number) => void;
  reset: () => void;
} {
  const [remaining, setRemaining] = useState(initialSeconds ?? 0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clear = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  };

  const start = (seconds: number) => {
    clear();
    setRemaining(seconds);
    intervalRef.current = setInterval(() => {
      setRemaining((prev) => {
        if (prev <= 1) {
          clear();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  const reset = () => {
    clear();
    setRemaining(0);
  };

  useEffect(() => {
    if (initialSeconds && initialSeconds > 0) start(initialSeconds);
    return clear;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { remaining, isActive: remaining > 0, start, reset };
}
