// 只存在这台设备上的小设置（同登录凭证、训练日提醒的存法）：手机存安全存储，网页预览存浏览器。
// 读不到一律当没存过，写不进去也不挡页面（隐私模式之类）。
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

export async function readLocal(key: string): Promise<string> {
  if (Platform.OS === "web") {
    try {
      return globalThis.localStorage?.getItem(key) ?? "";
    } catch {
      return "";
    }
  }
  try {
    return (await SecureStore.getItemAsync(key)) ?? "";
  } catch {
    return "";
  }
}

export async function writeLocal(key: string, value: string): Promise<void> {
  if (Platform.OS === "web") {
    try {
      globalThis.localStorage?.setItem(key, value);
    } catch {
      // 隐私模式：这次记着就行
    }
    return;
  }
  try {
    await SecureStore.setItemAsync(key, value);
  } catch {
    // 存不上：下次打开可能再提示一次，不挡页面
  }
}
