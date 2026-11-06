// 对话输入框（同网页版 composer）：多行输入，右边发送；正在回答时变成"停止"。
// 网页预览里回车发送、Shift+回车换行；手机上回车是换行，点按钮发送。
// 左边只有一个相机按钮（§152 "拍一张"）：拍或从相册选一张，传好就直接发，没写字时问"帮我看看这个"。
// 网页版还有"+ 附图片或报告"，App 按 §164 只放这一个相机按钮。
import { useState } from "react";
import { Image, Platform, Pressable, StyleSheet, Text, TextInput, type TextInputKeyPressEvent, View } from "react-native";

import { getPhoto, type Photo, photoErrText } from "@/lib/photo";
import { Icon } from "@/ui/icons";
import { color, space } from "@/ui/theme";

import type { Attach } from "./store";

export const LOOK_AT_THIS = "帮我看看这个";

export function Composer({ busy, onSend, onStop, value, onChange, files = [], onPhoto, onDrop }: {
  busy: boolean;
  onSend: (q: string) => void;
  onStop: () => void;
  value: string;
  onChange: (v: string) => void;
  files?: Attach[];
  onPhoto?: (p: Photo) => void;
  onDrop?: (key: string) => void;
}) {
  const [height, setHeight] = useState(44);
  const [picking, setPicking] = useState(false);
  const [err, setErr] = useState("");
  const loading = files.some((f) => !f.data && !f.error);
  const ready = files.some((f) => f.data);
  const canSend = busy || (!loading && (!!value.trim() || ready));
  const press = () => {
    if (busy) onStop();
    else if (canSend) {
      onSend(value.trim() ? value : LOOK_AT_THIS);
      onChange("");
      setHeight(44);
    }
  };
  const shoot = async () => {
    setErr("");
    setPicking(true);
    try {
      const p = await getPhoto("拍一张给 IronM 看");
      if (p) onPhoto?.(p);
    } catch (e) {
      setErr(photoErrText(e));
    } finally {
      setPicking(false);
    }
  };
  const onKey = (e: TextInputKeyPressEvent) => {
    if (Platform.OS !== "web") return;
    const k = e.nativeEvent as unknown as { key: string; shiftKey?: boolean; isComposing?: boolean };
    if (k.key === "Enter" && !k.shiftKey && !k.isComposing) {
      e.preventDefault();
      press();
    }
  };
  return (
    <View style={s.wrap}>
      {files.length ? (
        <View style={s.files}>
          {files.map((f) => (
            <View key={f.key} style={[s.file, f.error ? s.fileBad : null]}>
              <Image source={{ uri: f.uri }} style={s.thumb} accessibilityLabel="要发的照片" />
              <Text style={[s.fileText, f.error ? s.fileTextBad : null]} numberOfLines={2}>
                {f.error ? `没传上：${f.error}` : f.data ? "照片传好了" : "照片上传中…"}
              </Text>
              <Pressable accessibilityRole="button" accessibilityLabel="去掉这张照片" hitSlop={8} onPress={() => onDrop?.(f.key)} style={s.drop}>
                <Text style={s.dropText}>×</Text>
              </Pressable>
            </View>
          ))}
        </View>
      ) : null}
      {err ? <Text style={s.err} accessibilityLiveRegion="polite">{err}</Text> : null}
      <View style={s.bar}>
        {onPhoto ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="拍一张：吃的、器械都能认"
            accessibilityState={{ disabled: picking || loading }}
            disabled={picking || loading}
            onPress={shoot}
            style={({ pressed }) => [s.cam, (pressed || picking || loading) && s.down, (picking || loading) && s.off]}
          >
            <Icon name="camera" size={22} color={color.ink} />
          </Pressable>
        ) : null}
        <TextInput
          style={[s.input, { height: Math.min(Math.max(44, height), 140) }]}
          value={value}
          onChangeText={onChange}
          placeholder={onPhoto ? "问点什么，或拍一张…" : "问点什么…"}
          placeholderTextColor={color.muted}
          accessibilityLabel="输入问题"
          multiline
          onContentSizeChange={(e) => setHeight(e.nativeEvent.contentSize.height + 20)}
          onKeyPress={onKey}
          enterKeyHint="send"
          textAlignVertical="top"
        />
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={busy ? "停止" : "发送"}
          accessibilityState={{ disabled: !canSend }}
          disabled={!canSend}
          onPress={press}
          style={({ pressed }) => [s.send, busy && s.stop, (pressed || !canSend) && s.down, !canSend && s.off]}
        >
          <Text style={s.sendText}>{busy ? "停止" : "发送"}</Text>
        </Pressable>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { paddingTop: space.s, gap: space.s },
  bar: { flexDirection: "row", alignItems: "flex-end", gap: space.s },
  input: { flex: 1, minWidth: 0, backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.wood, paddingHorizontal: space.m, paddingTop: 10, paddingBottom: 10, fontSize: 16, lineHeight: 22, color: color.ink },
  cam: { width: 44, height: 44, alignItems: "center", justifyContent: "center", backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.wood, borderBottomWidth: 6 },
  send: { minWidth: 64, height: 44, alignItems: "center", justifyContent: "center", paddingHorizontal: space.m, backgroundColor: color.fire, borderWidth: 1, borderRadius: 14, borderColor: color.woodDark, borderBottomWidth: 6 },
  stop: { backgroundColor: color.heat },
  down: { borderBottomWidth: 1, marginTop: 3 },
  off: { opacity: 0.55 },
  sendText: { color: color.accentInk, fontSize: 15, fontWeight: "700" },
  files: { gap: space.xs },
  file: { flexDirection: "row", alignItems: "center", gap: space.s, alignSelf: "flex-start", maxWidth: "100%", backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.wood, padding: space.xs },
  fileBad: { borderColor: color.heat, backgroundColor: color.heatSoft },
  thumb: { width: 40, height: 40, backgroundColor: color.paper },
  fileText: { flexShrink: 1, color: color.ink, fontSize: 13, lineHeight: 18 },
  fileTextBad: { color: color.heat },
  drop: { width: 28, height: 28, alignItems: "center", justifyContent: "center" },
  dropText: { color: color.muted, fontSize: 20, lineHeight: 22, fontWeight: "700" },
  err: { color: color.heat, fontSize: 13, lineHeight: 19 },
});
