// "我"的设置里各行点开的内容（同网页 memorySheet、gearSection、addGrid、filesSection、citySection、modelSheet）。
// 都放在弹出页里；上传报告在手机上拍照或从相册选（§164 第四期），PDF 等文件、导入苹果健康、基因数据还要在网页版做。
import * as Location from "expo-location";
import { router } from "expo-router";
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { appendPhoto, getPhoto, photoErrText } from "@/lib/photo";
import { Caption, Chip, Failed, kit, KV, Pills, Row, Sub, TwoStep, useLoad } from "@/features/record/kit";
import { isoDay, md } from "@/features/record/logic";
import { Button, Field, LinkButton, Note, T } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { apiData, askPath } from "./data";
import { addGear, fileState, GEAR, GEAR_PLACES, type Gear, gearLine, type Memory, memoryGroups, sizeText, spotOf, stripRefs, type UploadedFile, validDay } from "./logic";

type Msg = { tone: "error" | "muted" | "ok"; text: string };
const quiet: Msg = { tone: "muted", text: "" };

// ---- IronM 记得的事（§121 需求 8、§141）：列出来，不对的删掉（删前当场再点一次） ----
export function MemoryBox() {
  const { data, error, reload } = useLoad(() => api<Memory>("/iron/api/memory"));
  const [gone, setGone] = useState<Set<string>>(new Set());
  const [msg, setMsg] = useState("");
  if (error) return <Failed error={error} retry={reload} />;
  if (!data) return <Caption>正在读取…</Caption>;
  const groups = memoryGroups(data);
  if (!groups.length) return <T muted>还没记下什么。聊天里说过的伤病、器材、作息、口味，IronM 会记在这里。</T>;
  const remove = async (id: string) => {
    try {
      await api(`/iron/api/memory/${encodeURIComponent(id)}`, { method: "DELETE" });
      setGone((g) => new Set(g).add(id));
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  return (
    <>
      <Note tone="error">{msg}</Note>
      {groups.map(([name, xs]) => (
        <View key={name} style={s.group}>
          <Text style={s.groupName}>{name}</Text>
          {xs.map((x) =>
            gone.has(x.id) ? (
              <Caption key={x.id}>删掉了。</Caption>
            ) : (
              <View key={x.id} style={s.memRow}>
                <T style={s.flex}>{stripRefs(x.content)}</T>
                <TwoStep label="删掉" sure="确定删掉" onConfirm={() => remove(x.id)} />
              </View>
            ),
          )}
        </View>
      ))}
    </>
  );
}

// ---- 器材和场所（§107）：排计划、换动作按这个 ----
export function GearBox({ close }: { close: () => void }) {
  const { data, error, reload, setData } = useLoad(() => api<Gear>("/iron/api/gear"));
  const [editing, setEditing] = useState(false);
  const [lacking, setLacking] = useState<Gear | null>(null);
  if (error) return <Failed error={error} retry={reload} />;
  if (!data) return <Caption>正在读取…</Caption>;
  if (editing)
    return (
      <GearForm
        g={data}
        done={(r) => {
          setData(r);
          setEditing(false);
          setLacking(r.lacking?.length ? r : null);
        }}
      />
    );
  const g = data;
  return (
    <>
      <View style={kit.card}>
        <Text style={s.title}>{g.known && g.place ? gearLine(g) : g.known ? "IronM 记过，但没说在哪练" : "还没填"}</Text>
        {g.text && !g.form ? <Caption>{`IronM 记的：${stripRefs(g.text)}`}</Caption> : null}
        <Caption>也可以直接跟 IronM 说，比如「搬家了，家里只有哑铃」。</Caption>
      </View>
      {lacking ? (
        <View style={s.notice}>
          <T>{`计划里有 ${lacking.lacking?.length} 个动作要用你没有的器械：${lacking.lacking?.join("、")}`}</T>
          <Button
            small
            title="让 IronM 按现在的器械调"
            onPress={() => {
              close();
              router.push(askPath(`我的场所和器材改成了：${gearLine(lacking)}。计划里${lacking.lacking?.join("、")}要用我没有的器械，帮我按现在的器械调一下计划`));
            }}
          />
        </View>
      ) : null}
      <View style={s.actions}>
        <View style={s.flex}>
          <Button small title={g.known ? "修改" : "填一下"} onPress={() => setEditing(true)} />
        </View>
        <View style={s.flex}>
          <Button
            small
            kind="ghost"
            title="跟 IronM 说"
            onPress={() => {
              close();
              router.push("/chat");
            }}
          />
        </View>
      </View>
    </>
  );
}

function GearForm({ g, done }: { g: Gear; done: (r: Gear) => void }) {
  const [place, setPlace] = useState<Gear["place"]>(g.place);
  const [gear, setGear] = useState<string[]>(g.gear ?? []);
  const [custom, setCustom] = useState<string[]>(g.custom ?? []);
  const [input, setInput] = useState("");
  const [msg, setMsg] = useState<Msg>(quiet);
  const [busy, setBusy] = useState(false);
  const add = () => {
    const r = addGear(input, gear, custom);
    if (typeof r === "string") return setMsg({ tone: "muted", text: r });
    setGear(r.gear);
    setCustom(r.custom);
    setInput("");
    setMsg(quiet);
  };
  const save = async () => {
    if (!place) return;
    setBusy(true);
    try {
      done(await api<Gear>("/iron/api/gear", { method: "PUT", json: { place, gear, custom } }));
    } catch (e) {
      setMsg({ tone: "error", text: (e as Error).message });
      setBusy(false);
    }
  };
  const homeOptions = [...GEAR, ["none", "只有自重"]] as const;
  return (
    <View style={s.form}>
      <Sub>一般在哪练</Sub>
      <Pills options={GEAR_PLACES} value={place} onPick={(k) => setPlace(k)} label="一般在哪练" />
      {place && place !== "gym" ? (
        <>
          <Sub>家里有什么</Sub>
          <Pills
            options={homeOptions}
            value={(k) => (k === "none" ? !gear.length && !custom.length : gear.includes(k))}
            onPick={(k) => {
              if (k === "none") {
                setGear([]);
                setCustom([]);
              } else setGear(gear.includes(k) ? gear.filter((x) => x !== k) : [...gear, k]);
            }}
            label="家里有什么"
          />
          {custom.length ? (
            <View style={s.tags}>
              {custom.map((n) => (
                <View key={n} style={s.tag}>
                  <Text style={s.tagText}>{n}</Text>
                  <LinkButton title="×" onPress={() => setCustom(custom.filter((x) => x !== n))} />
                </View>
              ))}
            </View>
          ) : null}
          <View style={s.addRow}>
            <Field style={s.flex} value={input} onChangeText={setInput} maxLength={12} placeholder="其他器材，比如跳绳、TRX" accessibilityLabel="其他器材" returnKeyType="done" onSubmitEditing={add} />
            <Button small kind="ghost" title="加上" onPress={add} />
          </View>
        </>
      ) : null}
      <Button title="好了" onPress={save} disabled={!place || busy} />
      <Note tone={msg.tone}>{msg.text}</Note>
    </View>
  );
}

// ---- 上传报告（同网页 uploadSheet）：手机上拍一页或从相册选一张，传到 /files/upload?file=true，后台识别指标 ----
// 一次传一张：多页报告一页一页拍；PDF、Excel 等文件还是在网页版传（要选文件的组件，没装）。
export function ReportUpload() {
  const [msg, setMsg] = useState<Msg>(quiet);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setMsg(quiet);
    let photo;
    try {
      photo = await getPhoto("报告");
    } catch (e) {
      return setMsg({ tone: "error", text: photoErrText(e) });
    }
    if (!photo) return;
    const form = new FormData();
    appendPhoto(form, "files", photo, "report.jpg");
    setBusy(true);
    setMsg({ tone: "muted", text: "上传中…" });
    try {
      const r = await api<{ code?: number; msg?: string }>("/files/upload?file=true", { method: "POST", body: form });
      setMsg(
        r.code === 0 || r.code === undefined
          ? { tone: "ok", text: "传好了，正在识别，结果会出现在「我的文件」里。还有下一页就再拍一张。" }
          : { tone: "error", text: `没有上传成功${r.msg ? `：${r.msg}` : "，请再试一次。"}` },
      );
    } catch (e) {
      setMsg({ tone: "error", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Button title={busy ? "上传中…" : "拍一页或从相册选"} onPress={go} disabled={busy} />
      <Note tone={msg.tone}>{msg.text}</Note>
      <Caption>上传后自动识别报告里的指标，一般几十秒到几分钟，只进你自己的记录。PDF、Excel 等文件请在网页版上传。</Caption>
    </>
  );
}

// ---- 导入健康数据和化验单：上传报告（拍照）、随手记一条；导入苹果健康、基因、设备还在网页版 ----
const KIND_NAMES: Record<string, string> = { symptom: "症状", condition: "病情", note: "笔记", measurement: "读数", medication: "用药" };
type JournalEntry = { id: string | number; text: string; kind: string; display?: string };
type Journal = { days?: { date: string; entries: JournalEntry[] }[] };
type Written = { text?: string; quote?: string; value?: string | number; unit?: string; kind?: string; reason?: string };

export function ImportBox() {
  return (
    <>
      <View style={kit.card}>
        <Row title="导入苹果健康" sub="睡眠、心率、步数一次导入" end="网页版" />
        <Row title="基因数据" sub="WeGene、23andMe 等原始数据" end="网页版" />
        <Row title="连接设备" sub="Garmin、Oura、Whoop" end="网页版" last />
      </View>
      {/* 苹果健康要单独打包的原生组件（Expo Go 里用不了），基因数据、设备要选文件或授权，先在网页版做 */}
      <Caption>导入苹果健康、基因数据、连接设备暂时在网页版里做。</Caption>
      <Sub>上传报告</Sub>
      <ReportUpload />
      <Sub>随手记一条</Sub>
      <JournalBox />
    </>
  );
}

function JournalBox() {
  const { data, error, reload } = useLoad(() => apiData<Journal>("/api/v1/journal"));
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState<[string, string][] | string>("");
  const [err, setErr] = useState("");
  const go = async () => {
    const t = text.trim();
    if (!t) return;
    setBusy(true);
    setErr("");
    setOut("正在记…");
    try {
      let tz = "";
      try {
        tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
      } catch {
        tz = "";
      }
      const r = await apiData<{ written?: Written[]; medications?: Written[]; skipped?: Written[]; already_logged?: boolean }>("/api/v1/journal/sentence", { method: "POST", json: { text: t, tz } });
      const lines: [string, string][] = [
        ...(r.written ?? []).map((x): [string, string] => ["记下了", `${x.text ?? ""}${x.value ? ` ${x.value}${x.unit ?? ""}` : ""}（${KIND_NAMES[x.kind ?? ""] ?? x.kind ?? ""}）`]),
        ...(r.medications ?? []).map((x): [string, string] => ["用药", `${x.text ?? ""}${x.reason ? `：${x.reason}` : ""}`]),
        ...(r.skipped ?? []).map((x): [string, string] => ["没有记", `${x.text || x.quote || ""}${x.reason ? `：${x.reason}` : ""}`]),
      ];
      setOut(lines.length ? lines : r.already_logged ? "这条已经记过了。" : "没有可记的内容。");
      setText("");
      reload();
    } catch (e) {
      const m = (e as Error).message;
      setOut("");
      setErr(/text model/i.test(m) ? "服务器还没有配置文字模型，暂时不能按句子记录。" : /could not be read/i.test(m) ? "这句话没读懂，换个说法再试试。" : m);
    }
    setBusy(false);
  };
  const remove = async (id: string | number) => {
    try {
      await apiData(`/api/v1/journal/${id}`, { method: "DELETE" });
      reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const entries = (data?.days ?? []).flatMap((d) => d.entries.map((x) => ({ ...x, date: d.date })));
  return (
    <View style={s.form}>
      <T muted>用自己的话写，一句话里写几件也行。症状、病情会对上标准名称，提到的用药会加进用药清单，其他的记为笔记。</T>
      <Field multiline style={s.area} value={text} onChangeText={setText} placeholder="比如：今天有点头疼；早上血压 128/82；开始吃维生素 D" accessibilityLabel="记一条" />
      <Button title="记下" onPress={go} disabled={busy || !text.trim()} />
      <Note tone="error">{err}</Note>
      {typeof out === "string" ? <Note>{out}</Note> : <View style={kit.card}>{out.map(([k, v], i) => <KV key={i} k={k} v={v} />)}</View>}
      <Sub>最近 30 天</Sub>
      {error ? (
        <Failed error={error} retry={reload} />
      ) : !data ? (
        <Caption>正在读取…</Caption>
      ) : entries.length ? (
        <View style={kit.card}>
          {entries.map((x, i) => (
            <Row
              key={`${x.id}`}
              last={i === entries.length - 1}
              title={x.text}
              sub={`${md(x.date)} · ${KIND_NAMES[x.kind] ?? x.kind}${x.display && x.display !== x.text ? ` · ${x.display}` : ""}`}
              end={x.kind === "medication" ? undefined : <TwoStep label="删" sure="确定删" onConfirm={() => remove(x.id)} />}
            />
          ))}
        </View>
      ) : (
        <Caption>最近 30 天还没有记录。</Caption>
      )}
    </View>
  );
}

// ---- 我的文件：列出上传过的；能改报告日期、删除；拍照上传在"导入健康数据和化验单"里 ----
export function FilesBox() {
  const { data, error, reload } = useLoad(() => apiData<{ files?: UploadedFile[] }>("/api/v1/data/uploaded-files?limit=20&offset=0"));
  const [pick, setPick] = useState<UploadedFile | null>(null);
  if (error) return <Failed error={error} retry={reload} />;
  if (!data) return <Caption>正在读取…</Caption>;
  if (pick)
    return (
      <FileDetail
        f={pick}
        back={() => setPick(null)}
        changed={() => {
          setPick(null);
          reload();
        }}
      />
    );
  const files = data.files ?? [];
  const now = Date.now();
  return (
    <>
      {files.length ? (
        <View style={kit.card}>
          {files.map((f, i) => {
            const [state, tone] = fileState(f, now);
            return (
              <Row
                key={`${f.file_key ?? f.id ?? i}`}
                last={i === files.length - 1}
                title={f.original_name || f.file_name || "文件"}
                sub={`上传于 ${md(f.upload_time)}${f.report_date ? ` · 报告 ${md(f.report_date)}` : ""}`}
                end={<Chip text={state} tone={tone} />}
                onPress={() => setPick(f)}
              />
            );
          })}
        </View>
      ) : (
        <T muted>还没有上传过报告。</T>
      )}
      {files.some((f) => fileState(f, now)[0] === "识别中") ? <LinkButton title="刷新识别进度" onPress={reload} /> : null}
      <Caption>拍照上传报告在「导入健康数据和化验单」里，PDF 等文件在网页版上传，传好的都会列在这里。</Caption>
    </>
  );
}

function FileDetail({ f, back, changed }: { f: UploadedFile; back: () => void; changed: () => void }) {
  const [state, tone] = fileState(f, Date.now());
  const [date, setDate] = useState(String(f.report_date ?? "").slice(0, 10));
  const [msg, setMsg] = useState<Msg>(quiet);
  const saveDate = async () => {
    if (!validDay(date, isoDay(new Date()))) return setMsg({ tone: "error", text: "日期写成 2026-11-05 这样，不能晚于今天" });
    try {
      await apiData("/api/v1/health-indicators/file-date", { method: "POST", json: { file_key: f.file_key, report_date: date } });
      setMsg({ tone: "ok", text: "已改好，这份报告里的数据按新日期记。" });
    } catch (e) {
      setMsg({ tone: "error", text: (e as Error).message });
    }
  };
  const remove = async () => {
    try {
      await apiData("/api/v1/data/delete-files", { method: "POST", json: { message_id: f.created_source_id || f.id, file_keys: [f.file_key] } });
      changed();
    } catch (e) {
      setMsg({ tone: "error", text: (e as Error).message });
    }
  };
  return (
    <>
      <LinkButton title="‹ 全部文件" onPress={back} />
      <Text style={s.title}>{f.original_name || f.file_name}</Text>
      <View style={s.tags}>
        <Chip text={state} tone={tone} />
        <Chip text={String(f.file_type || f.type || "").toUpperCase()} />
        <Chip text={sizeText(f.file_size ?? 0)} />
      </View>
      <KV k="上传时间" v={md(f.upload_time)} />
      <KV k="报告日期" v={f.report_date ? `${md(f.report_date)}${f.date_confirmed ? "" : "（未确认）"}` : "未识别出"} />
      {f.error ? <KV k="原因" v={f.error} /> : null}
      <Sub>报告日期不对？</Sub>
      <View style={s.addRow}>
        <Field style={s.flex} value={date} onChangeText={setDate} placeholder="2026-11-05" accessibilityLabel="报告日期" autoCapitalize="none" />
        <Button small kind="ghost" title="保存日期" onPress={saveDate} />
      </View>
      <Note tone={msg.tone}>{msg.text}</Note>
      <Sub>删除</Sub>
      <Caption>删除后，从这份文件识别出的数据也会一起去掉。</Caption>
      <TwoStep label="删除这份文件" sure="确定删除" onConfirm={remove} />
    </>
  );
}

// ---- 城市和天气（§13）：按城市取实时天气和空气质量 ----
type Place = { city?: string; label?: string };
export function CityBox() {
  const { data, setData } = useLoad(() => api<Place>("/iron/api/place").catch(() => ({}) as Place));
  const [editing, setEditing] = useState(false);
  const [input, setInput] = useState("");
  const [msg, setMsg] = useState<Msg>(quiet);
  if (!data) return <Caption>正在读取…</Caption>;
  const save = async () => {
    if (!input.trim()) return;
    setMsg({ tone: "muted", text: "正在查找…" });
    try {
      setData(await api<Place>("/iron/api/place", { method: "PUT", json: { city: input.trim() } }));
      setEditing(false);
      setMsg(quiet);
    } catch (e) {
      setMsg({ tone: "error", text: (e as Error).message });
    }
  };
  // 用当前位置（同网页 citySection，§173）：只在点了才取一次，经纬度留两位小数（约 1 公里）交给服务端认城市
  const locate = async () => {
    setMsg({ tone: "muted", text: "正在定位…" });
    try {
      const perm = await Location.requestForegroundPermissionsAsync();
      if (perm.status !== "granted") return setMsg({ tone: "error", text: "没有同意定位，可以手填城市" });
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Low });
      setData(await api<Place>("/iron/api/place/locate", { method: "POST", json: spotOf(pos.coords) }));
      setMsg(quiet);
    } catch (e) {
      setMsg({ tone: "error", text: e instanceof Error && /[\u4e00-\u9fff]/.test(e.message) ? e.message : "这次没取到位置，可以手填城市" });
    }
  };
  return (
    <>
      {editing ? (
        <View style={s.form}>
          <Sub>所在城市</Sub>
          <Field value={input} onChangeText={setInput} maxLength={30} placeholder="比如：杭州、北京朝阳" accessibilityLabel="所在城市" returnKeyType="done" onSubmitEditing={save} autoFocus />
          <Note tone={msg.tone}>{msg.text}</Note>
          <View style={s.actions}>
            <View style={s.flex}>
              <Button kind="ghost" title="取消" onPress={() => setEditing(false)} />
            </View>
            <View style={s.flex}>
              <Button title="保存" onPress={save} />
            </View>
          </View>
        </View>
      ) : (
        <View style={kit.card}>
          <Row
            title="城市"
            end={data.label || data.city || "未设置"}
            last
            onPress={() => {
              setInput(data.city ?? "");
              setEditing(true);
            }}
          />
        </View>
      )}
      {editing ? null : <LinkButton title="用当前位置" onPress={() => void locate()} />}
      {editing ? null : <Note tone={msg.tone}>{msg.text}</Note>}
      <Caption>按城市取实时天气和空气质量，首页和 IronM 安排训练、饮食时会用上；问 IronM 天气也按这里。用当前位置只在你点了才取，只留到约 1 公里。</Caption>
    </>
  );
}

// ---- 模型和 API（§153）：选服务商、填密钥、选模型，先测试再保存；密钥只显示末四位 ----
type Preset = { name: string; base_url?: string; chat: string[]; vision: string[] };
type MyModel = { model: { provider: string; base_url: string; key_tail: string; chat_model: string; vision_model: string } | null; presets: Record<string, Preset> };
type Check = { ok: boolean; why?: string };

export function ModelBox({ close }: { close: () => void }) {
  const { data, error, reload } = useLoad(() => api<MyModel>("/iron/api/my-model"));
  if (error) return <Failed error={error} retry={reload} />;
  if (!data) return <Caption>正在读取…</Caption>;
  return <ModelForm r={data} close={close} />;
}

function ModelForm({ r, close }: { r: MyModel; close: () => void }) {
  const cur = r.model;
  const presets = r.presets;
  const first = cur?.provider ?? Object.keys(presets)[0] ?? "custom";
  const [provider, setProvider] = useState(first);
  const [url, setUrl] = useState(cur?.provider === "custom" ? cur.base_url : "");
  const [key, setKey] = useState("");
  const [chatModel, setChatModel] = useState(cur?.chat_model ?? presets[first]?.chat[0] ?? "");
  const [visionModel, setVisionModel] = useState(cur?.vision_model ?? "");
  const [msg, setMsg] = useState<Msg>(quiet);
  const [checks, setChecks] = useState<[string, Check][] | null>(null);
  const [busy, setBusy] = useState(false);
  const p = presets[provider];
  const options = [...Object.entries(presets).map(([k, x]) => [k, x.name] as const), ["custom", "自定义（兼容 OpenAI 格式）"] as const];
  const body = () => ({ provider, base_url: url.trim(), api_key: key.trim(), chat_model: chatModel.trim(), vision_model: visionModel.trim() });

  const pickProvider = (k: string) => {
    setProvider(k);
    setChatModel(presets[k]?.chat[0] ?? "");
    setVisionModel("");
  };
  const test = async () => {
    setBusy(true);
    setChecks(null);
    setMsg({ tone: "muted", text: "正在测试，用你的密钥发几句很短的话…" });
    try {
      const x = await api<{ chat: Check; tools: Check; vision: Check }>("/iron/api/my-model/test", { method: "POST", json: body() });
      setMsg(quiet);
      setChecks([["能不能通", x.chat], ["能不能调工具", x.tools], ["能不能看图", x.vision]]);
    } catch (e) {
      setMsg({ tone: "error", text: (e as Error).message });
    }
    setBusy(false);
  };
  const save = async () => {
    setBusy(true);
    try {
      await api("/iron/api/my-model", { method: "PUT", json: body() });
      setMsg({ tone: "ok", text: "已保存：以后用你自己的模型，费用记在你的账户上。" });
      setKey("");
    } catch (e) {
      setMsg({ tone: "error", text: (e as Error).message });
    }
    setBusy(false);
  };
  const drop = async () => {
    try {
      await api("/iron/api/my-model", { method: "DELETE" });
      close();
    } catch (e) {
      setMsg({ tone: "error", text: (e as Error).message });
    }
  };

  return (
    <View style={s.form}>
      <T muted>
        {cur
          ? `现在用的是你自己的模型：${presets[cur.provider]?.name || "自定义"} · ${cur.chat_model}`
          : "还没填自己的模型。IronM 用你自己的模型回答问题、估热量、认器械，费用记在你的账户上。"}
      </T>
      <Sub>服务商</Sub>
      <Pills options={options} value={provider} onPick={pickProvider} label="服务商" />
      {p ? null : (
        <>
          <Sub>接口地址</Sub>
          <Field value={url} onChangeText={setUrl} placeholder="接口地址，以 https 开头" accessibilityLabel="接口地址" autoCapitalize="none" autoCorrect={false} keyboardType="url" />
        </>
      )}
      <Sub>API 密钥</Sub>
      <Field
        value={key}
        onChangeText={setKey}
        secureTextEntry
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete="off"
        placeholder={cur ? `已保存，末四位 ${cur.key_tail}；不改就留空` : "API 密钥"}
        accessibilityLabel="API 密钥"
      />
      <Sub>对话模型</Sub>
      <Field value={chatModel} onChangeText={setChatModel} placeholder="对话用的模型名" accessibilityLabel="对话模型" autoCapitalize="none" autoCorrect={false} />
      {p?.chat.length ? <Pills options={p.chat.map((m) => [m, m] as const)} value={chatModel} onPick={setChatModel} label="常用的对话模型" /> : null}
      <Sub>看图模型</Sub>
      <Field value={visionModel} onChangeText={setVisionModel} placeholder="看图用的模型名（不填就用上面那个）" accessibilityLabel="看图模型" autoCapitalize="none" autoCorrect={false} />
      {p?.vision.length ? <Pills options={p.vision.map((m) => [m, m] as const)} value={visionModel} onPick={setVisionModel} label="常用的看图模型" /> : null}
      <View style={s.actions}>
        <View style={s.flex}>
          <Button kind="ghost" title="测试连接" onPress={test} disabled={busy} />
        </View>
        <View style={s.flex}>
          <Button title="保存" onPress={save} disabled={busy} />
        </View>
      </View>
      <Note tone={msg.tone}>{msg.text}</Note>
      {checks ? (
        <View style={kit.card}>
          {checks.map(([name, x]) => (
            <View key={name} style={s.check}>
              <Text style={s.checkName}>{name}</Text>
              <Text style={[s.checkVal, x.ok ? s.ok : s.bad]}>{x.ok ? "可以" : x.why || "不行"}</Text>
            </View>
          ))}
        </View>
      ) : null}
      {cur ? <TwoStep label="删除这个模型" sure="确定删除：估热量、认器械要重新填了才能用" onConfirm={drop} /> : null}
      <Caption>密钥加密存在服务器上，只显示末四位。对话要能调工具的模型；拍照识别要能看图的模型。你的模型出错时会告诉你，不会换成别的模型。</Caption>
    </View>
  );
}

const s = StyleSheet.create({
  flex: { flex: 1 },
  group: { gap: space.s },
  groupName: { color: color.muted, fontSize: 13, fontWeight: "700" },
  memRow: { flexDirection: "row", alignItems: "center", gap: space.m, backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.woodLight, padding: space.m },
  title: { color: color.ink, fontSize: 16, fontWeight: "700" },
  notice: { gap: space.s, backgroundColor: "rgba(242, 193, 78, 0.3)", borderLeftWidth: 1, borderLeftColor: "#8a5a10", padding: space.m },
  actions: { flexDirection: "row", gap: space.s },
  form: { gap: space.s },
  tags: { flexDirection: "row", flexWrap: "wrap", gap: space.s },
  tag: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: color.goodSoft, borderWidth: 1, borderRadius: 14, borderColor: color.accent, paddingLeft: space.s, paddingRight: 4 },
  tagText: { color: color.ink, fontSize: 14 },
  addRow: { flexDirection: "row", alignItems: "center", gap: space.s },
  area: { minHeight: 84, textAlignVertical: "top" },
  check: { flexDirection: "row", justifyContent: "space-between", gap: space.m },
  checkName: { color: color.muted, fontSize: 14 },
  checkVal: { fontSize: 14, fontWeight: "600", flexShrink: 1, textAlign: "right" },
  ok: { color: color.accentText },
  bad: { color: color.heat },
});
