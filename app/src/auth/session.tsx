// 登录会话（spec §164 第一期）：凭证存在系统的安全存储里；网页预览没有安全存储，存在浏览器里。
// 凭证失效时清掉，回登录页。
import * as SecureStore from "expo-secure-store";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Platform } from "react-native";

import { configureApi } from "@/api/client";
import { clearReminders } from "@/lib/notify";

const KEY = "iron.token";

const store = {
  async get(): Promise<string> {
    if (Platform.OS === "web") {
      try {
        return globalThis.localStorage?.getItem(KEY) ?? "";
      } catch {
        return "";
      }
    }
    return (await SecureStore.getItemAsync(KEY)) ?? "";
  },
  async set(value: string): Promise<void> {
    if (Platform.OS === "web") {
      try {
        if (value) globalThis.localStorage?.setItem(KEY, value);
        else globalThis.localStorage?.removeItem(KEY);
      } catch {
        // 隐私模式：这次会话里记着就行
      }
      return;
    }
    if (value) await SecureStore.setItemAsync(KEY, value);
    else await SecureStore.deleteItemAsync(KEY);
  },
};

type Session = { ready: boolean; token: string; signIn: (token: string) => Promise<void>; signOut: () => Promise<void> };

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [token, setToken] = useState("");
  const current = useRef("");

  const signIn = useCallback(async (next: string) => {
    current.current = next;
    setToken(next);
    await store.set(next);
  }, []);
  const signOut = useCallback(async () => {
    current.current = "";
    setToken("");
    await store.set("");
    // 提醒是按这个人的计划排的：退出（或凭证失效）就清掉，换账号不再响
    await clearReminders().catch(() => undefined);
  }, []);

  useEffect(() => {
    configureApi({ token: () => current.current, onUnauthorized: () => void signOut() });
    store.get().then((saved) => {
      current.current = saved;
      setToken(saved);
      setReady(true);
    });
  }, [signOut]);

  const value = useMemo(() => ({ ready, token, signIn, signOut }), [ready, token, signIn, signOut]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const s = useContext(SessionContext);
  if (!s) throw new Error("useSession 要在 SessionProvider 里用");
  return s;
}
