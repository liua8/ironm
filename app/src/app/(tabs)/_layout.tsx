// 底部四个标签（同网页版 §121）：首页 / 图鉴 / 战绩 / 我；木板样式的标签栏。没登录时回登录页。
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
  ["atlas", "图鉴", "atlas"],
  ["record", "战绩", "record"],
  ["me", "我", "me"],
];

function WoodTabBar({ state, navigateToTab }: BottomTabBarProps) {
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
            <Icon name={icon} size={22} color={on ? color.accentText : color.accentInk} />
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
    <Tabs screenOptions={{ headerShown: false }} tabBar={(props) => <WoodTabBar {...props} />}>
      {TABS.map(([name, label]) => (
        <Tabs.Screen key={name} name={name} options={{ title: label }} />
      ))}
    </Tabs>
  );
}

const s = StyleSheet.create({
  bar: { flexDirection: "row", gap: 6, backgroundColor: color.wood, borderTopWidth: 4, borderTopColor: color.woodDark, paddingTop: 8, paddingHorizontal: 8 },
  tab: { flex: 1, alignItems: "center", gap: 2, paddingVertical: 6, backgroundColor: color.plank, borderWidth: 2, borderColor: color.woodDark },
  tabOn: { backgroundColor: color.amber },
  label: { color: color.accentInk, fontSize: 13, fontWeight: "700" },
  labelOn: { color: color.accentText },
});
