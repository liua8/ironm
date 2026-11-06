// 登录页（同网页 spec §155）：密码登录、验证码登录、邮箱验证码注册设密码、忘记密码；没配发信时注册和找回如实说不能用。
import { Redirect, router } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { StyleSheet, View } from "react-native";

import { mailReady, sendCode, signInWith } from "@/api/auth";
import { useSession } from "@/auth/session";
import { Button, Field, LinkButton, Note, Panel, PixelText, Screen, Seg, T } from "@/ui/pixel";
import { color } from "@/ui/theme";

type Mode = "login" | "code" | "register" | "reset";

const SUBMIT: Record<Mode, string> = { login: "登录", code: "登录", register: "注册", reset: "改好并登录" };

export default function Login() {
  const { ready, token, signIn } = useSession();
  const [mode, setMode] = useState<Mode>("login");
  const [mail, setMail] = useState<boolean | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<{ tone: "error" | "muted"; text: string }>({ tone: "error", text: "" });
  const [busy, setBusy] = useState(false);
  const [wait, setWait] = useState(0);
  const [sending, setSending] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    mailReady().then(setMail);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, []);

  if (ready && token) return <Redirect href="/" />;

  const go = (next: Mode) => {
    setMode(next);
    setMsg({ tone: "error", text: "" });
  };
  const withCode = mode !== "login";
  const newPassword = mode === "register" || mode === "reset";
  const noMail = newPassword && mail === false;

  // 发信要十几秒：按下就变灰、说"正在发送"，发完再倒计时；免得连点（每点一次发一封，新码让旧码作废）
  const askCode = async () => {
    if (sending || wait) return;
    setMsg({ tone: "error", text: "" });
    if (!email.includes("@")) return setMsg({ tone: "error", text: "先填邮箱" });
    setSending(true);
    setMsg({ tone: "muted", text: "正在发送验证码，一般十几秒内到。" });
    try {
      await sendCode(email.trim());
      setMsg({ tone: "muted", text: "验证码已发到邮箱，10 分钟内有效；收到几封时以最新一封为准。" });
      setWait(60);
      timer.current = setInterval(() => setWait((w) => {
        if (w <= 1 && timer.current) clearInterval(timer.current);
        return Math.max(0, w - 1);
      }), 1000);
    } catch (e) {
      setMsg({ tone: "error", text: (e as Error).message });
    } finally {
      setSending(false);
    }
  };

  const submit = async () => {
    setMsg({ tone: "error", text: "" });
    const addr = email.trim();
    if (!addr.includes("@")) return setMsg({ tone: "error", text: "邮箱格式不对" });
    if (newPassword && password !== again) return setMsg({ tone: "error", text: "两次输的密码不一样" });
    setBusy(true);
    try {
      const got =
        mode === "login" ? await signInWith("/password/login", { email: addr, password })
        : mode === "code" ? await signInWith("/email/verify", { email: addr, code: code.trim() })
        : await signInWith(mode === "register" ? "/password/register" : "/password/reset", { email: addr, code: code.trim(), password });
      await signIn(got);
      router.replace("/");
    } catch (e) {
      setMsg({ tone: "error", text: (e as Error).message });
      // 没成功先停一下再让点：连点会把验证码的 5 次机会很快用完
      await new Promise((r) => setTimeout(r, 1500));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <View style={s.head}>
        <PixelText size={48} style={s.word}>IronM</PixelText>
        <T style={s.lede}>AI 健身助手：训练、饮食、恢复和身体数据，按你的情况安排。</T>
      </View>
      <Seg items={[["login", "登录"], ["register", "注册"]] as const} value={mode === "code" || mode === "reset" ? "login" : mode} onChange={(k) => go(k)} />
      <Panel>
        <Field placeholder="邮箱" value={email} onChangeText={setEmail} keyboardType="email-address" autoCapitalize="none" autoComplete="email" inputMode="email" />
        {mode === "login" && <Field placeholder="密码" value={password} onChangeText={setPassword} secureTextEntry autoComplete="current-password" />}
        {withCode && (
          <View style={s.row}>
            <Field style={s.flex} placeholder="验证码" value={code} onChangeText={setCode} keyboardType="number-pad" maxLength={8} autoComplete="one-time-code" />
            <Button kind="wood" small title={sending ? "发送中…" : wait ? `${wait} 秒后重发` : "获取验证码"} onPress={askCode} disabled={sending || wait > 0} />
          </View>
        )}
        {newPassword && (
          <>
            <Field placeholder={mode === "reset" ? "新密码（至少 8 位）" : "设密码（至少 8 位）"} value={password} onChangeText={setPassword} secureTextEntry autoComplete="new-password" />
            <Field placeholder="再输一遍密码" value={again} onChangeText={setAgain} secureTextEntry autoComplete="new-password" />
          </>
        )}
        {noMail && <Note>{mode === "register" ? "邮件服务还没配好，暂时不能注册。" : "邮件服务还没配好，暂时不能找回密码。"}</Note>}
        <Button title={SUBMIT[mode]} onPress={submit} disabled={busy || noMail} />
        <Note tone={msg.tone}>{msg.text}</Note>
      </Panel>
      <View style={s.links}>
        {mode === "login" && <LinkButton title="用验证码登录" onPress={() => go("code")} />}
        {mode === "code" && <LinkButton title="用密码登录" onPress={() => go("login")} />}
        {(mode === "login" || mode === "code") && <LinkButton title="忘记密码" onPress={() => go("reset")} />}
        {mode === "reset" && <LinkButton title="想起来了，去登录" onPress={() => go("login")} />}
      </View>
    </Screen>
  );
}

const s = StyleSheet.create({
  head: { marginTop: 32, gap: 8 },
  word: { color: color.ink },
  lede: { color: color.ink },
  row: { flexDirection: "row", gap: 8, alignItems: "center" },
  flex: { flex: 1 },
  links: { flexDirection: "row", justifyContent: "space-between", flexWrap: "wrap", gap: 12 },
});
