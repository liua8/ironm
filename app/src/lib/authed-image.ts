// 要带登录凭证才能取的图片（记一餐的照片、打卡照片）：
// 手机上图片请求能直接带凭证头；网页预览的 <img> 带不上，先用 fetch 取回来转成本地地址再显示。
import { useEffect, useState } from "react";
import { type ImageSourcePropType, Platform } from "react-native";

import { useSession } from "@/auth/session";
import { API_BASE } from "@/config";

/** 给 <Image source>：还没取到（或取不到）时是 null，调用方就不画图。 */
export function useAuthedImage(path: string): ImageSourcePropType | null {
  const { token } = useSession();
  const url = `${API_BASE}${path}`;
  const [webUri, setWebUri] = useState<string | null>(null);
  useEffect(() => {
    if (Platform.OS !== "web") return;
    let live = true;
    let made = "";
    setWebUri(null);
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => {
        if (b && live) {
          made = URL.createObjectURL(b);
          setWebUri(made);
        }
      })
      .catch(() => {}); // 照片取不到就不显示
    return () => {
      live = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [url, token]);
  if (Platform.OS !== "web") return { uri: url, headers: { Authorization: `Bearer ${token}` } };
  return webUri ? { uri: webUri } : null;
}
