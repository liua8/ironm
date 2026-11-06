// 根布局：登录会话，各页不显示系统标题栏（标题由页面自己画）。§175 起不载入像素字。
// 凭证从存储里读出来之前什么都不画：不然直接打开 /chat 这类页面会不带凭证发请求，被当成登录失效登出。
// 没登录只能进登录页（打开别的页面或登录失效都换到登录页）；登录了进不了登录页（Stack.Protected）。
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { SessionProvider, useSession } from "@/auth/session";
import { usePixelFont } from "@/ui/fonts";

function Screens() {
  const { ready, token } = useSession();
  if (!ready) return null;
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Protected guard={!!token} redirectTo="/login">
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="plan" />
        <Stack.Screen name="live" />
        <Stack.Screen name="eat" />
        <Stack.Screen name="timeline" />
        <Stack.Screen name="body" />
        <Stack.Screen name="rank/index" />
        <Stack.Screen name="rank/[board]/index" />
        <Stack.Screen name="rank/[board]/[item]" />
      </Stack.Protected>
      <Stack.Protected guard={!token} redirectTo="/">
        <Stack.Screen name="login" />
      </Stack.Protected>
    </Stack>
  );
}

export default function RootLayout() {
  if (!usePixelFont()) return null;
  return (
    <SafeAreaProvider>
      <SessionProvider>
        <StatusBar style="dark" />
        <Screens />
      </SessionProvider>
    </SafeAreaProvider>
  );
}
