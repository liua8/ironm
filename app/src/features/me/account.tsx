// 账号与隐私（同网页 exportSheet / deleteSheet，spec §180）：导出我的数据、注销账号。
import { router } from "expo-router";
import { useState } from "react";
import { Platform, Share, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { useSession } from "@/auth/session";
import { isoDay } from "@/features/record/logic";
import { Button, Field, Note, T } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

/** 存成文件：网页预览里直接下载，手机上交给系统分享（存到文件、发给自己都行）。 */
async function saveText(name: string, text: string): Promise<void> {
  if (Platform.OS === "web" && typeof document !== "undefined") {
    const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    return;
  }
  await Share.share({ title: name, message: text });
}

export function ExportBox() {
  const [msg, setMsg] = useState<{ tone: "muted" | "error"; text: string }>({ tone: "muted", text: "" });
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    setMsg({ tone: "muted", text: "正在准备…" });
    try {
      const data = await api("/iron/api/export");
      const name = `ironm-${isoDay(new Date())}.json`;
      await saveText(name, JSON.stringify(data, null, 2));
      setMsg({ tone: "muted", text: `已导出：${name}` });
    } catch (e) {
      setMsg({ tone: "error", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <View style={s.box}>
      <T muted>IronM 的数据：档案、计划、训练、饮食、目标、IronM 记得的事、器材场所、排行榜里你写的评论和投票，一个 JSON 文件。不含模型密钥、照片和内部运行记录。</T>
      <Button title="导出 IronM 的数据" onPress={go} disabled={busy} />
      <T muted>体重等身体读数、化验、手表、导入的健康数据在网页版「我 → 账号与隐私」里另下一个文件。</T>
      <Note tone={msg.tone}>{msg.text}</Note>
    </View>
  );
}

export function DeleteBox() {
  const { signOut } = useSession();
  const [email, setEmail] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    setMsg("正在注销…");
    try {
      await api("/iron/api/account/delete", { method: "POST", json: { confirm: email.trim() } });
      await signOut();
      router.replace("/login");
    } catch (e) {
      setMsg((e as Error).message);
      setBusy(false);
    }
  };
  return (
    <View style={s.box}>
      <Text style={s.bold}>注销后：</Text>
      <Text style={s.li}>· 马上不能再登录；</Text>
      <Text style={s.li}>· IronM 里你的训练、饮食、计划、IronM 记得的事等马上删除，不能恢复；</Text>
      <Text style={s.li}>· 体重等身体读数和其他健康记录、上传的文件、对话记录跟着账号一起关闭，不能再访问。</Text>
      <T muted>想留一份的，先在「导出我的数据」里导出。</T>
      <Field value={email} onChangeText={setEmail} placeholder="输入你的邮箱确认" accessibilityLabel="输入你的邮箱确认" autoCapitalize="none" keyboardType="email-address" />
      <Button title="确认注销账号" onPress={go} disabled={busy || !email.includes("@")} />
      <Note tone={msg === "正在注销…" ? "muted" : "error"}>{msg}</Note>
    </View>
  );
}

const s = StyleSheet.create({
  box: { gap: space.s },
  bold: { color: color.ink, fontWeight: "700" },
  li: { color: color.muted, fontSize: 14, lineHeight: 21 },
});
