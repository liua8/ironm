// 底部五格（同网页版 §175）：首页 / IronM / 图鉴 / 记录 / 我；白底，选中的珊瑚红。没登录时回登录页。
import { Redirect, Tabs } from "expo-router";
import type { BottomTabBarProps } from "expo-router/tabs";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useSession } from "@/auth/session";
import { useTrainingReminderSync } from "@/features/me/reminders";
import { Icon, type IconName } from "@/ui/icons";
import { color } from "@/ui/theme";

const TABS: readonly (readonly [string, string, IconName])[] = [
  ["index", "首页", "home"],
  ["chat", "IronM", "chat"],
  ["atlas", "图鉴", "atlas"],
  ["record", "记录", "record"],
  ["me", "我", "me"],
];

function CardTabBar({ state, navigateToTab }: BottomTabBarProps) {
  const insets = useSafeAreaInsets();
  return (
    <View style={[s.bar, { paddingBottom: Math.max(insets.bottom, 8) }]} accessibilityRole="tablist">
      {TABS.map(([name, label, icon]) => {
        const route = state.routes.find((r) => r.name === name);
        const on = state.routes[state.index]?.name === name;
        return (
          <Pressable
            key={name}
            accessibilityRole="tab"
            accessibilityState={{ selected: on }}
            accessibilityLabel={label}
            onPress={() => route && navigateToTab(route.key)}
            style={[s.tab, on && s.tabOn]}
          >
            <Icon name={icon} size={22} color={on ? color.accent : color.ink2} />
            <Text style={[s.label, on && s.labelOn]}>{label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export default function TabsLayout() {
  const { ready, token } = useSession();
  // 登录后：打开和回到 App 时按现在的计划重排训练日提醒（提醒关着时什么也不做）
  useTrainingReminderSync();
  if (!ready) return null;
  if (!token) return <Redirect href="/login" />;
  return (
    <Tabs screenOptions={{ headerShown: false }} tabBar={(props) => <CardTabBar {...props} />}>
      {TABS.map(([name, label]) => (
        <Tabs.Screen key={name} name={name} options={{ title: label }} />
      ))}
    </Tabs>
  );
}

const s = StyleSheet.create({
  bar: { flexDirection: "row", backgroundColor: color.paper, borderTopWidth: 1, borderTopColor: color.wood, paddingTop: 6, paddingHorizontal: 4 },
  tab: { flex: 1, alignItems: "center", justifyContent: "center", gap: 3, paddingVertical: 4 },
  tabOn: {},
  label: { color: color.ink2, fontSize: 11, fontWeight: "600" },
  labelOn: { color: color.accentText, fontWeight: "700" },
});
