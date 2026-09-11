import { useEffect, useState } from 'react';

/** 运行中每秒走字的已用秒数；终态固定为 finishedAt - startedAt */
export function useElapsedSeconds(startedAt: number, running: boolean, finishedAt: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    setNow(Date.now());
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [running]);
  const end = running ? now : (finishedAt ?? now);
  return Math.max(0, Math.round((end - startedAt) / 1000));
}
