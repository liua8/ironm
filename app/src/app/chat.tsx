// 对话页（spec §164 第二期，同网页版 chatPage）：从首页"IronM"那一段进来，整页显示。
// 页头：回首页、IronM 头像、以前的对话、新对话；没有消息时是欢迎和几个常问的；
// 回答边收边显示，可以停止；对话最后放管家消息和周报消息。输入框跟着键盘上移。
// 别的页想直接问一句，可以打开 /chat?q=问题（同网页版 askCoach）。
// 输入框的相机按钮（§152）：照片传好就连同输入框里的字一起发，没写字时问"帮我看看这个"。
import { router, useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  type ScrollEvent,
  type ScrollViewInstance,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/auth/session";
import { Composer, LOOK_AT_THIS } from "@/features/chat/composer";
import { HistorySheet } from "@/features/chat/history";
import { InboxMsg, WeekMsg } from "@/features/chat/inbox";
import { Mascot } from "@/features/chat/mascot";
import { Message } from "@/features/chat/message";
import { ask, attachPhoto, chatState, dropFile, ensureOwner, loadSession, newChat, openChat, rate, stop, uploading, useChat } from "@/features/chat/store";
import type { Photo } from "@/lib/photo";
import { PixelText } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

const STARTERS = [
  ["给我安排今天的训练", "按你的目标和状态"],
  ["深蹲时膝盖疼怎么办", "训练和恢复"],
  ["早餐怎么吃够蛋白质", "饮食"],
  ["我最近的静息心率正常吗", "身体数据"],
] as const;

export default function ChatPage() {
  const { token, signOut } = useSession();
  ensureOwner(token);
  const chat = useChat();
  const { q } = useLocalSearchParams<{ q?: string }>();
  const [draft, setDraft] = useState("");
  const [history, setHistory] = useState(false);
  const scroller = useRef<ScrollViewInstance>(null);
  const stick = useRef(true); // 停在最下面时，新内容到了跟着滚
  const asked = useRef(false);
  const draftNow = useRef(draft); // 照片传完时输入框里是什么（传的时候还能接着打字）
  draftNow.current = draft;

  const send = useCallback(
    (question: string) => {
      stick.current = true;
      void ask(question, { token, signOut: () => void signOut() });
    },
    [token, signOut],
  );

  const photo = useCallback(
    async (p: Photo) => {
      const ok = await attachPhoto(p);
      // 正在回答上一问时先留着，等用户自己点发送
      if (!ok || chatState().busy || uploading()) return;
      send(draftNow.current.trim() || LOOK_AT_THIS);
      setDraft("");
    },
    [send],
  );

  useEffect(() => {
    let live = true;
    void openChat().then(() => {
      if (!live || asked.current || !q) return;
      asked.current = true;
      // 正在回答别的：先放进输入框
      if (chatState().busy) setDraft(String(q));
      else send(String(q));
    });
    return () => {
      live = false;
    };
    // 只在打开页面时读一次
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const back = () => (router.canGoBack() ? router.back() : router.replace("/"));
  const fresh = () => {
    newChat();
    setDraft("");
  };
  const pick = (id: string) => {
    setHistory(false);
    if (chat.busy) return;
    stick.current = true;
    void loadSession(id);
  };
  const onScroll = (e: ScrollEvent) => {
    const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
    stick.current = contentSize.height - contentOffset.y - layoutMeasurement.height < 160;
  };

  const empty = !chat.messages.length;
  return (
    <SafeAreaView style={s.screen} edges={["top", "left", "right", "bottom"]}>
      <KeyboardAvoidingView style={s.flex} behavior={Platform.OS === "web" ? undefined : "padding"}>
        <View style={s.wrap}>
          <View style={s.bar}>
            <Pressable accessibilityRole="button" accessibilityLabel="回首页" onPress={back} hitSlop={8} style={s.backBtn}>
              <Text style={s.backText}>‹</Text>
            </Pressable>
            <Mascot size={34} />
            <PixelText size={24} style={s.name} numberOfLines={1}>IronM</PixelText>
            <Tool label="以前的对话" onPress={() => setHistory(true)} />
            <Tool label="新对话" onPress={fresh} />
          </View>

          <ScrollView
            ref={scroller}
            style={s.flex}
            contentContainerStyle={[s.thread, empty && s.threadEmpty]}
            keyboardShouldPersistTaps="handled"
            onScroll={onScroll}
            scrollEventThrottle={64}
            onContentSizeChange={() => stick.current && scroller.current?.scrollToEnd({ animated: false })}
          >
            {chat.loading && empty ? (
              <View style={s.loading}>
                <ActivityIndicator color={color.paperLight} />
              </View>
            ) : empty ? (
              <Welcome onAsk={send} busy={chat.busy} />
            ) : (
              chat.messages.map((m) => <Message key={m.key} msg={m} onRate={rate} />)
            )}
            {chat.inbox ? <InboxMsg key={chat.inboxKey} inbox={chat.inbox} /> : null}
            {chat.week ? <WeekMsg report={chat.week} /> : null}
          </ScrollView>

          <Composer
            busy={chat.busy}
            value={draft}
            onChange={setDraft}
            onSend={send}
            onStop={stop}
            files={chat.files}
            onPhoto={(p) => void photo(p)}
            onDrop={dropFile}
          />
        </View>
      </KeyboardAvoidingView>
      <HistorySheet visible={history} current={chat.session} onClose={() => setHistory(false)} onPick={pick} />
    </SafeAreaView>
  );
}

function Tool({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" onPress={onPress} hitSlop={4} style={({ pressed }) => [s.tool, pressed && s.toolDown]}>
      <Text style={s.toolText}>{label}</Text>
    </Pressable>
  );
}

function Welcome({ onAsk, busy }: { onAsk: (q: string) => void; busy: boolean }) {
  return (
    <View style={s.welcome}>
      <Mascot size={64} />
      <View style={s.welcomeText}>
        <PixelText size={24} style={s.welcomeTitle}>想问点什么？</PixelText>
        <Text style={s.welcomeSub}>练什么、吃什么、哪里不舒服，直接说就行。</Text>
      </View>
      <View style={s.starters}>
        {STARTERS.map(([question, who]) => (
          <Pressable
            key={question}
            accessibilityRole="button"
            disabled={busy}
            onPress={() => onAsk(question)}
            style={({ pressed }) => [s.starter, pressed && s.toolDown]}
          >
            <Text style={s.starterQ}>{question}</Text>
            <Text style={s.starterWho}>{who}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.grass },
  flex: { flex: 1 },
  wrap: { flex: 1, width: "100%", maxWidth: 720, alignSelf: "center", paddingHorizontal: space.l, paddingBottom: space.s },
  bar: { flexDirection: "row", alignItems: "center", gap: space.s, paddingVertical: space.s },
  backBtn: { width: 32, height: 36, alignItems: "center", justifyContent: "center", backgroundColor: color.plank, borderWidth: 2, borderColor: color.woodDark },
  backText: { color: color.accentInk, fontSize: 26, lineHeight: 28, fontWeight: "700" },
  name: { flex: 1, minWidth: 0, color: color.paperLight, textShadowColor: color.woodDark, textShadowOffset: { width: 2, height: 2 }, textShadowRadius: 0 },
  tool: { backgroundColor: color.paperLight, borderWidth: 2, borderColor: color.wood, paddingHorizontal: space.s, paddingVertical: 6 },
  toolDown: { opacity: 0.7 },
  toolText: { color: color.ink, fontSize: 13, fontWeight: "600" },
  thread: { gap: 14, paddingVertical: space.m },
  threadEmpty: { flexGrow: 1 },
  loading: { flex: 1, alignItems: "center", justifyContent: "center", paddingVertical: space.xl },
  welcome: { flexGrow: 1, justifyContent: "center", gap: space.l, paddingVertical: space.m },
  welcomeText: { gap: space.xs },
  welcomeTitle: { color: color.paperLight, textShadowColor: color.woodDark, textShadowOffset: { width: 2, height: 2 }, textShadowRadius: 0 },
  welcomeSub: { color: color.ink, fontSize: 15, lineHeight: 22 },
  starters: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  starter: { flexBasis: "47%", flexGrow: 1, backgroundColor: color.paper, borderWidth: 2, borderColor: color.wood, borderBottomWidth: 4, padding: space.m, gap: 4 },
  starterQ: { color: color.ink, fontSize: 15, lineHeight: 21, fontWeight: "600" },
  starterWho: { color: color.muted, fontSize: 12 },
});
